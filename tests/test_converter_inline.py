"""T2.3 inline styling: bold, italic, links, and their edge cases."""

from __future__ import annotations

import json
from pathlib import Path

from gdoc_to_medium.converter import convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _convert_para(elements: list) -> str:
    doc = {"body": {"content": [{"paragraph": {"elements": elements, "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}}}]}}
    return convert(doc, "x")[0]


def test_bold_and_italic_runs():
    md, _, _ = convert(_load("inline_styles.json"), "x")
    assert "Plain then **bold** and _italic_ words." in md


def test_link_run_becomes_markdown_link():
    md, _, _ = convert(_load("inline_styles.json"), "x")
    assert "See [the docs](https://example.com/docs) for more." in md


def test_bold_and_italic_on_same_run():
    md, _, _ = convert(_load("inline_styles.json"), "x")
    assert "Both _**at once**_ here." in md


def test_bold_link_wraps_link_around_bold_text():
    md, _, _ = convert(_load("inline_styles.json"), "x")
    assert "A [**bold link**](https://example.com/bold) text." in md


def test_run_with_no_textstyle_passes_through_plain():
    md, _, _ = convert(_load("inline_styles.json"), "x")
    assert "No style object at all on this run." in md


def test_emphasis_does_not_swallow_surrounding_whitespace():
    out = _convert_para([
        {"textRun": {"content": "before ", "textStyle": {}}},
        {"textRun": {"content": "word ", "textStyle": {"bold": True}}},
        {"textRun": {"content": "after\n", "textStyle": {}}},
    ])
    # Trailing space stays OUTSIDE the bold markers so Markdown renders it.
    assert out == "before **word** after"


def test_whitespace_only_styled_run_is_not_wrapped():
    out = _convert_para([
        {"textRun": {"content": "a", "textStyle": {"bold": True}}},
        {"textRun": {"content": "   ", "textStyle": {"bold": True}}},
        {"textRun": {"content": "b\n", "textStyle": {}}},
    ])
    assert "** **" not in out
    assert out == "**a**   b"


def test_link_with_empty_url_falls_back_to_plain_text():
    out = _convert_para([
        {"textRun": {"content": "text\n", "textStyle": {"link": {"url": ""}}}},
    ])
    assert out == "text"
