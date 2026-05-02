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
    monkeypatch.setenv("GEMINI_MAX_CONTEXT_TOKENS", "32000")
    monkeypatch.setenv("GEMINI_MAX_CONTEXT_CHARS", "120000")


def _seed_ai_state(sqlite_path):
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO pages (id, vault_id, title, slug, path, current_revision_id, status, created_at, updated_at) "
            "VALUES ('page_test', 'local-default', 'KnowNet Phase 16', 'knownet-phase-16', 'data/pages/knownet-phase-16.md', 'rev_test', 'active', '2026-05-03T00:00:00Z', '2026-05-03T00:00:00Z')"
        )
        connection.execute(
            "INSERT OR REPLACE INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
            "VALUES ('state_test', 'local-default', 'page_test', 'knownet-phase-16', 'KnowNet Phase 16', 'C:/knownet/data/pages/knownet-phase-16.md', 'hash_test', ?, '2026-05-03T00:00:00Z')",
            (
                '{"summary":"Phase 16 adds a provider-neutral model runner foundation.","current_state":"mock Gemini only","source":{"content_hash":"hash_test"}}',
            ),
        )
        connection.commit()


def test_gemini_mock_run_dry_run_import_flow(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)

        created = client.post("/api/model-runs/gemini/reviews", json={"mock": True, "review_focus": "Phase 16 foundation"})
        assert created.status_code == 200, created.text
        payload = created.json()["data"]
        run = payload["run"]
        assert run["provider"] == "gemini"
        assert run["status"] == "dry_run_ready"
        assert run["response"]["mock"] is True
        assert payload["dry_run"]["finding_count"] >= 1
        assert "C:/knownet" not in created.text
        assert "token_hash" not in created.text

        listed = client.get("/api/model-runs?provider=gemini")
        assert listed.status_code == 200, listed.text
        assert listed.json()["data"]["runs"][0]["id"] == run["id"]

        dry_run = client.post(f"/api/model-runs/{run['id']}/dry-run")
        assert dry_run.status_code == 200, dry_run.text
        assert dry_run.json()["data"]["finding_count"] == payload["dry_run"]["finding_count"]

        imported = client.post(f"/api/model-runs/{run['id']}/import")
        assert imported.status_code == 200, imported.text
        imported_data = imported.json()["data"]
        assert imported_data["run"]["status"] == "imported"
        assert imported_data["run"]["review_id"]
        assert imported_data["findings"]

        duplicate = client.post(f"/api/model-runs/{run['id']}/import")
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "model_run_not_importable"


def test_gemini_non_mock_is_not_enabled_yet(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/model-runs/gemini/reviews", json={"mock": False})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "gemini_disabled"


def test_model_context_rejects_secret_like_ai_state(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO pages (id, vault_id, title, slug, path, current_revision_id, status, created_at, updated_at) "
                "VALUES ('page_secret', 'local-default', 'Secret Page', 'secret-page', 'data/pages/secret-page.md', 'rev_secret', 'active', '2026-05-03T00:00:00Z', '2026-05-03T00:00:00Z')"
            )
            connection.execute(
                "INSERT OR REPLACE INTO ai_state_pages (id, vault_id, page_id, slug, title, source_path, content_hash, state_json, updated_at) "
                "VALUES ('state_secret', 'local-default', 'page_secret', 'secret-page', 'Secret Page', 'data/pages/secret-page.md', 'hash_secret', ?, '2026-05-03T00:00:00Z')",
                ('{"summary":"ADMIN_TOKEN=do-not-send-this"}',),
            )
            connection.commit()
        response = client.post("/api/model-runs/gemini/reviews", json={"mock": True})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_context_secret_detected"


def test_model_run_blocks_parallel_active_run(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO model_review_runs (id, provider, model, prompt_profile, vault_id, status, created_at, updated_at) "
                "VALUES ('modelrun_active', 'gemini', 'gemini-2.5-pro', 'test', 'local-default', 'running', '2026-05-03T00:00:00Z', '2026-05-03T00:00:00Z')"
            )
            connection.commit()
        response = client.post("/api/model-runs/gemini/reviews", json={"mock": True})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "model_run_already_active"
