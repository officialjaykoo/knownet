import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.routes.collaboration import parse_review_markdown


REPO_ROOT = Path(__file__).resolve().parents[3]


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
    assert findings[0]["area"] == "Docs"
    assert findings[0]["status"] == "pending"


def test_parser_fallback_for_missing_finding_headings():
    _metadata, findings, errors = parse_review_markdown("# Loose Review\n\nThis is not structured.")
    assert "no_finding_headings" in errors
    assert findings[0]["severity"] == "info"
    assert findings[0]["area"] == "Docs"
    assert findings[0]["status"] == "needs_more_context"
    assert findings[0]["raw_text"]


def test_parser_is_case_insensitive_and_normalizes_area():
    markdown = """# Review

### finding

Severity: medium
Area: api

Evidence:
Lower-case heading and area should parse.

Proposed change:
Normalize the area.

### FINDING

Severity: strange
Area: ui

Evidence:
Unknown severity should fall back.

Proposed change:
Keep parsing.
"""
    _metadata, findings, errors = parse_review_markdown(markdown)
    assert len(findings) == 2
    assert findings[0]["severity"] == "medium"
    assert findings[0]["area"] == "API"
    assert findings[1]["severity"] == "info"
    assert findings[1]["area"] == "UI"
    assert "unknown_severity:strange" in errors


def test_parser_truncates_more_than_50_findings():
    finding = """### Finding

Severity: low
Area: docs

Evidence:
Evidence.

Proposed change:
Change.
"""
    metadata, findings, errors = parse_review_markdown("# Review\n\n" + "\n".join(finding for _ in range(51)))
    assert len(findings) == 50
    assert metadata["truncated_findings"] is True
    assert "truncated_findings" in errors


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
                "INSERT INTO implementation_records (id, finding_id, changed_files, verification, created_at) "
                "VALUES ('impl_orphan', 'finding_missing', '[]', 'not run', '2026-05-02T00:00:00Z')"
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
        assert "implementation_record_orphan" in codes
        assert "context_bundle_forbidden_reference" in codes
    get_settings.cache_clear()


def test_active_docs_and_app_code_use_current_terms():
    scan_roots = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "PHASE_7_TASKS.md",
        REPO_ROOT / "PHASE_8_TASKS.md",
        REPO_ROOT / "docs",
        REPO_ROOT / "apps" / "api" / "knownet_api",
        REPO_ROOT / "apps" / "web" / "app",
        REPO_ROOT / "apps" / "web" / "components",
    ]
    stale = ("data/" + "wiki", "/api/" + "wiki", "Markdown" + "-first")
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
