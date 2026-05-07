import json
import re
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.routes.collaboration import parse_review_markdown
from knownet_api.services.packet_contract import build_packet_contract, contract_shape, explicit_stale_context_suppression, validate_packet_header, validate_packet_schema_core
from knownet_api.services.ai_review_comparator import compare_ai_reviews
from knownet_api.services.project_snapshot import EMPTY_STATE_REASONS, packet_diff_view, snapshot_self_test
from fixture_utils import load_json_fixture_dir


REPO_ROOT = Path(__file__).resolve().parents[3]


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "false")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def _review_markdown():
    return """---
type: agent_review
source_agent: claude
source_model: claude-3.7
---

# Review: Collaboration MVP

## Findings

### Finding 1: Review import needs durable storage

Title: Durable review storage is required
Severity: high
Area: collaboration-api

Evidence:
The review text should be stored as Markdown.

Proposed change:
Persist the review and parsed findings.

### Finding 2: Bundle export should reject secrets

Severity: medium
Area: security

Evidence:
External agents should not see credentials.

Proposed change:
Scan generated bundles before writing them.
"""


def test_phase20_packet_contract_self_test_validates_boundaries_budget_and_stale_state():
    contract = build_packet_contract(
        packet_kind="project_snapshot",
        target_agent="claude",
        operator_question="Review packet.",
        stale_context_suppression=explicit_stale_context_suppression(suppressed_before="2026-05-05T00:00:00Z"),
    )
    content = "# KnowNet Project Snapshot Packet\n\n## Packet Contract\n\n- contract_version: p26.v1\n- profile: overview\n\n## Important Changes\n\n## Do Not Suggest\n"
    result = snapshot_self_test(content=content, contract=contract, profile="overview", required_sections=["## Packet Contract", "## Important Changes"])
    assert result["overall_status"] == "pass", result

    malformed = dict(contract)
    malformed["stale_context_suppression"] = {}
    malformed["role_and_access_boundaries"] = {"allowed": [], "refused": [], "escalate_on": [], "narrative": []}
    failed = snapshot_self_test(content=content, contract=malformed, profile="overview", required_sections=["## Packet Contract"])
    failed_codes = {check["code"] for check in failed["checks"] if check["status"] == "fail"}
    assert "structured_role_boundaries_present" in failed_codes
    assert "stale_context_suppression_explicit" in failed_codes


