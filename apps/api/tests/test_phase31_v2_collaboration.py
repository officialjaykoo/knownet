from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_v2(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet-v2.db"))
    monkeypatch.setenv("KNOWNET_DB_VERSION", "v2")
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "false")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _review_markdown():
    return """---
type: agent_review
source_agent: claude
source_model: claude-sonnet
---

# Review: v2 collaboration runtime

## Findings

### Finding 1

Title: v2 collaboration writes need split evidence
Severity: high
Area: API
Evidence quality: operator_verified
Source path: apps/api/knownet_api/routes/collaboration.py
Source lines: 42-45

Evidence:
The runtime should persist evidence separately from decisions.

Proposed change:
Write findings into findings and finding_evidence, then insert decision history.

### Finding 2

Title: v2 low priority docs cleanup
Severity: low
Area: Docs

Evidence:
The docs mention an outdated runtime table.

Proposed change:
Update the phase note after the route is moved.
"""


def _create_agent_token(client: TestClient, scopes: list[str]):
    response = client.post(
        "/api/agents/tokens",
        json={
            "label": "Phase 31 v2 agent",
            "agent_name": "codex",
            "agent_model": "test",
            "purpose": "phase31-v2-dashboard",
            "role": "agent_reader",
            "scopes": scopes,
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


def test_v2_review_decision_task_and_implementation_use_clean_tables(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        data = imported.json()["data"]
        review_id = data["review"]["id"]
        target_finding = next(finding for finding in data["findings"] if finding["title"] == "v2 collaboration writes need split evidence")
        finding_id = target_finding["id"]
        assert data["graph_rebuild"]["status"] == "skipped"
        assert target_finding["evidence_quality"] == "operator_verified"
        assert target_finding["source_path"] == "apps/api/knownet_api/routes/collaboration.py"
        assert (app.state.settings.data_dir / "pages" / "reviews" / f"{review_id}.md").exists()

        reviews = client.get("/api/collaboration/reviews")
        assert reviews.status_code == 200, reviews.text
        assert reviews.json()["data"]["reviews"][0]["finding_count"] == 2

        accepted = client.post(
            f"/api/collaboration/findings/{finding_id}/decision",
            json={"status": "accepted", "decision_note": "Accepted into v2 task queue"},
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["status"] == "accepted"

        created_task = client.post(
            f"/api/collaboration/findings/{finding_id}/task",
            json={"priority": "high", "owner": "codex", "notes": "Created from v2 route test"},
        )
        assert created_task.status_code == 200, created_task.text
        assert created_task.json()["data"]["task"]["finding_id"] == finding_id

        tasks = client.get("/api/collaboration/tasks?status=open")
        assert tasks.status_code == 200, tasks.text
        assert tasks.json()["data"]["tasks"][0]["finding_id"] == finding_id

        implemented = client.post(
            f"/api/collaboration/findings/{finding_id}/implementation",
            json={"commit_sha": "abcdef1", "changed_files": ["apps/api/knownet_api/routes/collaboration.py"], "verification": "targeted v2 tests passed"},
        )
        assert implemented.status_code == 200, implemented.text
        assert implemented.json()["data"]["task_id"] == created_task.json()["data"]["task"]["id"]

        detail = client.get(f"/api/collaboration/reviews/{review_id}")
        assert detail.status_code == 200, detail.text
        detail_data = detail.json()["data"]
        assert detail_data["review"]["id"] == review_id
        assert {finding["status"] for finding in detail_data["findings"]} == {"implemented", "pending"}

        db_path = app.state.settings.sqlite_path

    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "collaboration_reviews" not in tables
        assert "collaboration_findings" not in tables
        assert "finding_tasks" not in tables
        assert connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM finding_evidence").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM finding_locations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        statuses = [row[0] for row in connection.execute("SELECT status FROM finding_decisions ORDER BY created_at")]
        assert statuses == ["accepted", "implemented"]
        changed_files = connection.execute("SELECT changed_files FROM implementation_records WHERE finding_id = ?", (finding_id,)).fetchone()[0]
        assert json.loads(changed_files) == ["apps/api/knownet_api/routes/collaboration.py"]

    get_settings.cache_clear()


def test_v2_sarif_export_uses_finding_evidence_and_locations(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        direct_finding = next(finding for finding in imported.json()["data"]["findings"] if finding["evidence_quality"] == "operator_verified")
        context_finding = next(finding for finding in imported.json()["data"]["findings"] if finding["evidence_quality"] == "unspecified")

        accepted = client.post(
            f"/api/collaboration/findings/{direct_finding['id']}/decision",
            json={"status": "accepted", "decision_note": "Trusted code scanning item"},
        )
        assert accepted.status_code == 200, accepted.text
        context_accepted = client.post(
            f"/api/collaboration/findings/{context_finding['id']}/decision",
            json={"status": "accepted", "decision_note": "Not trusted by default"},
        )
        assert context_accepted.status_code == 200, context_accepted.text

        sarif = client.get("/api/collaboration/findings.sarif")
        assert sarif.status_code == 200, sarif.text
        results = sarif.json()["runs"][0]["results"]
        assert len(results) == 1
        result = results[0]
        assert result["partialFingerprints"]["knownetFindingId"] == direct_finding["id"]
        location = result["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "apps/api/knownet_api/routes/collaboration.py"
        assert location["region"]["startLine"] == 42
        assert location["region"]["endLine"] == 45
        knownet = result["properties"]["knownet"]
        assert knownet["evidence_quality"] == "operator_verified"
        assert knownet["code_scanning_ready"] is True

        explicit = client.get("/api/collaboration/findings.sarif?evidence_quality=unspecified&status=accepted")
        assert explicit.status_code == 200, explicit.text
        explicit_results = explicit.json()["runs"][0]["results"]
        assert len(explicit_results) == 1
        assert explicit_results[0]["partialFingerprints"]["knownetFindingId"] == context_finding["id"]
        assert explicit_results[0]["properties"]["knownet"]["evidence_quality"] == "unspecified"

    get_settings.cache_clear()


def test_v2_project_snapshot_packet_uses_snapshots_packets_and_sources(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Packet candidate"})
        assert accepted.status_code == 200, accepted.text
        db_path = app.state.settings.sqlite_path
        now = "2026-05-08T00:00:00Z"
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "INSERT INTO pages (id, vault_id, title, slug, path, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("page_packet_context", "local-default", "Packet Context", "packet-context", "pages/packet-context.md", "active", now, now),
            )

        packet = client.post(
            "/api/collaboration/project-snapshot-packets",
            json={
                "vault_id": "local-default",
                "target_agent": "external_ai",
                "profile": "overview",
                "output_mode": "top_findings",
                "focus": "Review v2 packet runtime.",
            },
        )
        assert packet.status_code == 200, packet.text
        data = packet.json()["data"]
        packet_id = data["id"]
        assert data["content"]
        assert data["content_hash"]
        assert data["profile"] == "overview"
        assert data["node_cards"][0]["id"] == "page_packet_context"
        assert (app.state.settings.data_dir / "project-snapshot-packets" / f"{packet_id}.md").exists()

        fetched = client.get(f"/api/collaboration/project-snapshot-packets/{packet_id}")
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["data"]["content_hash"] == data["content_hash"]

    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "project_snapshot_packets" not in tables
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM packet_sources").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM node_cards").fetchone()[0] == 1

    get_settings.cache_clear()


def test_v2_model_run_runtime_uses_provider_tables(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post(
            "/api/model-runs/gemini/reviews",
            json={"vault_id": "local-default", "prompt_profile": "phase31_provider_v2", "mock": True, "max_pages": 1, "max_findings": 3},
        )
        assert created.status_code == 200, created.text
        run = created.json()["data"]["run"]
        run_id = run["id"]
        assert run["status"] == "dry_run_ready"
        assert run["trace_id"]

        listed = client.get("/api/model-runs?provider=gemini")
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"]["runs"][0]["id"] == run_id

        detail = client.get(f"/api/model-runs/{run_id}")
        assert detail.status_code == 200, detail.text
        detail_run = detail.json()["data"]["run"]
        assert detail_run["request"]["provider"] == "gemini"
        assert detail_run["response"]["dry_run"]["finding_count"] >= 1
        assert detail_run["output_tokens"] is not None

        observations = client.get("/api/model-runs/observations?provider=gemini")
        assert observations.status_code == 200, observations.text
        assert observations.json()["data"]["observations"][0]["run_id"] == run_id

        matrix = client.get("/api/operator/provider-matrix")
        assert matrix.status_code == 200, matrix.text
        gemini = next(item for item in matrix.json()["data"]["providers"] if item["provider_id"] == "gemini")
        assert gemini["run_counts"]["mock_successful"] == 1

        db_path = app.state.settings.sqlite_path

    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "model_review_runs" not in tables
        assert connection.execute("SELECT COUNT(*) FROM provider_runs WHERE id = ?", (run_id,)).fetchone()[0] == 1
        assert connection.execute("SELECT output_tokens FROM provider_run_metrics WHERE run_id = ?", (run_id,)).fetchone()[0] is not None
        artifact_types = {row[0] for row in connection.execute("SELECT artifact_type FROM provider_run_artifacts WHERE run_id = ?", (run_id,))}
        assert artifact_types == {"request", "response"}

    get_settings.cache_clear()


def test_v2_operator_and_agent_summaries_use_clean_tables(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        quality = client.get("/api/operator/ai-state-quality")
        assert quality.status_code == 200, quality.text
        quality_data = quality.json()["data"]
        assert quality_data["empty_state"]["active"] is True
        assert quality_data["summary"]["reviews"] == 0

        token = _create_agent_token(client, ["pages:read", "reviews:read", "findings:read"])
        headers = {"authorization": f"Bearer {token['raw_token']}"}
        summary = client.get("/api/agent/state-summary", headers=headers)
        assert summary.status_code == 200, summary.text
        summary_data = summary.json()["data"]
        assert summary_data["summary"]["reviews"] == 0
        assert summary_data["empty_state"]["active"] is True

        ai_state = client.get("/api/agent/ai-state", headers=headers)
        assert ai_state.status_code == 200, ai_state.text
        assert ai_state.json()["data"]["structured_state_pages"] == []
        assert ai_state.json()["meta"]["empty_state"]["active"] is True

        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Dashboard next action"})
        assert accepted.status_code == 200, accepted.text

        reviews = client.get("/api/agent/reviews", headers=headers)
        assert reviews.status_code == 200, reviews.text
        assert reviews.json()["data"]["reviews"][0]["id"] == imported.json()["data"]["review"]["id"]

        findings = client.get("/api/agent/findings", headers=headers)
        assert findings.status_code == 200, findings.text
        assert findings.json()["data"]["findings"][0]["id"] == finding_id

        next_action = client.get("/api/collaboration/next-action")
        assert next_action.status_code == 200, next_action.text
        next_data = next_action.json()["data"]
        assert next_data["action_type"] in {"create_task_from_accepted_finding", "implement_task"}
        assert next_data["finding_id"] == finding_id

    get_settings.cache_clear()


def test_v2_health_and_verify_index_report_schema_state(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        health = client.get("/health/summary")
        assert health.status_code == 200, health.text
        health_data = health.json()["data"]
        assert health_data["db_version"] == "v2"
        assert health_data["schema"]["db_version"] == "v2"
        assert health_data["schema"]["integrity_check"] == "ok"

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200, verify.text
        verify_data = verify.json()["data"]
        assert verify_data["db_version"] == "v2"
        assert verify_data["schema"]["integrity_check"] == "ok"
        assert verify_data["ok"] is True

        db_path = app.state.settings.sqlite_path

    with sqlite3.connect(db_path) as connection:
        old_tables = {"collaboration_reviews", "collaboration_findings", "finding_tasks", "project_snapshot_packets", "model_review_runs", "experiment_packets", "context_bundle_manifests"}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert not (tables & old_tables)

    get_settings.cache_clear()


def test_v2_audit_endpoint_reads_audit_events(tmp_path, monkeypatch):
    _isolate_v2(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text

        audit = client.get("/api/audit?action=review.import")
        assert audit.status_code == 200, audit.text
        events = audit.json()["data"]["events"]
        assert events
        assert events[0]["action"] == "review.import"
        assert "meta" in events[0]

        db_path = app.state.settings.sqlite_path

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] >= 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'audit_log'").fetchone() is None

    get_settings.cache_clear()
