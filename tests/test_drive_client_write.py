"""T3.3 write path: move() + append_note() against a mocked Google client.

No real network: fakes record the files.update and documents.batchUpdate request
bodies so we can assert addParents/removeParents and the insert-at-top location.
"""

from __future__ import annotations

import pytest

from gdoc_to_medium.drive_client import (
    DriveClient,
    PermanentDriveError,
    TransientDriveError,
)


def _http_error(status: int, content: bytes = b""):
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
    def __init__(self, update_error=None):
        self.update_calls = []
        self._update_error = update_error

    def update(self, **kwargs):
        self.update_calls.append(kwargs)
        return _Request(result={"id": kwargs.get("fileId")}, error=self._update_error)


class _DriveService:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


class _Documents:
    def __init__(self, batch_error=None):
        self.batch_calls = []
        self._batch_error = batch_error

    def batchUpdate(self, **kwargs):
        self.batch_calls.append(kwargs)
        return _Request(result={}, error=self._batch_error)


class _DocsService:
    def __init__(self, documents):
        self._documents = documents

    def documents(self):
        return self._documents


def _make_client(*, ready="ready-id", update_error=None, batch_error=None):
    files = _Files(update_error=update_error)
    documents = _Documents(batch_error=batch_error)
    client = DriveClient(_DocsService(documents), _DriveService(files), ready)
    return client, files, documents


def test_move_adds_dest_and_removes_ready():
    client, files, _ = _make_client(ready="ready-id")
    client.move("doc1", "published-id")
    call = files.update_calls[0]
    assert call["fileId"] == "doc1"
    assert call["addParents"] == "published-id"
    assert call["removeParents"] == "ready-id"


def test_move_to_failed_vs_published_only_changes_dest():
    client_pub, files_pub, _ = _make_client(ready="R")
    client_pub.move("d", "PUBLISHED")
    client_fail, files_fail, _ = _make_client(ready="R")
    client_fail.move("d", "FAILED")

    assert files_pub.update_calls[0]["addParents"] == "PUBLISHED"
    assert files_fail.update_calls[0]["addParents"] == "FAILED"
    # Both remove the same Ready parent — the destination is the only difference.
    assert files_pub.update_calls[0]["removeParents"] == "R"
    assert files_fail.update_calls[0]["removeParents"] == "R"


def test_move_transient_error_raised_for_retry():
    client, _, _ = _make_client(update_error=_http_error(500))
    with pytest.raises(TransientDriveError):
        client.move("d", "FAILED")


def test_move_permanent_error_raised():
    client, _, _ = _make_client(update_error=_http_error(403))
    with pytest.raises(PermanentDriveError):
        client.move("d", "FAILED")


def _insert_request(batch_call):
    requests = batch_call["body"]["requests"]
    assert len(requests) == 1
    return requests[0]["insertText"]


def test_append_note_inserts_at_top():
    client, _, documents = _make_client()
    client.append_note("doc1", "Published: https://medium.com/p/abc")
    call = documents.batch_calls[0]
    assert call["documentId"] == "doc1"
    insert = _insert_request(call)
    # Index 1 is the first editable position — the note lands above all body text.
    assert insert["location"]["index"] == 1
    assert insert["text"].startswith("Published: https://medium.com/p/abc")


def test_append_note_appends_trailing_newline():
    client, _, documents = _make_client()
    client.append_note("doc1", "one line")
    insert = _insert_request(documents.batch_calls[0])
    assert insert["text"] == "one line\n"


def test_append_note_preserves_existing_newline():
    client, _, documents = _make_client()
    client.append_note("doc1", "already ends\n")
    insert = _insert_request(documents.batch_calls[0])
    assert insert["text"] == "already ends\n"


def test_append_note_multiline_text_kept_intact():
    client, _, documents = _make_client()
    note = "Failed to publish.\nReason: 401 Unauthorized\nNext: re-check the token."
    client.append_note("doc1", note)
    insert = _insert_request(documents.batch_calls[0])
    assert insert["text"] == note + "\n"
    assert insert["text"].count("\n") == 3


def test_append_note_when_prior_note_exists_does_not_clobber_body():
    # Two appends in sequence: each inserts at index 1, so the second note ends up
    # above the first and neither overwrites the original body (insert never deletes).
    client, _, documents = _make_client()
    client.append_note("doc1", "first note")
    client.append_note("doc1", "second note")
    assert len(documents.batch_calls) == 2
    for call in documents.batch_calls:
        insert = _insert_request(call)
        assert insert["location"]["index"] == 1
        # insertText only inserts; there is no deleteContentRange that would touch the body.
        assert "deleteContentRange" not in str(call["body"]["requests"])


def test_append_note_empty_text_is_noop():
    client, _, documents = _make_client()
    client.append_note("doc1", "")
    assert documents.batch_calls == []


def test_append_note_transient_error_raised_for_retry():
    client, _, _ = _make_client(batch_error=_http_error(429))
    with pytest.raises(TransientDriveError):
        client.append_note("doc1", "note")


def test_append_note_permanent_error_raised():
    client, _, _ = _make_client(batch_error=_http_error(400))
    with pytest.raises(PermanentDriveError):
        client.append_note("doc1", "note")
