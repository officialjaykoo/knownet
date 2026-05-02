from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def _create_agent(client: TestClient):
    response = client.post(
        "/api/agents/tokens",
        json={
            "label": "Phase 15 integration agent",
            "agent_name": "phase15-integration",
            "agent_model": "pytest",
            "purpose": "phase15 integration flow",
            "role": "agent_reviewer",
            "scopes": ["preset:reader", "preset:reviewer"],
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


def test_phase7_to_14_agent_review_decision_and_implementation_flow(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        token = _create_agent(client)
        raw_token = token["raw_token"]
        agent_headers = {"authorization": f"Bearer {raw_token}"}

        onboarding = client.get("/api/agent/onboarding", headers=agent_headers)
        assert onboarding.status_code == 200, onboarding.text
        assert onboarding.json()["data"]["recommended_start_pages"]
        assert onboarding.json()["data"]["handoff_format"]["required_fields"][0] == "Title"

        state_summary = client.get("/api/agent/state-summary", headers=agent_headers)
        assert state_summary.status_code == 200, state_summary.text
        assert state_summary.json()["data"]["first_agent_brief"]["current_phase"] >= 14

        ai_state = client.get("/api/agent/ai-state?limit=5", headers=agent_headers)
        assert ai_state.status_code == 200, ai_state.text
        assert "source_path" not in ai_state.text
        assert "token_hash" not in ai_state.text
        assert "raw_token" not in ai_state.text

        markdown = """# Phase 15 Integration Review

### Finding

Title: Integration flow should remain connected
Severity: medium
Area: API

Evidence:
Onboarding, state-summary, dry-run, import, decision, and implementation should work as one flow.

Proposed change:
Keep the integration test as a regression guard.
"""

        dry_run = client.post(
            "/api/collaboration/reviews?dry_run=true",
            headers=agent_headers,
            json={"markdown": markdown, "source_agent": "phase15-integration", "source_model": "pytest"},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["data"]["finding_count"] == 1
        assert dry_run.json()["data"]["metadata"]["source_agent"] == "phase15-integration"

        submitted = client.post(
            "/api/collaboration/reviews",
            headers=agent_headers,
            json={"markdown": markdown, "source_agent": "phase15-integration", "source_model": "pytest"},
        )
        assert submitted.status_code == 200, submitted.text
        review = submitted.json()["data"]["review"]
        finding = submitted.json()["data"]["findings"][0]

        decided = client.post(
            f"/api/collaboration/findings/{finding['id']}/decision",
            json={"status": "accepted", "decision_note": "Verified by Phase 15 integration test."},
        )
        assert decided.status_code == 200, decided.text

        implemented = client.post(
            f"/api/collaboration/findings/{finding['id']}/implementation",
            json={
                "commit_sha": "abcdef1",
                "changed_files": ["apps/api/tests/test_phase15_integration.py"],
                "verification": "pytest integration flow passed",
                "notes": "Phase 7-14 regression path.",
            },
        )
        assert implemented.status_code == 200, implemented.text

        detail = client.get(f"/api/collaboration/reviews/{review['id']}")
        assert detail.status_code == 200
        assert detail.json()["data"]["review"]["status"] == "triaged"
        assert detail.json()["data"]["findings"][0]["status"] == "implemented"
        assert detail.json()["data"]["implementation_records"]

        graph = client.get("/api/graph?node_type=review,finding,commit&limit=100")
        assert graph.status_code == 200, graph.text
        assert {"review", "finding", "commit"}.issubset({node["node_type"] for node in graph.json()["data"]["nodes"]})

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200, verify.text
        assert verify.json()["data"]["ok"] is True
    get_settings.cache_clear()
