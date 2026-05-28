"""T2.7 metadata: title from filename, Tags: and Status: directive lines."""

from __future__ import annotations

import json
from pathlib import Path

from gdoc_to_medium.converter import convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _para(text: str) -> dict:
    return {"paragraph": {"elements": [{"textRun": {"content": text, "textStyle": {}}}],
                          "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}}}


def _doc(*texts: str) -> dict:
    return {"body": {"content": [_para(t) for t in texts]}}


def test_title_comes_from_filename_with_extension_stripped():
    _, _, meta = convert(_load("metadata.json"), "How I Ship.gdoc")
    assert meta.title == "How I Ship"


def test_title_strips_known_extensions_only():
    assert convert(_doc("body\n"), "Post.docx")[2].title == "Post"
    assert convert(_doc("body\n"), "Post.md")[2].title == "Post"
    assert convert(_doc("body\n"), "Plain Title")[2].title == "Plain Title"
    assert convert(_doc("body\n"), "weird.name.gdoc")[2].title == "weird.name"


def test_tags_parsed_trimmed_deduped_and_capped_at_five():
    _, _, meta = convert(_load("metadata.json"), "x")
    # Source line: "python, automation , medium ,, , devtools, docs, extra-six"
    # whitespace trimmed, empty entries dropped, capped at 5.
    assert meta.tags == ["python", "automation", "medium", "devtools", "docs"]


def test_status_publish_sets_public():
    _, _, meta = convert(_load("metadata.json"), "x")
    assert meta.publish_status == "public"


def test_tags_and_status_lines_removed_from_body():
    md, _, _ = convert(_load("metadata.json"), "x")
    assert "Tags:" not in md
    assert "Status:" not in md
    assert "The actual body of the post starts here." in md
    # Title line is still kept in the body.
    assert "# My Article" in md


def test_no_tags_line_yields_empty_tags():
    _, _, meta = convert(_load("metadata_minimal.json"), "x")
    assert meta.tags == []


def test_missing_status_defaults_to_draft():
    _, _, meta = convert(_load("metadata_minimal.json"), "x")
    assert meta.publish_status == "draft"


def test_status_key_is_case_insensitive():
    _, _, meta = convert(_doc("body\n", "status: publish\n"), "x")
    assert meta.publish_status == "public"


def test_status_value_is_case_insensitive():
    _, _, meta = convert(_doc("body\n", "Status: PUBLISH\n"), "x")
    assert meta.publish_status == "public"


def test_status_other_value_is_draft():
    _, _, meta = convert(_doc("body\n", "Status: hold\n"), "x")
    assert meta.publish_status == "draft"


def test_tags_all_empty_entries_yield_no_tags():
    _, _, meta = convert(_doc("Tags:  , ,,  \n", "body\n"), "x")
    assert meta.tags == []


def test_more_than_five_tags_truncated_to_first_five():
    _, _, meta = convert(_doc("Tags: a, b, c, d, e, f, g\n", "body\n"), "x")
    assert meta.tags == ["a", "b", "c", "d", "e"]