def test_packet_schema_documents_standard_header_and_trace_fields():
    schema = json.loads((REPO_ROOT / "docs" / "schemas" / "packet.p26.v1.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"] == "/api/schemas/packet/p26.v1"
    assert "protocol_version" in schema["required"]
    assert "schema_ref" in schema["required"]
    assert "contract" not in schema["properties"]
    assert "contract_shape" not in schema["properties"]
    trace_schema = schema["$defs"]["trace"]
    assert "traceparent" in trace_schema["required"]
    assert trace_schema["properties"]["trace_id"]["pattern"] == "^[0-9a-f]{32}$"
    assert "CLIENT" in trace_schema["properties"]["span_kind"]["enum"]


def test_packet_schema_endpoint_exposes_p26_contract(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/schemas/packet/p26.v1")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["$id"] == "/api/schemas/packet/p26.v1"


def test_packet_schema_core_validator_uses_schema_required_fields():
    schema = json.loads((REPO_ROOT / "docs" / "schemas" / "packet.p26.v1.schema.json").read_text(encoding="utf-8"))
    contract = build_packet_contract(packet_kind="project_snapshot", target_agent="claude", operator_question="Review packet.")
    packet = {
        "id": "packet_test",
        "type": "project_snapshot_packet",
        "contract_version": "p26.v1",
        "protocol_version": "2026-05-05",
        "schema_ref": "/api/schemas/packet/p26.v1",
        "contract_ref": "/api/schemas/packet/p26.v1",
        "generated_at": "2026-05-05T00:00:00Z",
        "links": {"self": {"href": "/api/test"}},
        "trace": {
            "trace_id": "0" * 32,
            "span_id": "1" * 16,
            "traceparent": f"00-{'0' * 32}-{'1' * 16}-01",
            "name": "knownet.test_packet",
            "span_kind": "INTERNAL",
            "attributes": {"service.name": "knownet"},
        },
        "ai_context": {"role": "test", "target_agent": "claude", "task": "validate", "read_order": ["contract"]},
    }
    assert validate_packet_schema_core(packet, schema) == []
    broken = dict(packet)
    broken.pop("schema_ref")
    assert "schema_required_missing:schema_ref" in validate_packet_schema_core(broken, schema)


def test_import_triage_implementation_and_bundle(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        data = imported.json()["data"]
        review_id = data["review"]["id"]
        finding_id = data["findings"][0]["id"]
        assert len(data["findings"]) == 2
        assert data["findings"][0]["evidence_quality"] == "unspecified"
        assert (app.state.settings.data_dir / "pages" / "reviews" / f"{review_id}.md").exists()

        reviews = client.get("/api/collaboration/reviews")
        assert reviews.status_code == 200
        assert reviews.json()["data"]["reviews"][0]["finding_count"] == 2

        decided = client.post(
            f"/api/collaboration/findings/{finding_id}/decision",
            json={"status": "accepted", "decision_note": "Valid MVP concern"},
        )
        assert decided.status_code == 200, decided.text
        second_finding_id = data["findings"][1]["id"]
        deferred = client.post(
            f"/api/collaboration/findings/{second_finding_id}/decision",
            json={"status": "deferred", "decision_note": "Useful but later"},
        )
        assert deferred.status_code == 200, deferred.text
        detail = client.get(f"/api/collaboration/reviews/{review_id}")
        assert detail.json()["data"]["review"]["status"] == "triaged"

        implemented = client.post(
            f"/api/collaboration/findings/{finding_id}/implementation",
            json={"commit_sha": "abcdef1", "changed_files": ["apps/api/x.py"], "verification": "pytest passed"},
        )
        assert implemented.status_code == 200, implemented.text
        graph = client.get("/api/graph?node_type=review,finding,commit&limit=100")
        assert graph.status_code == 200, graph.text
        node_types = {node["node_type"] for node in graph.json()["data"]["nodes"]}
        assert {"review", "finding", "commit"}.issubset(node_types)

        page = client.post("/api/pages", json={"slug": "collaboration-context", "title": "Collaboration Context"})
        assert page.status_code == 200, page.text
        page_id = "page_collaboration_context"
        bundle = client.post(
            "/api/collaboration/context-bundles",
            json={"vault_id": "local-default", "page_ids": [page_id], "include_graph_summary": True},
        )
        assert bundle.status_code == 200, bundle.text
        assert "KnowNet Context Bundle" in bundle.json()["data"]["content"]
        assert (app.state.settings.data_dir / "context-bundles" / bundle.json()["data"]["manifest"]["filename"]).exists()

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        review_count = connection.execute("SELECT COUNT(*) FROM collaboration_reviews").fetchone()[0]
        finding_status = connection.execute("SELECT status FROM collaboration_findings WHERE id = ?", (finding_id,)).fetchone()[0]
        finding_quality = connection.execute("SELECT evidence_quality FROM collaboration_findings WHERE id = ?", (finding_id,)).fetchone()[0]
        manifest_count = connection.execute("SELECT COUNT(*) FROM context_bundle_manifests").fetchone()[0]
        audit_count = connection.execute("SELECT COUNT(*) FROM audit_events WHERE action = 'review.import'").fetchone()[0]
    assert review_count == 1
    assert finding_status == "implemented"
    assert finding_quality == "unspecified"
    assert manifest_count == 1
    assert audit_count == 1
    get_settings.cache_clear()


def test_accepted_findings_become_actionable_tasks(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]

        blocked = client.post(f"/api/collaboration/findings/{finding_id}/task", json={"priority": "high"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "finding_task_requires_accepted"

        decided = client.post(
            f"/api/collaboration/findings/{finding_id}/decision",
            json={"status": "accepted", "decision_note": "Turn into task"},
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["data"]["auto_task"] is None

        queue = client.get("/api/collaboration/finding-queue")
        assert queue.status_code == 200, queue.text
        queue_items = queue.json()["data"]["queue"]
        assert len(queue_items) == 1
        assert queue_items[0]["id"] == finding_id
        assert queue_items[0]["has_task"] is False
        assert "Implement accepted KnowNet finding" in queue_items[0]["task_prompt"]
        assert queue_items[0]["expected_verification"]

        created = client.post(
            f"/api/collaboration/findings/{finding_id}/task",
            json={"priority": "high", "owner": "codex", "notes": "Created from Review Inbox"},
        )
        assert created.status_code == 200, created.text
        task = created.json()["data"]["task"]
        assert task["finding_id"] == finding_id
        assert task["priority"] == "high"
        assert task["owner"] == "codex"

        tasks = client.get("/api/collaboration/finding-tasks?status=open")
        assert tasks.status_code == 200, tasks.text
        task_rows = tasks.json()["data"]["tasks"]
        assert len(task_rows) == 1
        assert task_rows[0]["id"] == task["id"]
        assert task_rows[0]["title"] == "Durable review storage is required"

        updated = client.post(
            f"/api/collaboration/findings/{finding_id}/task",
            json={"priority": "urgent", "task_prompt": "Do this exact task.", "expected_verification": "Run focused tests."},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["data"]["task"]["id"] == task["id"]
        assert updated.json()["data"]["task"]["priority"] == "urgent"

        queue_after = client.get("/api/collaboration/finding-queue")
        assert queue_after.status_code == 200, queue_after.text
        assert queue_after.json()["data"]["queue"][0]["has_task"] is True
        assert queue_after.json()["data"]["queue"][0]["task_prompt"] == "Do this exact task."

        next_action = client.get("/api/collaboration/next-action")
        assert next_action.status_code == 200, next_action.text
        action = next_action.json()["data"]
        assert action["action_type"] == "implement_finding_task"
        assert action["finding_id"] == finding_id
        assert action["task_id"] == task["id"]
        assert action["after_implementation"]["endpoint"] == f"/api/collaboration/findings/{finding_id}/implementation-evidence"
        assert action["task_template"]["endpoint"] == f"/api/collaboration/findings/{finding_id}/implementation-evidence"
        assert action["simple_evidence_template"]["endpoint"] == f"/api/collaboration/findings/{finding_id}/evidence"
    get_settings.cache_clear()


def test_next_action_falls_back_to_accepted_finding_then_snapshot(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        empty = client.get("/api/collaboration/next-action")
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"]["action_type"] == "generate_project_snapshot"

        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][1]["id"]
        pending = client.get("/api/collaboration/next-action")
        assert pending.status_code == 200, pending.text
        assert pending.json()["data"]["action_type"] == "triage_review_findings"

        decided = client.post(
            f"/api/collaboration/findings/{finding_id}/decision",
            json={"status": "accepted", "decision_note": "Accepted but no task yet"},
        )
        assert decided.status_code == 200, decided.text
        accepted = client.get("/api/collaboration/next-action")
        assert accepted.status_code == 200, accepted.text
        action = accepted.json()["data"]
        assert action["action_type"] == "create_task_from_accepted_finding"
        assert action["finding_id"] == finding_id
        assert action["next_endpoint"] == f"/api/collaboration/findings/{finding_id}/task"
        assert action["task_template"]["body"]["priority"] == "normal"
    get_settings.cache_clear()


def test_next_action_recommends_gemini_fast_lane_when_configured(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.get("/api/collaboration/next-action")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["action_type"] == "run_ai_review_now"
        assert data["next_endpoint"] == "/api/model-runs/review-now"
        assert data["payload"]["provider"] == "gemini"
        assert data["payload"]["allow_mock_fallback"] is False
    get_settings.cache_clear()


def test_next_action_prefers_backlog_work_before_gemini(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        decided = client.post(
            f"/api/collaboration/findings/{finding_id}/decision",
            json={"status": "accepted", "decision_note": "Accepted but no task yet"},
        )
        assert decided.status_code == 200, decided.text

        response = client.get("/api/collaboration/next-action")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["action_type"] == "create_task_from_accepted_finding"
        assert data["finding_id"] == finding_id
        assert data["task_template"]["method"] == "POST"
    get_settings.cache_clear()


def test_finding_duplicates_and_dry_run_duplicate_candidates(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        first = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert first.status_code == 200, first.text
        second = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert second.status_code == 200, second.text

        duplicates = client.get("/api/collaboration/finding-duplicates")
        assert duplicates.status_code == 200, duplicates.text
        data = duplicates.json()["data"]
        assert data["duplicate_group_count"] >= 2
        titles = {group["title"] for group in data["duplicate_groups"]}
        assert "Durable review storage is required" in titles

        dry_run = client.post("/api/collaboration/reviews?dry_run=true", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["data"]["duplicate_candidates"]
    get_settings.cache_clear()


def test_project_snapshot_packet_summarizes_safe_handoff_state(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Snapshot task"})
        assert accepted.status_code == 200, accepted.text
        task = client.post(f"/api/collaboration/findings/{finding_id}/task", json={"priority": "high", "owner": "codex"})
        assert task.status_code == 200, task.text

        response = client.post(
            "/api/collaboration/project-snapshot-packets",
            json={"focus": "Tell Codex the next implementation move.", "target_agent": "codex"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        content = data["content"]
        assert data["copy_ready"] is True
        assert data["type"] == "project_snapshot_packet"
        assert data["generated_at"]
        assert data["links"]["self"]["href"] == data["links"]["content"]["href"]
        assert data["links"]["storage"]["href"].startswith("project-snapshot-packets/")
        assert "packet_id" not in data
        assert "read_url" not in data
        assert "storage_path" not in data
        content_json = json.loads(content)
        assert content_json["type"] == "project_snapshot_packet"
        assert "links" not in content_json
        assert content_json["packet_url"].startswith("/api/collaboration/project-snapshot-packets/")
        assert "narrative" not in content_json["role_boundaries"]
        assert "preflight" not in content_json
        assert "ai_state_quality" not in content_json
        assert content_json["packet_fitness"]["advisory_only"] is True
        assert "Tell Codex the next implementation move." in content
        assert content_json["packet_summary"]["accepted_findings"]
        assert finding_id in content
        assert "C:\\" not in content
        assert str(app.state.settings.data_dir) not in content
        assert (app.state.settings.data_dir / data["links"]["storage"]["href"]).exists()

        read = client.get(data["links"]["self"]["href"])
        assert read.status_code == 200, read.text
        assert read.json()["data"]["content_hash"] == data["content_hash"]
    get_settings.cache_clear()


def test_project_snapshot_packet_can_include_since_delta(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Delta task"})
        assert accepted.status_code == 200, accepted.text
        task = client.post(f"/api/collaboration/findings/{finding_id}/task", json={"priority": "high", "owner": "codex"})
        assert task.status_code == 200, task.text

        response = client.post(
            "/api/collaboration/project-snapshot-packets",
            json={"focus": "Only summarize recent changes.", "target_agent": "deepseek", "since": "2026-01-01T00:00:00Z"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["delta"]["since"] == "2026-01-01T00:00:00Z"
        assert {"summary", "added", "changed"} <= set(data["delta"])
        assert data["delta"]["changed"]["findings"]
        assert data["delta"]["changed"]["finding_tasks"]
        assert data["delta"]["summary"]["new_or_updated_findings"] >= 1
        assert data["delta"]["summary"]["changed_tasks"] >= 1
        assert "delta_summary" not in data
        assert "delta_standard" not in data
        content_json = json.loads(data["content"])
        assert content_json["delta"]["summary"]
        assert "delta_summary" not in data["content"]

        bad = client.post("/api/collaboration/project-snapshot-packets", json={"since": "not-a-date"})
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "project_snapshot_invalid_since"
    get_settings.cache_clear()


def test_project_snapshot_profiles_contract_quality_and_since_packet(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post(
            "/api/collaboration/reviews",
            json={
                "markdown": """---
evidence_quality: direct_access
---
# Review

### Finding

Title: Provider run failed repeatedly
Severity: high
Area: Ops

Evidence:
Provider matrix reported repeated failures.

Proposed change:
Add provider retry and alerting.
""",
                "vault_id": "local-default",
            },
        )
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "High confidence"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["auto_task"]["finding_id"] == finding_id
        page = client.post("/api/pages", json={"slug": "snapshot-card-node", "title": "Snapshot Card Node"})
        assert page.status_code == 200, page.text

        overview = client.post("/api/collaboration/project-snapshot-packets", json={"target_agent": "claude"})
        assert overview.status_code == 200, overview.text
        overview_data = overview.json()["data"]
        assert overview_data["profile"] == "overview"
        assert overview_data["effective_focus"].startswith("Summarize the current KnowNet state")
        assert overview_data["contract_version"] == "p26.v1"
        assert overview_data["type"] == "project_snapshot_packet"
        assert overview_data["generated_at"]
        assert overview_data["links"]["self"]["href"].startswith("/api/collaboration/project-snapshot-packets/")
        assert "packet_id" not in overview_data
        assert "packet_schema_version" not in overview_data
        assert overview_data["protocol_version"] == "2026-05-05"
        assert overview_data["schema_ref"] == "/api/schemas/packet/p26.v1"
        assert overview_data["contract_ref"] == "/api/schemas/packet/p26.v1"
        assert overview_data["contract_hash"].startswith("sha256:")
        assert overview_data["trace"]["name"] == "knownet.project_snapshot_packet"
        assert re.fullmatch(r"[0-9a-f]{32}", overview_data["trace"]["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", overview_data["trace"]["span_id"])
        assert overview_data["trace"]["traceparent"] == f"00-{overview_data['trace']['trace_id']}-{overview_data['trace']['span_id']}-01"
        assert overview_data["trace"]["span_kind"] == "INTERNAL"
        assert overview_data["trace"]["attributes"]["knownet.packet.source_id"] == overview_data["id"]
        assert overview_data["trace"]["attributes"]["knownet.packet.profile"] == "overview"
        assert validate_packet_header(overview_data) == []
        assert overview_data["ai_context"]["role"] == "overview_reviewer"
        assert overview_data["issues"]
        assert overview_data["issues"][0]["action_template"]
        assert overview_data["issues"][0]["action_input_schema"]["type"] == "object"
        assert overview_data["issues"][0]["action_input_schema"]["additionalProperties"] is False
        assert overview_data["signals"]
        assert overview_data["signals"][0]["severity"] in {"high", "medium", "low", "expected_degraded"}
        assert overview_data["limits"]["max_findings"] == 3
        assert overview_data["limits"]["max_signals"] == 5
        assert overview_data["packet_summary"]["accepted_findings"][0]["detail_url"] == f"/api/collaboration/findings/{finding_id}"
        assert overview_data["packet_summary"]["finding_tasks"][0]["detail_url"].startswith("/api/collaboration/finding-tasks/")
        assert overview_data["node_cards"]
        assert overview_data["node_cards"][0]["detail_url"].startswith("/api/pages/")
        boundaries = overview_data["role_boundaries"]
        assert boundaries["allowed"]
        assert "raw_db" in boundaries["refused"]
        assert "system_state_assertion" in boundaries["escalate_on"]
        assert len(boundaries["narrative"]) <= 3
        assert overview_data["snapshot_quality"]["advisory_only"] is True
        assert overview_data["snapshot_quality"]["details"]["profile_char_budget"] == 12000
        assert "details" in overview_data["snapshot_quality"]
        assert overview_data["important_changes"]["summary"]["high_severity_findings"] >= 1
        assert overview_data["important_changes"]["high_severity_findings"][0]["action_route"] == "implement"
        assert overview_data["snapshot_diff_summary"]
        assert overview_data["packet_integrity"]["status"] == "pass"
        assert overview_data["packet_integrity"]["content_chars"] == len(overview_data["content"])
        assert overview_data["packet_integrity"]["content_chars"] <= 12000
        assert overview_data["packet_integrity"]["char_budget"] == 12000
        assert overview_data["packet_integrity"]["optimization_target_chars"] == 8000
        assert "snapshot_self_test" not in overview_data
        assert "contract_shape" not in overview_data
        assert "contract" not in overview_data
        assert "profile_hard_limits" not in overview_data
        assert any("release_check" in rule for rule in overview_data["do_not_suggest"])
        content_json = json.loads(overview_data["content"])
        assert content_json["contract_ref"] == "/api/schemas/packet/p26.v1"
        assert len(overview_data["content"]) <= 12000
        assert "links" not in content_json
        assert content_json["packet_url"].startswith("/api/collaboration/project-snapshot-packets/")
        assert "snapshot_self_test" not in content_json
        assert "snapshot_quality" not in content_json
        assert "contract_shape" not in content_json
        assert "contract" not in content_json
        assert "preflight" not in content_json
        assert "ai_state_quality" not in content_json
        assert "narrative" not in content_json["role_boundaries"]
        assert "signals" in content_json
        assert "signals.required_context" in content_json["ai_context"]["read_order"]
        assert content_json["packet_fitness"]["advisory_only"] is True
        assert "formula" in content_json["packet_fitness"]

        finding_detail = client.get(f"/api/collaboration/findings/{finding_id}")
        assert finding_detail.status_code == 200, finding_detail.text
        assert finding_detail.json()["data"]["finding"]["id"] == finding_id

        stability = client.post(
            "/api/collaboration/project-snapshot-packets",
            json={
                "profile": "stability",
                "output_mode": "provider_risk_check",
                "focus": "Only stability risks.",
                "target_agent": "deepseek",
                "since_packet_id": overview_data["id"],
                "allow_since_packet_fallback": False,
            },
        )
        assert stability.status_code == 200, stability.text
        stability_data = stability.json()["data"]
        assert stability_data["profile"] == "stability"
        assert stability_data["effective_focus"].startswith("Only stability risks.")
        assert stability_data["limits"]["max_recent_tasks"] == 4
        assert stability_data["limits"]["max_recent_runs"] == 4
        assert "model_runs" not in stability_data["packet_summary"]
        assert json.loads(stability_data["content"])["profile"] == "stability"
        assert "profile_mismatch_delta" in stability_data["warnings"]
        assert stability_data["delta"]

        invalid = client.post("/api/collaboration/project-snapshot-packets", json={"profile": "unknown"})
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "project_snapshot_invalid_profile"

        missing = client.post("/api/collaboration/project-snapshot-packets", json={"since_packet_id": "snapshot_missing"})
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "project_snapshot_since_packet_not_found"
    get_settings.cache_clear()


def test_phase26_empty_state_context_questions_and_diff_helpers(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/collaboration/project-snapshot-packets",
            json={"target_agent": "claude", "output_mode": "context_questions"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        content_json = json.loads(data["content"])
        assert data["output_mode"] == "context_questions"
        assert content_json["context_questions"]
        assert content_json["context_questions"][0]["question"]
        assert content_json["signals"][0]["required_context"]
        assert content_json["signals"][0]["evidence_upgrade_path"]["from"] == "context_limited"
        assert content_json["empty_state"]["reason"] in EMPTY_STATE_REASONS
        assert content_json["empty_state"]["reason"] != "fresh_install_or_no_pages"

        compact = {
            "output_mode": "context_questions",
            "questions": [
                {
                    "question": "Is this a fresh install?",
                    "missing": ["fresh_install_confirmation"],
                    "reason": "No pages are present.",
                }
            ],
        }
        dry_run = client.post("/api/collaboration/reviews?dry_run=true", json={"markdown": json.dumps(compact)})
        assert dry_run.status_code == 200, dry_run.text
        dry_data = dry_run.json()["data"]
        assert dry_data["finding_count"] == 0
        assert dry_data["context_questions"][0]["missing"] == ["fresh_install_confirmation"]
        assert dry_data["import_ready"] is False

        diff = client.post(
            "/api/collaboration/project-snapshot-packets/compare",
            json={
                "left_packet": {"contract_version": "p26.v1", "signals": []},
                "right_packet": content_json,
            },
        )
        assert diff.status_code == 200, diff.text
        diff_data = diff.json()["data"]
        assert "actionability_delta" in diff_data
        assert diff_data["actionability_delta"] > 0
    get_settings.cache_clear()


def test_phase26_golden_packet_fixtures_are_actionable():
    fixtures = load_json_fixture_dir("project_packets")
    assert {fixture["name"] for fixture in fixtures} == {"empty-project-overview", "healthy-project-overview", "degraded-project-overview"}
    for fixture in fixtures:
        packet = fixture["packet"]
        expected = fixture["expected"]
        content = json.dumps(packet, ensure_ascii=False)
        assert expected["min_chars"] <= len(content) <= expected["max_chars"]
        assert packet["output_mode"] == expected["output_mode"]
        signal_codes = [signal["code"] for signal in packet.get("signals") or []]
        assert signal_codes == expected["signals"]
        has_required = any(signal.get("required_context") for signal in packet.get("signals") or [])
        assert has_required is expected["required_context"]
        if expected.get("empty_state_reason"):
            assert packet["empty_state"]["reason"] == expected["empty_state_reason"]


def test_phase26_ai_review_comparator_reports_consensus_and_conflict():
    comparison = compare_ai_reviews(
        [
            {"source_agent": "claude", "text": "## Top Changes\n- Remove ai_state_quality duplication\n\n## Do Not Change\n- Keep traceparent"},
            {"source_agent": "deepseek", "text": "## Top Changes\n- Remove ai_state_quality duplication\n\n## Do Not Change\n- Keep traceparent"},
            {"source_agent": "gemini", "text": "## Top Changes\n- Strip traceparent\n\n## Do Not Change\n- Do not remove traceparent"},
        ]
    )
    assert comparison["common_recommendations"]
    assert any("ai_state_quality" in item["text"] for item in comparison["common_recommendations"])
    assert comparison["do_not_change_consensus"]
    assert comparison["candidate_implementation_list"]


def test_context_limited_high_finding_does_not_auto_create_task(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post(
            "/api/collaboration/reviews",
            json={
                "markdown": """---
evidence_quality: context_limited
---
# Review

### Finding

Title: Context limited high finding needs operator translation
Severity: high
Area: API

Evidence:
The external AI only saw a context-limited packet.

Proposed change:
Ask the operator to verify before creating implementation work.
""",
                "vault_id": "local-default",
            },
        )
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Accepted for review"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["auto_task"] is None
        tasks = client.get("/api/collaboration/finding-tasks?status=all")
        assert tasks.status_code == 200, tasks.text
        assert tasks.json()["data"]["tasks"] == []
    get_settings.cache_clear()


def test_patch_suggestion_stub_exposes_safety_contract(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        response = client.get(f"/api/collaboration/patch-suggestion?finding_id={finding_id}")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "unsupported_until_implemented"
        assert data["safety_contract"]["requires_local_code_context"] is True
        assert data["safety_contract"]["external_ai_raw_code_access"] is False
    get_settings.cache_clear()


def test_experiment_packet_accepts_minimum_inline_context(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        first = client.post("/api/pages", json={"slug": "access-fallback-protocol", "title": "Access Fallback Protocol"})
        assert first.status_code == 200, first.text
        path = app.state.settings.data_dir / "pages" / "access-fallback-protocol.md"
        path.write_text(
            """---
title: Access Fallback Protocol
slug: access-fallback-protocol
---

# Access Fallback Protocol

fallback_order: Use inline context first.
""",
            encoding="utf-8",
        )
        response = client.post(
            "/api/collaboration/experiment-packets",
            json={
                "experiment_name": "Minimum inline context test",
                "task": "Check the supplied minimum context.",
                "node_slugs": ["access-fallback-protocol"],
                "minimum_inline_context": "Critical inline summary: do not guess from node names.",
            },
        )
        assert response.status_code == 200, response.text
        content = response.json()["data"]["content"]
        assert "contract_version: p26.v1" in content
        assert "output_mode: top_findings" in content
        assert "Role And Access Boundaries" in content
        assert "Node Cards" in content
        assert "Operator-Supplied Minimum Inline Context" in content
        assert "Critical inline summary: do not guess from node names." in content
        data = response.json()["data"]
        assert "packet_schema_version" not in data
        assert data["protocol_version"] == "2026-05-05"
        assert data["schema_ref"] == "/api/schemas/packet/p26.v1"
        assert data["trace"]["name"] == "knownet.experiment_packet"
        assert re.fullmatch(r"[0-9a-f]{32}", data["trace"]["trace_id"])
        assert data["trace"]["traceparent"] == f"00-{data['trace']['trace_id']}-{data['trace']['span_id']}-01"
        assert data["trace"]["span_kind"] == "INTERNAL"
        assert validate_packet_header(data) == []
        assert data["node_cards"][0]["slug"] == "access-fallback-protocol"
        assert data["node_cards"][0]["detail_url"] == "/api/pages/access-fallback-protocol"
    get_settings.cache_clear()


def test_phase20_packet_shape_and_dry_run_are_provider_agnostic(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        page = client.post("/api/pages", json={"slug": "access-fallback-protocol", "title": "Access Fallback Protocol"})
        assert page.status_code == 200, page.text
        (app.state.settings.data_dir / "pages" / "access-fallback-protocol.md").write_text(
            "# Access Fallback Protocol\n\nUse inline context and return compact findings.\n",
            encoding="utf-8",
        )

        snapshot = client.post("/api/collaboration/project-snapshot-packets", json={"target_agent": "gemini", "profile": "provider_review"})
        assert snapshot.status_code == 200, snapshot.text
        snapshot_data = snapshot.json()["data"]
        assert snapshot_data["contract_ref"] == "/api/schemas/packet/p26.v1"

        packet = client.post(
            "/api/collaboration/experiment-packets",
            json={
                "experiment_name": "Provider agnostic parser",
                "task": "Return one compact finding.",
                "target_agent": "claude",
                "node_slugs": ["access-fallback-protocol"],
            },
        )
        assert packet.status_code == 200, packet.text
        packet_data = packet.json()["data"]
        assert packet_data["contract_shape"]["valid"] is True
        assert "role_and_access_boundaries" in packet_data["contract_shape"]["sections"]
        packet_id = packet_data["id"]

        responses = [
            ("claude", "claude-test", "Claude response passes same parser."),
            ("gemini", "gemini-test", "Gemini response passes same parser."),
        ]
        for source_agent, source_model, evidence in responses:
            dry_run = client.post(
                f"/api/collaboration/experiment-packets/{packet_id}/responses/dry-run",
                json={
                    "source_agent": source_agent,
                    "source_model": source_model,
                    "response_markdown": json.dumps(
                        {
                            "output_mode": "top_findings",
                            "findings": [
                                {
                                    "title": f"{source_agent} compact finding",
                                    "severity": "low",
                                    "area": "Docs",
                                    "evidence_quality": "context_limited",
                                    "evidence": evidence,
                                    "proposed_change": "Keep provider responses on the shared compact contract.",
                                }
                            ],
                        }
                    ),
                },
            )
            assert dry_run.status_code == 200, dry_run.text
            dry_data = dry_run.json()["data"]
            assert dry_data["import_ready"] is True
            assert dry_data["parser_errors"] == []
            assert dry_data["findings"][0]["evidence_quality"] == "context_limited"

        noisy = client.post(
            f"/api/collaboration/experiment-packets/{packet_id}/responses/dry-run",
            json={
                "source_agent": "claude",
                "response_markdown": json.dumps(
                    {
                        "output_mode": "top_findings",
                        "unsupported_sections": ["Long Summary"],
                        "findings": [
                            {
                                "title": "Noisy response",
                                "severity": "low",
                                "area": "Docs",
                                "evidence_quality": "context_limited",
                                "evidence": "Unsupported sections should reject import readiness.",
                                "proposed_change": "Return only compact findings.",
                            }
                        ],
                    }
                ),
            },
        )
        assert noisy.status_code == 200, noisy.text
        noisy_data = noisy.json()["data"]
        assert noisy_data["import_ready"] is False
        assert noisy_data["rejection_reason"] == "parser_errors"
        assert "unsupported_sections_present" in noisy_data["parser_errors"]
        assert noisy_data["ai_feedback_prompt"]

        blocked_import = client.post(f"/api/collaboration/experiment-packets/{packet_id}/responses/{noisy_data['response_id']}/import")
        assert blocked_import.status_code == 422
        assert blocked_import.json()["detail"]["code"] == "experiment_packet_response_parser_errors"
    get_settings.cache_clear()


def test_implementation_evidence_dry_run_and_record_updates_task(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Implement now"})
        assert accepted.status_code == 200, accepted.text
        task = client.post(f"/api/collaboration/findings/{finding_id}/task", json={"priority": "normal", "owner": "codex"})
        assert task.status_code == 200, task.text
        task_id = task.json()["data"]["task"]["id"]

        bad_path = client.post(
            f"/api/collaboration/findings/{finding_id}/implementation-evidence",
            json={"verification": "pytest", "changed_files": ["C:/knownet/data/knownet.db"]},
        )
        assert bad_path.status_code == 422
        assert bad_path.json()["detail"]["code"] == "implementation_file_forbidden_path"

        dry_run = client.post(
            f"/api/collaboration/findings/{finding_id}/implementation-evidence",
            json={"dry_run": True, "changed_files": ["apps/api/knownet_api/routes/collaboration.py"], "verification": "targeted pytest passed"},
        )
        assert dry_run.status_code == 200, dry_run.text
        draft = dry_run.json()["data"]["draft"]
        assert dry_run.json()["data"]["dry_run"] is True
        assert draft["task_id"] == task_id
        assert draft["would_mark_task_done"] is True

        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            assert connection.execute("SELECT status FROM collaboration_findings WHERE id = ?", (finding_id,)).fetchone()[0] == "accepted"
            assert connection.execute("SELECT status FROM finding_tasks WHERE id = ?", (task_id,)).fetchone()[0] == "open"

        recorded = client.post(
            f"/api/collaboration/findings/{finding_id}/implementation-evidence",
            json={"dry_run": False, "changed_files": ["apps/api/knownet_api/routes/collaboration.py"], "verification": "targeted pytest passed", "notes": "Evidence endpoint smoke"},
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["data"]["record"]["task_id"] == task_id
        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            assert connection.execute("SELECT status FROM collaboration_findings WHERE id = ?", (finding_id,)).fetchone()[0] == "implemented"
            assert connection.execute("SELECT status FROM finding_tasks WHERE id = ?", (task_id,)).fetchone()[0] == "done"
            assert connection.execute("SELECT COUNT(*) FROM implementation_records WHERE finding_id = ?", (finding_id,)).fetchone()[0] == 1
    get_settings.cache_clear()


def test_simple_evidence_endpoint_records_minimal_payload(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{finding_id}/decision", json={"status": "accepted", "decision_note": "Simple evidence"})
        assert accepted.status_code == 200, accepted.text

        dry_run = client.post(
            f"/api/collaboration/findings/{finding_id}/evidence",
            json={"dry_run": True, "implemented": True, "commit": "abcdef1", "note": "Targeted pytest passed."},
        )
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["data"]["dry_run"] is True
        assert dry_run.json()["data"]["draft"]["verification"] == "Targeted pytest passed."

        blocked = client.post(f"/api/collaboration/findings/{finding_id}/evidence", json={"implemented": False, "note": "Blocked"})
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "implementation_evidence_not_implemented"

        recorded = client.post(
            f"/api/collaboration/findings/{finding_id}/evidence",
            json={"implemented": True, "commit": "abcdef1", "note": "Targeted pytest passed."},
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["data"]["dry_run"] is False
        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            assert connection.execute("SELECT status FROM collaboration_findings WHERE id = ?", (finding_id,)).fetchone()[0] == "implemented"
            assert connection.execute("SELECT commit_sha FROM implementation_records WHERE finding_id = ?", (finding_id,)).fetchone()[0] == "abcdef1"
    get_settings.cache_clear()


def test_context_bundle_rejects_secret_like_page_content(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        page = client.post("/api/pages", json={"slug": "secret-context", "title": "Secret Context"})
        assert page.status_code == 200
        page_path = app.state.settings.data_dir / "pages" / "secret-context.md"
        page_path.write_text("# Secret Context\n\napi_key = 'sk-testsecret1234567890'\n", encoding="utf-8")
        response = client.post(
            "/api/collaboration/context-bundles",
            json={"vault_id": "local-default", "page_ids": ["page_secret_context"]},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "context_bundle_secret_detected"
    get_settings.cache_clear()


def test_context_bundle_secret_guard_boundary_cases(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        page = client.post("/api/pages", json={"slug": "safe-context", "title": "Safe Context"})
        assert page.status_code == 200
        page_path = app.state.settings.data_dir / "pages" / "safe-context.md"
        page_path.write_text(
            "# Safe Context\n\n# ADMIN_TOKEN=example\n\nADMIN_TOKEN_MIN_CHARS=32\n\nmy_password_field: display only\n",
            encoding="utf-8",
        )
        response = client.post(
            "/api/collaboration/context-bundles",
            json={"vault_id": "local-default", "page_ids": ["page_safe_context"]},
        )
        assert response.status_code == 200, response.text
    get_settings.cache_clear()


def test_context_bundle_rejects_configured_admin_token_value(tmp_path, monkeypatch):
    token = "x" * 40
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    monkeypatch.setenv("ADMIN_TOKEN_MIN_CHARS", "32")
    with TestClient(app) as client:
        page = client.post("/api/pages", headers={"x-knownet-admin-token": token}, json={"slug": "token-context", "title": "Token Context"})
        assert page.status_code == 200, page.text
        page_path = app.state.settings.data_dir / "pages" / "token-context.md"
        page_path.write_text(f"# Token Context\n\n{token}\n", encoding="utf-8")
        response = client.post(
            "/api/collaboration/context-bundles",
            headers={"x-knownet-admin-token": token},
            json={"vault_id": "local-default", "page_ids": ["page_token_context"]},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "context_bundle_secret_detected"
    get_settings.cache_clear()


def test_experiment_packet_generates_inline_context(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        first = client.post("/api/pages", json={"slug": "access-fallback-protocol", "title": "Access Fallback Protocol"})
        second = client.post("/api/pages", json={"slug": "evidence-quality-registry", "title": "Evidence Quality Registry"})
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        (app.state.settings.data_dir / "pages" / "access-fallback-protocol.md").write_text(
            """---
schema_version: 1
id: page_access_fallback_protocol
title: Access Fallback Protocol
slug: access-fallback-protocol
status: active
---
# Access Fallback Protocol

If direct KnowNet access fails, state the limitation and continue from supplied context.
""",
            encoding="utf-8",
        )
        (app.state.settings.data_dir / "pages" / "evidence-quality-registry.md").write_text(
            """---
schema_version: 1
id: page_evidence_quality_registry
title: Evidence Quality Registry
slug: evidence-quality-registry
status: active
---
# Evidence Quality Registry

context_limited findings may flag review work, but need operator verification before release blocking.
""",
            encoding="utf-8",
        )

        response = client.post(
            "/api/collaboration/experiment-packets",
            json={
                "experiment_name": "Boundary smoke",
                "task": "Decide scenarios only.",
                "target_agent": "claude",
                "node_slugs": ["access-fallback-protocol", "evidence-quality-registry"],
                "scenarios": ["Can a model infer whole-system health from ping?"],
                "output_schema": "Return Access Status and Scenario Decision Table.",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        content = data["content"]
        packet_id = data["id"]
        assert data["copy_ready"] is True
        assert data["type"] == "experiment_packet"
        assert data["generated_at"]
        assert data["links"]["self"]["href"] == f"/api/collaboration/experiment-packets/{packet_id}"
        assert "packet_id" not in data
        assert "read_url" not in data
        assert "content_path" not in data
        assert data["preflight"]["pages"] == 2
        assert (app.state.settings.data_dir / "experiment-packets" / f"{packet_id}.md").exists()
        assert "Boundary smoke" in content
        assert "Node: Access Fallback Protocol" in content
        assert "context_limited findings may flag review work" in content
        assert "Can a model infer whole-system health from ping?" in content
        assert "### Finding" in content

        read = client.get(f"/api/collaboration/experiment-packets/{packet_id}")
        assert read.status_code == 200, read.text
        assert read.json()["data"]["content_hash"] == data["content_hash"]

        dry_run = client.post(
            f"/api/collaboration/experiment-packets/{packet_id}/responses/dry-run",
            json={
                "source_agent": "claude",
                "source_model": "claude-test",
                "response_markdown": """# Response

**Finding 1**
Title: Packet response parses
Severity: low
Area: Docs
Evidence quality: context_limited

Evidence:
The response dry-run endpoint parsed this finding.

Proposed change:
Use the dry-run before importing.
""",
            },
        )
        assert dry_run.status_code == 200, dry_run.text
        dry_run_data = dry_run.json()["data"]
        assert dry_run_data["finding_count"] == 1
        assert dry_run_data["findings"][0]["evidence_quality"] == "context_limited"

        imported = client.post(f"/api/collaboration/experiment-packets/{packet_id}/responses/{dry_run_data['response_id']}/import")
        assert imported.status_code == 200, imported.text
        imported_data = imported.json()["data"]
        assert imported_data["review"]["id"]
        assert imported_data["findings"][0]["title"] == "Packet response parses"
        assert imported_data["findings"][0]["evidence_quality"] == "context_limited"

        duplicate = client.post(f"/api/collaboration/experiment-packets/{packet_id}/responses/{dry_run_data['response_id']}/import")
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "experiment_packet_response_already_imported"
    get_settings.cache_clear()


def test_experiment_packet_reports_missing_nodes(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/collaboration/experiment-packets",
            json={"experiment_name": "Missing node", "task": "Build packet.", "node_slugs": ["missing-node"]},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "experiment_packet_node_missing"
    get_settings.cache_clear()


def test_review_import_limits_body_size_and_decision_note(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        too_large = "x" * (256 * 1024 + 1)
        response = client.post("/api/collaboration/reviews", json={"markdown": too_large, "vault_id": "local-default"})
        assert response.status_code == 413

        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding_id = imported.json()["data"]["findings"][0]["id"]
        bad_note = client.post(
            f"/api/collaboration/findings/{finding_id}/decision",
            json={"status": "accepted", "decision_note": "x" * 2001},
        )
        assert bad_note.status_code == 422
    get_settings.cache_clear()


def test_collaboration_permissions_reuse_existing_auth(tmp_path, monkeypatch):
    token = "z" * 40
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("ADMIN_TOKEN", token)
    with TestClient(app) as client:
        anonymous = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert anonymous.status_code == 401

        owner = client.post(
            "/api/collaboration/reviews",
            headers={"x-knownet-admin-token": token},
            json={"markdown": _review_markdown(), "vault_id": "local-default"},
        )
        assert owner.status_code == 200, owner.text

        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            connection.execute("INSERT INTO users (id, username, password_hash, role, created_at) VALUES ('user_viewer', 'viewer', 'x', 'viewer', '2026-05-02T00:00:00Z')")
            connection.execute("INSERT INTO sessions (id, user_id, actor_type, session_meta, expires_at, created_at) VALUES ('session_viewer', 'user_viewer', 'user', '{}', '2999-01-01T00:00:00Z', '2026-05-02T00:00:00Z')")
            connection.execute("INSERT INTO vault_members (vault_id, user_id, role, created_at) VALUES ('local-default', 'user_viewer', 'viewer', '2026-05-02T00:00:00Z')")
            connection.commit()

        read = client.get("/api/collaboration/reviews", headers={"authorization": "Bearer session_viewer"})
        assert read.status_code == 200, read.text
        mutate = client.post(
            "/api/collaboration/reviews",
            headers={"authorization": "Bearer session_viewer"},
            json={"markdown": _review_markdown(), "vault_id": "local-default"},
        )
        assert mutate.status_code == 403
        bundle = client.post(
            "/api/collaboration/context-bundles",
            headers={"authorization": "Bearer session_viewer"},
            json={"vault_id": "local-default", "page_ids": ["page_missing"]},
        )
        assert bundle.status_code == 403
    get_settings.cache_clear()


def test_verify_index_reports_collaboration_drift(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO collaboration_reviews (id, vault_id, title, source_agent, review_type, status, page_id, meta, created_at, updated_at) "
                "VALUES ('review_missing_page', 'local-default', 'Missing Page', 'test', 'agent_review', 'pending_review', 'page_missing', '{}', '2026-05-02T00:00:00Z', '2026-05-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO collaboration_findings (id, review_id, severity, area, title, status, created_at, updated_at) "
                "VALUES ('finding_orphan', 'review_orphan', 'high', 'API', 'Orphan', 'pending', '2026-05-02T00:00:00Z', '2026-05-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO collaboration_findings (id, review_id, severity, area, title, evidence_quality, status, created_at, updated_at) "
                "VALUES ('finding_bad_quality', 'review_missing_page', 'low', 'Docs', 'Bad quality', 'direct-ish', 'pending', '2026-05-02T00:00:00Z', '2026-05-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO implementation_records (id, finding_id, changed_files, verification, created_at) "
                "VALUES ('impl_orphan', 'finding_missing', '[]', 'not run', '2026-05-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO finding_tasks (id, finding_id, task_prompt, expected_verification, created_at, updated_at) "
                "VALUES ('task_orphan', 'finding_missing', 'do work', 'run tests', '2026-05-02T00:00:00Z', '2026-05-02T00:00:00Z')"
            )
            connection.execute(
                "INSERT INTO context_bundle_manifests (id, vault_id, filename, path, selected_pages, included_sections, excluded_sections, content_hash, created_by, created_at) "
                "VALUES ('bundle_bad', 'local-default', 'bad.md', 'data/backups/bad.md', '[]', '[]', '[]', 'abc', 'test', '2026-05-02T00:00:00Z')"
            )
            connection.commit()

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200, verify.text
        codes = {issue["code"] for issue in verify.json()["data"]["issues"]}
        assert "collaboration_review_missing_page" in codes
        assert "collaboration_finding_orphan" in codes
        assert "collaboration_finding_invalid_evidence_quality" in codes
        assert "implementation_record_orphan" in codes
        assert "finding_task_orphan" in codes
        assert "context_bundle_forbidden_reference" in codes
    get_settings.cache_clear()


def test_active_docs_and_app_code_use_current_terms():
    scan_roots = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "phases" / "PHASE_7_TASKS.md",
        REPO_ROOT / "docs" / "phases" / "PHASE_8_TASKS.md",
        REPO_ROOT / "docs",
        REPO_ROOT / "apps" / "api" / "knownet_api",
        REPO_ROOT / "apps" / "web" / "app",
        REPO_ROOT / "apps" / "web" / "components",
    ]
    stale = ("Markdown" + "-first",)
    hits: list[str] = []
    for root in scan_roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if path.is_file() and path.suffix.lower() in {".md", ".py", ".tsx", ".ts", ".css"}:
                text = path.read_text(encoding="utf-8", errors="ignore")
                for pattern in stale:
                    if pattern in text:
                        hits.append(f"{path.relative_to(REPO_ROOT)}:{pattern}")
    assert hits == []
