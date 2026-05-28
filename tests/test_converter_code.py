"""T2.5 code: inline monospace runs and coalesced fenced blocks."""

from __future__ import annotations

import json
from pathlib import Path

from gdoc_to_medium.converter import MONOSPACE_FONTS, convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _para(elements: list) -> dict:
    return {"paragraph": {"elements": elements, "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"}}}


def _mono(text: str, font: str = "Consolas") -> dict:
    return {"textRun": {"content": text, "textStyle": {"weightedFontFamily": {"fontFamily": font}}}}


def test_inline_monospace_run_becomes_backticked_code():
    md, _, _ = convert(_load("code.json"), "x")
    assert "Call `print(x)` to see it." in md


def test_consecutive_monospace_paragraphs_coalesce_into_one_fence():
    md, _, _ = convert(_load("code.json"), "x")
    expected = "```\ndef greet(name):\n    return f\"hi {name}\"\n```"
    assert expected in md


def test_code_block_does_not_swallow_following_prose():
    md, _, _ = convert(_load("code.json"), "x")
    assert "```\n\nBack to normal prose here." in md


def test_inline_monospace_adjacent_to_normal_text_is_isolated():
    doc = {"body": {"content": [_para([
        {"textRun": {"content": "x=", "textStyle": {}}},
        _mono("compute()"),
        {"textRun": {"content": " here\n", "textStyle": {}}},
    ])]}}
    md, _, _ = convert(doc, "x")
    assert md == "x=`compute()` here"


def test_documented_monospace_set_is_recognized():
    # Each pinned font, when it is the sole font of a paragraph, yields a fenced block.
    for font in ["Consolas", "Courier New", "Roboto Mono", "Source Code Pro"]:
        doc = {"body": {"content": [_para([_mono("code_line\n", font)])]}}
        md, _, _ = convert(doc, "x")
        assert md == "```\ncode_line\n```", f"{font} not treated as code"


def test_non_monospace_font_is_not_code():
    doc = {"body": {"content": [_para([
        {"textRun": {"content": "just prose\n", "textStyle": {"weightedFontFamily": {"fontFamily": "Arial"}}}},
    ])]}}
    md, _, _ = convert(doc, "x")
    assert "`" not in md
    assert md == "just prose"


def test_monospace_set_pinned_and_lowercased():
    assert "consolas" in MONOSPACE_FONTS
    assert "courier new" in MONOSPACE_FONTS
    assert "roboto mono" in MONOSPACE_FONTS
    assert "source code pro" in MONOSPACE_FONTS
    assert all(f == f.lower() for f in MONOSPACE_FONTS)


def test_font_matching_is_case_insensitive():
    doc = {"body": {"content": [_para([_mono("code\n", "CONSOLAS")])]}}
    md, _, _ = convert(doc, "x")
    assert md == "```\ncode\n```"
