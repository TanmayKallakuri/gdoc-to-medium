"""Launch a logged-in Medium browser session for the Playwright backend (Wave 6).

Medium login is an email magic-link / OAuth flow that CANNOT be automated (Wave 6
research). The supported pattern is a PERSISTENT browser profile: you log in by hand
ONCE in a headed window (`gdoc-to-medium login`), and every scheduled run afterward
reuses that profile headlessly. The profile dir holds cookies + localStorage and is
gitignored (`.auth/`), treated like a credential.

Everything here imports Playwright lazily, inside the functions, so importing the
package (and running the unit tests) needs no `playwright` install — only the live
`login`/run paths do.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from . import selectors as S

logger = logging.getLogger("gdoc_to_medium.medium.session")

# Grant the editor clipboard access (used by the real-clipboard paste fallback) and
# isolate the profile so it can't touch the user's normal Chrome data.
_PERMISSIONS = ["clipboard-read", "clipboard-write"]
_LOGIN_WAIT_MS = 300_000  # up to 5 minutes for the human to finish signing in


class SessionError(RuntimeError):
    """The browser session could not be launched or is missing its profile."""


def default_session_dir(config) -> Path:
    """Where the Medium browser profile lives. Override with [playwright].session_dir.

    Defaults next to the config (which is already a locked-down, gitignored dir) so the
    session sits with the other secrets rather than in the repo tree.
    """
    override = getattr(config, "playwright_session_dir", None)
    if override:
        return Path(override)
    base = getattr(config, "config_dir", None)
    if base:
        return Path(base) / "medium-session"
    return Path(".auth") / "medium-session"


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - import guard
        raise SessionError(
            "Playwright is not installed. Run `pip install -e .` then "
            "`python -m playwright install chromium`."
        ) from exc
    return sync_playwright


@contextlib.contextmanager
def launch_page(session_dir: Path, *, headless: bool = True):
    """Yield a Playwright page backed by the persistent Medium profile.

    Context-managed so the browser is always closed. The caller (cli) keeps it open
    across a whole run so every doc in the batch reuses one browser.
    """
    sync_playwright = _require_playwright()
    session_dir = Path(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=headless,
            permissions=_PERMISSIONS,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            yield page
        finally:
            context.close()


def login(session_dir: Path) -> bool:
    """Open a headed window for a one-time manual Medium login; persist the session.

    Returns True once the editor becomes reachable (i.e. login succeeded), False on
    timeout. The persistent context saves cookies automatically, so subsequent headless
    runs are authenticated.
    """
    print(
        "Opening a browser window. Sign in to Medium (Google / email link / however you\n"
        "normally do). This window stays open until you're signed in — then it closes\n"
        "automatically and your session is saved. You only do this once."
    )
    with launch_page(session_dir, headless=False) as page:
        page.goto(S.NEW_STORY_URL, wait_until="domcontentloaded")
        combined = ",".join(S.EDITOR)
        try:
            # The editor only loads once authenticated; wait (generously) for it.
            page.wait_for_selector(combined, timeout=_LOGIN_WAIT_MS)
        except Exception:
            print("Timed out waiting for sign-in. Re-run `gdoc-to-medium login` to try again.")
            return False
    print("Signed in. Session saved — you're ready to publish.")
    return True
