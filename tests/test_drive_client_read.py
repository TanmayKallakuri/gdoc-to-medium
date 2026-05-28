"""T3.2 read path: list_ready() + fetch_document() against a mocked Google client.

No real network: fakes mimic the discovery client's builder chain
(drive.files().list(...).execute()) and record the arguments passed.
"""

from __future__ import annotations

import pytest

from gdoc_to_medium.drive_client import (
    GOOGLE_DOC_MIMETYPE,
    DriveClient,
    PermanentDriveError,
    TransientDriveError,
)
from gdoc_to_medium.types import DocRef


def _http_error(status: int, content: bytes = b""):
    """Build a realistic googleapiclient HttpError with the given status code."""
    from googleapiclient.errors import HttpError

    class _Resp:
        def __init__(self, status):
            self.status = status
            self.reason = "error"

    return HttpError(_Resp(status), content)


class _Request:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _Files:
    """Stands in for drive.files(); returns queued list pages and records list() kwargs."""

    def __init__(self, pages):
        self._pages = list(pages)
        self.list_calls = []
        self.update_calls = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        page = self._pages.pop(0) if self._pages else {}
        return _Request(result=page)

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return _Request(result={"id": kwargs.get("fileId")})


class _DriveService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


class _Documents:
    def __init__(self, *, get_result=None, get_error=None):
        self._get_result = get_result
        self._get_error = get_error
        self.get_calls = []
        self.batch_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _Request(result=self._get_result, error=self._get_error)

    def batchUpdate(self, **kwargs):
        self.batch_calls.append(kwargs)
        return _Request(result={})


class _DocsService:
    def __init__(self, documents):
        self._documents = documents

    def documents(self):
        return self._documents


def _doc_file(file_id, name):
    return {"id": file_id, "name": name, "mimeType": GOOGLE_DOC_MIMETYPE}


def _make_client(pages, *, ready="ready-id", docs=None):
    files = _Files(pages)
    drive = _DriveService(files)
    documents = docs or _Documents()
    docs_service = _DocsService(documents)
    client = DriveClient(docs_service, drive, ready)
    return client, files, documents


def test_empty_folder_returns_empty_list():
    client, files, _ = _make_client([{"files": []}])
    assert client.list_ready() == []
    assert len(files.list_calls) == 1


def test_query_filters_by_parent_folder_and_doc_mimetype():
    client, files, _ = _make_client([{"files": []}], ready="parent-xyz")
    client.list_ready()
    q = files.list_calls[0]["q"]
    assert "'parent-xyz' in parents" in q
    assert GOOGLE_DOC_MIMETYPE in q
    assert "trashed = false" in q


def test_returns_docrefs_for_each_doc():
    page = {"files": [_doc_file("d1", "First"), _doc_file("d2", "Second")]}
    client, _, _ = _make_client([page])
    refs = client.list_ready()
    assert refs == [DocRef("d1", "First"), DocRef("d2", "Second")]


def test_non_doc_files_in_folder_ignored():
    page = {
        "files": [
            _doc_file("d1", "Real Doc"),
            {"id": "s1", "name": "sheet", "mimeType": "application/vnd.google-apps.spreadsheet"},
            {"id": "f1", "name": "pdf", "mimeType": "application/pdf"},
        ]
    }
    client, _, _ = _make_client([page])
    refs = client.list_ready()
    assert refs == [DocRef("d1", "Real Doc")]


def test_pagination_followed_across_two_pages():
    page1 = {"files": [_doc_file("d1", "One")], "nextPageToken": "TOKEN2"}
    page2 = {"files": [_doc_file("d2", "Two")]}
    client, files, _ = _make_client([page1, page2])
    refs = client.list_ready()
    assert refs == [DocRef("d1", "One"), DocRef("d2", "Two")]
    # Two list calls; the second carried the token from the first response.
    assert len(files.list_calls) == 2
    assert files.list_calls[0]["pageToken"] is None
    assert files.list_calls[1]["pageToken"] == "TOKEN2"


def test_file_missing_id_skipped_not_crash():
    page = {"files": [{"name": "no id", "mimeType": GOOGLE_DOC_MIMETYPE}, _doc_file("d2", "Two")]}
    client, _, _ = _make_client([page])
    assert client.list_ready() == [DocRef("d2", "Two")]


def test_fetch_document_returns_raw_resource():
    resource = {"documentId": "d1", "body": {"content": [{"paragraph": {}}]}}
    docs = _Documents(get_result=resource)
    client, _, documents = _make_client([{"files": []}], docs=docs)
    result = client.fetch_document("d1")
    assert result == resource
    assert documents.get_calls[0]["documentId"] == "d1"


def test_fetch_document_4xx_classified_permanent():
    docs = _Documents(get_error=_http_error(404, b"not found"))
    client, _, _ = _make_client([{"files": []}], docs=docs)
    with pytest.raises(PermanentDriveError):
        client.fetch_document("missing")


def test_fetch_document_5xx_classified_transient():
    docs = _Documents(get_error=_http_error(503, b"unavailable"))
    client, _, _ = _make_client([{"files": []}], docs=docs)
    with pytest.raises(TransientDriveError):
        client.fetch_document("d1")
