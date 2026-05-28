"""T5.2 image placeholder resolution: every PLACEHOLDER:objectId becomes its uploaded
Medium URL in order; an unresolved placeholder is a permanent failure (never ship a
broken image, risk R6); image-download transient/permanent routes per spec 6."""

from __future__ import annotations

from gdoc_to_medium import orchestrator
from gdoc_to_medium.config import Config, SecretStr
from gdoc_to_medium.orchestrator import ImageDownloadError
from gdoc_to_medium.types import DocRef, ImageRef, Metadata, PostResult


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


class SeqMedium:
    """upload_image returns a distinct URL per call so ordering is observable."""

    def __init__(self):
        self.uploaded = []
        self.posts = []

    def upload_image(self, data, content_type):
        url = f"https://medium.com/img/{len(self.uploaded)}"
        self.uploaded.append((data, content_type))
        return url

    def create_post(self, *, title, markdown, tags, publish_status):
        self.posts.append(markdown)
        return PostResult(url="https://medium.com/p/draft")


def test_multiple_images_resolved_in_document_order(monkeypatch):
    doc = DocRef(doc_id="d1", name="Two Pics")
    drive = FakeDrive([doc])
    medium = SeqMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: (
            "a ![x](PLACEHOLDER:imgA) b ![y](PLACEHOLDER:imgB)",
            [ImageRef(object_id="imgA"), ImageRef(object_id="imgB")],
            Metadata(title="Two Pics"),
        ),
    )
    byte_map = {"imgA": b"AAA", "imgB": b"BBB"}
    downloader = lambda ref, document: (byte_map[ref.object_id], "image/png")

    ok = orchestrator.run(drive, medium, _config(), image_downloader=downloader)

    assert ok == 1
    # Uploaded in document order, and both placeholders replaced in the posted body.
    assert [d for d, _ in medium.uploaded] == [b"AAA", b"BBB"]
    posted = medium.posts[0]
    assert "PLACEHOLDER:" not in posted
    assert "https://medium.com/img/0" in posted  # imgA
    assert "https://medium.com/img/1" in posted  # imgB
    assert posted.index("https://medium.com/img/0") < posted.index("https://medium.com/img/1")


def test_unresolved_placeholder_is_permanent_never_posted(monkeypatch):
    # convert emits a placeholder but returns NO matching ImageRef -> it can never
    # be resolved -> permanent failure, doc to Failed, post never created.
    doc = DocRef(doc_id="d1", name="Orphan Image")
    drive = FakeDrive([doc])
    medium = SeqMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("body ![x](PLACEHOLDER:ghost)", [], Metadata(title="Orphan Image")),
    )

    ok = orchestrator.run(drive, medium, _config(), image_downloader=lambda r, d: (b"", "image/png"))

    assert ok == 0
    assert medium.posts == []  # never posted a broken image
    move = next(c for c in drive.calls if c[0] == "move")
    assert move == ("move", "d1", "FAIL")
    note = next(c for c in drive.calls if c[0] == "append_note")
    assert "placeholder" in note[2].lower() or "image" in note[2].lower()


def test_image_download_transient_leaves_doc_in_ready(monkeypatch):
    doc = DocRef(doc_id="d1", name="Flaky Image")
    drive = FakeDrive([doc])
    medium = SeqMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("![x](PLACEHOLDER:img1)", [ImageRef(object_id="img1")], Metadata(title="Flaky")),
    )

    def downloader(ref, document):
        raise ImageDownloadError("network blip", transient=True)

    ok = orchestrator.run(drive, medium, _config(), image_downloader=downloader)

    assert ok == 0
    assert medium.posts == []
    assert not any(c[0] == "move" for c in drive.calls)  # left in Ready, no move


def test_image_download_permanent_routes_to_failed(monkeypatch):
    doc = DocRef(doc_id="d1", name="Dead Image")
    drive = FakeDrive([doc])
    medium = SeqMedium()
    monkeypatch.setattr(
        orchestrator, "convert",
        lambda d, f: ("![x](PLACEHOLDER:img1)", [ImageRef(object_id="img1")], Metadata(title="Dead")),
    )

    def downloader(ref, document):
        raise ImageDownloadError("403 forbidden", transient=False)

    ok = orchestrator.run(drive, medium, _config(), image_downloader=downloader)

    assert ok == 0
    assert medium.posts == []
    move = next(c for c in drive.calls if c[0] == "move")
    assert move == ("move", "d1", "FAIL")
