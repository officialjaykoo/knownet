import json

from fastapi.testclient import TestClient

from fixture_utils import load_json_fixture_dir
from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.services.sarif_export import build_sarif_log, safe_sarif_path, validate_sarif_log


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("LOCAL_EMBEDDING_AUTO_LOAD", "false")


def test_sarif_export_service_uses_standard_shape_and_safe_locations():
    log = build_sarif_log(
        [
            {
                "id": "finding_1",
                "review_id": "review_1",
                "severity": "high",
                "area": "API",
                "title": "Route should validate SARIF export",
                "evidence": "Synthetic evidence.",
                "proposed_change": "Add SARIF export test.",
                "evidence_quality": "operator_verified",
                "status": "implemented",
                "source_agent": "codex",
                "source_model": "gpt",
                "changed_files_values": [
                    json.dumps(["apps/api/knownet_api/routes/collaboration.py", ".env", "C:/knownet/secret.txt"])
                ],
                "commit_sha": "abcdef1",
            }
        ],
        run_id="run_test",
        generated_at="2026-05-07T00:00:00Z",
    )
    assert log["$schema"].endswith("sarif-schema-2.1.0.json")
    assert log["version"] == "2.1.0"
    run = log["runs"][0]
    assert run["tool"]["driver"]["name"] == "KnowNet"
    assert run["tool"]["driver"]["rules"][0]["id"] == "knownet.api.high"
    result = run["results"][0]
    assert result["level"] == "error"
    assert result["message"]["text"] == "Route should validate SARIF export"
    assert result["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "apps/api/knownet_api/routes/collaboration.py"
    knownet = result["properties"]["knownet"]
    assert knownet["evidence_quality"] == "operator_verified"
    assert knownet["implementation"]["commit"] == "abcdef1"
    assert len(knownet["omitted_locations"]) == 2
    assert validate_sarif_log(log) == []


def test_sarif_safe_path_rejects_generated_secret_and_absolute_paths():
    assert safe_sarif_path("apps/api/x.py") == ("apps/api/x.py", None)
    assert safe_sarif_path(".env")[0] is None
    assert safe_sarif_path("apps/web/.next/server.js")[0] is None
    assert safe_sarif_path("C:/knownet/apps/api/x.py")[0] is None
    assert safe_sarif_path("../outside.py")[0] is None


def test_phase27_sarif_fixtures_keep_standard_core_shape():
    fixtures = load_json_fixture_dir("sarif")
    assert {fixture_name["$schema"].split("/")[-1] for fixture_name in fixtures} == {"sarif-schema-2.1.0.json"}
    assert len(fixtures) == 3
    qualities = set()
    for fixture in fixtures:
        assert fixture["version"] == "2.1.0"
        assert fixture["runs"][0]["tool"]["driver"]["name"] == "KnowNet"
        result = fixture["runs"][0]["results"][0]
        assert result["ruleId"].startswith("knownet.")
        assert result["level"] in {"error", "warning", "note"}
        qualities.add(result["properties"]["knownet"]["evidence_quality"])
        assert validate_sarif_log(fixture) == []
    assert {"direct_access", "operator_verified", "context_limited"} <= qualities


def test_findings_sarif_endpoint_defaults_to_trusted_findings(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        direct_review = """---
evidence_quality: direct_access
---
# Direct review

### Finding

Title: SARIF endpoint needs export
Severity: high
Area: API

Evidence:
The finding is direct access.

Proposed change:
Export it as SARIF.
"""
        context_review = """---
evidence_quality: context_limited
---
# Context review

### Finding

Title: Context limited should not export by default
Severity: medium
Area: Docs

Evidence:
The evidence is limited.

Proposed change:
Verify before export.
"""
        direct = client.post("/api/collaboration/reviews", json={"markdown": direct_review, "vault_id": "local-default"})
        assert direct.status_code == 200, direct.text
        direct_finding_id = direct.json()["data"]["findings"][0]["id"]
        accepted = client.post(f"/api/collaboration/findings/{direct_finding_id}/decision", json={"status": "accepted", "decision_note": "Trusted"})
        assert accepted.status_code == 200, accepted.text
        implemented = client.post(
            f"/api/collaboration/findings/{direct_finding_id}/implementation",
            json={"commit_sha": "abcdef1", "changed_files": ["apps/api/knownet_api/services/sarif_export.py"], "verification": "pytest"},
        )
        assert implemented.status_code == 200, implemented.text

        context = client.post("/api/collaboration/reviews", json={"markdown": context_review, "vault_id": "local-default"})
        assert context.status_code == 200, context.text
        context_finding_id = context.json()["data"]["findings"][0]["id"]
        context_accept = client.post(f"/api/collaboration/findings/{context_finding_id}/decision", json={"status": "accepted", "decision_note": "Needs verification"})
        assert context_accept.status_code == 200, context_accept.text

        sarif = client.get("/api/collaboration/findings.sarif")
        assert sarif.status_code == 200, sarif.text
        assert sarif.headers["content-type"].startswith("application/sarif+json")
        data = sarif.json()
        assert data["version"] == "2.1.0"
        results = data["runs"][0]["results"]
        assert len(results) == 1
        assert results[0]["partialFingerprints"]["knownetFindingId"] == direct_finding_id
        assert results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "apps/api/knownet_api/services/sarif_export.py"

        explicit = client.get("/api/collaboration/findings.sarif?evidence_quality=context_limited&status=accepted")
        assert explicit.status_code == 200, explicit.text
        explicit_results = explicit.json()["runs"][0]["results"]
        assert len(explicit_results) == 1
        assert explicit_results[0]["partialFingerprints"]["knownetFindingId"] == context_finding_id
        assert explicit_results[0]["properties"]["knownet"]["evidence_quality"] == "context_limited"
    get_settings.cache_clear()
