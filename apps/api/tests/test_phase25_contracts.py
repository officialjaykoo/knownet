import json
import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.services.ignore_policy import classify_path, forbidden_text_reason


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("LOCAL_EMBEDDING_AUTO_LOAD", "false")


def test_ignore_policy_blocks_common_secret_and_generated_paths():
    assert classify_path(".env")["blocked"] is True
    assert classify_path("data/knownet.db")["blocked"] is True
    assert classify_path("apps/web/.next/server.js")["blocked"] is True
    assert classify_path("data/pages/safe.md")["blocked"] is False
    assert forbidden_text_reason("OPENAI_API_KEY=sk-test")["reason"] == "secret_assignment"
    assert forbidden_text_reason("plain public note") is None


def test_agent_onboarding_exposes_contract_v1(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = client.post(
            "/api/agents/tokens",
            json={
                "label": "Claude review",
                "agent_name": "claude",
                "agent_model": "sonnet",
                "purpose": "review",
                "role": "agent_reviewer",
                "scopes": ["preset:reader", "preset:reviewer"],
            },
        )
        assert token.status_code == 200, token.text
        raw = token.json()["data"]["token"]["raw_token"]
        onboarding = client.get("/api/agent/onboarding", headers={"authorization": f"Bearer {raw}"})
        assert onboarding.status_code == 200, onboarding.text
        contract = onboarding.json()["data"]["agent_contract"]
        assert contract["contract_version"] == "knownet.agent.v1"
        assert contract["access_mode"] == "snapshot"
        assert contract["entrypoints"]["mcp_resource"] == "knownet://snapshot/overview"
        assert "request_database_file" in {item["action"] for item in contract["forbidden"]}
    get_settings.cache_clear()


def test_verify_fts_reports_missing_index_rows(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        page = client.post("/api/pages", json={"slug": "verify-fts-missing", "title": "Verify FTS Missing"})
        assert page.status_code == 200
        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute("DELETE FROM pages_fts")
            connection.commit()
        verify = client.get("/api/maintenance/search/verify-fts")
        assert verify.status_code == 200
        codes = {issue["code"] for issue in verify.json()["data"]["issues"]}
        assert "fts_page_missing" in codes
        verify_index = client.get("/api/maintenance/verify-index")
        assert verify_index.status_code == 200
        index_codes = {issue["code"] for issue in verify_index.json()["data"]["issues"]}
        assert "fts_page_missing" in index_codes
    get_settings.cache_clear()


def test_project_snapshot_includes_source_manifest(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        page = client.post("/api/pages", json={"slug": "manifest-node", "title": "Manifest Node"})
        assert page.status_code == 200
        snapshot = client.post("/api/collaboration/project-snapshot-packets", json={"target_agent": "claude"})
        assert snapshot.status_code == 200, snapshot.text
        data = snapshot.json()["data"]
        assert data["source_manifest"]["type"] == "source_manifest"
        assert data["source_manifest"]["sources"]
        packet_file = get_settings().data_dir / data["links"]["storage"]["href"]
        content = packet_file.read_text(encoding="utf-8")
        assert json.loads(content)["source_manifest"]["type"] == "source_manifest"
    get_settings.cache_clear()


def test_snapshot_verify_endpoint_reports_valid_snapshot(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        page = client.post("/api/pages", json={"slug": "verify-snapshot", "title": "Verify Snapshot"})
        assert page.status_code == 200
        snapshot = client.post("/api/maintenance/snapshots")
        assert snapshot.status_code == 200
        name = snapshot.json()["data"]["name"]
        verified = client.get(f"/api/maintenance/snapshots/{name}/verify")
        assert verified.status_code == 200, verified.text
        data = verified.json()["data"]
        assert data["status"] == "valid"
        assert data["manifest"]["kind"] == "knownet.snapshot"
    get_settings.cache_clear()
