from fastapi.testclient import TestClient
import json
import sqlite3

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def _create_token(client: TestClient, scopes, role="agent_reader", expires_at="2099-01-01T00:00:00Z"):
    response = client.post(
        "/api/agents/tokens",
        json={
            "label": "External reviewer",
            "agent_name": "claude",
            "agent_model": "claude-test",
            "purpose": "phase9-test",
            "role": role,
            "scopes": scopes,
            "expires_at": expires_at,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


def test_agent_token_lifecycle_and_self_read(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _create_token(client, ["preset:reader"])
        raw_token = token["raw_token"]
        assert raw_token.startswith("kn_agent_")
        assert "token_hash" not in token
        assert set(token["scopes"]) == {"pages:read", "graph:read", "citations:read"}

        listed = client.get("/api/agents/tokens")
        assert listed.status_code == 200
        listed_token = listed.json()["data"]["tokens"][0]
        assert "raw_token" not in listed_token
        assert "token_hash" not in listed_token

        ping = client.get("/api/agent/ping")
        assert ping.status_code == 200
        assert ping.json() == {"ok": True, "version": "9.0"}

        me = client.get("/api/agent/me", headers={"authorization": f"Bearer {raw_token}"})
        assert me.status_code == 200, me.text
        assert me.headers["X-Token-Expires-In"].isdigit()
        data = me.json()["data"]
        assert data["token_id"] == token["id"]
        assert "raw_token" not in str(data)
        assert "token_hash" not in str(data)

        revoked = client.post(f"/api/agents/tokens/{token['id']}/revoke")
        assert revoked.status_code == 200
        rejected = client.get("/api/agent/me", headers={"authorization": f"Bearer {raw_token}"})
        assert rejected.status_code == 401
    get_settings.cache_clear()


def test_agent_token_expiry_validation_and_missing_revoke(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        invalid = client.post(
            "/api/agents/tokens",
            json={
                "label": "Bad expiry",
                "agent_name": "agent",
                "purpose": "test",
                "role": "agent_reader",
                "scopes": ["pages:read"],
                "expires_at": "2099-01-01T00:00:00",
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "agent_expiry_invalid"

        valid = _create_token(client, ["pages:read"], expires_at="2099-01-01T09:00:00+09:00")
        assert valid["expires_at"] == "2099-01-01T00:00:00Z"

        missing = client.post("/api/agents/tokens/agent_missing/revoke")
        assert missing.status_code == 404
    get_settings.cache_clear()


def test_agent_scoped_read_and_denied_write(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "phase9-page", "title": "Phase9 Page"})
        assert created.status_code == 200
        page_id = "page_phase9_page"
        token = _create_token(client, ["pages:read"])
        raw_token = token["raw_token"]

        pages = client.get("/api/agent/pages", headers={"authorization": f"Bearer {raw_token}"})
        assert pages.status_code == 200
        assert pages.json()["data"]["pages"][0]["id"] == page_id

        page = client.get(f"/api/agent/pages/{page_id}", headers={"authorization": f"Bearer {raw_token}"})
        assert page.status_code == 200
        assert page.json()["data"]["page"]["slug"] == "phase9-page"

        write = client.post(
            "/api/collaboration/reviews",
            headers={"authorization": f"Bearer {raw_token}"},
            json={"markdown": "### Finding\n\nSeverity: info\nArea: Docs\n\nEvidence:\nRead.\n\nProposed change:\nNone."},
        )
        assert write.status_code == 403

        maintenance = client.get("/api/maintenance/snapshots", headers={"authorization": f"Bearer {raw_token}"})
        assert maintenance.status_code == 403
    get_settings.cache_clear()


def test_agent_ai_state_returns_structured_json_rows(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "structured-state", "title": "Structured State"})
        assert created.status_code == 200
        settings = app.state.settings
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "ai_state_structured_state",
                    "local-default",
                    "page_structured_state",
                    "structured-state",
                    "Structured State",
                    "data/pages/structured-state.md",
                    "hash",
                    json.dumps({"schema_version": 1, "summary": "structured json"}),
                    "2026-05-02T00:00:00Z",
                ),
            )
        token = _create_token(client, ["pages:read"])
        response = client.get("/api/agent/ai-state", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["data"]["ai_state_pages"][0]["slug"] == "structured-state"
        assert payload["data"]["ai_state_pages"][0]["state"]["summary"] == "structured json"
        assert payload["meta"]["total_count"] == 1
    get_settings.cache_clear()


def test_agent_review_dry_run_and_access_events(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _create_token(client, ["preset:reviewer"], role="agent_reviewer")
        raw_token = token["raw_token"]
        markdown = "# Review\n\n### Finding\n\nSeverity: medium\nArea: api\n\nEvidence:\nEndpoint needs preview.\n\nProposed change:\nUse dry-run."

        dry_run = client.post(
            "/api/collaboration/reviews?dry_run=true",
            headers={"authorization": f"Bearer {raw_token}"},
            json={"markdown": markdown, "source_agent": "claude"},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["data"]["dry_run"] is True
        assert dry_run.json()["data"]["finding_count"] == 1

        reviews = client.get("/api/collaboration/reviews")
        assert reviews.status_code == 200
        assert reviews.json()["data"]["reviews"] == []

        events = client.get(f"/api/agents/tokens/{token['id']}/events")
        assert events.status_code == 200
        event = events.json()["data"]["events"][0]
        assert event["action"] == "review.dry_run"
        assert "raw_token" not in str(event)
        assert "token_hash" not in str(event)
    get_settings.cache_clear()
