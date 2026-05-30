"""Load secrets from a local, gitignored config directory (spec 7).

The Medium token is wrapped so it never appears in repr()/str() of the config,
and is registered with the redacting logger the moment it is loaded.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .logging_setup import RedactingFilter

CONFIG_DIR_ENV = "GDOC_TO_MEDIUM_CONFIG_DIR"
CONFIG_FILENAME = "config.toml"


class ConfigError(Exception):
    """Base class for configuration problems."""


class ConfigNotFoundError(ConfigError):
    """No config.toml was found in any resolved config directory."""


class MissingSecretError(ConfigError):
    """A required secret is absent or empty in the config file."""


class SecretStr:
    """Holds a secret value while keeping it out of repr()/str()/logs."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretStr('***REDACTED***')"

    __str__ = __repr__

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SecretStr) and other._value == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __bool__(self) -> bool:
        return bool(self._value)


@dataclass
class Config:
    config_dir: Path
    service_account_file: Path
    medium_token: SecretStr = field(repr=False)
    backend: str = "token"
    folders: dict[str, str] = field(default_factory=dict)
    # Playwright backend only (spec 5.3 fallback). session_dir defaults next to the
    # config dir; headless can be turned off to watch the browser while debugging.
    playwright_session_dir: str | None = None
    playwright_headless: bool = True

    def register_secrets(self, redactor: RedactingFilter) -> None:
        """Teach the redacting logger this run's token so it is scrubbed everywhere."""
        redactor.add_secret(self.medium_token.get())


def candidate_config_dirs() -> list[Path]:
    """Config directories in resolution order: env override, LOCALAPPDATA, project .secrets/."""
    dirs: list[Path] = []
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        dirs.append(Path(override))
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        dirs.append(Path(local_appdata) / "gdoc-to-medium")
    dirs.append(_project_root() / ".secrets")
    return dirs


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_config_file() -> Path:
    dirs = candidate_config_dirs()
    for directory in dirs:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(d) for d in dirs)
    raise ConfigNotFoundError(
        f"No {CONFIG_FILENAME} found. Looked in: {searched}. "
        f"Copy config.example.toml into one of these directories and fill it in."
    )


def _require(data: dict, key: str, source: Path) -> str:
    if key not in data:
        raise MissingSecretError(f"Required key '{key}' is missing from {source}.")
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise MissingSecretError(f"Required key '{key}' is empty in {source}.")
    return value


def load_config(config_file: Path | None = None) -> Config:
    """Load and validate the config, resolving the config dir per spec 7."""
    path = Path(config_file) if config_file is not None else _resolve_config_file()
    if not path.is_file():
        raise ConfigNotFoundError(f"Config file does not exist: {path}")

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Config file {path} is not valid TOML: {exc}") from exc

    config_dir = path.parent

    sa_raw = _require(data, "service_account_file", path)
    sa_path = Path(sa_raw)
    if not sa_path.is_absolute():
        sa_path = config_dir / sa_path

    backend = data.get("backend", "token")
    if not isinstance(backend, str) or backend not in {"token", "playwright"}:
        raise ConfigError(
            f"backend in {path} must be 'token' or 'playwright', got {backend!r}."
        )

    # Token is required for the token backend; the playwright backend uses a
    # stored browser session instead (spec 5.3), so an empty token is allowed there.
    if backend == "token":
        token = _require(data, "medium_token", path)
    else:
        token = data.get("medium_token", "") or ""
        if not isinstance(token, str):
            raise MissingSecretError(f"Key 'medium_token' in {path} must be a string.")

    folders_raw = data.get("folders", {})
    folders = {k: str(v) for k, v in folders_raw.items()} if isinstance(folders_raw, dict) else {}

    pw_raw = data.get("playwright", {})
    pw = pw_raw if isinstance(pw_raw, dict) else {}
    session_dir = pw.get("session_dir")
    if session_dir is not None and not isinstance(session_dir, str):
        raise ConfigError(
            f"[playwright].session_dir in {path} must be a quoted path string, got {session_dir!r}."
        )
    session_dir = session_dir if isinstance(session_dir, str) and session_dir.strip() else None
    headless = pw.get("headless", True)
    if not isinstance(headless, bool):
        raise ConfigError(f"[playwright].headless in {path} must be true or false, got {headless!r}.")

    return Config(
        config_dir=config_dir,
        service_account_file=sa_path,
        medium_token=SecretStr(token),
        backend=backend,
        folders=folders,
        playwright_session_dir=session_dir,
        playwright_headless=headless,
    )
