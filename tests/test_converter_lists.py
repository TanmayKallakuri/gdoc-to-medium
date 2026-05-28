"""T2.4 lists: bulleted, numbered, and degradation of nested lists to flat."""

from __future__ import annotations

import json
from pathlib import Path

from gdoc_to_medium.converter import convert

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_bulleted_list_items_use_dash():
    md, _, _ = convert(_load("lists.json"), "x")
    assert "- Apples" in md
    assert "- Pears" in md


def test_numbered_list_items_use_one_dot():
    md, _, _ = convert(_load("lists.json"), "x")
    assert "1. First do this" in md
    assert "1. Then that" in md


def test_consecutive_items_are_adjacent_lines():
    md, _, _ = convert(_load("lists.json"), "x")
    assert "- Apples\n- Pears" in md


def test_list_immediately_after_heading():
    md, _, _ = convert(_load("lists.json"), "x")
    assert "## Shopping list\n\n- Apples" in md


def test_single_item_list_still_renders_a_marker():
    md, _, _ = convert(_load("lists.json"), "x")
    assert "- Lonely item" in md


def test_nested_list_degrades_to_flat_without_crash():
    md, refs, meta = convert(_load("nested_list.json"), "x")
    # All three items survive as flat bullets; nesting (level 1) is dropped, not crashed.
    assert "- Top level one" in md
    assert "- Child of one" in md
    assert "- Top level two" in md
    assert refs == []


def test_bullet_with_dangling_list_id_defaults_to_unordered():
    md, _, _ = convert(_load("gappy.json"), "x")
    assert "- Bullet with missing list reference" in md


def test_nested_ordered_list_marks_all_items_numbered_known_v1_limitation():
    # ACCEPTED v1 degradation (spec 5.2): orderness is read from nestingLevels[0], so a
    # DECIMAL-at-level-0 list renders its level-1 child as "1." too. This pins that the
    # mismark is intentional, not accidental; a per-level read is out of scope for v1.
    md, _, _ = convert(_load("nested_ordered_list.json"), "x")
    assert "1. Top numbered item" in md
    assert "1. Nested item at level one" in md
    assert "- Nested item at level one" not in md
