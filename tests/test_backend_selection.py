"""Backend selection: config parsing of backend/[playwright] and cli._build_medium dispatch.

Confirms `backend = "token" | "playwright"` picks the right implementation, the orchestrator
depends only on the MediumBackend Protocol, and a Playwright dry-run launches no browser.
"""

from __future__ import annotations

import contextlib

import pytest

from gdoc_to_medium import cli
from gdoc_to_medium.config import ConfigError, load_config
from gdoc_to_medium.logging_setup import setup_logging
from gdoc_to_medium.medium.playwright_backend import PlaywrightBackend
from gdoc_to_medium.medium.token_backend import TokenBackend
from gdoc_to_medium.types import MediumBackend

from tests._playwright_fakes import FakePage


def _write(tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_default_backend_is_token(tmp_path):
    cfg = load_config(_write(tmp_path, 'service_account_file = "sa.json"\nmedium_token = "t"\n'))
    assert cfg.backend == "token"


def test_playwright_backend_allows_empty_token(tmp_path):
    cfg = load_config(
        _write(tmp_path, 'service_account_file = "sa.json"\nbackend = "playwright"\n')
    )
    assert cfg.backend == "playwright"
    assert cfg.medium_token.get() == ""


def test_invalid_backend_rejected(tmp_path):
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, 'service_account_file = "sa.json"\nbackend = "ftp"\n'))


def test_playwright_settings_parsed(tmp_path):
    body = (
        'service_account_file = "sa.json"\n'
        'backend = "playwright"\n'
        "[playwright]\n"
        'session_dir = "D:/sessions/medium"\n'
        "headless = false\n"
    )
    cfg = load_config(_write(tmp_path, body))
    assert cfg.playwright_session_dir == "D:/sessions/medium"
    assert cfg.playwright_headless is False


def test_invalid_headless_rejected(tmp_path):
    body = (
        'service_account_file = "sa.json"\n'
        'backend = "playwright"\n'
        "[playwright]\n"
        'headless = "yes"\n'
    )
    with pytest.raises(ConfigError):
        load_config(_write(tmp_path, body))


def test_build_medium_token_returns_token_backend(tmp_path):
    cfg = load_config(_write(tmp_path, 'service_account_file = "sa.json"\nmedium_token = "tok"\n'))
    redactor = setup_logging()
    with contextlib.ExitStack() as stack:
        backend = cli._build_medium(cfg, redactor, stack, dry_run=False)
    assert isinstance(backend, TokenBackend)
    assert isinstance(backend, MediumBackend)


def test_build_medium_playwright_dry_run_launches_no_browser(tmp_path, monkeypatch):
    cfg = load_config(_write(tmp_path, 'service_account_file = "sa.json"\nbackend = "playwright"\n'))
    redactor = setup_logging()

    def _boom(*a, **k):
        raise AssertionError("dry-run must not launch a browser")

    monkeypatch.setattr(cli.pw_session, "launch_page", _boom)
    with contextlib.ExitStack() as stack:
        backend = cli._build_medium(cfg, redactor, stack, dry_run=True)
    assert isinstance(backend, PlaywrightBackend)
    assert isinstance(backend, MediumBackend)


def test_build_medium_playwright_live_uses_launched_page(tmp_path, monkeypatch):
    cfg = load_config(_write(tmp_path, 'service_account_file = "sa.json"\nbackend = "playwright"\n'))
    redactor = setup_logging()
    fake_page = FakePage()

    @contextlib.contextmanager
    def _fake_launch(session_dir, *, headless=True):
        yield fake_page

    monkeypatch.setattr(cli.pw_session, "launch_page", _fake_launch)
    with contextlib.ExitStack() as stack:
        backend = cli._build_medium(cfg, redactor, stack, dry_run=False)
        assert isinstance(backend, PlaywrightBackend)
        assert backend._page is fake_page  # noqa: SLF001
