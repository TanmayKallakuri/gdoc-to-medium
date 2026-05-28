"""The Task Scheduler entrypoint logic: process each Ready doc end to end (spec 5.4).

For one ready doc the happy path is: fetch the Docs JSON -> convert to markdown +
image refs + metadata -> download each inline image and upload it to Medium,
rewriting its PLACEHOLDER: into the hosted URL -> create the Medium post -> move
the doc to Published and write the review URL back into it.

Every doc is processed in its own try/except so one failure never affects the
others (spec 6 isolation). Failures are routed by type: transient (network /
429 / 5xx from Drive or Medium) leaves the doc in Ready for the next run with no
move; permanent (4xx auth, malformed doc, conversion crash, empty body, an
image that could not be resolved) moves the doc to Failed and appends a
human-readable reason to the top of the doc. An unresolved PLACEHOLDER: is forced
to be permanent here so a broken image URL can never reach readers (spec risk R6).
"""

from __future__ import annotations

import logging
import re

from .config import Config
from .converter import convert
from .drive_client import DriveClient, TransientDriveError
from .medium.token_backend import TransientMediumError
from .types import DocRef, ImageRef, MediumBackend

logger = logging.getLogger("gdoc_to_medium.orchestrator")

_PUBLISHED = "published"
_FAILED = "failed"

# Matches a single emitted image placeholder so we can swap in the uploaded URL.
# The objectId is whatever the converter put after "PLACEHOLDER:" up to the ")".
_PLACEHOLDER_RE = re.compile(r"PLACEHOLDER:([^)]+)")

# Transient failures leave the doc in Ready for the next scheduled run (spec 6);
# every other exception (the Permanent* errors, PermanentDocError, an unexpected
# crash) is treated as permanent and routed to Failed.
_TRANSIENT = (TransientDriveError, TransientMediumError)


class PermanentDocError(Exception):
    """A doc-level permanent failure the orchestrator raises itself (spec 6).

    Covers the conditions the collaborators can't signal on their own: a doc that
    converts to an empty body (never post nothing) and an image placeholder with
    no resolved upload (never ship a broken PLACEHOLDER: to readers, risk R6).
    """


class ImageDownloadError(Exception):
    """Wraps an inline-image download failure, carrying the transient/permanent split."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


def run(
    drive: DriveClient,
    medium: MediumBackend,
    config: Config,
    *,
    image_downloader,
    dry_run: bool = False,
) -> int:
    """Process every doc currently in Ready; return the count processed without error.

    `image_downloader(image_ref, document) -> (bytes, content_type)` fetches one
    inline image's bytes with the service-account credentials; it is injected so
    tests run with no network. In `dry_run` the converted markdown is printed and
    no Medium call or file move happens (spec 5.4).
    """
    docs = drive.list_ready()
    if not docs:
        print("Nothing to do — the 'Ready to Publish' folder is empty.")
        return 0

    ok = 0
    for doc in docs:
        try:
            _process_one(doc, drive, medium, config, image_downloader, dry_run)
            ok += 1
        except _TRANSIENT as exc:
            # Leave the doc in Ready; the next scheduled run retries it (spec 6).
            logger.warning("transient failure on doc %s; leaving in Ready: %s", doc.doc_id, exc)
        except ImageDownloadError as exc:
            # The downloader carries its own transient/permanent split: a network
            # blip leaves the doc in Ready, a missing/forbidden image is permanent.
            if exc.transient:
                logger.warning(
                    "transient image-download failure on doc %s; leaving in Ready: %s",
                    doc.doc_id, exc,
                )
            else:
                _route_permanent(doc, drive, config, exc, dry_run)
        except Exception as exc:
            # Everything else is permanent: the Permanent* errors, PermanentDocError,
            # and any unexpected crash -> route to Failed rather than retry (spec 6).
            _route_permanent(doc, drive, config, exc, dry_run)
    return ok


def _process_one(
    doc: DocRef,
    drive: DriveClient,
    medium: MediumBackend,
    config: Config,
    image_downloader,
    dry_run: bool,
) -> None:
    document = drive.fetch_document(doc.doc_id)

    try:
        markdown, image_refs, metadata = convert(document, doc.name)
    except Exception as exc:
        # A converter crash is permanent: the doc is malformed in a way we can't
        # fix by retrying, so route it to Failed rather than loop forever (spec 6).
        raise PermanentDocError(f"conversion failed: {type(exc).__name__}: {exc}") from exc

    if not markdown.strip():
        raise PermanentDocError("converted document body is empty; refusing to publish an empty post")

    markdown = _resolve_images(markdown, image_refs, document, medium, image_downloader, dry_run)

    if dry_run:
        _emit_dry_run(doc, markdown)
        return

    result = medium.create_post(
        title=metadata.title,
        markdown=markdown,
        tags=metadata.tags,
        publish_status=metadata.publish_status,
    )

    drive.move(doc.doc_id, _dest(config, _PUBLISHED))
    drive.append_note(doc.doc_id, f"Published to Medium (review draft): {result.url}")
    logger.info("published doc %s", doc.doc_id)


def _resolve_images(
    markdown: str,
    image_refs: list[ImageRef],
    document: dict,
    medium: MediumBackend,
    image_downloader,
    dry_run: bool,
) -> str:
    """Replace every PLACEHOLDER:objectId with its uploaded Medium URL (spec 5.2).

    In dry-run the placeholders are left intact (no Medium calls); otherwise each
    inline image is downloaded with the service-account credentials, uploaded to
    Medium, and its placeholder rewritten. After rewriting, any PLACEHOLDER: still
    present means an image went unresolved -> permanent failure, so a broken image
    URL can never reach readers (risk R6).
    """
    if dry_run:
        return markdown

    for ref in image_refs:
        data, content_type = image_downloader(ref, document)
        url = medium.upload_image(data, content_type)
        # Anchor on the closing ')' of the markdown image token so an objectId that
        # is a prefix of another can't corrupt the longer placeholder (which would
        # then slip past the leftover guard below as a broken URL).
        placeholder = f"PLACEHOLDER:{ref.object_id})"
        markdown = markdown.replace(placeholder, url + ")")

    leftover = _PLACEHOLDER_RE.search(markdown)
    if leftover is not None:
        raise PermanentDocError(
            f"unresolved image placeholder for object {leftover.group(1)!r}; "
            f"refusing to publish a post with a broken image"
        )
    return markdown


def _emit_dry_run(doc: DocRef, markdown: str) -> None:
    print(f"===== {doc.name} ({doc.doc_id}) =====")
    print(markdown)
    print()


def _dest(config: Config, key: str) -> str:
    folder = config.folders.get(key)
    if not folder:
        raise PermanentDocError(f"no '{key}' folder id configured; cannot route the doc")
    return folder


def _route_permanent(
    doc: DocRef, drive: DriveClient, config: Config, exc: Exception, dry_run: bool
) -> None:
    """Move a permanently-failed doc to Failed and append a readable reason (spec 6).

    Best-effort: if Drive itself is unavailable while we try to move/note, that is
    logged but not re-raised, so one doc's cleanup failure never aborts the batch.
    """
    reason = f"Failed to publish to Medium: {exc}"
    logger.error("permanent failure on doc %s: %s", doc.doc_id, exc)
    if dry_run:
        return
    try:
        drive.move(doc.doc_id, _dest(config, _FAILED))
        drive.append_note(doc.doc_id, reason)
    except Exception as cleanup_exc:
        logger.error("could not route doc %s to Failed: %s", doc.doc_id, cleanup_exc)
