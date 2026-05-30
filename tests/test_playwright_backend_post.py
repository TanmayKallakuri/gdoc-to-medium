"""PlaywrightBackend.create_post: drive the editor (title, paste body, images, publish).

Asserts the control flow against a fake page (no browser): title entry, ordered HTML
pastes, image upload via the file input, draft-vs-publish, tag entry, and URL capture —
the behaviors Wave 6 (T6.2) requires, especially the image upload-then-capture path.
"""

from __future__ import annotations

from pathlib import Path

from gdoc_to_medium.medium.playwright_backend import PlaywrightBackend
from gdoc_to_medium.types import PostResult

from tests._playwright_fakes import FakePage

DRAFT_URL = "https://medium.com/p/abc123/edit"


def _backend(page, tmp_path):
    return PlaywrightBackend(page=page, temp_dir=Path(tmp_path))


def test_draft_flow_types_title_pastes_body_and_returns_url(tmp_path):
    page = FakePage(draft_url=DRAFT_URL)
    backend = _backend(page, tmp_path)

    result = backend.create_post("Filename", "# My Post\n\nHello **world**", [], "draft")

    assert isinstance(result, PostResult)
    assert result.url == DRAFT_URL
    # Title came from the body's H1 (not the filename), typed once.
    assert page.typed() == ["My Post"]
    # Body pasted as HTML.
    assert page.pastes() == ["<p>Hello <strong>world</strong></p>"]
    # A draft must NOT open the publish dialog.
    assert "click" not in page.kinds()


def test_draft_flow_navigates_to_new_story(tmp_path):
    page = FakePage(draft_url=DRAFT_URL)
    backend = _backend(page, tmp_path)
    backend.create_post("F", "# T\n\nbody", [], "draft")
    assert ("goto", "https://medium.com/new-story") in page.events


def test_publish_flow_enters_tags_and_clicks_publish(tmp_path):
    page = FakePage(draft_url=DRAFT_URL)
    backend = _backend(page, tmp_path)

    backend.create_post("F", "# T\n\nbody", ["python", "automation"], "public")

    clicks = [e[1] for e in page.events if e[0] == "click"]
    # Publish opened and confirmed (first candidate selector of each group).
    assert any("publish" in c.lower() or "Publish" in c for c in clicks)
    # Tags were typed (after the title).
    typed = page.typed()
    assert typed[0] == "T"
    assert "python" in typed and "automation" in typed


def test_tags_capped_at_five_on_publish(tmp_path):
    page = FakePage(draft_url=DRAFT_URL)
    backend = _backend(page, tmp_path)
    tags = ["a", "b", "c", "d", "e", "f", "g"]
    backend.create_post("F", "# T\n\nbody", tags, "public")
    typed = page.typed()
    entered = [t for t in typed if t in tags]
    assert entered == ["a", "b", "c", "d", "e"]  # only the first 5


def test_image_is_uploaded_through_the_file_input(tmp_path):
    page = FakePage(draft_url=DRAFT_URL)
    backend = _backend(page, tmp_path)
    sentinel = backend.upload_image(b"\x89PNG", "image/png")

    backend.create_post("F", f"# T\n\n![a cat]({sentinel})", [], "draft")

    uploads = [e for e in page.events if e[0] == "set_input_files"]
    assert len(uploads) == 1
    _, selector, files = uploads[0]
    # The stashed temp file (not a URL) is what gets uploaded.
    assert Path(files).read_bytes() == b"\x89PNG"


def test_mixed_text_and_image_preserve_document_order(tmp_path):
    page = FakePage(draft_url=DRAFT_URL)
    backend = _backend(page, tmp_path)
    sentinel = backend.upload_image(b"img", "image/png")
    md = f"# Title\n\nBefore\n\n![pic]({sentinel})\n\nAfter"

    backend.create_post("F", md, [], "draft")

    order = [e[0] for e in page.events if e[0] in ("paste", "set_input_files")]
    assert order == ["paste", "set_input_files", "paste"]
    assert page.pastes() == ["<p>Before</p>", "<p>After</p>"]
