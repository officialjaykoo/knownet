import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "false")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_MAX_CONTEXT_TOKENS", "32000")
    monkeypatch.setenv("GEMINI_MAX_CONTEXT_CHARS", "120000")


def _admin_headers():
    token = get_settings().admin_token
    return {"x-knownet-admin-token": token} if token else {}


def _seed_operator_state(sqlite_path):
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO pages (id, vault_id, title, slug, path, current_revision_id, status, created_at, updated_at) "
            "VALUES ('page_p17', 'local-default', 'Phase 17 State', 'phase-17-state', 'data/pages/phase-17-state.md', 'rev_p17', 'active', '2026-05-04T00:00:00Z', '2026-05-04T00:00:00Z')"
        )
        connection.execute(
            "INSERT OR REPLACE INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
            "VALUES ('state_p17', 'local-default', 'page_p17', 'phase-17-state', 'Phase 17 State', 'C:/knownet/data/pages/phase-17-state.md', 'hash_p17', ?, '2026-05-04T00:00:00Z')",
            (
                '{"summary":"Phase 17 operator console state.","current_state":"Operator console implementation in progress.","boundaries":["no raw DB","no unreviewed AI writes"],"review_targets":["provider matrix","AI state quality"],"verification":"pytest and release_check must cover this state."}',
            ),
        )
        connection.execute(
            "INSERT OR REPLACE INTO graph_nodes (id, vault_id, node_type, target_id, label, status, weight, meta, created_at, updated_at) "
            "VALUES ('node_p17', 'local-default', 'page', 'page_p17', 'Phase 17 State', 'active', 1.0, '{}', '2026-05-04T00:00:00Z', '2026-05-04T00:00:00Z')"
        )
        connection.execute(
            "INSERT OR REPLACE INTO implementation_records (id, finding_id, commit_sha, changed_files, verification, notes, created_at) "
            "VALUES ('impl_p17', NULL, 'abc123', '[]', 'Phase 17 seed verification', 'Seed record for quality test', '2026-05-04T00:00:00Z')"
        )
        connection.commit()


def test_ai_state_quality_passes_safe_structured_state(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_operator_state(settings.sqlite_path)

        response = client.get("/api/operator/ai-state-quality")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["overall_status"] == "pass"
        assert data["summary"]["ai_state_pages"] == 1
        assert {check["code"]: check["status"] for check in data["checks"]}["forbidden_context_hits"] == "pass"
        assert "C:/knownet" not in response.text


def test_ai_state_quality_fails_for_secret_like_state(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_operator_state(settings.sqlite_path)
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute("UPDATE ai_state_pages SET state_json = ? WHERE id = 'state_p17'", ('{"summary":"GEMINI_API_KEY=do-not-send"}',))
            connection.commit()

        response = client.get("/api/operator/ai-state-quality")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["overall_status"] == "fail"
        assert {check["code"]: check["status"] for check in data["checks"]}["forbidden_context_hits"] == "fail"


def test_provider_matrix_does_not_mark_mocked_runs_live_verified(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    with TestClient(app) as client:
        settings = get_settings()
        now = "2026-05-04T00:00:00Z"
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO model_review_runs (id, provider, model, prompt_profile, vault_id, status, context_summary_json, request_json, response_json, created_at, updated_at) "
                "VALUES ('modelrun_mock', 'gemini', 'gemini-2.5-pro', 'test', 'local-default', 'dry_run_ready', '{}', ?, '{}', ?, ?)",
                ('{"mock": true}', now, now),
            )
            connection.commit()

        response = client.get("/api/operator/provider-matrix")
        assert response.status_code == 200, response.text
        providers = response.json()["data"]["providers"]
        gemini = next(item for item in providers if item["provider_id"] == "gemini")
        assert gemini["verification_level"] == "mocked"
        assert gemini["run_counts"]["mock_successful"] == 1
        assert gemini["run_counts"]["live_successful"] == 0


def test_provider_matrix_exposes_latest_failure_and_consecutive_alert(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            for index in range(3):
                connection.execute(
                "INSERT INTO model_review_runs (id, provider, model, prompt_profile, vault_id, status, context_summary_json, request_json, response_json, error_code, error_message, created_at, updated_at) "
                    "VALUES (?, 'glm', 'glm-5.1', 'test', 'local-default', 'failed', '{}', ?, '{}', ?, ?, ?, ?)",
                    (
                        f"modelrun_glm_failed_{index}",
                        '{"mock": false}',
                        "glm_timeout",
                        f"GLM API request timed out attempt {index}",
                        f"2026-05-04T00:0{index}:00Z",
                        f"2026-05-04T00:0{index}:00Z",
                    ),
                )
            connection.commit()

        response = client.get("/api/operator/provider-matrix")
        assert response.status_code == 200, response.text
        providers = response.json()["data"]["providers"]
        glm = next(item for item in providers if item["provider_id"] == "glm")
        assert glm["verification_level"] == "failed"
        assert glm["run_counts"]["failed"] == 3
        assert glm["run_counts"]["consecutive_failed"] == 3
        assert glm["stability_alert"] is True
        assert glm["latest_failure"]["run_id"] == "modelrun_glm_failed_2"
        assert glm["latest_failure"]["error_code"] == "glm_timeout"


def test_provider_matrix_exposes_failure_duration(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO model_review_runs (id, provider, model, prompt_profile, vault_id, status, context_summary_json, request_json, response_json, error_code, error_message, created_at, updated_at) "
                "VALUES ('modelrun_glm_slow', 'glm', 'glm-5.1', 'test', 'local-default', 'failed', '{}', ?, ?, 'glm_timeout', 'timeout', '2026-05-04T00:00:00Z', '2026-05-04T00:00:00Z')",
                ('{"mock": false}', '{"duration_ms": 90001}'),
            )
            connection.commit()

        response = client.get("/api/operator/provider-matrix")
        assert response.status_code == 200, response.text
        glm = next(item for item in response.json()["data"]["providers"] if item["provider_id"] == "glm")
        assert glm["latest_failure"]["duration_ms"] == 90001


def test_release_readiness_includes_quality_and_provider_summary(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_operator_state(settings.sqlite_path)

        response = client.get("/api/operator/release-readiness")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["release_ready"] is True
        assert data["ai_state_quality"]["overall_status"] == "pass"
        assert "provider_matrix" in data
        assert "no_live_provider_verified" in data["warnings"]


def test_restore_plan_inspects_snapshot_without_restoring(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_operator_state(settings.sqlite_path)

        headers = _admin_headers()
        snapshot = client.post("/api/maintenance/snapshots", headers=headers)
        assert snapshot.status_code == 200, snapshot.text
        snapshot_name = snapshot.json()["data"]["name"]

        plan = client.get(f"/api/maintenance/restore-plan?snapshot_name={snapshot_name}", headers=headers)
        assert plan.status_code == 200, plan.text
        data = plan.json()["data"]
        assert data["snapshot"] == snapshot_name
        assert data["format"] == "tar.gz"
        assert data["safe_to_inspect"] is True
        assert data["restore_requires_confirmation"] is True
        assert data["pre_restore_snapshot_required"] is True
        assert data["manifest"]["kind"] == "knownet.snapshot"
