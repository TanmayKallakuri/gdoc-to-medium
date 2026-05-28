"""T5.2 image sourcing: download inline-image bytes with the SA-authorized session,
classifying failures transient vs permanent (spec 6) with no network."""

from __future__ import annotations

import pytest

from gdoc_to_medium.image_source import make_authorized_downloader
from gdoc_to_medium.orchestrator import ImageDownloadError
from gdoc_to_medium.types import ImageRef


class _Resp:
    def __init__(self, status_code, content=b"", content_type="image/png"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


def _session_factory(resp=None, raise_exc=None):
    class _Session:
        def __init__(self, creds):
            self.creds = creds

        def get(self, uri, timeout=None):
            if raise_exc is not None:
                raise raise_exc
            return resp

    return _Session


def test_returns_bytes_and_normalized_content_type():
    factory = _session_factory(_Resp(200, b"PNGDATA", "image/png; charset=binary"))
    download = make_authorized_downloader("creds", session_factory=factory)
    data, content_type = download(ImageRef(object_id="o1", content_uri="https://g/img"), {})
    assert data == b"PNGDATA"
    assert content_type == "image/png"  # parameters stripped


def test_missing_content_uri_is_permanent():
    download = make_authorized_downloader("creds", session_factory=_session_factory(_Resp(200)))
    with pytest.raises(ImageDownloadError) as caught:
        download(ImageRef(object_id="o1", content_uri=None), {})
    assert caught.value.transient is False


def test_network_error_is_transient_without_chain():
    factory = _session_factory(raise_exc=ConnectionError("connection reset"))
    download = make_authorized_downloader("creds", session_factory=factory)
    with pytest.raises(ImageDownloadError) as caught:
        download(ImageRef(object_id="o1", content_uri="https://g/img"), {})
    assert caught.value.transient is True
    # from None: the underlying error is not chained (could carry the signed URL).
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_5xx_and_429_are_transient():
    for status in (500, 503, 429):
        factory = _session_factory(_Resp(status))
        download = make_authorized_downloader("c", session_factory=factory)
        with pytest.raises(ImageDownloadError) as caught:
            download(ImageRef(object_id="o1", content_uri="u"), {})
        assert caught.value.transient is True, status


def test_4xx_is_permanent():
    for status in (403, 404):
        factory = _session_factory(_Resp(status))
        download = make_authorized_downloader("c", session_factory=factory)
        with pytest.raises(ImageDownloadError) as caught:
            download(ImageRef(object_id="o1", content_uri="u"), {})
        assert caught.value.transient is False, status
