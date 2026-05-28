"""Google Drive + Docs access for the folder-state workflow (spec 5.1).

Wraps the service-account-authenticated Drive and Docs API clients behind the
four operations the orchestrator needs: list ready docs, fetch a doc's JSON,
move a doc between folders, and append a note to the top of a doc.

HttpError responses are classified into transient (retry next run) vs permanent
(move to Failed) so Wave 5's orchestrator can route per spec 6.
"""

from __future__ import annotations

import logging
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .types import DocRef

logger = logging.getLogger("gdoc_to_medium.drive_client")

# Docs are read-only; Drive needs read + metadata write to move files between
# folders (addParents/removeParents) and run batchUpdate on docs.
SCOPES = (
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
)

GOOGLE_DOC_MIMETYPE = "application/vnd.google-apps.document"

# Drive files.list page cap; the real default is 100, we ask for the max so a
# typical Ready folder is one page while still paging correctly when it isn't.
_PAGE_SIZE = 100


class DriveClientError(Exception):
    """Base class for drive_client failures."""


class TransientDriveError(DriveClientError):
    """A retryable failure (network, HTTP 429/5xx) — leave the doc in Ready (spec 6)."""


class PermanentDriveError(DriveClientError):
    """A non-retryable failure (HTTP 4xx, malformed response) — route to Failed (spec 6)."""


def _classify(exc: HttpError) -> DriveClientError:
    """Map a Google HttpError to transient vs permanent by status code (spec 6)."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    msg = f"Google API error (status={status})"
    if status == 429 or (status is not None and 500 <= status < 600):
        return TransientDriveError(msg)
    return PermanentDriveError(msg)


def _execute(request):
    """Run a Google API request, normalizing transport failures into our error types."""
    try:
        return request.execute()
    except HttpError as exc:
        raise _classify(exc) from exc
    except (OSError, TimeoutError) as exc:
        # Connection refused/reset/DNS/timeout are retryable.
        raise TransientDriveError(f"Network error contacting Google API: {type(exc).__name__}") from exc


class DriveClient:
    """Drive + Docs operations for one configured service account."""

    def __init__(self, docs_service, drive_service, ready_folder_id: str) -> None:
        self._docs = docs_service
        self._drive = drive_service
        self._ready_folder_id = ready_folder_id

    @classmethod
    def from_service_account(
        cls,
        service_account_file: str | Path,
        ready_folder_id: str,
        *,
        credentials_factory=Credentials.from_service_account_file,
        build_service=build,
    ) -> "DriveClient":
        """Build Docs + Drive clients from a service-account key file (T3.1).

        credentials_factory/build_service are injectable so tests can supply
        fakes; in production they default to the real google-auth/discovery calls.
        """
        creds = credentials_factory(str(service_account_file), scopes=list(SCOPES))
        docs_service = build_service("docs", "v1", credentials=creds)
        drive_service = build_service("drive", "v3", credentials=creds)
        return cls(docs_service, drive_service, ready_folder_id)

    def list_ready(self) -> list[DocRef]:
        """List Google Docs in the Ready-to-Publish folder (spec 4: empty -> empty list)."""
        query = (
            f"'{self._ready_folder_id}' in parents "
            f"and mimeType = '{GOOGLE_DOC_MIMETYPE}' "
            f"and trashed = false"
        )
        refs: list[DocRef] = []
        page_token: str | None = None
        files = self._drive.files()
        while True:
            request = files.list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageSize=_PAGE_SIZE,
                pageToken=page_token,
            )
            response = _execute(request) or {}
            for entry in response.get("files", []) or []:
                # Defensive: trust the query but re-check mimeType so a non-Doc
                # can never slip through into the converter.
                if entry.get("mimeType") != GOOGLE_DOC_MIMETYPE:
                    continue
                doc_id = entry.get("id")
                if not doc_id:
                    continue
                refs.append(DocRef(doc_id=doc_id, name=entry.get("name") or doc_id))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return refs

    def fetch_document(self, doc_id: str) -> dict:
        """Return the raw Docs API document resource for doc_id (spec 5.1)."""
        request = self._docs.documents().get(documentId=doc_id)
        return _execute(request) or {}

    def move(self, doc_id: str, dest_folder: str) -> None:
        """Move a doc out of Ready into dest_folder via files.update (spec 5.1).

        Adds dest_folder as a parent and removes the Ready folder in one call so
        the doc's folder location — the system's state — flips atomically.
        """
        request = self._drive.files().update(
            fileId=doc_id,
            addParents=dest_folder,
            removeParents=self._ready_folder_id,
            fields="id, parents",
        )
        _execute(request)

    def append_note(self, doc_id: str, text: str) -> None:
        """Insert a note at the very top of the doc without clobbering the body (spec 5.1).

        Index 1 is the first editable location (index 0 is the document start);
        inserting there pushes existing content — including any prior note — down,
        so notes stack newest-first and the original body is preserved.
        """
        if not text:
            return
        note = text if text.endswith("\n") else text + "\n"
        request = self._docs.documents().batchUpdate(
            documentId=doc_id,
            body={
                "requests": [
                    {
                        "insertText": {
                            "location": {"index": 1},
                            "text": note,
                        }
                    }
                ]
            },
        )
        _execute(request)
