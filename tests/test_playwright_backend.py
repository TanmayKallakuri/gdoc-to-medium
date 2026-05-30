"""PlaywrightBackend: image stashing, session/auth handling, title derivation, cleanup.

All against a fake page (tests/_playwright_fakes.FakePage) — no browser, no network,
mirroring how TokenBackend is tested against a fake httpx client.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gdoc_to_medium.medium.playwright_backend import (
    PlaywrightBackend,
    PlaywrightSessionError,
    PlaywrightUIError,
    _split_title,
)
from gdoc_to_medium.types import MediumBackend, PostResult

from tests._playwright_fakes import FakePage


def _backend(page, tmp_path) -> PlaywrightBackend:
    return PlaywrightBackend(page=page, temp_dir=Path(tmp_path))


def test_is_a_medium_backend():
    # Runtime-checkable Protocol: orchestrator depends only on this shape.
    assert isinstance(PlaywrightBackend(page=FakePage()), MediumBackend)


def test_upload_image_stashes_bytes_and_returns_unique_sentinel(tmp_path):
    backend = _backend(FakePage(), tmp_path)
    url1 = backend.upload_image(b"\x89PNG-data", "image/png")
    url2 = backend.upload_image(b"GIF-data", "image/gif")

    assert url1 != url2
    assert url1.startswith("https://gdoc2medium.local/img/")
    assert url1.endswith(".png") and url2.endswith(".gif")
    # The bytes were written and are recoverable for the later editor upload.
    stashed = backend._images[url1]  # noqa: SLF001
    assert stashed.read_bytes() == b"\x89PNG-data"


def test_upload_image_unknown_content_type_still_stashes(tmp_path):
    backend = _backend(FakePage(), tmp_path)
    url = backend.upload_image(b"data", "application/octet-stream")
    assert url.endswith(".img")
    assert backend._images[url].read_bytes() == b"data"  # noqa: SLF001


def test_health_check_true_when_signed_in(tmp_path):
    backend = _backend(FakePage(signed_in=True, draft_url=None), tmp_path)
    assert backend.health_check() is True


def test_health_check_false_when_signin_redirect(tmp_path):
    backend = _backend(FakePage(signed_in=False), tmp_path)
    assert backend.health_check() is False


def test_create_post_raises_session_error_when_not_signed_in(tmp_path):
    backend = _backend(FakePage(signed_in=False), tmp_path)
    with pytest.raises(PlaywrightSessionError):
        backend.create_post("T", "# T\n\nhi", [], "draft")


def test_create_post_raises_ui_error_when_editor_missing(tmp_path):
    # Signed in (markers present via goto not hitting signin) but the editor selector
    # never resolves -> a UI change, surfaced as a (transient) PlaywrightUIError.
    page = FakePage(present={"a[href=\"/new-story\"]"}, draft_url="https://medium.com/p/x/edit")
    backend = _backend(page, tmp_path)
    with pytest.raises(PlaywrightUIError):
        backend.create_post("T", "# T\n\nhi", [], "draft")


def test_close_removes_owned_temp_dir():
    backend = PlaywrightBackend(page=FakePage())  # owns its temp dir
    tmp = backend._temp_dir  # noqa: SLF001
    backend.upload_image(b"x", "image/png")
    assert tmp.exists()
    backend.close()
    assert not tmp.exists()


def test_close_does_not_remove_injected_temp_dir(tmp_path):
    backend = _backend(FakePage(), tmp_path)
    backend.close()
    assert Path(tmp_path).exists()  # caller-owned dir is left alone


@pytest.mark.parametrize(
    "title, markdown, expected_title, expected_body",
    [
        ("File Name", "# Doc Heading\n\nbody", "Doc Heading", "body"),
        ("File Name", "no heading here\n\nmore", "File Name", "no heading here\n\nmore"),
        ("File Name", "## Not H1\n\nbody", "File Name", "## Not H1\n\nbody"),
        ("File Name", "\n\n# Heading after blanks\n\nb", "Heading after blanks", "b"),
    ],
)
def test_split_title(title, markdown, expected_title, expected_body):
    assert _split_title(title, markdown) == (expected_title, expected_body)
