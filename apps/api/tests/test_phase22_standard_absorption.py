import json
import re
import sqlite3

from fastapi.testclient import TestClient

from fixture_utils import load_json_fixture
from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.services.packet_contract import build_packet_contract
from knownet_api.services.project_snapshot import node_card
from knownet_api.services.provider_registry import provider_capabilities
from knownet_api.services.provenance import compact_provenance, validate_provenance_safe


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("GEMINI_RUNNER_ENABLED", "false")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_provider_capability_registry_matches_file_fixture(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    expected = load_json_fixture("provider_capabilities/compatibility_classes.json")["providers"]
    capabilities = {item["provider_id"]: item for item in provider_capabilities(get_settings())}
    assert expected.keys() <= capabilities.keys()
    for provider_id, compatibility_class in expected.items():
        assert capabilities[provider_id]["compatibility_class"] == compatibility_class
    assert capabilities["gemini"]["custom_api"] is True
    assert capabilities["deepseek"]["openai_compatible"] is True


def test_operator_provider_capabilities_endpoint_and_matrix(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/operator/provider-capabilities")
        assert response.status_code == 200, response.text
        providers = {item["provider_id"]: item for item in response.json()["data"]["providers"]}
        assert providers["gemini"]["compatibility_class"] == "custom_api"
        assert providers["glm"]["compatibility_class"] == "openai_compatible_with_overrides"

        matrix = client.get("/api/operator/provider-matrix")
        assert matrix.status_code == 200, matrix.text
        glm = next(item for item in matrix.json()["data"]["providers"] if item["provider_id"] == "glm")
        assert glm["capability"]["provider_id"] == "glm"
        assert glm["openai_compatible"] is True
    get_settings.cache_clear()


def test_model_run_observations_expose_trace_metrics_and_summary(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            connection.execute(
                "INSERT INTO model_review_runs (id, provider, model, prompt_profile, vault_id, status, context_summary_json, request_json, response_json, input_tokens, output_tokens, trace_id, packet_trace_id, error_code, error_message, created_at, updated_at) "
                "VALUES ('modelrun_obs', 'glm', 'glm-5.1', 'test', 'local-default', 'failed', '{}', ?, ?, 100, 0, ?, ?, 'glm_timeout', 'timeout', '2026-05-05T00:00:00Z', '2026-05-05T00:00:00Z')",
                (
                    json.dumps({"mock": False}),
                    json.dumps({"duration_ms": 90001}),
                    "a" * 32,
                    "b" * 32,
                ),
            )
            connection.commit()
        response = client.get("/api/model-runs/observations")
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        observation = data["observations"][0]
        assert observation["trace_id"] == "a" * 32
        assert observation["packet_trace_id"] == "b" * 32
        assert observation["duration_ms"] == 90001
        assert observation["error_code"] == "glm_timeout"
        assert observation["evidence_quality"] == "direct_access"
        assert data["summary"]["providers"][0]["failure_count"] == 1
    get_settings.cache_clear()


def test_mcp_contract_uses_standard_method_uri_and_tool_names():
    contract = build_packet_contract(packet_kind="project_snapshot", target_agent="claude", operator_question="Review.")
    mcp = contract["mcp"]
    assert mcp["protocolVersion"] == "2025-06-18"
    assert mcp["serverInfo"]["name"] == "knownet"
    assert {"resources/list", "resources/read", "tools/list", "tools/call", "prompts/list", "prompts/get"} <= set(mcp["methods"])
    assert "resources" in mcp["capabilities"]
    assert any(item["uri"] == "knownet://model-run/{run_id}/observation" for item in mcp["resources"])
    assert all(item["uri"].startswith("knownet://") for item in mcp["resources"])
    assert any(item["name"] == "knownet.propose_finding" for item in mcp["tools"])
    assert all(item["name"].startswith("knownet.") for item in mcp["tools"])
    assert any(item["name"] == "knownet.compact_review" for item in mcp["prompts"])
    assert "raw_db" in mcp["refused"]
    assert "mcp_style_boundary" not in contract
    assert contract["node_card_contract"]["required_fields"]
    assert "detail_url" in contract["node_card_contract"]["required_fields"]
    assert "short_summary first" in contract["node_card_contract"]["read_rules"][0]


def test_compact_provenance_and_node_cards_stay_safe():
    provenance = compact_provenance(source_type="model_run", source_id="modelrun_1", source_packet_trace_id="b" * 32, source_model_run_trace_id="a" * 32, evidence_quality="direct_access")
    assert validate_provenance_safe(provenance) == []
    unsafe = compact_provenance(source_type="node_card", source_id="C:\\knownet\\data\\knownet.db")
    assert validate_provenance_safe(unsafe) == ["provenance_forbidden_value:source_id"]
    card = node_card({"id": "page_1", "slug": "phase-22", "title": "Phase 22", "system_kind": "phase", "updated_at": "2026-05-05T00:00:00Z"})
    assert card["provenance"]["source_type"] == "node_card"
    assert card["provenance_warnings"] == []
    assert re.match(r"/api/pages/phase-22", card["detail_url"])
