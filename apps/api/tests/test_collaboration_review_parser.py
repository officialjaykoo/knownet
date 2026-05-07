import json

from knownet_api.routes.collaboration import parse_review_markdown
from fixture_utils import load_json_fixture_dir


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


def test_parser_extracts_multiple_findings():
    metadata, findings, errors = parse_review_markdown(_review_markdown())
    assert metadata["source_agent"] == "claude"
    assert metadata["evidence_quality"] == "unspecified"
    assert errors == []
    assert len(findings) == 2
    assert findings[0]["severity"] == "high"
    assert findings[0]["area"] == "Docs"
    assert findings[0]["title"] == "Durable review storage is required"
    assert findings[0]["evidence_quality"] == "unspecified"
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


def test_parser_accepts_bold_labels():
    markdown = """# Review

### Finding

**Title:** Bold label title
**Severity:** medium
**Area:** API

**Evidence:**
Bold labels should parse.

**Proposed change:**
Keep the fields.
"""
    _metadata, findings, errors = parse_review_markdown(markdown)
    assert errors == []
    assert findings[0]["title"] == "Bold label title"
    assert findings[0]["severity"] == "medium"
    assert findings[0]["area"] == "API"
    assert findings[0]["evidence"] == "Bold labels should parse."


def test_parser_extracts_evidence_quality_defaults_and_overrides():
    markdown = """---
type: agent_review
source_agent: claude
evidence_quality: context_limited
---

# Review

### Finding

Title: Uses review default
Severity: medium
Area: Docs

Evidence:
Review frontmatter should supply the default.

Proposed change:
Keep the review-level quality.

### Finding

Title: Finding override
Severity: low
Area: Ops
Evidence quality: operator_verified

Evidence:
Finding field should override the default.

Proposed change:
Store the finding-level quality.
"""
    metadata, findings, errors = parse_review_markdown(markdown)
    assert errors == []
    assert metadata["evidence_quality"] == "context_limited"
    assert findings[0]["evidence_quality"] == "context_limited"
    assert findings[1]["evidence_quality"] == "operator_verified"


def test_parser_accepts_import_recommendation_finding_blocks():
    markdown = """# Experiment Result

## Findings To Import

**Finding 1**
Title: Import recommendation should become a draft finding
Severity: medium
Area: Ops
Evidence quality: context_limited

Evidence:
Claude often emits import recommendations as bold Finding blocks rather than h3 headings.

Proposed change:
Parse bold Finding blocks with the same field contract as normal findings.
"""
    _metadata, findings, errors = parse_review_markdown(markdown)
    assert errors == []
    assert len(findings) == 1
    assert findings[0]["title"] == "Import recommendation should become a draft finding"
    assert findings[0]["area"] == "Ops"
    assert findings[0]["evidence_quality"] == "context_limited"


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


def test_compact_output_contract_parser_and_feedback():
    compact = {
        "output_mode": "top_findings",
        "findings": [
            {
                "title": "Compact parser should import finding",
                "severity": "medium",
                "area": "API",
                "evidence_quality": "direct_access",
                "evidence": "The response used the compact JSON contract.",
                "proposed_change": "Parse compact JSON findings before markdown fallback.",
            }
        ],
    }
    metadata, findings, errors = parse_review_markdown(json.dumps(compact))
    assert errors == []
    assert metadata["output_mode"] == "top_findings"
    assert findings[0]["title"] == "Compact parser should import finding"
    assert findings[0]["evidence_quality"] == "direct_access"

    noisy = {"output_mode": "decision_only", "findings": [{"title": "Should not import"}], "unsupported_sections": ["Long Summary"]}
    metadata, findings, errors = parse_review_markdown(json.dumps(noisy))
    assert findings == []
    assert "decision_only_does_not_accept_findings" in errors
    assert "unsupported_sections_present" in errors
    assert "ai_feedback_prompt" in metadata


def test_context_questions_output_mode_does_not_import_findings():
    payload = {
        "output_mode": "context_questions",
        "questions": [
            {
                "question": "Is this a fresh install?",
                "missing": ["fresh_install_confirmation"],
                "reason": "No pages are present.",
                "signal_code": "ai_state_quality.fail",
            }
        ],
    }
    metadata, findings, errors = parse_review_markdown(json.dumps(payload))
    assert errors == []
    assert findings == []
    assert metadata["output_mode"] == "context_questions"
    assert metadata["context_questions"][0]["question"] == "Is this a fresh install?"

    noisy = {"output_mode": "context_questions", "findings": [{"title": "Wrong"}]}
    metadata, findings, errors = parse_review_markdown(json.dumps(noisy))
    assert findings == []
    assert "context_questions_does_not_accept_findings" in errors
    assert "ai_feedback_prompt" in metadata


def test_output_mode_fixtures_assert_parser_behavior():
    fixtures = load_json_fixture_dir("provider_comparison")
    assert {fixture["name"] for fixture in fixtures} == {"decision_only", "implementation_candidates", "provider_risk_check", "top_findings_too_many"}
    for fixture in fixtures:
        payload = fixture["payload"]
        metadata, findings, errors = parse_review_markdown(json.dumps(payload))
        assert metadata["output_mode"] == payload["output_mode"]
        assert len(findings) == fixture["expected_finding_count"]
        for expected_error in fixture["expected_errors"]:
            assert expected_error in errors

