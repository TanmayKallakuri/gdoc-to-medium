"""T2.2 block elements: title, headings, paragraphs."""

from __future__ import annotations

import json
from pathlib import Path

from gdoc_to_medium.converter import convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_title_and_each_heading_level():
    md, _, _ = convert(_load("title_and_headings.json"), "Doc.gdoc")
    lines = md.splitlines()
    # Title stays in the body as a single hash (Medium's title field does not render).
    assert "# My Great Post" in lines
    assert "# First Section" in lines
    assert "## A Subsection" in lines
    assert "### Level Three" in lines
    assert "#### Level Four" in lines
    assert "##### Level Five" in lines
    assert "###### Level Six" in lines


def test_normal_paragraphs_kept_with_blank_line_separation():
    md, _, _ = convert(_load("title_and_headings.json"), "Doc.gdoc")
    assert "A normal body paragraph of prose." in md
    assert "A second body paragraph." in md
    block = "A normal body paragraph of prose.\n\nA second body paragraph."
    assert block in md


def test_heading_separated_from_following_paragraph_by_blank_line():
    md, _, _ = convert(_load("title_and_headings.json"), "Doc.gdoc")
    assert "###### Level Six\n\nA normal body paragraph of prose." in md


def test_empty_document_yields_empty_body_not_crash():
    md, refs, meta = convert(_load("empty.json"), "Empty.gdoc")
    assert md == ""
    assert refs == []
    assert meta.title == "Empty"


def test_none_and_missing_body_do_not_crash():
    assert convert(None, "x")[0] == ""
    assert convert({}, "x")[0] == ""
    assert convert({"body": {}}, "x")[0] == ""
    assert convert({"body": {"content": "not a list"}}, "x")[0] == ""
