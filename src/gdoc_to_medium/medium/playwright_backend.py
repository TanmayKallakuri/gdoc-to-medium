"""Medium web-editor backend driven by Playwright (Wave 6, spec 5.3 fallback).

This is the path that works WITHOUT a Medium integration token — the one most new
users need, since Medium stopped issuing tokens in Jan 2025 (Wave 6 research). It
drives the real Medium story editor through a logged-in browser session:

  new-story -> wait for the ProseMirror editor -> type the title -> replay the post
  as ordered paste/upload operations (HTML pasted via a synthetic ClipboardEvent so it
  works headless; local images uploaded through the editor's file input) -> capture the
  draft URL, optionally publishing with tags.

It operates on an injected `page` and imports nothing from Playwright at module load,
so the unit tests run against a fake page with no browser installed — exactly how
TokenBackend is tested against a fake httpx client. Live wiring (launching a persistent
browser context and the one-time login) lives in session.py and cli.py.

Error policy: session/auth problems and "a selector didn't resolve" (a Medium UI
change) are TRANSIENT — the orchestrator leaves the doc in Ready so re-login or a
selector fix recovers it with NO lost docs, rather than dumping every doc into Failed
on a systemic break. Per-doc permanent conditions (empty body, unresolved image) are
still caught upstream in the orchestrator.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from ..types import PostResult
from . import selectors as S
from .markdown_html import ImageOp, PasteOp, to_operations
from .token_backend import PermanentMediumError, TransientMediumError

logger = logging.getLogger("gdoc_to_medium.medium.playwright_backend")

# Sentinel URL upload_image hands back for a local image; create_post recognizes it and
# uploads the stashed file through the editor instead of pasting an <img src> Medium
# cannot fetch. Shaped as a URL with no spaces/parens so it survives in `![alt](url)`.
_SENTINEL_PREFIX = "https://gdoc2medium.local/img/"

# milliseconds — short settles for ProseMirror's async rendering between operations.
_PASTE_SETTLE_MS = 200
# Poll the URL after content is in, until Medium's autosave swaps new-story -> /p/<id>.
_URL_POLL_MS = 250
_URL_POLL_TRIES = 24  # ~6s budget for autosave to land
_NAV_TIMEOUT_MS = 30_000
_EDITOR_TIMEOUT_MS = 20_000
_STEP_TIMEOUT_MS = 8_000

_EXT_BY_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
}

# Synthetic paste: build a DataTransfer with text/html (+plain fallback, required by
# Chromium) and dispatch a 'paste' ClipboardEvent on the editor. ProseMirror's paste
# handler reads clipboardData, so this inserts rich content with no OS clipboard.
_PASTE_JS = """
({sel, html}) => {
  const el = document.querySelector(sel) || document.activeElement;
  if (!el) return false;
  el.focus();
  const dt = new DataTransfer();
  dt.setData('text/html', html);
  dt.setData('text/plain', html.replace(/<[^>]+>/g, ''));
  const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true});
  el.dispatchEvent(ev);
  return true;
}
"""


def _split_title(title: str, markdown: str) -> tuple[str, str]:
    """Decide the post title and the body to paste below it.

    In the web editor the first H1 IS the title (it renders as the title, not a body
    heading). So if the markdown opens with a top-level `# ` heading, use its text as the
    title and drop that line from the body — otherwise we'd get the title twice. If there
    is no leading H1, fall back to the given title (the doc's filename, spec 4).
    """
    lines = (markdown or "").split("\n")
    for idx, line in enumerate(lines):
        if line.strip() == "":
            continue
        if line.startswith("# "):  # exactly one '#' + space => H1 (not ##, ### ...)
            heading = line[2:].strip()
            rest = lines[idx + 1:]
            while rest and rest[0].strip() == "":
                rest.pop(0)
            return heading, "\n".join(rest)
        break  # first non-blank line isn't an H1; keep the body as-is
    return (title or "").strip(), markdown or ""


class PlaywrightSessionError(TransientMediumError):
    """Not signed in / session expired. Transient: re-login fixes it, doc stays in Ready."""


class PlaywrightUIError(TransientMediumError):
    """A required selector didn't resolve (Medium UI likely changed). Transient by design."""


class PlaywrightBackend:
    """Create Medium posts by automating the web editor through a logged-in `page`.

    `page` is a Playwright sync Page in production (built in session.py) or a fake in
    tests. `temp_dir` holds downloaded image bytes between upload_image and create_post;
    one is created if not supplied and removed by close().
    """

    def __init__(self, page, *, temp_dir: Path | None = None) -> None:
        self._page = page
        self._owns_temp = temp_dir is None
        self._temp_dir = temp_dir or Path(tempfile.mkdtemp(prefix="gdoc2medium-img-"))
        self._images: dict[str, Path] = {}
        self._counter = 0

    # --- MediumBackend protocol -----------------------------------------------------

    def upload_image(self, data: bytes, content_type: str) -> str:
        """Stash image bytes locally and return a sentinel URL the orchestrator subs in.

        Unlike the token backend (which uploads to Medium's API here), the web path can't
        get a CDN URL out of band — the image is uploaded through the editor during
        create_post. So this just persists the bytes and returns a unique marker.
        """
        ext = _EXT_BY_TYPE.get((content_type or "").strip().lower(), ".img")
        self._counter += 1
        path = self._temp_dir / f"image-{self._counter}{ext}"
        path.write_bytes(data)
        sentinel = f"{_SENTINEL_PREFIX}{self._counter}{ext}"
        self._images[sentinel] = path
        return sentinel

    def create_post(
        self,
        title: str,
        markdown: str,
        tags: list[str],
        publish_status: str = "draft",
    ) -> PostResult:
        """Drive the editor to build the post; return its draft (or published) URL."""
        page = self._page
        page.goto(S.NEW_STORY_URL, wait_until="domcontentloaded")
        self._assert_signed_in()
        self._wait_for_editor()

        title_text, body_md = _split_title(title, markdown)
        self._enter_title(title_text)
        for op in to_operations(body_md):
            if isinstance(op, PasteOp):
                self._paste(op.html)
            elif isinstance(op, ImageOp):
                self._insert_image(op)

        url = self._capture_url(expect_change_from=S.NEW_STORY_URL)

        if publish_status == "public":
            url = self._publish(tags) or url
            logger.info("published Medium post via web editor")
        else:
            logger.info("saved Medium draft via web editor")
        return PostResult(url=url)

    # --- lifecycle / health ---------------------------------------------------------

    def health_check(self) -> bool:
        """True if the session is logged in and the editor reachable (for `doctor`/preflight)."""
        try:
            self._page.goto(S.NEW_STORY_URL, wait_until="domcontentloaded")
            if S.SIGNIN_URL_FRAGMENT in (self._page.url or ""):
                return False
            return self._query_first(S.SIGNED_IN_MARKERS) is not None
        except Exception as exc:  # noqa: BLE001 — health check must never raise
            logger.warning("Playwright health check failed: %s", type(exc).__name__)
            return False

    def close(self) -> None:
        """Remove the temp image dir (best effort). Does not close the browser/page."""
        if self._owns_temp:
            shutil.rmtree(self._temp_dir, ignore_errors=True)

    # --- editor steps ---------------------------------------------------------------

    def _assert_signed_in(self) -> None:
        if S.SIGNIN_URL_FRAGMENT in (self._page.url or ""):
            raise PlaywrightSessionError(
                "Medium session is not signed in or has expired — run `gdoc-to-medium login`"
            )

    def _wait_for_editor(self) -> None:
        """Wait for the ProseMirror surface; a miss means signin or a UI change."""
        combined = ",".join(S.EDITOR)
        try:
            self._page.wait_for_selector(combined, timeout=_EDITOR_TIMEOUT_MS)
        except Exception:
            self._assert_signed_in()  # surface the friendlier reason if that's it
            raise PlaywrightUIError(
                "could not find the Medium story editor (Medium's UI may have changed); "
                "run `gdoc-to-medium doctor` to check selectors"
            ) from None

    def _enter_title(self, title: str) -> None:
        """Type the title into the title graf, then drop into the body.

        The body's leading H1 (if any) was already lifted out into `title` by
        _split_title, so there's exactly one title and no duplicate heading.
        """
        title = (title or "").strip()
        handle = self._query_first(S.TITLE)
        if handle is None:
            # Fall back to the editor itself: the first line becomes the title.
            handle = self._query_first(S.EDITOR)
        if handle is None:
            raise PlaywrightUIError("could not locate the title field in the Medium editor")
        handle.click()
        if title:
            self._page.keyboard.type(title)
        self._page.keyboard.press("Enter")

    def _paste(self, html: str) -> None:
        if not html:
            return
        ok = self._page.evaluate(_PASTE_JS, {"sel": ",".join(S.EDITOR), "html": html})
        if ok is False:
            raise PlaywrightUIError("editor element vanished while pasting content")
        self._page.wait_for_timeout(_PASTE_SETTLE_MS)

    def _insert_image(self, op: ImageOp) -> None:
        """Upload a stashed local image through the editor's hidden file input.

        If the sentinel isn't one we stashed (shouldn't happen — every image comes from
        upload_image), fall back to pasting an <img src> and let Medium try to fetch it.
        """
        path = self._images.get(op.url)
        if path is None:
            self._paste(f'<p><img src="{op.url}" alt="{op.alt}"></p>')
            return
        selector = self._first_present(S.IMAGE_FILE_INPUT)
        if selector is None:
            raise PlaywrightUIError(
                "could not find Medium's image upload input (UI may have changed)"
            )
        self._page.set_input_files(selector, str(path))
        self._page.wait_for_timeout(_PASTE_SETTLE_MS)

    def _publish(self, tags: list[str]) -> str | None:
        """Open the publish dialog, add up to 5 tags, and publish; return the post URL."""
        self._click_first(S.PUBLISH_BUTTON)
        tag_selector = self._first_present(S.TAG_INPUT)
        if tag_selector is not None:
            for tag in list(tags)[:5]:
                self._page.click(tag_selector)
                self._page.keyboard.type(tag)
                self._page.keyboard.press("Enter")
        self._click_first(S.PUBLISH_NOW_BUTTON)
        return self._capture_url(expect_change_from=S.NEW_STORY_URL)

    def _capture_url(self, *, expect_change_from: str) -> str:
        """Return the post URL once Medium autosaves/navigates away from `expect_change_from`.

        Medium autosaves asynchronously and only then does the URL become the real
        /p/<id> draft link, so poll (bounded) until the URL changes off new-story rather
        than reading it immediately. Falls back to whatever URL is present if it never
        changes within the budget.
        """
        for _ in range(_URL_POLL_TRIES):
            url = self._page.url or ""
            if url and url != expect_change_from and "/new-story" not in url:
                return url
            self._page.wait_for_timeout(_URL_POLL_MS)
        return self._page.url or ""

    # --- selector resolution --------------------------------------------------------

    def _query_first(self, selectors):
        """Return the first element handle that resolves, or None."""
        for sel in selectors:
            try:
                handle = self._page.query_selector(sel)
            except Exception:  # noqa: BLE001 — a bad/unsupported selector just misses
                continue
            if handle:
                return handle
        return None

    def _first_present(self, selectors) -> str | None:
        """Return the first selector string whose element exists, or None."""
        for sel in selectors:
            try:
                if self._page.query_selector(sel):
                    return sel
            except Exception:  # noqa: BLE001
                continue
        return None

    def _click_first(self, selectors) -> None:
        """Click the first selector that works; raise PlaywrightUIError if none do."""
        last_exc: Exception | None = None
        for sel in selectors:
            try:
                self._page.click(sel, timeout=_STEP_TIMEOUT_MS)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        raise PlaywrightUIError(
            f"none of these Medium controls resolved: {selectors!r} "
            f"({type(last_exc).__name__ if last_exc else 'no candidates'})"
        ) from None
