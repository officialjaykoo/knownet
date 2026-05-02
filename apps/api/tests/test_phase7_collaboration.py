import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.routes.collaboration import parse_review_markdown


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def _review_markdown():
    return """---
type: agent_review
source_agent: claude
source_model: claude-3.7
---

# Review: Collaboration MVP

## Findings

### Finding 1: Review import needs durable storage

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


def test_parser_extracts_multiple_findings():
    metadata, findings, errors = parse_review_markdown(_review_markdown())
    assert metadata["source_agent"] == "claude"
    assert errors == []
    assert len(findings) == 2
    assert findings[0]["severity"] == "high"
    assert findings[0]["area"] == "collaboration-api"
    assert findings[0]["status"] == "pending"


def test_parser_fallback_for_missing_finding_headings():
    _metadata, findings, errors = parse_review_markdown("# Loose Review\n\nThis is not structured.")
    assert "no_finding_headings" in errors
    assert findings[0]["severity"] == "info"
    assert findings[0]["status"] == "needs_more_context"
    assert findings[0]["raw_text"]


def test_import_triage_implementation_and_bundle(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        imported = client.post("/api/collaboration/reviews", json={"markdown": _review_markdown(), "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        data = imported.json()["data"]
        review_id = data["review"]["id"]
        finding_id = data["findings"][0]["id"]
        assert len(data["findings"]) == 2
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
        manifest_count = connection.execute("SELECT COUNT(*) FROM context_bundle_manifests").fetchone()[0]
        audit_count = connection.execute("SELECT COUNT(*) FROM audit_events WHERE action = 'review.import'").fetchone()[0]
    assert review_count == 1
    assert finding_status == "implemented"
    assert manifest_count == 1
    assert audit_count == 1
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
