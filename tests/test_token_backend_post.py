"""T4.3 create_post: POST to /v1/users/{authorId}/posts with the documented body,
returns PostResult(url=data.url). Edge cases: tags truncated to 5;
publishStatus defaults to draft; 429/5xx transient, 4xx permanent.

No real network: a fake httpx client records requests and returns queued
httpx.Response objects (an /v1/me response first so author id resolves).
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
from gdoc_to_medium.types import MediumBackend, PostResult

FAKE_TOKEN = "2a1b3c4d5e6f7g8h9i0jklmnopqrstuvwx"
AUTHOR = "user-123"


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


def _me():
    return httpx.Response(
        status_code=200, json={"data": {"id": AUTHOR}},
        request=httpx.Request("GET", f"{API_BASE}/me"),
    )


def _post_response(url="https://medium.com/p/abc123", status=201):
    body = {"data": {"id": "p1", "url": url, "publishStatus": "draft"}} if status in (200, 201) else {}
    return httpx.Response(
        status_code=status, json=body,
        request=httpx.Request("POST", f"{API_BASE}/users/{AUTHOR}/posts"),
    )


def _backend(post_responses):
    return TokenBackend(SecretStr(FAKE_TOKEN), client=FakeClient([_me(), *post_responses]))


def _post_request(client):
    return next(r for r in client.requests if r["url"].endswith("/posts"))


def test_returns_post_result_url():
    backend = _backend([_post_response("https://medium.com/p/xyz")])
    result = backend.create_post("Title", "# Title\n\nbody", ["a"], "draft")
    assert isinstance(result, PostResult)
    assert result.url == "https://medium.com/p/xyz"


def test_posts_to_users_author_posts_endpoint():
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("T", "body", [], "draft")
    req = _post_request(client)
    assert req["method"] == "POST"
    assert req["url"] == f"https://api.medium.com/v1/users/{AUTHOR}/posts"


def test_body_has_documented_shape():
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("My Title", "# My Title\n\ntext", ["x", "y"], "public")
    body = _post_request(client)["json"]
    assert body["title"] == "My Title"
    assert body["content"] == "# My Title\n\ntext"
    assert body["contentFormat"] == "markdown"
    assert body["tags"] == ["x", "y"]
    assert body["publishStatus"] == "public"


def test_bearer_header_present_on_post():
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("T", "b", [], "draft")
    assert _post_request(client)["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"


def test_tags_truncated_to_five():
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("T", "b", ["t1", "t2", "t3", "t4", "t5", "t6", "t7"], "draft")
    assert _post_request(client)["json"]["tags"] == ["t1", "t2", "t3", "t4", "t5"]


def test_publish_status_defaults_to_draft():
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("T", "b", [])
    assert _post_request(client)["json"]["publishStatus"] == "draft"


def test_unknown_publish_status_falls_back_to_draft():
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("T", "b", [], "PUBLISHED-NOW")
    # Never ship a public post by accident on an unrecognized status.
    assert _post_request(client)["json"]["publishStatus"] == "draft"


@pytest.mark.parametrize("status", ["draft", "public", "unlisted"])
def test_valid_publish_statuses_passed_through(status):
    client = FakeClient([_me(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("T", "b", [], status)
    assert _post_request(client)["json"]["publishStatus"] == status


def test_200_response_also_accepted():
    backend = _backend([_post_response(status=200)])
    assert backend.create_post("T", "b", [], "draft").url


@pytest.mark.parametrize("status", [429, 500, 503])
def test_5xx_and_429_transient(status):
    backend = _backend([_post_response(status=status)])
    with pytest.raises(TransientMediumError):
        backend.create_post("T", "b", [], "draft")


@pytest.mark.parametrize("status", [400, 401, 403, 422])
def test_4xx_permanent(status):
    backend = _backend([_post_response(status=status)])
    with pytest.raises(PermanentMediumError):
        backend.create_post("T", "b", [], "draft")


def test_author_resolution_failure_propagates_as_permanent():
    me_401 = httpx.Response(
        status_code=401, json={}, request=httpx.Request("GET", f"{API_BASE}/me")
    )
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=FakeClient([me_401]))
    with pytest.raises(PermanentMediumError):
        backend.create_post("T", "b", [], "draft")


def test_author_id_reused_across_posts():
    client = FakeClient([_me(), _post_response(), _post_response()])
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=client)
    backend.create_post("A", "b", [], "draft")
    backend.create_post("B", "b", [], "draft")
    me_calls = [r for r in client.requests if r["url"].endswith("/me")]
    assert len(me_calls) == 1


def test_network_error_on_post_is_transient():
    backend = TokenBackend(
        SecretStr(FAKE_TOKEN), client=FakeClient([_me(), httpx.ConnectError("refused")])
    )
    with pytest.raises(TransientMediumError):
        backend.create_post("T", "b", [], "draft")


def test_malformed_post_response_missing_url_is_permanent():
    bad = httpx.Response(
        status_code=201, json={"data": {"id": "p1"}},
        request=httpx.Request("POST", f"{API_BASE}/users/{AUTHOR}/posts"),
    )
    backend = _backend([bad])
    with pytest.raises(PermanentMediumError):
        backend.create_post("T", "b", [], "draft")


def test_satisfies_medium_backend_protocol():
    backend = TokenBackend(SecretStr(FAKE_TOKEN), client=FakeClient([]))
    assert isinstance(backend, MediumBackend)


def test_token_not_in_post_error_message():
    backend = _backend([_post_response(status=400)])
    try:
        backend.create_post("T", "b", [], "draft")
    except PermanentMediumError as exc:
        assert FAKE_TOKEN not in str(exc)
    else:
        raise AssertionError("expected PermanentMediumError")
