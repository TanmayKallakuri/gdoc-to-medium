"""Command-line entrypoint: wire real backends from config and run the pipeline (spec 5.4).

Commands:
  gdoc-to-medium            process every doc in Ready-to-Publish once (the scheduled run)
  gdoc-to-medium --dry-run  convert and print markdown for each ready doc; no Medium calls, no moves
  gdoc-to-medium login      one-time: open a browser to sign in to Medium (Playwright backend)
  gdoc-to-medium doctor     check the Medium session + that the editor selectors still resolve

Backends (spec 5.3): `token` uses a pre-2025 Medium integration token via the REST API;
`playwright` drives the Medium web editor through a saved browser session and needs no
token — the path for users who can't get one (Medium stopped issuing them in 2025).

Security: the redacting logger is set up first and the Medium token registered with it
BEFORE any backend is built, so the token is scrubbed everywhere it could surface (spec 7).
"""

from __future__ import annotations

import argparse
import contextlib
import logging

from . import orchestrator
from .config import ConfigError, load_config
from .drive_client import SCOPES, DriveClient
from .image_source import make_authorized_downloader
from .logging_setup import setup_logging
from .medium import session as pw_session
from .medium.playwright_backend import PlaywrightBackend
from .medium.token_backend import MediumClientError, TokenBackend
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


def _build_medium(config, redactor, stack, *, dry_run: bool) -> MediumBackend:
    """Build the Medium backend; for live Playwright runs, open the persistent browser.

    In dry-run the Medium backend is never called, so no browser is launched even for the
    Playwright backend. The browser context is entered on `stack` so it always closes.
    """
    if config.backend == "token":
        return TokenBackend(config.medium_token, redactor=redactor)

    if dry_run:
        backend = PlaywrightBackend(page=None)
    else:
        session_dir = pw_session.default_session_dir(config)
        page = stack.enter_context(
            pw_session.launch_page(session_dir, headless=config.playwright_headless)
        )
        backend = PlaywrightBackend(page=page)
    close = getattr(backend, "close", None)
    if callable(close):
        stack.callback(close)
    return backend


def _build_context(config, redactor, stack, *, dry_run: bool):
    """Construct the live collaborators. Isolated so tests can substitute fakes."""
    creds = _build_credentials(config)
    drive = _build_drive(config, creds)
    medium = _build_medium(config, redactor, stack, dry_run=dry_run)
    downloader = make_authorized_downloader(creds)
    return drive, medium, downloader


def _preflight(medium: MediumBackend, config, *, dry_run: bool) -> str | None:
    """Cheap check before processing any doc. Returns an error message, or None if OK.

    Catches the two systemic failures that would otherwise waste a run or mis-route docs:
    a Playwright session that isn't signed in, and a token that's been revoked/invalid.
    Skipped in dry-run (no Medium calls happen).
    """
    if dry_run:
        return None
    if isinstance(medium, PlaywrightBackend):
        if not medium.health_check():
            return (
                "Medium session is not signed in or has expired.\n"
                "Run `gdoc-to-medium login` to sign in once, then try again."
            )
        return None
    # token backend: confirm the token still authenticates (Wave 6 research recommendation).
    if isinstance(medium, TokenBackend):
        try:
            medium.author_id()
        except MediumClientError as exc:
            return (
                f"Medium token did not authenticate ({exc}).\n"
                "Pre-2025 integration tokens still work but new ones can't be created; "
                "if yours was revoked, switch to backend = \"playwright\" in config.toml."
            )
    return None


def _cmd_login(config) -> int:
    session_dir = pw_session.default_session_dir(config)
    ok = pw_session.login(session_dir)
    return 0 if ok else 1


def _cmd_doctor(config) -> int:
    """Launch the saved session and report whether sign-in + key selectors resolve."""
    from .medium import selectors as S

    session_dir = pw_session.default_session_dir(config)
    print(f"Medium session profile: {session_dir}")
    with contextlib.ExitStack() as stack:
        try:
            page = stack.enter_context(
                pw_session.launch_page(session_dir, headless=config.playwright_headless)
            )
        except pw_session.SessionError as exc:
            print(f"Could not launch browser: {exc}")
            return 2
        backend = PlaywrightBackend(page=page)
        stack.callback(backend.close)
        if not backend.health_check():
            print("Not signed in. Run `gdoc-to-medium login` first.")
            return 1
        print("Signed in: yes")
        for name, group in (
            ("editor", S.EDITOR),
            ("title", S.TITLE),
            ("publish button", S.PUBLISH_BUTTON),
        ):
            resolved = backend._first_present(group)  # noqa: SLF001 — doctor inspects internals
            status = resolved if resolved else "NONE MATCHED (Medium UI may have changed)"
            print(f"  {name}: {status}")
    print("Doctor check complete.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="gdoc-to-medium",
        description="Publish Google Docs from a Ready-to-Publish folder to Medium.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Convert and print the markdown for each ready doc; make no Medium calls and move no files.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("login", help="One-time: sign in to Medium for the Playwright backend.")
    sub.add_parser("doctor", help="Check the Medium session and editor selectors (Playwright backend).")
    args = parser.parse_args(argv)

    # Set up redaction and register the token BEFORE building any backend (spec 7).
    redactor = setup_logging(level=logging.INFO)
    try:
        config = load_config()
        config.register_secrets(redactor)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2

    if args.command == "login":
        return _cmd_login(config)
    if args.command == "doctor":
        return _cmd_doctor(config)

    with contextlib.ExitStack() as stack:
        try:
            drive, medium, downloader = _build_context(
                config, redactor, stack, dry_run=args.dry_run
            )
        except ConfigError as exc:
            print(f"Configuration error: {exc}")
            return 2

        problem = _preflight(medium, config, dry_run=args.dry_run)
        if problem is not None:
            print(problem)
            return 2

        processed = orchestrator.run(
            drive, medium, config, image_downloader=downloader, dry_run=args.dry_run
        )
    logger.info("run complete: %d doc(s) processed", processed)
    return 0
