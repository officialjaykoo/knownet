import json

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.routes.collaboration import parse_review_markdown
from knownet_api.services.sarif_export import build_sarif_log, code_scanning_readiness, content_fingerprint, validate_sarif_log
from knownet_api.services.source_locations import parse_source_location_ref


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("LOCAL_EMBEDDING_AUTO_LOAD", "false")


def test_source_location_ref_parser_accepts_ranges_and_rejects_unsafe_paths():
    assert parse_source_location_ref("apps/api/routes.py") == {
        "status": "accepted",
        "path": "apps/api/routes.py",
        "start_line": None,
        "end_line": None,
    }
    assert parse_source_location_ref("apps\\api\\routes.py#L45")["start_line"] == 45
    ranged = parse_source_location_ref("apps/api/routes.py#L45-L52")
    assert ranged["path"] == "apps/api/routes.py"
    assert ranged["start_line"] == 45
    assert ranged["end_line"] == 52
    assert parse_source_location_ref("apps/api/routes.py#L0")["status"] == "rejected"
    assert parse_source_location_ref("apps/api/routes.py#L52-L45")["reason"] == "invalid_range"
    assert parse_source_location_ref("../secret.py")["reason"] == "parent_reference"
    assert parse_source_location_ref("C:/knownet/secret.py")["reason"] == "absolute_path"
    assert parse_source_location_ref(".env")["reason"] == "forbidden_path_pattern"
    assert parse_source_location_ref("apps/api/my file.py")["reason"] == "unsafe_whitespace"


def test_markdown_and_compact_review_parser_capture_optional_source_location():
    markdown = """# Review

### Finding

Title: Location-aware finding
Severity: high
Area: API
Evidence quality: direct_access
Source path: apps/api/knownet_api/services/sarif_export.py
Source lines: 42-57
Source snippet:
return build_sarif_log(rows)

Evidence:
The finding points to source.

Proposed change:
Emit SARIF region data.
"""
    _metadata, findings, errors = parse_review_markdown(markdown)
    assert errors == []
    assert findings[0]["source_path"] == "apps/api/knownet_api/services/sarif_export.py"
    assert findings[0]["source_start_line"] == 42
    assert findings[0]["source_end_line"] == 57
    assert findings[0]["source_snippet"] == "return build_sarif_log(rows)"
    assert findings[0]["source_location_status"] == "accepted"

    compact = {
        "output_mode": "top_findings",
        "findings": [
            {
                "title": "Compact location",
                "severity": "medium",
                "area": "API",
                "evidence_quality": "operator_verified",
                "evidence": "Compact JSON includes location.",
                "proposed_change": "Store it.",
                "source_location": {"path": ".env", "start_line": 1},
            }
        ],
    }
    _metadata, findings, errors = parse_review_markdown(json.dumps(compact))
    assert errors == []
    assert findings[0]["source_path"] is None
    assert findings[0]["source_location_status"] == "rejected:forbidden_path_pattern"


def test_sarif_region_snippet_stable_fingerprint_and_ready_summary():
    finding = {
        "id": "finding_1",
        "review_id": "review_1",
        "severity": "high",
        "area": "API",
        "title": "Location is actionable",
        "evidence": "The code path is identified.",
        "proposed_change": "Patch the line.",
        "evidence_quality": "direct_access",
        "status": "accepted",
        "source_path": "apps/api/knownet_api/services/sarif_export.py",
        "source_start_line": 88,
        "source_end_line": 90,
        "source_snippet": "result = Result(...)",
        "source_location_status": "accepted",
    }
    log = build_sarif_log([finding], run_id="run_test", generated_at="2026-05-07T00:00:00Z")
    assert validate_sarif_log(log) == []
    result = log["runs"][0]["results"][0]
    region = result["locations"][0]["physicalLocation"]["region"]
    assert region["startLine"] == 88
    assert region["endLine"] == 90
    assert region["snippet"]["text"] == "result = Result(...)"
    assert result["properties"]["knownet"]["code_scanning_ready"] is True
    assert log["runs"][0]["properties"]["knownet"]["code_scanning_ready_summary"] == {
        "total_results": 1,
        "ready": 1,
        "not_ready_reasons": {},
    }
    first = content_fingerprint(finding, [{"path": finding["source_path"], "start_line": 88, "end_line": 90}])
    changed_status = dict(finding, status="implemented", updated_at="later")
    assert content_fingerprint(changed_status, [{"path": finding["source_path"], "start_line": 88, "end_line": 90}]) == first
    whitespace_title = dict(finding, title="  Location   is actionable  ")
    assert content_fingerprint(whitespace_title, [{"path": finding["source_path"], "start_line": 88, "end_line": 90}]) == first
    changed_evidence = dict(finding, evidence="Different evidence.")
    assert content_fingerprint(changed_evidence, [{"path": finding["source_path"], "start_line": 88, "end_line": 90}]) != first


def test_context_limited_finding_is_not_code_scanning_ready():
    readiness = code_scanning_readiness(
        {"evidence_quality": "context_limited"},
        [{"path": "apps/api/x.py", "start_line": 1, "end_line": 1}],
    )
    assert readiness["code_scanning_ready"] is False
    assert "untrusted_evidence_quality" in readiness["code_scanning_ready_reasons"]


def test_imported_review_persists_source_location_and_exports_region(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        review = """---
evidence_quality: direct_access
---
# Review

### Finding

Title: Stored source location
Severity: high
Area: API
Source path: apps/api/knownet_api/services/sarif_export.py
Source lines: 10-12

Evidence:
This has a source location.

Proposed change:
Emit a region.
"""
        imported = client.post("/api/collaboration/reviews", json={"markdown": review, "vault_id": "local-default"})
        assert imported.status_code == 200, imported.text
        finding = imported.json()["data"]["findings"][0]
        assert finding["source_location_status"] == "accepted"
        accepted = client.post(f"/api/collaboration/findings/{finding['id']}/decision", json={"status": "accepted", "decision_note": "Trusted"})
        assert accepted.status_code == 200, accepted.text
        detail = client.get(f"/api/collaboration/findings/{finding['id']}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["finding"]["source_start_line"] == 10

        sarif = client.get("/api/collaboration/findings.sarif")
        assert sarif.status_code == 200, sarif.text
        region = sarif.json()["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["region"]
        assert region["startLine"] == 10
        assert region["endLine"] == 12
    get_settings.cache_clear()
