"""Logging that redacts secrets before anything reaches a handler.

Spec 7: tokens are never printed in logs. Redaction happens in a filter so it
applies no matter which handler/formatter is attached downstream.
"""

from __future__ import annotations

import logging
import re

REDACTED = "***REDACTED***"

# A token value: opaque, >=8 chars, and not a plain dictionary word (must carry
# a digit or one of . _ -). This keeps the bearer pattern off natural prose.
_TOKEN_VALUE = r"(?=[A-Za-z0-9._\-]*[0-9._\-])[A-Za-z0-9._\-]{8,}"

# Shapes that are secret-looking on their own, redacted even if no exact value
# was registered. Order matters: more specific patterns first.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "Authorization: Bearer <token>" / "Bearer <token>" — only when the value
    # is token-shaped, so prose like "bearer of gifts" is left untouched.
    re.compile(rf"(?i)(bearer\s+){_TOKEN_VALUE}"),
    # key=value / key: value where the key names a secret. The value stops before
    # surrounding punctuation/quotes so context (e.g. password='x') survives; the
    # value is not allowed to be "Bearer ..." so the bearer pattern above owns that.
    re.compile(
        r"(?i)((?:authorization|token|api[_-]?key|secret|password|passwd|integration[_-]?token)"
        r"\s*[:=]\s*['\"]?)(?!bearer\b)([^\s,;'\"!?()<>]+)"
    ),
)


def _redact_known(text: str, secrets: frozenset[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def _redact_patterns(text: str) -> str:
    text = _PATTERNS[0].sub(lambda m: m.group(1) + REDACTED, text)
    text = _PATTERNS[1].sub(lambda m: m.group(1) + REDACTED, text)
    return text


def redact(text: str, secrets: frozenset[str] = frozenset()) -> str:
    """Replace registered secret values and secret-looking patterns with a marker."""
    return _redact_patterns(_redact_known(text, secrets))


class RedactingFilter(logging.Filter):
    """Rewrites each record's rendered message so no secret survives to a handler."""

    def __init__(self, secrets: list[str] | None = None) -> None:
        super().__init__()
        self._secrets: frozenset[str] = frozenset(s for s in (secrets or []) if s)

    def add_secret(self, value: str) -> None:
        if value:
            self._secrets = self._secrets | {value}

    def filter(self, record: logging.LogRecord) -> bool:
        # Render with args here so the substituted message is what gets scrubbed,
        # then neutralize args so handlers re-render to the same safe string.
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        record.msg = redact(rendered, self._secrets)
        record.args = None
        # Tracebacks bypass the message entirely: an exception whose text carries a
        # secret (or a locals-rendering traceback formatter) would leak it past the
        # message scrub. Format exc_info to text now, redact it, and hand the handler
        # the pre-scrubbed text with exc_info cleared so it won't re-render raw frames.
        # Covers logger.exception(...) and any exc_info=/stack_info= call. Idempotent
        # across the dual handler+logger registration.
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = redact(record.exc_text, self._secrets)
        if record.stack_info:
            record.stack_info = redact(record.stack_info, self._secrets)
        return True


def setup_logging(
    level: int = logging.INFO,
    secrets: list[str] | None = None,
    handler: logging.Handler | None = None,
) -> RedactingFilter:
    """Attach a redacting filter to the package logger and return it for later secret registration."""
    logger = logging.getLogger("gdoc_to_medium")
    logger.setLevel(level)
    redactor = RedactingFilter(secrets)
    target = handler or logging.StreamHandler()
    target.addFilter(redactor)
    logger.addHandler(target)
    # Logger-level filter intentionally duplicates the handler's so any handler a
    # later wave adds is also covered; redaction is idempotent so running twice is safe.
    logger.addFilter(redactor)
    return redactor
