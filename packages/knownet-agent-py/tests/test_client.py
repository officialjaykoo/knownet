import json
import socket
import sys
import threading
import time
import urllib.request
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from knownet_agent import (
    AsyncKnowNetClient,
    KnowNetAuthError,
    KnowNetClient,
    KnowNetConnectionError,
    KnowNetPage,
    KnowNetPayloadTooLargeError,
    KnowNetRateLimitError,
    KnowNetScopeError,
    KnowNetVersionError,
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
    assert response.meta_obj.total_count == 9


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
        error = HTTPError("http://knownet", status, "failed", {}, BytesIO(body))
        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(error_type):
                client.me()


def test_error_properties_and_connection_mapping():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    body = json.dumps({"detail": {"message": "missing", "details": {"scope": "reviews:read", "current_scopes": ["pages:read"]}}}).encode("utf-8")
    error = HTTPError("http://knownet", 403, "failed", {}, BytesIO(body))
    with patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(KnowNetScopeError) as raised:
            client.me()
    assert raised.value.required_scope == "reviews:read"
    assert raised.value.current_scopes == ["pages:read"]

    with patch("urllib.request.urlopen", side_effect=URLError("down")):
        with pytest.raises(KnowNetConnectionError):
            client.submit_review("### Finding")


def test_malformed_json_and_schema_version():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")

    class BadJson(FakeResponse):
        def read(self):
            return b"{"

    with patch("urllib.request.urlopen", return_value=BadJson({})):
        with pytest.raises(Exception):
            client.me()
    with patch("urllib.request.urlopen", return_value=FakeResponse({"ok": True, "data": {}, "meta": {"schema_version": 999}})):
        with pytest.raises(KnowNetVersionError):
            client.me()


def test_dry_run_and_submit_paths():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch("urllib.request.urlopen", return_value=FakeResponse({"ok": True, "data": {}})) as mocked:
        client.dry_run_review("### Finding")
        client.submit_review("### Finding")
    paths = [call.args[0].full_url for call in mocked.call_args_list]
    assert paths[0].endswith("/api/collaboration/reviews?dry_run=true")
    assert paths[1].endswith("/api/collaboration/reviews")


def test_typed_models_context_manager_and_async_placeholder():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch("urllib.request.urlopen", return_value=FakeResponse({"ok": True, "data": {"pages": [{"id": "page_1", "slug": "one", "title": "One"}]}, "meta": {}})):
        with client as active:
            pages = active.list_pages().pages()
    assert client._closed is True
    assert pages == [KnowNetPage(id="page_1", slug="one", title="One", updated_at=None, content=None)]
    with pytest.raises(NotImplementedError):
        AsyncKnowNetClient()


def test_iteration_helpers_respect_next_offset_and_max_items():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    responses = [
        FakeResponse({"ok": True, "data": {"pages": [{"id": "page_1"}, {"id": "page_2"}]}, "meta": {"next_offset": 2}}),
        FakeResponse({"ok": True, "data": {"pages": [{"id": "page_3"}]}, "meta": {}}),
    ]
    with patch("urllib.request.urlopen", side_effect=responses):
        pages = list(client.iter_pages(limit=2, max_items=3))
    assert [page.id for page in pages] == ["page_1", "page_2", "page_3"]


def test_workflow_helpers():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch.object(client, "me", return_value=FakeResponse({"scopes": ["pages:read"]})):
        pass
    me_response = type("Response", (), {"data": {"scopes": ["pages:read"]}, "expires_in_seconds": 10, "meta_obj": type("Meta", (), {"token_expires_in_seconds": None})()})()
    with patch.object(client, "me", return_value=me_response):
        with pytest.raises(KnowNetScopeError):
            client.require_scopes(["reviews:create"])
        assert client.token_expires_soon(60) is True

    dry_zero = type("Response", (), {"data": {"finding_count": 0}, "meta": {}})()
    with patch.object(client, "dry_run_review", return_value=dry_zero), patch.object(client, "submit_review") as submit:
        result = client.dry_run_then_submit_review("review")
    assert result.meta["warning"] == "dry_run_zero_findings_not_submitted"
    assert submit.call_count == 0

    dry_ok = type("Response", (), {"data": {"finding_count": 1}, "meta": {}})()
    submitted = type("Response", (), {"data": {"id": "review_1"}, "meta": {}})()
    with patch.object(client, "dry_run_review", return_value=dry_ok), patch.object(client, "submit_review", return_value=submitted) as submit:
        assert client.dry_run_then_submit_review("review") is submitted
    assert submit.call_count == 1


def test_writes_do_not_retry():
    client = KnowNetClient(base_url="http://knownet", token="kn_agent_test")
    with patch("urllib.request.urlopen", side_effect=URLError("down")) as mocked:
        with pytest.raises(KnowNetConnectionError):
            client.submit_review("### Finding")
    assert mocked.call_count == 1


def test_sdk_end_to_end_against_knownet_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "data" / "state.sqlite"))
    sys.path.insert(0, "apps/api")
    import uvicorn
    from knownet_api.config import get_settings
    from knownet_api.main import app

    get_settings.cache_clear()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", ws="none")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                urllib.request.urlopen(f"{base_url}/api/agent/ping", timeout=1).read()
                break
            except URLError:
                time.sleep(0.05)
        create_page = urllib.request.Request(
            f"{base_url}/api/pages",
            data=json.dumps({"slug": "sdk-page", "title": "SDK Page"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(create_page, timeout=5).read()
        create_token = urllib.request.Request(
            f"{base_url}/api/agents/tokens",
            data=json.dumps({
                "label": "SDK E2E",
                "agent_name": "sdk-test",
                "purpose": "phase12",
                "role": "agent_reviewer",
                "scopes": ["preset:reader", "preset:reviewer"],
                "expires_at": "2099-01-01T00:00:00Z",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        token_value = json.loads(urllib.request.urlopen(create_token, timeout=5).read().decode("utf-8"))["data"]["token"]["raw" + "_token"]
        client = KnowNetClient(base_url=base_url, token=token_value)
        assert client.ping().data["ok"] is True
        assert client.me().data["token_id"]
        assert [page.id for page in client.iter_pages(max_items=1)]
        assert client.read_page("page_sdk_page").page().slug == "sdk-page"
        client.require_scopes(["reviews:create", "pages:read"])
        assert client.token_expires_soon() is False
        review = "### Finding\n\nSeverity: info\nArea: Docs\n\nEvidence:\nSDK E2E.\n\nProposed change:\nNone."
        assert client.dry_run_review(review).data["finding_count"] == 1
        assert client.submit_review(review).data["review"]["id"]
        assert token_value not in json.dumps(client.me().data)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        get_settings.cache_clear()
