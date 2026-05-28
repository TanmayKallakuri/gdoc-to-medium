"""T4.1 auth resolution: GET /v1/me resolves + caches authorId; Bearer header on
every request; the token never appears in any log line.

No real network: a fake httpx client records each request and returns queued
httpx.Response objects, so status/json behave like the real thing offline.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from gdoc_to_medium.config import SecretStr
from gdoc_to_medium.logging_setup import REDACTED, RedactingFilter
from gdoc_to_medium.medium.token_backend import (
    API_BASE,
    PermanentMediumError,
    TokenBackend,
)

FAKE_TOKEN = "2a1b3c4d5e6f7g8h9i0jklmnopqrstuvwx"


class FakeClient:
    """Stands in for httpx.Client; returns queued responses and records requests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        if not self._responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _me_response(author_id="user-123", status=200):
    body = {"data": {"id": author_id, "username": "tanmay"}} if status == 200 else {}
    return httpx.Response(status_code=status, json=body, request=httpx.Request("GET", f"{API_BASE}/me"))


def _backend(responses, redactor=None):
    return TokenBackend(SecretStr(FAKE_TOKEN), client=FakeClient(responses), redactor=redactor)


def test_resolves_author_id_from_me():
    backend = _backend([_me_response("user-abc")])
    assert backend.author_id() == "user-abc"


def test_author_id_is_cached_one_call():
    client = FakeClient([_me_response("user-abc")])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    first = backend.author_id()
    second = backend.author_id()
    assert first == second == "user-abc"
    # Only one /v1/me request despite two calls.
    me_calls = [r for r in client.requests if r["url"].endswith("/me")]
    assert len(me_calls) == 1


def test_bearer_header_present_on_request():
    client = FakeClient([_me_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.author_id()
    headers = client.requests[0]["headers"]
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_me_url_is_https_medium():
    client = FakeClient([_me_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.author_id()
    assert client.requests[0]["url"] == "https://api.medium.com/v1/me"


def test_401_on_me_is_permanent():
    backend = _backend([_me_response(status=401)])
    with pytest.raises(PermanentMediumError):
        backend.author_id()


def test_403_on_me_is_permanent():
    backend = _backend([_me_response(status=403)])
    with pytest.raises(PermanentMediumError):
        backend.author_id()


def test_malformed_me_response_is_permanent():
    bad = httpx.Response(
        status_code=200,
        json={"data": {}},
        request=httpx.Request("GET", f"{API_BASE}/me"),
    )
    backend = _backend([bad])
    with pytest.raises(PermanentMediumError):
        backend.author_id()


def test_token_registered_with_redactor_on_construction():
    redactor = RedactingFilter()
    TokenBackend(SecretStr(FAKE_TOKEN), client=FakeClient([]), redactor=redactor)
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=f"sending {FAKE_TOKEN}", args=(), exc_info=None,
    )
    redactor.filter(record)
    assert FAKE_TOKEN not in record.getMessage()
    assert REDACTED in record.getMessage()


def test_token_never_in_log_during_auth(caplog):
    backend = _backend([_me_response()])
    with caplog.at_level(logging.DEBUG, logger="gdoc_to_medium"):
        backend.author_id()
    assert all(FAKE_TOKEN not in rec.getMessage() for rec in caplog.records)


def test_token_not_in_repr_or_str():
    backend = _backend([_me_response()])
    assert FAKE_TOKEN not in repr(backend)
    assert FAKE_TOKEN not in str(backend)


def test_token_not_in_permanent_error_message():
    backend = _backend([_me_response(status=401)])
    try:
        backend.author_id()
    except PermanentMediumError as exc:
        assert FAKE_TOKEN not in str(exc)
    else:
        raise AssertionError("expected PermanentMediumError")


def test_rejects_raw_string_token():
    with pytest.raises(TypeError):
        TokenBackend(FAKE_TOKEN, client=FakeClient([]))  # type: ignore[arg-type]
