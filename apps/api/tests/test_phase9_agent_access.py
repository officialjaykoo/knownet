from fastapi.testclient import TestClient
import json
import sqlite3

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.services.ai_state import build_ai_state_for_page


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
        assert data["start_here_hint"] == "recommended"
        assert data["start_here_status"]["hint_reason"] == "no_recent_start_seen"
        assert data["onboarding_endpoint"] == "/api/agent/onboarding"
        assert "token creation label" in data["model_label_note"]
        assert data["recommended_start_pages"][0]["slug"] == "start-here-for-external-ai-agents"
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


def test_agent_onboarding_available_without_read_scopes(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _create_token(client, [])
        response = client.get("/api/agent/onboarding", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert response.status_code == 200, response.text
        payload = response.json()
        data = payload["data"]
        assert data["start_here_hint"] == "recommended"
        assert data["start_here_status"]["hint_reason"] == "no_recent_start_seen"
        assert data["recommended_start_pages"][0]["slug"] == "start-here-for-external-ai-agents"
        assert data["allowed_actions"] == []
        assert any(item["required_scope"] == "pages:read" for item in data["unavailable_actions"])
        assert "dry-run" in " ".join(item["purpose"] for item in data["review_workflow"]).lower()
        assert data["start_here_hint_legend"]["recommended"]
        assert data["start_here_status"]["scope"] == "token_local"
        assert any(item["action"] == "request_database_file" for item in data["forbidden_actions"])
        assert data["handoff_format"]["required_fields"][0] == "Title"
        assert "example_valid_finding" in data["handoff_format"]
        assert data["conflict_resolution_policy"]["on_conflict"]
        assert "raw_tokens" in data["security_boundary_policy"]
        assert data["infrastructure_notice"]["production_ready"] is False
        assert payload["meta"]["schema_version"] == 1

        events = client.get(f"/api/agents/tokens/{token['id']}/events")
        assert events.status_code == 200
        assert events.json()["data"]["events"][0]["action"] == "agent.onboarding"

        second = client.get("/api/agent/onboarding", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert second.status_code == 200
        assert second.json()["data"]["start_here_hint"] == "available"
        assert second.json()["data"]["start_here_status"]["seen_count"] == 1
    get_settings.cache_clear()


def test_agent_me_warns_when_token_has_no_expiry(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _create_token(client, ["pages:read"], expires_at=None)
        response = client.get("/api/agent/me", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert response.status_code == 200, response.text
        assert response.headers["X-Token-Warning"] == "no_expiry"
        data = response.json()["data"]
        assert data["expires_at"] is None
        assert data["token_warning"] == "no_expiry"
        assert data["token_management"]["warning"] == "no_expiry"
        assert data["token_management"]["operator_alert_available"] is False
        assert data["token_management"]["escalation_endpoint"] is None
        assert "Agent Dashboard" in data["token_management"]["operator_action"]
        assert "raw token" in data["token_management"]["agent_rule"]

        onboarding = client.get("/api/agent/onboarding", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert onboarding.status_code == 200
        assert onboarding.json()["data"]["token_management"]["warning"] == "no_expiry"

        state_summary = client.get("/api/agent/state-summary", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert state_summary.status_code == 200
        assert state_summary.json()["data"]["token_management"]["warning"] == "no_expiry"
    get_settings.cache_clear()


def test_onboarding_pages_are_locked_and_marked_on_read_surfaces(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        protected_slug = "protected-system-page"
        protected_page_id = "page_protected_system_page"
        created = client.post("/api/pages", json={"slug": protected_slug, "title": "Protected System Page"})
        assert created.status_code == 200
        settings = app.state.settings
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO system_pages (page_id, kind, tier, locked, owner, description, registered_at_phase, created_at, updated_at) "
                "VALUES (?, 'onboarding', 1, 1, 'system', 'test', 'phase_14', '2026-05-02T00:00:00Z', '2026-05-02T00:00:00Z')",
                (protected_page_id,),
            )
            connection.execute(
                "INSERT INTO suggestions (id, job_id, message_id, path, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', '2026-05-02T00:00:00Z', '2026-05-02T00:00:00Z')",
                ("sug_locked", "job_locked", "msg_locked", str(settings.data_dir / "suggestions" / "locked.md"), "Start Here"),
            )
            connection.commit()

        listed = client.get("/api/pages")
        assert listed.status_code == 200
        page_row = next(row for row in listed.json()["data"]["pages"] if row["slug"] == protected_slug)
        assert page_row["system_kind"] == "onboarding"
        assert page_row["system_tier"] == 1
        assert page_row["system_locked"] is True

        detail = client.get(f"/api/pages/{protected_slug}")
        assert detail.status_code == 200
        assert detail.json()["data"]["system_locked"] is True

        token = _create_token(client, ["pages:read"])
        agent_pages = client.get("/api/agent/pages", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert agent_pages.status_code == 200
        agent_page = next(row for row in agent_pages.json()["data"]["pages"] if row["slug"] == protected_slug)
        assert agent_page["system_kind"] == "onboarding"

        agent_page_detail = client.get(f"/api/agent/pages/{protected_page_id}", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert agent_page_detail.status_code == 200
        assert agent_page_detail.json()["data"]["page"]["system_locked"] is True

        graph_rebuild = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert graph_rebuild.status_code == 200
        graph = client.get("/api/graph", params={"node_type": "page"})
        assert graph.status_code == 200
        graph_node = next(row for row in graph.json()["data"]["nodes"] if row["target_id"] == protected_page_id)
        assert graph_node["system_kind"] == "onboarding"
        assert graph_node["meta"]["system_tier"] == 1

        create_again = client.post("/api/pages", json={"slug": protected_slug, "title": "Overwrite"})
        assert create_again.status_code == 423
        assert create_again.json()["detail"]["code"] == "system_page_locked"

        applied = client.post("/api/suggestions/sug_locked/apply", json={"slug": protected_slug})
        assert applied.status_code == 423
        assert applied.json()["detail"]["code"] == "system_page_locked"

        restored = client.post(f"/api/pages/{protected_slug}/revisions/rev_missing/restore")
        assert restored.status_code == 423

        deleted = client.delete(f"/api/pages/{protected_slug}")
        assert deleted.status_code == 423
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
            connection.execute(
                "INSERT INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "ai_state_structured_state_2",
                    "local-default",
                    "page_structured_state_2",
                    "structured-state-2",
                    "Structured State 2",
                    "data/pages/structured-state-2.md",
                    "hash2",
                    json.dumps({"schema_version": 1, "summary": "structured json 2"}),
                    "2026-05-02T00:00:01Z",
                ),
            )
        token = _create_token(client, ["pages:read"])
        response = client.get("/api/agent/ai-state?limit=1", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["data"]["ai_state_pages"][0]["slug"] == "structured-state-2"
        assert "source_path" not in payload["data"]["ai_state_pages"][0]
        assert payload["data"]["ai_state_pages"][0]["source_ref"] == "pages/structured-state-2.md"
        assert payload["data"]["ai_state_pages"][0]["state"]["summary"] == "structured json 2"
        assert "path" not in payload["data"]["ai_state_pages"][0]["state"].get("source", {})
        assert payload["meta"]["total_count"] == 2
        assert payload["meta"]["truncated"] is True
        assert payload["meta"]["has_more"] is True
        assert payload["meta"]["next_offset"] == 1
    get_settings.cache_clear()


def test_ai_state_builder_preserves_api_path_hyphens(tmp_path):
    page = tmp_path / "external-ai-first-30-minutes.md"
    page.write_text(
        "---\ntitle: External AI First 30 Minutes\nslug: external-ai-first-30-minutes\n---\n\n"
        "# External AI First 30 Minutes\n\n"
        "Call `GET /api/agent/state-summary` and `GET /api/agent/ai-state`.\n",
        encoding="utf-8",
    )
    state = build_ai_state_for_page(page)["state_json"]
    assert "state-summary" in state["summary"]
    assert "ai-state" in state["summary"]
    assert "state summary" not in state["summary"]
    assert "ai state" not in state["summary"]


def test_agent_ai_state_advances_offset_when_range_contains_only_drafts(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = app.state.settings
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "ai_state_draft_only",
                    "local-default",
                    "page_draft_only",
                    "draft-only",
                    "Draft Only",
                    "data/pages/draft-only.md",
                    "hash-draft",
                    json.dumps(
                        {
                            "schema_version": 1,
                            "summary": "draft",
                            "sections": [
                                {"heading": "Question"},
                                {"heading": "Claims"},
                                {"heading": "Evidence"},
                                {"heading": "Next Actions"},
                            ],
                        }
                    ),
                    "2026-05-02T00:00:02Z",
                ),
            )
            connection.execute(
                "INSERT INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "ai_state_published_after_draft",
                    "local-default",
                    "page_published_after_draft",
                    "published-after-draft",
                    "Published After Draft",
                    "data/pages/published-after-draft.md",
                    "hash-published",
                    json.dumps({"schema_version": 1, "summary": "published", "sections": [{"heading": "Current State"}]}),
                    "2026-05-02T00:00:01Z",
                ),
            )
        token = _create_token(client, ["pages:read"])
        response = client.get("/api/agent/ai-state?limit=1", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["data"]["ai_state_pages"] == []
        assert payload["meta"]["returned_count"] == 0
        assert payload["meta"]["skipped_drafts"] == 1
        assert payload["meta"]["has_more"] is True
        assert payload["meta"]["next_offset"] == 1
        assert payload["meta"]["no_published_in_range"] is True
        assert payload["meta"]["warning"] == "page_range_contains_only_drafts_use_next_offset"
    get_settings.cache_clear()


def test_agent_state_summary_explains_counts(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _create_token(client, ["pages:read"])
        response = client.get("/api/agent/state-summary", headers={"authorization": f"Bearer {token['raw_token']}"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert response.json()["meta"]["has_more"] is False
        assert "ai_state_coverage_note" in data
        assert "graph_node_breakdown" in data
        assert data["collaboration_status"]["ready_for_review"] is True
        assert data["first_agent_brief"]["current_phase"] >= 14
        assert "current_phase" in data["first_agent_brief"]["phase_label_note"]
        assert data["first_agent_brief"]["current_priorities"]
        assert data["phase_status"]["implemented"] is True
        assert data["phase_status"]["release_ready_blockers"]
        assert data["conflict_resolution_policy"]["canonical_state"]
        assert data["security_boundary_policy"]["write_boundary"]
        assert data["infrastructure_notice"]["recommended_use"] == "testing_only"
        assert data["first_agent_brief"]["risk_mitigation_status"]
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
        assert dry_run.json()["data"]["metadata"]["source_agent"] == "claude"

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
