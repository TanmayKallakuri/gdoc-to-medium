import logging

from gdoc_to_medium.logging_setup import (
    REDACTED,
    RedactingFilter,
    redact,
    setup_logging,
)

FAKE_TOKEN = "2a1b3c4d5e6f7g8h9i0jklmnopqrstuvwx"


def _emit(filt: RedactingFilter, msg, args=()):
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )
    filt.filter(record)
    return record.getMessage()


def test_token_mid_string_redacted():
    filt = RedactingFilter([FAKE_TOKEN])
    out = _emit(filt, f"calling api with {FAKE_TOKEN} now")
    assert FAKE_TOKEN not in out
    assert REDACTED in out
    assert out == f"calling api with {REDACTED} now"


def test_token_as_whole_message_redacted():
    filt = RedactingFilter([FAKE_TOKEN])
    out = _emit(filt, FAKE_TOKEN)
    assert out == REDACTED


def test_normal_message_untouched():
    filt = RedactingFilter([FAKE_TOKEN])
    out = _emit(filt, "fetched 3 documents from Ready to Publish")
    assert out == "fetched 3 documents from Ready to Publish"


def test_token_passed_via_log_args_redacted():
    filt = RedactingFilter([FAKE_TOKEN])
    out = _emit(filt, "auth=%s", (FAKE_TOKEN,))
    assert FAKE_TOKEN not in out
    assert REDACTED in out


def test_bearer_pattern_redacted_without_registration():
    out = redact("Authorization: Bearer abc123DEF456ghi")
    assert "abc123DEF456ghi" not in out
    assert out == f"Authorization: Bearer {REDACTED}"


def test_keyed_secret_pattern_redacted_without_registration():
    out = redact("integration_token=xyz987secretvalue")
    assert "xyz987secretvalue" not in out
    assert REDACTED in out


def test_bearer_in_prose_not_redacted():
    text = "She is the bearer of gifts"
    assert redact(text) == text


def test_keyed_secret_preserves_surrounding_quotes_and_punctuation():
    out = redact("password='secretpass1'")
    assert "secretpass1" not in out
    assert out == f"password='{REDACTED}'"


def test_keyed_secret_in_sentence_preserves_trailing_words():
    out = redact("the token=abc123def was rejected")
    assert "abc123def" not in out
    assert out == f"the token={REDACTED} was rejected"


def test_setup_logging_scrubs_through_handler(caplog):
    redactor = setup_logging(secrets=[FAKE_TOKEN])
    try:
        logger = logging.getLogger("gdoc_to_medium")
        with caplog.at_level(logging.INFO, logger="gdoc_to_medium"):
            logger.info("token is %s here", FAKE_TOKEN)
        assert any(FAKE_TOKEN not in rec.getMessage() for rec in caplog.records)
        assert all(FAKE_TOKEN not in rec.getMessage() for rec in caplog.records)
        assert any(REDACTED in rec.getMessage() for rec in caplog.records)
    finally:
        logging.getLogger("gdoc_to_medium").removeFilter(redactor)
        for h in list(logging.getLogger("gdoc_to_medium").handlers):
            logging.getLogger("gdoc_to_medium").removeHandler(h)


def test_add_secret_after_construction():
    filt = RedactingFilter()
    filt.add_secret(FAKE_TOKEN)
    out = _emit(filt, f"leaking {FAKE_TOKEN}")
    assert FAKE_TOKEN not in out


def test_filter_scrubs_secret_in_traceback():
    # A secret can ride in an exception's text and bypass the message scrub.
    # The filter must format exc_info, redact it, clear exc_info, and leave the
    # handler a pre-scrubbed exc_text.
    import sys

    filt = RedactingFilter([FAKE_TOKEN])
    try:
        raise ValueError(f"upstream failed with token {FAKE_TOKEN}")
    except ValueError:
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="operation failed", args=(), exc_info=sys.exc_info(),
        )
    filt.filter(record)
    assert record.exc_info is None
    assert record.exc_text is not None
    assert FAKE_TOKEN not in record.exc_text
    assert REDACTED in record.exc_text


def test_logger_exception_traceback_is_scrubbed_end_to_end():
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    redactor = setup_logging(secrets=[FAKE_TOKEN], handler=handler)
    try:
        logger = logging.getLogger("gdoc_to_medium")
        try:
            raise ValueError(f"boom with {FAKE_TOKEN}")
        except ValueError:
            logger.exception("publish failed")
        output = stream.getvalue()
        assert "Traceback" in output  # the traceback was still emitted
        assert FAKE_TOKEN not in output  # but the token is scrubbed out of it
        assert REDACTED in output
    finally:
        logging.getLogger("gdoc_to_medium").removeFilter(redactor)
        for h in list(logging.getLogger("gdoc_to_medium").handlers):
            logging.getLogger("gdoc_to_medium").removeHandler(h)
