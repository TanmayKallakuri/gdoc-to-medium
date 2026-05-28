import logging

import pytest

from gdoc_to_medium.config import (
    Config,
    ConfigError,
    ConfigNotFoundError,
    MissingSecretError,
    SecretStr,
    load_config,
)
from gdoc_to_medium.logging_setup import REDACTED, RedactingFilter

FAKE_TOKEN = "tok_live_4815162342abcdef"


def _write(tmp_path, body: str):
    cfg = tmp_path / "config.toml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_loads_service_account_and_token(tmp_path):
    cfg = _write(
        tmp_path,
        'service_account_file = "sa.json"\n'
        f'medium_token = "{FAKE_TOKEN}"\n'
        'backend = "token"\n'
        '[folders]\nready_to_publish = "abc123"\n',
    )
    config = load_config(cfg)
    assert config.service_account_file == tmp_path / "sa.json"
    assert config.medium_token.get() == FAKE_TOKEN
    assert config.backend == "token"
    assert config.folders["ready_to_publish"] == "abc123"


def test_missing_file_raises_not_found(tmp_path):
    with pytest.raises(ConfigNotFoundError):
        load_config(tmp_path / "does-not-exist.toml")


def test_missing_required_key_raises_typed_error(tmp_path):
    cfg = _write(tmp_path, f'medium_token = "{FAKE_TOKEN}"\n')
    with pytest.raises(MissingSecretError) as exc:
        load_config(cfg)
    assert "service_account_file" in str(exc.value)


def test_empty_token_raises_typed_error_not_keyerror(tmp_path):
    cfg = _write(
        tmp_path,
        'service_account_file = "sa.json"\nmedium_token = "   "\n',
    )
    with pytest.raises(MissingSecretError):
        load_config(cfg)


def test_token_absent_from_repr_and_str(tmp_path):
    cfg = _write(
        tmp_path,
        f'service_account_file = "sa.json"\nmedium_token = "{FAKE_TOKEN}"\n',
    )
    config = load_config(cfg)
    assert FAKE_TOKEN not in repr(config)
    assert FAKE_TOKEN not in str(config)
    assert FAKE_TOKEN not in repr(config.medium_token)
    assert FAKE_TOKEN not in str(config.medium_token)
    assert REDACTED in repr(config.medium_token)


def test_invalid_backend_rejected(tmp_path):
    cfg = _write(
        tmp_path,
        'service_account_file = "sa.json"\n'
        f'medium_token = "{FAKE_TOKEN}"\n'
        'backend = "carrier-pigeon"\n',
    )
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_playwright_backend_allows_empty_token(tmp_path):
    cfg = _write(
        tmp_path,
        'service_account_file = "sa.json"\nbackend = "playwright"\n',
    )
    config = load_config(cfg)
    assert config.backend == "playwright"
    assert config.medium_token.get() == ""


def test_absolute_service_account_path_preserved(tmp_path):
    abs_sa = (tmp_path / "creds" / "sa.json").resolve()
    cfg = _write(
        tmp_path,
        f'service_account_file = "{abs_sa.as_posix()}"\n'
        f'medium_token = "{FAKE_TOKEN}"\n',
    )
    config = load_config(cfg)
    assert config.service_account_file == abs_sa


def test_invalid_toml_raises_config_error(tmp_path):
    cfg = _write(tmp_path, "this is = = not valid toml\n")
    with pytest.raises(ConfigError):
        load_config(cfg)


def test_register_secrets_protects_token_in_logs(tmp_path):
    cfg = _write(
        tmp_path,
        f'service_account_file = "sa.json"\nmedium_token = "{FAKE_TOKEN}"\n',
    )
    config = load_config(cfg)
    redactor = RedactingFilter()
    config.register_secrets(redactor)
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="posting with token %s", args=(FAKE_TOKEN,), exc_info=None,
    )
    redactor.filter(record)
    assert FAKE_TOKEN not in record.getMessage()


def test_secretstr_equality_and_bool():
    assert SecretStr("a") == SecretStr("a")
    assert SecretStr("a") != SecretStr("b")
    assert bool(SecretStr("x")) is True
    assert bool(SecretStr("")) is False
