"""Medium REST backend using a pre-2025 integration token (spec 5.3, TokenBackend).

Talks to https://api.medium.com over httpx. The token is read from a SecretStr
only at the moment a request header is built, is never interpolated into a log
line or an exception message, and is registered with the redacting logger so it
is scrubbed even if some downstream code logs a header by mistake.

HTTP failures are classified transient (network, 429, 5xx) vs permanent (other
4xx, malformed response) so Wave 5's orchestrator can route per spec 6 — the
same split drive_client uses (TransientDriveError/PermanentDriveError).
"""

from __future__ import annotations

import logging

import httpx

from ..config import SecretStr
from ..logging_setup import RedactingFilter
from ..types import PostResult

logger = logging.getLogger("gdoc_to_medium.medium.token_backend")

API_BASE = "https://api.medium.com/v1"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Medium accepts only these image content types on /v1/images (research note).
SUPPORTED_IMAGE_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/tiff"}
)

# Medium caps tags at 5; truncate defensively rather than let the API 400.
MAX_TAGS = 5

_VALID_PUBLISH_STATUS = frozenset({"draft", "public", "unlisted"})


class MediumClientError(Exception):
    """Base class for medium_client failures."""


class TransientMediumError(MediumClientError):
    """A retryable failure (network, HTTP 429/5xx) — leave the doc in Ready (spec 6)."""


class PermanentMediumError(MediumClientError):
    """A non-retryable failure (other HTTP 4xx, malformed response) — route to Failed (spec 6)."""


def _classify_status(status: int, context: str) -> MediumClientError:
    """Map an HTTP status to transient vs permanent (spec 6). Token is never in the message."""
    if status == 429 or 500 <= status < 600:
        return TransientMediumError(f"{context}: Medium API returned HTTP {status} (transient)")
    return PermanentMediumError(f"{context}: Medium API returned HTTP {status} (permanent)")


class TokenBackend:
    """Create posts and upload images on Medium via the REST API (spec 5.3).

    The httpx client is injected so tests run against a mock with no network; in
    production a default client with sane timeouts is created. The author id is
    resolved once from /v1/me and cached for the life of the backend.
    """

    def __init__(
        self,
        token: SecretStr,
        *,
        client: httpx.Client | None = None,
        redactor: RedactingFilter | None = None,
    ) -> None:
        if not isinstance(token, SecretStr):
            raise TypeError("token must be a SecretStr so it is never logged or repr'd")
        self._token = token
        # Register before any request so the value is scrubbed everywhere it could surface.
        if redactor is not None:
            redactor.add_secret(token.get())
        self._client = client if client is not None else httpx.Client(timeout=_TIMEOUT)
        self._author_id: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        # The only place the raw token is read; the dict is passed straight to httpx,
        # never logged. If httpx is ever asked to log this header, the redactor scrubs it.
        return {
            "Authorization": f"Bearer {self._token.get()}",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Issue a request, turning transport failures into typed errors.

        Connection/timeout problems are retryable; the orchestrator leaves the
        doc in Ready and tries again next run. `from None` suppresses the
        exception chain: the chained httpx error holds .request.headers with the
        live Bearer token, which the traceback printer would otherwise surface in
        logs or on an uncaught crash. The error keeps only the transport type.
        """
        headers = {**self._auth_headers(), **kwargs.pop("headers", {})}
        try:
            return self._client.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise TransientMediumError(
                f"Timed out contacting Medium API ({type(exc).__name__})"
            ) from None
        except httpx.TransportError as exc:
            raise TransientMediumError(
                f"Network error contacting Medium API ({type(exc).__name__})"
            ) from None
        except httpx.RequestError as exc:
            # e.g. DecodingError: garbled response encoding — not retryable.
            raise PermanentMediumError(
                f"Unexpected error contacting Medium API ({type(exc).__name__})"
            ) from None

    @staticmethod
    def _data_field(response: httpx.Response, key: str, context: str) -> str:
        """Pull data.<key> from a Medium JSON response, failing clearly on a malformed body.

        A missing data/key or a non-JSON body is a permanent error (we can't make
        the response well-formed by retrying), surfaced with a clear message rather
        than a raw KeyError/JSONDecodeError leaking to the orchestrator.
        """
        try:
            payload = response.json()
        except ValueError as exc:
            raise PermanentMediumError(
                f"{context}: Medium response was not valid JSON"
            ) from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise PermanentMediumError(f"{context}: Medium response missing 'data' object")
        value = data.get(key)
        if not isinstance(value, str) or not value:
            raise PermanentMediumError(f"{context}: Medium response missing 'data.{key}'")
        return value

    def author_id(self) -> str:
        """Resolve and cache the author id from GET /v1/me (spec research note).

        A 401/403 here means the token is invalid or lacks scope — permanent, so
        the orchestrator routes the doc to Failed rather than retrying forever.
        """
        if self._author_id is not None:
            return self._author_id
        response = self._request("GET", f"{API_BASE}/me")
        if response.status_code != 200:
            raise _classify_status(response.status_code, "resolving author id (/v1/me)")
        author_id = self._data_field(response, "id", "resolving author id (/v1/me)")
        self._author_id = author_id
        logger.info("resolved Medium author id")
        return author_id

    def upload_image(self, data: bytes, content_type: str) -> str:
        """Upload image bytes to /v1/images and return the hosted Medium URL (spec 5.3).

        The content type is validated locally first: Medium accepts only
        jpeg/png/gif/tiff, so an unsupported type is a permanent error caught
        before we waste a network round trip. The multipart form field must be
        named exactly 'image' (research note).
        """
        normalized = (content_type or "").strip().lower()
        if normalized not in SUPPORTED_IMAGE_TYPES:
            supported = ", ".join(sorted(SUPPORTED_IMAGE_TYPES))
            raise PermanentMediumError(
                f"uploading image: unsupported content type {normalized!r}; "
                f"Medium accepts only {supported}"
            )
        files = {"image": ("image", data, normalized)}
        response = self._request("POST", f"{API_BASE}/images", files=files)
        if response.status_code != 201:
            raise _classify_status(response.status_code, "uploading image (/v1/images)")
        return self._data_field(response, "url", "uploading image (/v1/images)")

    def create_post(
        self,
        title: str,
        markdown: str,
        tags: list[str],
        publish_status: str = "draft",
    ) -> PostResult:
        """Create a Medium post from markdown and return its URL (spec 5.3, research note).

        Posts to /v1/users/{authorId}/posts; the author id is resolved lazily on
        first use. Tags are defensively capped at Medium's limit of 5 and an
        unrecognized publish_status falls back to 'draft' so we never ship a
        public post by accident. A 429/5xx is transient (retry next run); any
        other failure is permanent (route the doc to Failed).
        """
        author = self.author_id()
        status = publish_status if publish_status in _VALID_PUBLISH_STATUS else "draft"
        body = {
            "title": title,
            "content": markdown,
            "contentFormat": "markdown",
            "tags": list(tags)[:MAX_TAGS],
            "publishStatus": status,
        }
        context = "creating post (/v1/users/{authorId}/posts)"
        # httpx sets Content-Type: application/json automatically from json=.
        response = self._request(
            "POST",
            f"{API_BASE}/users/{author}/posts",
            json=body,
        )
        if response.status_code not in (200, 201):
            raise _classify_status(response.status_code, context)
        url = self._data_field(response, "url", context)
        logger.info("created Medium post (publishStatus=%s)", status)
        return PostResult(url=url)
