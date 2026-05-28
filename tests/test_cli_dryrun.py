"""T5.4 CLI: --dry-run converts and prints, makes no Medium calls and no file moves;
empty Ready prints a clear "nothing to do"; the redactor is wired into the backend."""

from __future__ import annotations

import pytest

from gdoc_to_medium import cli
from gdoc_to_medium.config import Config, ConfigError, SecretStr
from gdoc_to_medium.logging_setup import RedactingFilter
from gdoc_to_medium.types import DocRef, PostResult

# A minimal real Docs document the real converter turns into "Hello world".
_DOCUMENT = {
    "body": {"content": [{"paragraph": {"elements": [{"textRun": {"content": "Hello world\n"}}]}}]}
}


def _config():
    return Config(
        config_dir=".",
        service_account_file="sa.json",
        medium_token=SecretStr("tok"),
        backend="token",
        folders={"published": "PUB", "failed": "FAIL", "ready": "READY"},
    )


class FakeDrive:
    def __init__(self, docs, document):
        self._docs = docs
        self._document = document
        self.calls = []

    def list_ready(self):
        self.calls.append(("list_ready",))
        return self._docs

    def fetch_document(self, doc_id):
        self.calls.append(("fetch_document", doc_id))
        return self._document

    def move(self, doc_id, dest):
        self.calls.append(("move", doc_id, dest))

    def append_note(self, doc_id, text):
        self.calls.append(("append_note", doc_id, text))


class FakeMedium:
    def __init__(self):
        self.calls = []

    def upload_image(self, data, content_type):
        self.calls.append("upload_image")
        return "x"

    def create_post(self, *, title, markdown, tags, publish_status):
        self.calls.append("create_post")
        return PostResult(url="x")


def test_dry_run_prints_markdown_and_makes_no_calls(monkeypatch, capsys):
    doc = DocRef(doc_id="d1", name="Hello Post")
    drive = FakeDrive([doc], _DOCUMENT)
    medium = FakeMedium()

    def no_download(ref, document):
        raise AssertionError("dry-run must not download images")

    monkeypatch.setattr(cli, "load_config", lambda: _config())
    monkeypatch.setattr(cli, "_build_context", lambda config, redactor: (drive, medium, no_download))

    code = cli.main(["--dry-run"])

    assert code == 0
    out = capsys.readouterr().out
    assert "Hello world" in out  # converted markdown printed
    assert medium.calls == []  # no Medium calls at all
    assert not any(c[0] == "move" for c in drive.calls)  # no file moves


def test_dry_run_empty_ready_says_nothing_to_do(monkeypatch, capsys):
    drive = FakeDrive([], _DOCUMENT)
    medium = FakeMedium()
    monkeypatch.setattr(cli, "load_config", lambda: _config())
    monkeypatch.setattr(
        cli, "_build_context", lambda config, redactor: (drive, medium, lambda r, d: (b"", "x"))
    )

    code = cli.main(["--dry-run"])

    assert code == 0
    assert "nothing to do" in capsys.readouterr().out.lower()


def test_build_medium_wires_the_redactor_into_the_backend(monkeypatch):
    captured = {}

    class SpyBackend:
        def __init__(self, token, *, redactor=None, client=None):
            captured["token"] = token
            captured["redactor"] = redactor

    monkeypatch.setattr(cli, "TokenBackend", SpyBackend)
    redactor = RedactingFilter()
    config = _config()

    cli._build_medium(config, redactor)

    # The exact token holder and the live redactor are passed through (spec 7).
    assert captured["redactor"] is redactor
    assert captured["token"] is config.medium_token


def test_unknown_backend_is_a_clean_config_error():
    config = Config(
        config_dir=".",
        service_account_file="sa.json",
        medium_token=SecretStr("tok"),
        backend="playwright",
        folders={"ready": "READY"},
    )
    with pytest.raises(ConfigError) as caught:
        cli._build_medium(config, RedactingFilter())
    assert "playwright" in str(caught.value).lower()


def test_config_error_exits_2_with_message(monkeypatch, capsys):
    def boom():
        raise ConfigError("no config.toml found")

    monkeypatch.setattr(cli, "load_config", boom)
    code = cli.main([])
    assert code == 2
    assert "configuration error" in capsys.readouterr().out.lower()
