"""Review-driven hardening for TokenBackend.

S1: a transport failure must NOT leak the token via the exception chain or a
printed traceback (httpx attaches the token-bearing request to its errors).
C1: a DecodingError (RequestError but not TransportError) must be classified,
not escape unclassified.
C3: the MediumBackend Protocol must hold against the real call signatures, not
just method-name presence.
"""

from __future__ import annotations

import traceback

import httpx
import pytest

from gdoc_to_medium.config import SecretStr
from gdoc_to_medium.medium.token_backend import (
    API_BASE,
    PermanentMediumError,
    TokenBackend,
    TransientMediumError,
)
from gdoc_to_medium.types import MediumBackend, PostResult

FAKE_TOKEN = "2a1b3c4d5e6f7g8h9i0jklmnopqrstuvwx"


class _RaisingClient:
    """httpx.Client stand-in that raises a pre-built transport exception."""

    def __init__(self, exc):
        self._exc = exc

    def request(self, method, url, **kwargs):
        raise self._exc


def _token_bearing_request():
    # Mirror what httpx attaches on a real failure: a request whose headers carry
    # the live Bearer token. This is exactly the object we must NOT let surface.
    return httpx.Request(
        "GET",
        f"{API_BASE}/me",
        headers={"Authorization": f"Bearer {FAKE_TOKEN}"},
    )


def test_transport_error_does_not_leak_token_in_traceback():
    exc = httpx.ConnectError("connection refused", request=_token_bearing_request())
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=_RaisingClient(exc))
    try:
        backend.author_id()
    except TransientMediumError as e:
        # `from None` severs the chain: the token-bearing httpx error is neither
        # the cause nor printable as context.
        assert e.__cause__ is None
        assert e.__suppress_context__ is True
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        assert FAKE_TOKEN not in tb
        assert "Authorization" not in tb
    else:
        raise AssertionError("expected TransientMediumError")


def test_decoding_error_is_classified_permanent_without_leak():
    exc = httpx.DecodingError("garbled response encoding", request=_token_bearing_request())
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=_RaisingClient(exc))
    with pytest.raises(PermanentMediumError) as caught:
        backend.author_id()
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    tb = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )
    assert FAKE_TOKEN not in str(caught.value)
    assert FAKE_TOKEN not in tb


class _SeqClient:
    """Returns queued responses in order, ignoring request details."""

    def __init__(self, responses):
        self._responses = list(responses)

    def request(self, method, url, **kwargs):
        return self._responses.pop(0)


def test_satisfies_medium_backend_protocol_with_real_signatures():
    # Drive the actual signatures through a Protocol-typed variable so signature
    # drift (not just method-name presence) would fail this test.
    me = httpx.Response(
        status_code=200,
        json={"data": {"id": "user-1"}},
        request=httpx.Request("GET", f"{API_BASE}/me"),
    )
    uploaded = httpx.Response(
        status_code=201,
        json={"data": {"url": "https://cdn.medium.com/img.png"}},
        request=httpx.Request("POST", f"{API_BASE}/images"),
    )
    created = httpx.Response(
        status_code=201,
        json={"data": {"url": "https://medium.com/p/abc"}},
        request=httpx.Request("POST", f"{API_BASE}/users/user-1/posts"),
    )
    # Call order: upload_image (POST /images) → create_post resolves author (/me)
    # then posts (/posts).
    backend: MediumBackend = TokenBackend(
        SecretStr(FAKE_TOKEN), client=_SeqClient([uploaded, me, created])
    )
    assert backend.upload_image(b"\x89PNG", "image/png") == "https://cdn.medium.com/img.png"
    result = backend.create_post("Title", "# Title\n\nbody", ["a", "b"], "draft")
    assert isinstance(result, PostResult)
    assert result.url == "https://medium.com/p/abc"
