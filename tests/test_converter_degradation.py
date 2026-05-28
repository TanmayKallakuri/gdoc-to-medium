"""T2.8 graceful degradation: out-of-scope elements must not crash (spec 5.2, 8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gdoc_to_medium.converter import convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"

OUT_OF_SCOPE_FIXTURES = [
    "out_of_scope_table.json",
    "out_of_scope_footnote.json",
    "out_of_scope_suggestion.json",
    "out_of_scope_blockquote.json",
    "out_of_scope_columns.json",
]


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", OUT_OF_SCOPE_FIXTURES)
def test_out_of_scope_fixture_does_not_raise(name: str):
    md, refs, meta = convert(_load(name), "x")
    assert isinstance(md, str)
    assert isinstance(refs, list)
    assert meta.title == "x"


def test_table_content_passes_through_as_plain_text_and_neighbors_survive():
    md, _, _ = convert(_load("out_of_scope_table.json"), "x")
    assert "Before the table." in md
    assert "After the table." in md
    # Cell text is preserved rather than dropped.
    assert "Cell A1" in md
    assert "Cell B2" in md


def test_footnote_reference_dropped_but_surrounding_text_kept():
    md, _, _ = convert(_load("out_of_scope_footnote.json"), "x")
    assert "A claim with a footnote right here." in md


def test_suggestion_runs_pass_through_as_resolved_text():
    md, _, _ = convert(_load("out_of_scope_suggestion.json"), "x")
    # Tracked-change markers are ignored; the text content survives.
    assert "Original kept" in md
    assert "plus a normal tail." in md


def test_blockquote_indent_degrades_to_a_paragraph():
    md, _, _ = convert(_load("out_of_scope_blockquote.json"), "x")
    assert "An ordinary lead-in." in md
    assert "A quoted passage that Docs indents." in md
    assert "Back to normal flow." in md


def test_columns_section_break_dropped_content_survives():
    md, _, _ = convert(_load("out_of_scope_columns.json"), "x")
    assert "Text that lives inside a two-column section." in md


def test_gappy_document_survives_and_converts_the_rest():
    md, refs, meta = convert(_load("gappy.json"), "Gappy.gdoc")
    assert "Survivor text after several malformed elements." in md
    assert meta.title == "Gappy"


def test_combined_fixture_converts_every_element_together():
    md, refs, meta = convert(_load("combined.json"), "Everything.gdoc")
    assert meta.title == "Everything"
    assert meta.tags == ["demo", "combined"]
    assert meta.publish_status == "public"
    assert "# Everything Together" in md
    assert "# Introduction" in md
    assert "**bold**" in md
    assert "_italic_" in md
    assert "[link](https://example.com)" in md
    assert "`code()`" in md
    assert "- Point one" in md
    assert "- Point two" in md
    assert "```\nimport sys\nsys.exit(0)\n```" in md
    assert "![A combined figure](PLACEHOLDER:kix.fig)" in md
    assert [r.object_id for r in refs] == ["kix.fig"]
    assert "Tags:" not in md
    assert "Status:" not in md
