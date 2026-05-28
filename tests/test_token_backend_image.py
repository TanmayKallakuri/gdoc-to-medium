"""T4.2 upload_image: multipart POST to /v1/images, form field exactly 'image',
returns data.url. Edge cases: unsupported type rejected before upload;
non-201 classified transient (429/5xx) vs permanent (other 4xx).

No real network: a fake httpx client records requests and returns queued
httpx.Response objects.
"""

from __future__ import annotations

import httpx
import pytest

from gdoc_to_medium.config import SecretStr
from gdoc_to_medium.medium.token_backend import (
    API_BASE,
    PermanentMediumError,
    TokenBackend,
    TransientMediumError,
)

FAKE_TOKEN = "2a1b3c4d5e6f7g8h9i0jklmnopqrstuvwx"
PNG_BYTES = b"\x89PNG\r\n\x1a\n fake png bytes"


class FakeClient:
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


def _image_response(url="https://cdn-images.medium.com/abc.png", status=201):
    body = {"data": {"url": url, "md5": "deadbeef"}} if status == 201 else {}
    return httpx.Response(
        status_code=status, json=body,
        request=httpx.Request("POST", f"{API_BASE}/images"),
    )


def _backend(responses):
    return TokenBackend(SecretStr(FAKE_TOKEN), client=FakeClient(responses))


def test_returns_data_url_on_201():
    backend = _backend([_image_response("https://cdn.medium.com/x.png")])
    assert backend.upload_image(PNG_BYTES, "image/png") == "https://cdn.medium.com/x.png"


def test_posts_multipart_to_images_endpoint():
    client = FakeClient([_image_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.upload_image(PNG_BYTES, "image/png")
    req = client.requests[0]
    assert req["method"] == "POST"
    assert req["url"] == "https://api.medium.com/v1/images"
    assert "files" in req


def test_form_field_named_exactly_image():
    client = FakeClient([_image_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.upload_image(PNG_BYTES, "image/jpeg")
    files = client.requests[0]["files"]
    assert list(files.keys()) == ["image"]
    _name, content, ctype = files["image"]
    assert content == PNG_BYTES
    assert ctype == "image/jpeg"


def test_bearer_header_present_on_upload():
    client = FakeClient([_image_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.upload_image(PNG_BYTES, "image/png")
    assert client.requests[0]["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


@pytest.mark.parametrize("ctype", ["image/jpeg", "image/png", "image/gif", "image/tiff"])
def test_all_supported_types_accepted(ctype):
    backend = _backend([_image_response()])
    assert backend.upload_image(PNG_BYTES, ctype)


def test_content_type_normalized_case_and_whitespace():
    client = FakeClient([_image_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.upload_image(PNG_BYTES, "  IMAGE/PNG  ")
    assert client.requests[0]["files"]["image"][2] == "image/png"


def test_unsupported_type_rejected_before_upload():
    client = FakeClient([])  # any request would raise
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    with pytest.raises(PermanentMediumError):
        backend.upload_image(PNG_BYTES, "image/webp")
    # No network call was made.
    assert client.requests == []


def test_empty_content_type_rejected_before_upload():
    client = FakeClient([])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    with pytest.raises(PermanentMediumError):
        backend.upload_image(PNG_BYTES, "")
    assert client.requests == []


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_5xx_and_429_classified_transient(status):
    backend = _backend([_image_response(status=status)])
    with pytest.raises(TransientMediumError):
        backend.upload_image(PNG_BYTES, "image/png")


@pytest.mark.parametrize("status", [400, 401, 403, 413])
def test_other_4xx_classified_permanent(status):
    backend = _backend([_image_response(status=status)])
    with pytest.raises(PermanentMediumError):
        backend.upload_image(PNG_BYTES, "image/png")


def test_network_error_classified_transient():
    err = httpx.ConnectError("connection refused")
    backend = _backend([err])
    with pytest.raises(TransientMediumError):
        backend.upload_image(PNG_BYTES, "image/png")


def test_timeout_classified_transient():
    backend = _backend([httpx.ReadTimeout("timed out")])
    with pytest.raises(TransientMediumError):
        backend.upload_image(PNG_BYTES, "image/png")


def test_malformed_201_missing_url_is_permanent():
    bad = httpx.Response(
        status_code=201, json={"data": {"md5": "x"}},
        request=httpx.Request("POST", f"{API_BASE}/images"),
    )
    backend = _backend([bad])
    with pytest.raises(PermanentMediumError):
        backend.upload_image(PNG_BYTES, "image/png")


def test_token_not_in_upload_error_messages():
    backend = _backend([_image_response(status=400)])
    try:
        backend.upload_image(PNG_BYTES, "image/png")
    except PermanentMediumError as exc:
        assert FAKE_TOKEN not in str(exc)
    else:
        raise AssertionError("expected PermanentMediumError")
