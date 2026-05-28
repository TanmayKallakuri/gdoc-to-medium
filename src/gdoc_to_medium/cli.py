"""Command-line entrypoint: wire real backends from config and run the pipeline (spec 5.4).

`gdoc-to-medium` (or `python -m gdoc_to_medium`) processes every doc in the
Ready-to-Publish folder once. `--dry-run` converts and prints the markdown for
each ready doc and makes no Medium calls and no file moves — the acceptance check
(spec 8). The scheduled task (spec 9) invokes the no-arg form every few minutes.

Security: the redacting logger is set up first and the Medium token registered
with it BEFORE any backend is built, and the same redactor is handed to the
TokenBackend, so the token is scrubbed everywhere it could surface (spec 7).
"""

from __future__ import annotations

import argparse
import logging

from . import orchestrator
from .config import ConfigError, load_config
from .drive_client import SCOPES, DriveClient
from .image_source import make_authorized_downloader
from .logging_setup import setup_logging
from .medium.token_backend import TokenBackend
from .types import MediumBackend

logger = logging.getLogger("gdoc_to_medium.cli")


def _build_credentials(config):
    """Service-account credentials for Drive/Docs and image downloads (imported lazily)."""
    from google.oauth2.service_account import Credentials

    return Credentials.from_service_account_file(
        str(config.service_account_file), scopes=list(SCOPES)
    )


def _build_drive(config, credentials) -> DriveClient:
    from googleapiclient.discovery import build

    docs = build("docs", "v1", credentials=credentials)
    drive = build("drive", "v3", credentials=credentials)
    ready = config.folders.get("ready")
    if not ready:
        raise ConfigError("no 'ready' folder id configured (set folders.ready in config.toml)")
    return DriveClient(docs, drive, ready)


def _build_medium(config, redactor) -> MediumBackend:
    """Build the Medium backend, passing the redactor so the token is scrubbed (spec 7)."""
    if config.backend == "token":
        return TokenBackend(config.medium_token, redactor=redactor)
    raise ConfigError(
        "backend='playwright' is not built yet (Wave 6); set backend='token' in config.toml"
    )


def _build_context(config, redactor):
    """Construct the live collaborators. Isolated so tests can substitute fakes."""
    creds = _build_credentials(config)
    drive = _build_drive(config, creds)
    medium = _build_medium(config, redactor)
    downloader = make_authorized_downloader(creds)
    return drive, medium, downloader


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="gdoc-to-medium",
        description="Publish Google Docs from a Ready-to-Publish folder to Medium as drafts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Convert and print the markdown for each ready doc; make no Medium calls and move no files.",
    )
    args = parser.parse_args(argv)

    # Set up redaction and register the token BEFORE building any backend (spec 7).
    redactor = setup_logging(level=logging.INFO)
    try:
        config = load_config()
        config.register_secrets(redactor)
        drive, medium, downloader = _build_context(config, redactor)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2

    processed = orchestrator.run(
        drive, medium, config, image_downloader=downloader, dry_run=args.dry_run
    )
    logger.info("run complete: %d doc(s) processed", processed)
    return 0
