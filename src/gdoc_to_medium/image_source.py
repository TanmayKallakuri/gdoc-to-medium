"""Download an inline image's bytes using the service-account credentials (spec 5.2).

A Google Docs image `contentUri` is short-lived (~30 minutes) and scoped to the
authenticated principal, so it is fetched with an AuthorizedSession built from the
same service-account credentials Drive/Docs use. The session factory is injectable
so tests run with a fake and no network.

Failures carry the transient/permanent split the orchestrator routes on (spec 6):
a network blip or 429/5xx is retryable (leave the doc in Ready); a missing
contentUri or a 4xx is permanent (route to Failed) — we will never ship a post
with a broken image (risk R6).

REAL-WORLD NOTE (validate at the T5.5 live dry-run): whether the contentUri is
fetchable with the service account's AuthorizedSession can only be confirmed
against a real shared doc. If Google returns 403 here against a live doc, the
fetch may need the Drive `files.get?alt=media` route instead of the raw
contentUri — revisit at T5.5 with a real image.
"""

from __future__ import annotations

from .orchestrator import ImageDownloadError
from .types import ImageRef

_DOWNLOAD_TIMEOUT = 30


def make_authorized_downloader(credentials, *, session_factory=None):
    """Return a `download(image_ref, document) -> (bytes, content_type)` callable.

    `credentials` are the service-account credentials; `session_factory(creds)`
    builds the authorized HTTP session (defaults to google-auth's
    AuthorizedSession, imported lazily so this module loads without network deps
    in tests).
    """
    if session_factory is None:
        from google.auth.transport.requests import AuthorizedSession

        session_factory = AuthorizedSession
    session = session_factory(credentials)

    def download(ref: ImageRef, document: dict) -> tuple[bytes, str]:
        uri = ref.content_uri
        if not uri:
            raise ImageDownloadError(
                f"image {ref.object_id} has no contentUri to download", transient=False
            )
        try:
            response = session.get(uri, timeout=_DOWNLOAD_TIMEOUT)
        except Exception as exc:
            # Any transport-level failure reaching Google's image host is retryable.
            raise ImageDownloadError(
                f"network error downloading image {ref.object_id}: {type(exc).__name__}",
                transient=True,
            ) from None
        status = getattr(response, "status_code", None)
        if status == 429 or (isinstance(status, int) and 500 <= status < 600):
            raise ImageDownloadError(
                f"transient HTTP {status} downloading image {ref.object_id}", transient=True
            )
        if status != 200:
            raise ImageDownloadError(
                f"HTTP {status} downloading image {ref.object_id}", transient=False
            )
        content_type = (response.headers.get("Content-Type", "") or "").split(";")[0].strip()
        return response.content, content_type

    return download
