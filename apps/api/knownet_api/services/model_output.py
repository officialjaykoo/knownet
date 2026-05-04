from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException


SEVERITIES = {"critical", "high", "medium", "low", "info"}
AREAS = {"API", "UI", "Rust", "Security", "Data", "Ops", "Docs"}
LOCAL_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")


def _dedupe_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()


def normalize_model_output(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail={"code": "model_response_invalid", "message": "Model response must be a JSON object", "details": {}})
    findings_in = raw.get("findings")
    if not isinstance(findings_in, list):
        raise HTTPException(status_code=502, detail={"code": "model_response_invalid", "message": "Model response must include findings array", "details": {}})
    findings: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for index, finding in enumerate(findings_in[:50], start=1):
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "info").lower()
        if severity not in SEVERITIES:
            severity = "info"
        area_raw = str(finding.get("area") or "Docs").strip()
        area = next((candidate for candidate in AREAS if candidate.lower() == area_raw.lower()), "Docs")
        evidence = str(finding.get("evidence") or "").strip()
        proposed_change = str(finding.get("proposed_change") or finding.get("proposed change") or "").strip()
        if not evidence or not proposed_change:
            continue
        title = str(finding.get("title") or "").strip()
        if not title:
            title = evidence.splitlines()[0][:120] or f"Model finding {index}"
        title_key = _dedupe_key(title)
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        confidence = finding.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        findings.append(
            {
                "title": title[:220],
                "severity": severity,
                "area": area,
                "evidence": evidence[:4000],
                "proposed_change": proposed_change[:4000],
                "confidence": confidence_value,
            }
        )
    if not findings:
        raise HTTPException(status_code=502, detail={"code": "model_response_no_findings", "message": "Model response did not include any valid findings", "details": {}})
    return {
        "review_title": str(raw.get("review_title") or raw.get("title") or "Gemini model review")[:180],
        "overall_assessment": str(raw.get("overall_assessment") or raw.get("summary") or "").strip()[:4000],
        "findings": findings,
        "summary": str(raw.get("summary") or raw.get("overall_assessment") or "").strip()[:2000],
    }


def model_output_to_markdown(output: dict[str, Any], *, source_agent: str, source_model: str) -> str:
    lines = [
        "---",
        "type: agent_review",
        f"source_agent: {source_agent}",
        f"source_model: {source_model}",
        "evidence_quality: context_limited",
        "---",
        "",
        f"# {output['review_title']}",
        "",
    ]
    if output.get("overall_assessment"):
        lines.extend(["## Overall Assessment", "", str(output["overall_assessment"]).strip(), ""])
    for finding in output["findings"]:
        lines.extend(
            [
                "### Finding",
                "",
                f"Title: {finding['title']}",
                f"Severity: {finding['severity']}",
                f"Area: {finding['area']}",
                "",
                "Evidence:",
                finding["evidence"].strip(),
                "",
                "Proposed change:",
                finding["proposed_change"].strip(),
                "",
            ]
        )
    if output.get("summary"):
        lines.extend(["## Summary", "", str(output["summary"]).strip(), ""])
    return "\n".join(lines).strip() + "\n"


def strip_think_tags(text: str) -> str:
    return re.sub(r"(?is)<think>.*?</think>", "", text).strip()


def extract_json_object_text(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def sanitize_error_message(message: str | None) -> str | None:
    if not message:
        return None
    sanitized = LOCAL_PATH_RE.sub("[local-path]", message)
    sanitized = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", sanitized)
    return sanitized[:1000]
