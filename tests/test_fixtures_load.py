"""Every fixture must be valid JSON shaped like a Docs `document` resource."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "docs"


def _fixture_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.json"))


def test_fixture_directory_is_populated():
    assert _fixture_files(), "no fixtures found under tests/fixtures/docs"


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_fixture_parses_and_has_document_shape(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict)
    assert "body" in doc, f"{path.name} missing top-level 'body'"
    assert isinstance(doc["body"].get("content"), list), f"{path.name} body.content is not a list"
