"""T5.3 error routing (spec 6): transient errors leave the doc in Ready (no move);
permanent errors move it to Failed with a readable note; one bad doc never blocks
the rest of the batch."""

from __future__ import annotations

from gdoc_to_medium import orchestrator
from gdoc_to_medium.config import Config, SecretStr
from gdoc_to_medium.drive_client import TransientDriveError
from gdoc_to_medium.medium.token_backend import PermanentMediumError, TransientMediumError
from gdoc_to_medium.types import DocRef, ImageRef, Metadata, PostResult

_DOC = {"body": {"content": []}}


def _config():
    return Config(
        config_dir=".",
        service_account_file="sa.json",
        medium_token=SecretStr("tok"),
        backend="token",
        folders={"published": "PUB", "failed": "FAIL", "ready": "READY"},
    )


class FakeDrive:
    """fetch behavior keyed per doc_id: a dict value is returned, an Exception is raised."""

    def __init__(self, docs, fetch_behavior=None):
        self._docs = docs
        self._fetch = fetch_behavior or {}
        self.calls = []

    def list_ready(self):
        self.calls.append(("list_ready",))
        return self._docs

    def fetch_document(self, doc_id):
        self.calls.append(("fetch_document", doc_id))
        behavior = self._fetch.get(doc_id, _DOC)
        if isinstance(behavior, Exception):
            raise behavior
        return behavior

    def move(self, doc_id, dest):
        self.calls.append(("move", doc_id, dest))

    def append_note(self, doc_id, text):
        self.calls.append(("append_note", doc_id, text))


class FakeMedium:
    def __init__(self, *, post_exc=None):
        self._post_exc = post_exc
        self.posts = []

    def upload_image(self, data, content_type):
        return "https://medium.com/img/1"

    def create_post(self, *, title, markdown, tags, publish_status):
        if self._post_exc is not None:
            raise self._post_exc
        self.posts.append(title)
        return PostResult(url="https://medium.com/p/draft")


def _plain(title="Post"):
    return lambda d, f: ("# Body\n\nhello", [], Metadata(title=title))


def test_transient_drive_error_leaves_in_ready(monkeypatch):
    doc = DocRef(doc_id="d1", name="P")
    drive = FakeDrive([doc], fetch_behavior={"d1": TransientDriveError("429")})
    medium = FakeMedium()
    monkeypatch.setattr(orchestrator, "convert", _plain())

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 0
    assert medium.posts == []
    assert not any(c[0] == "move" for c in drive.calls)  # no move on transient


def test_transient_medium_error_leaves_in_ready(monkeypatch):
    doc = DocRef(doc_id="d1", name="P")
    drive = FakeDrive([doc])
    medium = FakeMedium(post_exc=TransientMediumError("503"))
    monkeypatch.setattr(orchestrator, "convert", _plain())

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 0
    assert not any(c[0] == "move" for c in drive.calls)


def test_permanent_medium_error_routes_to_failed_with_note(monkeypatch):
    doc = DocRef(doc_id="d1", name="P")
    drive = FakeDrive([doc])
    medium = FakeMedium(post_exc=PermanentMediumError("400 bad request"))
    monkeypatch.setattr(orchestrator, "convert", _plain())

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 0
    move = next(c for c in drive.calls if c[0] == "move")
    assert move == ("move", "d1", "FAIL")
    note = next(c for c in drive.calls if c[0] == "append_note")
    assert note[1] == "d1" and note[2]  # a human-readable reason was written


def test_one_bad_doc_does_not_stop_the_others(monkeypatch):
    docs = [DocRef("d1", "Good A"), DocRef("d2", "Bad Middle"), DocRef("d3", "Good B")]
    drive = FakeDrive(docs)
    medium = FakeMedium()

    def convert(document, filename):
        if filename == "Bad Middle":
            raise ValueError("malformed structure")  # permanent conversion crash
        return ("# ok\n\nbody", [], Metadata(title=filename))

    monkeypatch.setattr(orchestrator, "convert", convert)

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 2  # the two good docs still published
    assert sorted(medium.posts) == ["Good A", "Good B"]
    # The bad one was routed to Failed.
    assert ("move", "d2", "FAIL") in drive.calls
    assert not any(c == ("move", "d1", "FAIL") for c in drive.calls)
    assert not any(c == ("move", "d3", "FAIL") for c in drive.calls)


def test_transient_image_upload_leaves_doc_in_ready(monkeypatch):
    # A transient failure during image upload (inside _resolve_images) must route
    # like any other transient error: leave the doc in Ready, never post.
    doc = DocRef(doc_id="d1", name="Pic")
    drive = FakeDrive([doc])

    class UploadFailMedium(FakeMedium):
        def upload_image(self, data, content_type):
            raise TransientMediumError("503 uploading image")

    medium = UploadFailMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("![x](PLACEHOLDER:img1)", [ImageRef(object_id="img1")], Metadata(title="Pic")),
    )

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"x", "image/png"))

    assert ok == 0
    assert medium.posts == []
    assert not any(c[0] == "move" for c in drive.calls)


def test_missing_failed_folder_is_logged_not_raised(monkeypatch):
    # If the Failed folder id is misconfigured, the cleanup can't move the doc;
    # _route_permanent must log it and NOT re-raise, so the batch never crashes.
    doc = DocRef(doc_id="d1", name="P")
    drive = FakeDrive([doc])
    medium = FakeMedium(post_exc=PermanentMediumError("400 bad request"))
    monkeypatch.setattr(orchestrator, "convert", _plain())
    config = Config(
        config_dir=".",
        service_account_file="sa.json",
        medium_token=SecretStr("tok"),
        backend="token",
        folders={"published": "PUB", "ready": "READY"},  # no 'failed'
    )

    ok = orchestrator.run(drive, medium, config, image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 0  # did not crash the run
    assert not any(c[0] == "move" for c in drive.calls)  # dest lookup failed before move


def test_transient_on_A_success_on_B_same_run(monkeypatch):
    docs = [DocRef("dA", "A"), DocRef("dB", "B")]
    drive = FakeDrive(docs, fetch_behavior={"dA": TransientDriveError("timeout")})
    medium = FakeMedium()
    monkeypatch.setattr(orchestrator, "convert", lambda d, f: ("# x\n\ny", [], Metadata(title=f)))

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 1  # B succeeded
    assert medium.posts == ["B"]
    # A left in Ready (no move), B moved to Published.
    assert not any(c == ("move", "dA", "FAIL") for c in drive.calls)
    assert ("move", "dB", "PUB") in drive.calls
