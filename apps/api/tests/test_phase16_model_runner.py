import sqlite3
import re
import json

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.services.model_output import normalize_model_output


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "false")
    monkeypatch.setenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_RESPONSE_MIME_TYPE", "application/json")
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "0")
    monkeypatch.setenv("DEEPSEEK_RUNNER_ENABLED", "false")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "high")
    monkeypatch.setenv("DEEPSEEK_THINKING_ENABLED", "true")
    monkeypatch.setenv("MINIMAX_RUNNER_ENABLED", "false")
    monkeypatch.setenv("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    monkeypatch.setenv("MINIMAX_MAX_TOKENS", "4000")
    monkeypatch.setenv("MINIMAX_REASONING_SPLIT", "true")
    monkeypatch.setenv("KIMI_RUNNER_ENABLED", "false")
    monkeypatch.setenv("KIMI_MODEL", "kimi-k2.5")
    monkeypatch.setenv("QWEN_RUNNER_ENABLED", "false")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")
    monkeypatch.setenv("QWEN_MAX_TOKENS", "4000")
    monkeypatch.setenv("QWEN_ENABLE_SEARCH", "false")
    monkeypatch.setenv("GLM_RUNNER_ENABLED", "false")
    monkeypatch.setenv("GLM_MODEL", "glm-5.1")
    monkeypatch.setenv("GLM_BASE_URL", "https://api.z.ai/api/paas/v4")
    monkeypatch.setenv("GLM_MAX_TOKENS", "4000")
    monkeypatch.setenv("GLM_THINKING_ENABLED", "false")
    monkeypatch.setenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
    monkeypatch.setenv("KIMI_MAX_TOKENS", "4000")
    monkeypatch.setenv("KIMI_THINKING_ENABLED", "false")
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


def _seed_duplicate_findings(sqlite_path):
    with sqlite3.connect(sqlite_path) as connection:
        connection.execute(
            "INSERT OR REPLACE INTO collaboration_reviews (id, vault_id, title, source_agent, review_type, status, created_at, updated_at) "
            "VALUES ('review_context', 'local-default', 'Context Review', 'claude', 'agent_review', 'pending_review', '2026-05-03T00:00:00Z', '2026-05-03T00:00:00Z')"
        )
        for finding_id, status in [("finding_context_1", "pending"), ("finding_context_2", "accepted")]:
            connection.execute(
                "INSERT OR REPLACE INTO collaboration_findings (id, review_id, severity, area, title, evidence, proposed_change, evidence_quality, status, created_at, updated_at) "
                "VALUES (?, 'review_context', 'medium', 'API', 'Duplicate context issue', 'Evidence from context.', 'Change the context handling.', 'context_limited', ?, '2026-05-03T00:00:00Z', '2026-05-03T00:00:00Z')",
                (finding_id, status),
            )
        connection.commit()


def test_normalize_model_output_dedupes_duplicate_titles():
    output = normalize_model_output(
        {
            "review_title": "Deduping test",
            "overall_assessment": "Duplicate titles should collapse.",
            "findings": [
                {
                    "title": "Repeated finding",
                    "severity": "medium",
                    "area": "API",
                    "evidence": "First evidence.",
                    "proposed_change": "First change.",
                },
                {
                    "title": "Repeated Finding!",
                    "severity": "high",
                    "area": "API",
                    "evidence": "Second evidence.",
                    "proposed_change": "Second change.",
                },
            ],
            "summary": "Done.",
        }
    )
    assert len(output["findings"]) == 1
    assert output["findings"][0]["title"] == "Repeated finding"


def test_model_context_slims_and_dedupes_findings(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        _seed_duplicate_findings(settings.sqlite_path)

        response = client.post("/api/model-runs/gemini/reviews", json={"mock": True, "max_pages": 1, "max_findings": 1, "slim_context": True})
        assert response.status_code == 200, response.text
        summary = response.json()["data"]["run"]["context_summary"]
        request_payload = response.json()["data"]["run"]["request"]
        assert summary["page_count"] == 1
        assert summary["context_mode"] == "slim"
        assert summary["max_pages"] == 1
        assert summary["max_findings"] == 1
        assert summary["open_finding_count"] == 1
        assert summary["existing_finding_title_count"] == 1
        assert request_payload["max_findings"] == 1
        assert request_payload["slim_context"] is True


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

        def __init__(self, *, api_key, base_url, model, response_mime_type, thinking_budget, timeout_seconds):
            assert api_key == "test-gemini-key"
            assert base_url == "https://generativelanguage.googleapis.com/v1beta"
            assert model == "gemini-2.5-pro"
            assert response_mime_type == "application/json"
            assert thinking_budget == 0
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


def test_review_now_uses_live_gemini_when_configured(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    class FakeGeminiAdapter:
        provider_id = "gemini"

        def __init__(self, *, api_key, base_url, model, response_mime_type, thinking_budget, timeout_seconds):
            assert api_key == "test-gemini-key"
            assert base_url == "https://generativelanguage.googleapis.com/v1beta"
            assert model == "gemini-2.5-pro"
            assert response_mime_type == "application/json"
            assert thinking_budget == 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["request"]["max_pages"] == 10
            assert request["request"]["max_findings"] == 15
            assert request["request"]["slim_context"] is True
            assert request["context"]["contract_version"] == "p20.v1"
            assert "packet_schema_version" not in request["context"]
            assert request["context"]["protocol_version"] == "2026-05-05"
            assert request["context"]["schema_ref"] == "knownet://schemas/packet/p20.v1"
            assert request["context"]["trace"]["name"] == "knownet.provider_fast_lane_context"
            assert request["context"]["trace"]["span_kind"] == "CLIENT"
            assert re.fullmatch(r"[0-9a-f]{32}", request["context"]["trace"]["trace_id"])
            assert request["context"]["trace"]["traceparent"] == f"00-{request['context']['trace']['trace_id']}-{request['context']['trace']['span_id']}-01"
            assert request["context"]["trace"]["attributes"]["knownet.packet.kind"] == "provider_fast_lane"
            assert request["context"]["ai_context"]["role"] == "provider_review_reviewer"
            assert "packet_summary" in request["context"]
            assert "node_cards" in request["context"]
            assert request["context"]["contract"]["packet_metadata"]["packet_kind"] == "provider_fast_lane"
            assert request["context"]["contract"]["output_contract"]["output_mode"] == "top_findings"
            assert request["context"]["protocols"]["boundary_enforcement"]
            assert request["context"]["stale_suppression"]["rule"]
            return {
                "review_title": "Fast lane Gemini review",
                "overall_assessment": "Fast lane invoked Gemini directly.",
                "findings": [
                    {
                        "title": "Fast lane should bypass packet copy",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The review-now endpoint selected the configured Gemini adapter.",
                        "proposed_change": "Use server-side provider calls before packet fallback.",
                        "confidence": 0.95,
                    }
                ],
                "summary": "Fast lane result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.GeminiApiAdapter", FakeGeminiAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/review-now", json={"provider": "auto", "prefer_live": True, "allow_mock_fallback": False})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["fast_lane"] is True
        assert data["provider"] == "gemini"
        assert data["live"] is True
        assert data["mock_fallback"] is False
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["request"]["mock"] is False
        assert re.fullmatch(r"[0-9a-f]{32}", data["run"]["trace_id"])
        assert data["run"]["packet_trace_id"] == data["run"]["request"]["packet_trace_id"]
        assert data["run"]["response"]["trace"]["trace_id"] == data["run"]["trace_id"]
        assert data["run"]["response"]["packet_trace_id"] == data["run"]["packet_trace_id"]
        assert data["dry_run"]["finding_count"] == 1
    get_settings.cache_clear()


def test_review_now_can_mock_fallback_and_auto_import(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/review-now", json={"allow_mock_fallback": True, "auto_import": True})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["live"] is False
        assert data["mock_fallback"] is True
        assert data["run"]["status"] == "imported"
        assert data["import"]["review"]["id"]
        assert data["next_step"] == "triage_imported_findings"
    get_settings.cache_clear()


def test_review_now_requires_live_when_fallback_disabled(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/model-runs/review-now", json={"prefer_live": True, "allow_mock_fallback": False})
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "gemini_fast_lane_unavailable"
    get_settings.cache_clear()


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

        def __init__(self, *, api_key, base_url, model, reasoning_effort, thinking_enabled, timeout_seconds):
            assert api_key == "test-deepseek-key"
            assert base_url == "https://api.deepseek.com"
            assert model == "deepseek-v4-flash"
            assert reasoning_effort == "high"
            assert thinking_enabled is True
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

        def __init__(self, *, api_key, base_url, model, max_tokens, reasoning_split, timeout_seconds):
            assert api_key == "test-minimax-key"
            assert base_url == "https://api.minimaxi.com/v1"
            assert model == "MiniMax-M2.7"
            assert max_tokens == 4000
            assert reasoning_split is True
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


def test_qwen_mock_run_and_disabled_real_path(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)

        mock = client.post("/api/model-runs/qwen/reviews", json={"mock": True, "review_focus": "Qwen path"})
        assert mock.status_code == 200, mock.text
        data = mock.json()["data"]
        assert data["run"]["provider"] == "qwen"
        assert data["run"]["status"] == "dry_run_ready"
        assert data["run"]["response"]["mock"] is True
        assert data["dry_run"]["finding_count"] == 1

        real = client.post("/api/model-runs/qwen/reviews", json={"mock": False})
        assert real.status_code == 503
        assert real.json()["detail"]["code"] == "qwen_disabled"


def test_qwen_non_mock_uses_provider_adapter(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("QWEN_RUNNER_ENABLED", "true")
    monkeypatch.setenv("QWEN_API_KEY", "test-qwen-key")

    class FakeQwenAdapter:
        provider_id = "qwen"

        def __init__(self, *, api_key, base_url, model, max_tokens, enable_search, timeout_seconds):
            assert api_key == "test-qwen-key"
            assert base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
            assert model == "qwen-plus"
            assert max_tokens == 4000
            assert enable_search is False
            assert timeout_seconds > 0

        async def generate_review(self, request):
            assert request["request"]["mock"] is False
            assert request["context"]["pages"]
            return {
                "review_title": "Fake Qwen live adapter review",
                "overall_assessment": "Qwen provider adapter route wiring works.",
                "findings": [
                    {
                        "title": "Qwen adapter should stay dry-run-first",
                        "severity": "medium",
                        "area": "API",
                        "evidence": "The non-mock Qwen route used the provider adapter and returned dry_run_ready.",
                        "proposed_change": "Keep Qwen output behind the same operator import gate as Gemini, DeepSeek, and MiniMax.",
                        "confidence": 0.86,
                    }
                ],
                "summary": "Fake Qwen provider result.",
            }

    monkeypatch.setattr("knownet_api.routes.model_runs.QwenApiAdapter", FakeQwenAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        response = client.post("/api/model-runs/qwen/reviews", json={"mock": False, "review_focus": "adapter smoke"})
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["run"]["provider"] == "qwen"
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

        def __init__(self, *, api_key, base_url, model, max_tokens, thinking_enabled, timeout_seconds):
            assert api_key == "test-kimi-key"
            assert base_url == "https://api.moonshot.ai/v1"
            assert model == "kimi-k2.5"
            assert max_tokens == 4000
            assert thinking_enabled is False
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

        def __init__(self, *, api_key, base_url, model, max_tokens, thinking_enabled, timeout_seconds):
            assert api_key == "test-glm-key"
            assert base_url == "https://api.z.ai/api/paas/v4"
            assert model == "glm-5.1"
            assert max_tokens == 4000
            assert thinking_enabled is False
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


def test_provider_run_records_duration_on_success_and_failure(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)

    class SuccessfulAdapter:
        provider_id = "gemini"

        def __init__(self, *, api_key, base_url, model, response_mime_type, thinking_budget, timeout_seconds):
            pass

        async def generate_review(self, request):
            return {
                "review_title": "Timed run",
                "overall_assessment": "ok",
                "findings": [
                    {
                        "title": "Duration is recorded",
                        "severity": "low",
                        "area": "Ops",
                        "evidence": "The run completed through the fake adapter.",
                        "proposed_change": "Keep duration_ms in model run responses.",
                    }
                ],
                "summary": "ok",
            }

    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr("knownet_api.routes.model_runs.GeminiApiAdapter", SuccessfulAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        success = client.post("/api/model-runs/gemini/reviews", json={"mock": False})
        assert success.status_code == 200, success.text
        assert isinstance(success.json()["data"]["run"]["response"]["duration_ms"], int)

    get_settings.cache_clear()
    _isolate_settings(monkeypatch, tmp_path)

    class FailingAdapter:
        provider_id = "gemini"

        def __init__(self, *, api_key, base_url, model, response_mime_type, thinking_budget, timeout_seconds):
            pass

        async def generate_review(self, request):
            from fastapi import HTTPException

            raise HTTPException(status_code=504, detail={"code": "gemini_timeout", "message": "timeout"})

    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr("knownet_api.routes.model_runs.GeminiApiAdapter", FailingAdapter)
    with TestClient(app) as client:
        settings = get_settings()
        _seed_ai_state(settings.sqlite_path)
        failed = client.post("/api/model-runs/gemini/reviews", json={"mock": False})
        assert failed.status_code == 504
        row = sqlite3.connect(settings.sqlite_path).execute("SELECT response_json, trace_id, packet_trace_id FROM model_review_runs WHERE status = 'failed'").fetchone()
        assert row is not None
        assert "duration_ms" in row[0]
        failed_response = json.loads(row[0])
        assert failed_response["trace"]["trace_id"] == row[1]
        assert failed_response["packet_trace_id"] == row[2]


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
