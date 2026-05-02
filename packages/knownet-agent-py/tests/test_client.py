import json
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from knownet_agent import (
    KnowNetAuthError,
    KnowNetClient,
    KnowNetPayloadTooLargeError,
    KnowNetRateLimitError,
    KnowNetScopeError,
)


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_auth_header_and_metadata():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch("urllib.request.urlopen", return_value=FakeResponse({"ok": True, "data": {"pages": []}, "meta": {"truncated": True, "total_count": 9, "returned_count": 1}}, {"X-Token-Expires-In": "42"})) as mocked:
        response = client.list_pages(limit=1)
    request = mocked.call_args.args[0]
    assert request.headers["Authorization"] == "Bearer kn_agent_test"
    assert response.truncated is True
    assert response.total_count == 9
    assert response.returned_count == 1
    assert response.expires_in_seconds == 42


def test_from_env_requires_token(monkeypatch):
    monkeypatch.delenv("KNOWNET_AGENT_TOKEN", raising=False)
    with pytest.raises(ValueError):
        KnowNetClient.from_env()

    monkeypatch.setenv("KNOWNET_AGENT_TOKEN", "kn_agent_env")
    monkeypatch.setenv("KNOWNET_BASE_URL", "http://knownet")
    client = KnowNetClient.from_env()
    assert client.base_url == "http://knownet"
    assert client.token == "kn_agent_env"


def test_error_mapping():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    for status, error_type in [(401, KnowNetAuthError), (403, KnowNetScopeError), (413, KnowNetPayloadTooLargeError), (429, KnowNetRateLimitError)]:
        body = json.dumps({"detail": {"message": "failed", "details": {"retry_after_seconds": 30}}}).encode("utf-8")
        error = HTTPError("http://knownet", status, "failed", {}, None)
        error.fp = type("Body", (), {"read": lambda self, data=body: data})()
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(error_type):
                client.me()


def test_dry_run_and_submit_paths():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch("urllib.request.urlopen", return_value=FakeResponse({"ok": True, "data": {}})) as mocked:
        client.dry_run_review("### Finding")
        client.submit_review("### Finding")
    paths = [call.args[0].full_url for call in mocked.call_args_list]
    assert paths[0].endswith("/api/collaboration/reviews?dry_run=true")
    assert paths[1].endswith("/api/collaboration/reviews")


def test_writes_do_not_retry():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch("urllib.request.urlopen", side_effect=URLError("down")) as mocked:
        with pytest.raises(URLError):
            client.submit_review("### Finding")
    assert mocked.call_count == 1
