"""T5.1 core loop: one ready doc runs fetch -> convert -> upload images ->
create_post -> move(Published) -> append review URL, in that order.

All collaborators are mocked and record an ordered call log so we can assert the
SEQUENCE, not just that each step ran. Edge cases: a doc with zero images skips
the upload step; a doc that converts to an empty body is a permanent failure and
is never posted.
"""

from __future__ import annotations

import pytest

from gdoc_to_medium import orchestrator
from gdoc_to_medium.config import Config, SecretStr
from gdoc_to_medium.types import DocRef, ImageRef, Metadata, PostResult

REVIEW_URL = "https://medium.com/p/draft-123"


def _config():
    return Config(
        config_dir=".",
        service_account_file="sa.json",
        medium_token=SecretStr("tok"),
        backend="token",
        folders={"published": "PUB", "failed": "FAIL", "ready": "READY"},
    )


class FakeDrive:
    def __init__(self, docs, document=None):
        self._docs = docs
        self._document = document if document is not None else {"body": {"content": []}}
        self.calls = []

    def list_ready(self):
        self.calls.append(("list_ready",))
        return self._docs

    def fetch_document(self, doc_id):
        self.calls.append(("fetch_document", doc_id))
        return self._document

    def move(self, doc_id, dest):
        self.calls.append(("move", doc_id, dest))

    def append_note(self, doc_id, text):
        self.calls.append(("append_note", doc_id, text))


class FakeMedium:
    def __init__(self, *, upload_url="https://medium.com/img/1", post_url=REVIEW_URL):
        self._upload_url = upload_url
        self._post_url = post_url
        self.calls = []

    def upload_image(self, data, content_type):
        self.calls.append(("upload_image", content_type))
        return self._upload_url

    def create_post(self, *, title, markdown, tags, publish_status):
        self.calls.append(("create_post", title, markdown, tags, publish_status))
        return PostResult(url=self._post_url)


def _downloader_for(byte_map):
    def download(ref, document):
        return byte_map[ref.object_id], "image/png"
    return download


def test_happy_path_call_sequence(monkeypatch):
    doc = DocRef(doc_id="d1", name="My Post")
    drive = FakeDrive([doc])
    medium = FakeMedium()

    def fake_convert(document, filename):
        return ("# My Post\n\n![pic](PLACEHOLDER:img1)", [ImageRef(object_id="img1")], Metadata(title="My Post", tags=["t"], publish_status="draft"))

    monkeypatch.setattr(orchestrator, "convert", fake_convert)

    ok = orchestrator.run(drive, medium, _config(), image_downloader=_downloader_for({"img1": b"PNG"}))

    assert ok == 1
    sequence = [c[0] for c in drive.calls] + [c[0] for c in medium.calls]
    # Interleave preserved: list -> fetch -> upload -> create_post -> move -> append.
    assert drive.calls[0] == ("list_ready",)
    assert drive.calls[1] == ("fetch_document", "d1")
    assert medium.calls[0][0] == "upload_image"
    assert medium.calls[1][0] == "create_post"
    move_call = next(c for c in drive.calls if c[0] == "move")
    append_call = next(c for c in drive.calls if c[0] == "append_note")
    assert move_call == ("move", "d1", "PUB")
    assert REVIEW_URL in append_call[2]
    # Ordering within drive: fetch before move, move before append.
    assert drive.calls.index(("fetch_document", "d1")) < drive.calls.index(move_call)
    assert drive.calls.index(move_call) < drive.calls.index(append_call)


def test_upload_runs_before_create_post(monkeypatch):
    doc = DocRef(doc_id="d1", name="P")
    drive = FakeDrive([doc])
    medium = FakeMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("body ![a](PLACEHOLDER:o1)", [ImageRef(object_id="o1")], Metadata(title="P")),
    )
    orchestrator.run(drive, medium, _config(), image_downloader=_downloader_for({"o1": b"x"}))
    kinds = [c[0] for c in medium.calls]
    assert kinds.index("upload_image") < kinds.index("create_post")


def test_zero_images_skips_upload(monkeypatch):
    doc = DocRef(doc_id="d1", name="No Images")
    drive = FakeDrive([doc])
    medium = FakeMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("# No Images\n\nplain text only", [], Metadata(title="No Images")),
    )

    def downloader(ref, document):
        raise AssertionError("downloader must not be called when there are no images")

    ok = orchestrator.run(drive, medium, _config(), image_downloader=downloader)
    assert ok == 1
    assert not any(c[0] == "upload_image" for c in medium.calls)
    assert any(c[0] == "create_post" for c in medium.calls)


def test_empty_body_is_permanent_never_posted(monkeypatch):
    doc = DocRef(doc_id="d1", name="Empty")
    drive = FakeDrive([doc])
    medium = FakeMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("   \n  ", [], Metadata(title="Empty")),
    )
    ok = orchestrator.run(drive, medium, _config(), image_downloader=_downloader_for({}))
    assert ok == 0
    # Never posted; routed to Failed with a reason.
    assert not any(c[0] == "create_post" for c in medium.calls)
    move_call = next(c for c in drive.calls if c[0] == "move")
    assert move_call == ("move", "d1", "FAIL")
    note = next(c for c in drive.calls if c[0] == "append_note")
    assert "empty" in note[2].lower()


def test_empty_ready_folder_processes_nothing():
    drive = FakeDrive([])
    medium = FakeMedium()
    ok = orchestrator.run(drive, medium, _config(), image_downloader=_downloader_for({}))
    assert ok == 0
    assert drive.calls == [("list_ready",)]
    assert medium.calls == []
