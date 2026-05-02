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
    monkeypatch.setenv("DEEPSEEK_RUNNER_ENABLED", "false")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("MINIMAX_RUNNER_ENABLED", "false")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("KIMI_RUNNER_ENABLED", "false")
    monkeypatch.setenv("KIMI_MODEL", "kimi-k2-0905-preview")
    monkeypatch.setenv("GLM_RUNNER_ENABLED", "false")
    monkeypatch.setenv("GLM_MODEL", "glm-5.1")
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


def test_gemini_non_mock_uses_provider_adapter(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    class FakeGeminiAdapter:
        provider_id = "gemini"

        def __init__(self, *, api_key, model, timeout_seconds):
            assert api_key == "test-gemini-key"
            assert model == "gemini-2.5-pro"
            assert timeout_seconds > 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["context"]["pages"]
            return {
                "review_title": "Fake Gemini live adapter review",
                "overall_assessment": "Provider adapter route wiring works.",
                "findings": [
                    {
                        "title": "Real adapter path should stay behind dry-run",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The non-mock route used the configured Gemini adapter and returned dry_run_ready instead of importing directly.",
                        "proposed_change": "Keep operator import mandatory after every Gemini API run.",
                        "confidence": 0.9,
                    }
                ],
                "summary": "Fake provider result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.GeminiApiAdapter", FakeGeminiAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/gemini/reviews", json={"mock": False, "review_focus": "adapter smoke"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is False
        assert data["dry_run"]["finding_count"] == 1
        assert data["dry_run"]["parser_errors"] == []


def test_deepseek_mock_run_and_disabled_real_path(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)

        mock = client.post("/api/model-runs/deepseek/reviews", json={"mock": True, "review_focus": "DeepSeek path"})
        assert mock.status_code == 200, mock.text
        data = mock.json()["data"]
        assert data["run"]["provider"] == "deepseek"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is True
        assert data["dry_run"]["finding_count"] == 1

        real = client.post("/api/model-runs/deepseek/reviews", json={"mock": False})
        assert real.status_code == 503
        assert real.json()["detail"]["code"] == "deepseek_disabled"


def test_deepseek_non_mock_uses_provider_adapter(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("DEEPSEEK_RUNNER_ENABLED", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")

    class FakeDeepSeekAdapter:
        provider_id = "deepseek"

        def __init__(self, *, api_key, model, timeout_seconds):
            assert api_key == "test-deepseek-key"
            assert model == "deepseek-v4-flash"
            assert timeout_seconds > 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["context"]["pages"]
            return {
                "review_title": "Fake DeepSeek live adapter review",
                "overall_assessment": "DeepSeek provider adapter route wiring works.",
                "findings": [
                    {
                        "title": "DeepSeek adapter should stay dry-run-first",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The non-mock DeepSeek route used the provider adapter and returned dry_run_ready.",
                        "proposed_change": "Keep DeepSeek output behind the same operator import gate as Gemini.",
                        "confidence": 0.88,
                    }
                ],
                "summary": "Fake DeepSeek provider result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.DeepSeekApiAdapter", FakeDeepSeekAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/deepseek/reviews", json={"mock": False, "review_focus": "adapter smoke"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run"]["provider"] == "deepseek"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is False
        assert data["dry_run"]["finding_count"] == 1
        assert data["dry_run"]["parser_errors"] == []


def test_minimax_mock_run_and_disabled_real_path(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)

        mock = client.post("/api/model-runs/minimax/reviews", json={"mock": True, "review_focus": "MiniMax path"})
        assert mock.status_code == 200, mock.text
        data = mock.json()["data"]
        assert data["run"]["provider"] == "minimax"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is True
        assert data["dry_run"]["finding_count"] == 1

        real = client.post("/api/model-runs/minimax/reviews", json={"mock": False})
        assert real.status_code == 503
        assert real.json()["detail"]["code"] == "minimax_disabled"


def test_minimax_non_mock_uses_provider_adapter(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("MINIMAX_RUNNER_ENABLED", "true")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-minimax-key")

    class FakeMiniMaxAdapter:
        provider_id = "minimax"

        def __init__(self, *, api_key, base_url, model, timeout_seconds):
            assert api_key == "test-minimax-key"
            assert base_url == "https://api.minimax.io/v1"
            assert model == "MiniMax-M2.7"
            assert timeout_seconds > 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["context"]["pages"]
            return {
                "review_title": "Fake MiniMax live adapter review",
                "overall_assessment": "MiniMax provider adapter route wiring works.",
                "findings": [
                    {
                        "title": "MiniMax adapter should stay dry-run-first",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The non-mock MiniMax route used the provider adapter and returned dry_run_ready.",
                        "proposed_change": "Keep MiniMax output behind the same operator import gate as Gemini and DeepSeek.",
                        "confidence": 0.86,
                    }
                ],
                "summary": "Fake MiniMax provider result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.MiniMaxApiAdapter", FakeMiniMaxAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/minimax/reviews", json={"mock": False, "review_focus": "adapter smoke"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run"]["provider"] == "minimax"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is False
        assert data["dry_run"]["finding_count"] == 1
        assert data["dry_run"]["parser_errors"] == []


def test_glm_mock_run_and_disabled_real_path(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)

        mock = client.post("/api/model-runs/glm/reviews", json={"mock": True, "review_focus": "GLM path"})
        assert mock.status_code == 200, mock.text
        data = mock.json()["data"]
        assert data["run"]["provider"] == "glm"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is True
        assert data["dry_run"]["finding_count"] == 1

        real = client.post("/api/model-runs/glm/reviews", json={"mock": False})
        assert real.status_code == 503
        assert real.json()["detail"]["code"] == "glm_disabled"


def test_kimi_mock_run_and_disabled_real_path(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)

        mock = client.post("/api/model-runs/kimi/reviews", json={"mock": True, "review_focus": "Kimi path"})
        assert mock.status_code == 200, mock.text
        data = mock.json()["data"]
        assert data["run"]["provider"] == "kimi"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is True
        assert data["dry_run"]["finding_count"] == 1

        real = client.post("/api/model-runs/kimi/reviews", json={"mock": False})
        assert real.status_code == 503
        assert real.json()["detail"]["code"] == "kimi_disabled"


def test_kimi_non_mock_uses_provider_adapter(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("KIMI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("KIMI_API_KEY", "test-kimi-key")

    class FakeKimiAdapter:
        provider_id = "kimi"

        def __init__(self, *, api_key, base_url, model, timeout_seconds):
            assert api_key == "test-kimi-key"
            assert base_url == "https://api.moonshot.ai/v1"
            assert model == "kimi-k2-0905-preview"
            assert timeout_seconds > 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["context"]["pages"]
            return {
                "review_title": "Fake Kimi live adapter review",
                "overall_assessment": "Kimi provider adapter route wiring works.",
                "findings": [
                    {
                        "title": "Kimi adapter should stay dry-run-first",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The non-mock Kimi route used the provider adapter and returned dry_run_ready.",
                        "proposed_change": "Keep Kimi output behind the same operator import gate as Gemini, DeepSeek, MiniMax, and GLM.",
                        "confidence": 0.86,
                    }
                ],
                "summary": "Fake Kimi provider result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.KimiApiAdapter", FakeKimiAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/kimi/reviews", json={"mock": False, "review_focus": "adapter smoke"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run"]["provider"] == "kimi"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is False
        assert data["dry_run"]["finding_count"] == 1
        assert data["dry_run"]["parser_errors"] == []


def test_glm_non_mock_uses_provider_adapter(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("GLM_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GLM_API_KEY", "test-glm-key")

    class FakeGlmAdapter:
        provider_id = "glm"

        def __init__(self, *, api_key, base_url, model, timeout_seconds):
            assert api_key == "test-glm-key"
            assert base_url == "https://api.z.ai/api/paas/v4"
            assert model == "glm-5.1"
            assert timeout_seconds > 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["context"]["pages"]
            return {
                "review_title": "Fake GLM live adapter review",
                "overall_assessment": "GLM provider adapter route wiring works.",
                "findings": [
                    {
                        "title": "GLM adapter should stay dry-run-first",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The non-mock GLM route used the provider adapter and returned dry_run_ready.",
                        "proposed_change": "Keep GLM output behind the same operator import gate as Gemini, DeepSeek, and MiniMax.",
                        "confidence": 0.86,
                    }
                ],
                "summary": "Fake GLM provider result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.GlmApiAdapter", FakeGlmAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/glm/reviews", json={"mock": False, "review_focus": "adapter smoke"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run"]["provider"] == "glm"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is False
        assert data["dry_run"]["finding_count"] == 1
        assert data["dry_run"]["parser_errors"] == []


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

        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute("UPDATE ai_state_pages SET state_json = ? WHERE id = 'state_secret'", ('{"summary":"DEEPSEEK_API_KEY=do-not-send-this"}',))
            connection.commit()
        response = client.post("/api/model-runs/deepseek/reviews", json={"mock": True})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_context_secret_detected"

        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute("UPDATE ai_state_pages SET state_json = ? WHERE id = 'state_secret'", ('{"summary":"MINIMAX_API_KEY=do-not-send-this"}',))
            connection.commit()
        response = client.post("/api/model-runs/minimax/reviews", json={"mock": True})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_context_secret_detected"

        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute("UPDATE ai_state_pages SET state_json = ? WHERE id = 'state_secret'", ('{"summary":"KIMI_API_KEY=do-not-send-this"}',))
            connection.commit()
        response = client.post("/api/model-runs/kimi/reviews", json={"mock": True})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "model_context_secret_detected"

        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute("UPDATE ai_state_pages SET state_json = ? WHERE id = 'state_secret'", ('{"summary":"GLM_API_KEY=do-not-send-this"}',))
            connection.commit()
        response = client.post("/api/model-runs/glm/reviews", json={"mock": True})
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
