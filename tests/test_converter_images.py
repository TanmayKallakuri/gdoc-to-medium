"""T2.6 inline images: PLACEHOLDER markdown plus an ImageRef per image."""

from __future__ import annotations

import json
from pathlib import Path

from gdoc_to_medium.converter import convert
from gdoc_to_medium.types import ImageRef

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_image_emits_placeholder_with_alt_and_object_id():
    md, refs, _ = convert(_load("images.json"), "x")
    assert "![Architecture diagram of the system](PLACEHOLDER:kix.img1)" in md


def test_image_with_no_alt_uses_empty_alt():
    md, refs, _ = convert(_load("images.json"), "x")
    assert "![](PLACEHOLDER:kix.img2)" in md


def test_image_alone_in_paragraph_renders_on_its_own():
    md, _, _ = convert(_load("images.json"), "x")
    assert "![Standalone photo](PLACEHOLDER:kix.img3)" in md


def test_one_image_ref_per_image_in_order():
    _, refs, _ = convert(_load("images.json"), "x")
    assert [r.object_id for r in refs] == ["kix.img1", "kix.img2", "kix.img3"]


def test_image_ref_carries_alt_and_content_uri_for_orchestrator():
    _, refs, _ = convert(_load("images.json"), "x")
    by_id = {r.object_id: r for r in refs}
    assert by_id["kix.img1"] == ImageRef(
        object_id="kix.img1",
        content_uri="https://lh3.googleusercontent.com/docs/img1",
        alt="Architecture diagram of the system",
    )
    assert by_id["kix.img2"].alt == ""
    assert by_id["kix.img2"].content_uri == "https://lh3.googleusercontent.com/docs/img2"


def test_image_with_missing_inline_object_still_placeholder_no_crash():
    md, refs, _ = convert(_load("gappy.json"), "x")
    assert "![](PLACEHOLDER:kix.missingobject)" in md
    assert any(r.object_id == "kix.missingobject" for r in refs)


def test_inline_image_keeps_surrounding_text():
    md, _, _ = convert(_load("images.json"), "x")
    assert "Here is a figure: ![Architecture diagram of the system](PLACEHOLDER:kix.img1) and some text after." in md
