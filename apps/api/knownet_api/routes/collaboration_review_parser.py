from __future__ import annotations

import json
import re
from typing import Any

from ..services.packet_contract import OUTPUT_MODES


SEVERITIES = {"critical", "high", "medium", "low", "info"}
AREAS = {"API": "API", "UI": "UI", "Rust": "Rust", "Security": "Security", "Data": "Data", "Ops": "Ops", "Docs": "Docs"}
AREA_NORMALIZE = {key.lower(): value for key, value in AREAS.items()}
EVIDENCE_QUALITIES = {"direct_access", "context_limited", "inferred", "operator_verified", "unspecified"}
MAX_FINDINGS_PER_REVIEW = 50

try:
    import frontmatter
except Exception:  # pragma: no cover - fallback is for minimally installed dev envs.
    frontmatter = None


def title_from_markdown(markdown: str, fallback: str = "Agent review") -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()[:180]
    return fallback


def parse_frontmatter(markdown: str) -> tuple[dict, str]:
    if frontmatter:
        post = frontmatter.loads(markdown)
        return dict(post.metadata), post.content
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end != -1:
            raw = markdown[4:end]
            meta: dict[str, str] = {}
            for line in raw.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip("\"'")
            return meta, markdown[end + 5 :]
    return {}, markdown


def field(block: str, name: str) -> str | None:
    pattern = re.compile(rf"^\s*(?:\*\*)?{re.escape(name)}\s*:\s*(?:\*\*)?\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(block)
    return match.group(1).strip() if match else None


def section(block: str, start: str, end: str | None = None) -> str | None:
    if end:
        pattern = rf"(?is)^\s*(?:\*\*)?{re.escape(start)}\s*:\s*(?:\*\*)?\s*\n(.*?)(?=^\s*(?:\*\*)?{re.escape(end)}\s*:\s*(?:\*\*)?\s*$|\Z)"
    else:
        pattern = rf"(?is)^\s*(?:\*\*)?{re.escape(start)}\s*:\s*(?:\*\*)?\s*\n(.*)\Z"
    match = re.search(pattern, block, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def normalize_area(value: str | None) -> str:
    if not value:
        return "Docs"
    return AREA_NORMALIZE.get(value.strip().lower(), "Docs")


def normalize_evidence_quality(value: str | None) -> str:
    if not value:
        return "unspecified"
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized if normalized in EVIDENCE_QUALITIES else "unspecified"


def finding_dedupe_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def extract_json_payload(text: str) -> dict | None:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    match = re.search(r"(?is)```json\s*(\{.*?\})\s*```", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_compact_review_json(data: dict, metadata: dict) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    output_mode = str(data.get("output_mode") or metadata.get("output_mode") or "top_findings").strip()
    if output_mode not in OUTPUT_MODES:
        errors.append(f"unsupported_output_mode:{output_mode}")
        output_mode = "top_findings"
    metadata["output_mode"] = output_mode
    findings_raw = data.get("findings") or data.get("implementation_candidates") or []
    if isinstance(findings_raw, dict):
        findings_raw = [findings_raw]
    if not isinstance(findings_raw, list):
        errors.append("compact_findings_not_list")
        findings_raw = []
    max_findings = int(OUTPUT_MODES[output_mode]["max_findings"])
    if output_mode == "decision_only" and findings_raw:
        errors.append("decision_only_does_not_accept_findings")
        findings_raw = []
    if len(findings_raw) > max_findings:
        errors.append(f"too_many_findings:{len(findings_raw)}>{max_findings}")
    findings: list[dict] = []
    for index, item in enumerate(findings_raw[:max_findings]):
        if not isinstance(item, dict):
            errors.append(f"compact_finding_not_object:{index + 1}")
            continue
        title = str(item.get("title") or item.get("candidate") or f"Finding {index + 1}").strip()[:220]
        evidence = item.get("evidence") or item.get("why") or item.get("reason")
        proposed_change = item.get("proposed_change") or item.get("implementation_shape") or item.get("change")
        if not evidence or not proposed_change:
            errors.append(f"compact_finding_missing_required_fields:{index + 1}")
        findings.append(
            {
                "severity": str(item.get("severity") or "info").lower() if str(item.get("severity") or "info").lower() in SEVERITIES else "info",
                "area": normalize_area(str(item.get("area") or "Docs")),
                "title": title,
                "evidence": str(evidence or "Compact response did not include evidence."),
                "proposed_change": str(proposed_change or "Ask the provider to resend this item with a concrete proposed_change."),
                "raw_text": None,
                "evidence_quality": normalize_evidence_quality(str(item.get("evidence_quality") or metadata.get("evidence_quality"))),
                "status": "pending",
            }
        )
    unsupported_sections = data.get("unsupported_sections") or data.get("extra_sections") or []
    if unsupported_sections:
        errors.append("unsupported_sections_present")
    if errors:
        metadata["ai_feedback_prompt"] = (
            "Revise the response to match the packet output contract. "
            f"Errors: {', '.join(errors)}. Return only supported compact findings."
        )
    return findings, errors


def review_dry_run_result(markdown: str) -> dict:
    metadata, findings, parser_errors = parse_review_markdown(markdown)
    feedback = metadata.get("ai_feedback_prompt")
    import_ready = bool(findings) and not parser_errors
    return {
        "metadata": metadata,
        "finding_count": len(findings),
        "findings": findings,
        "parser_errors": parser_errors,
        "truncated_findings": bool(metadata.get("truncated_findings")),
        "import_ready": import_ready,
        "rejection_reason": None if import_ready else "parser_errors" if parser_errors else "no_findings",
        "ai_feedback_prompt": feedback,
    }


def parse_review_markdown(markdown: str) -> tuple[dict, list[dict], list[str]]:
    metadata, body = parse_frontmatter(markdown)
    errors: list[str] = []
    metadata.setdefault("type", "agent_review")
    metadata.setdefault("status", "pending_review")
    metadata.setdefault("source_agent", "unknown")
    metadata["evidence_quality"] = normalize_evidence_quality(metadata.get("evidence_quality"))
    compact_json = extract_json_payload(body)
    if compact_json:
        findings, compact_errors = parse_compact_review_json(compact_json, metadata)
        return metadata, findings, compact_errors
    heading_matches = list(re.finditer(r"(?im)^(?:###\s+finding\b.*|\*\*Finding\b.*\*\*)\s*$", body))
    if not heading_matches:
        errors.append("no_finding_headings")
        return metadata, [
            {
                "severity": "info",
                "area": "Docs",
                "title": title_from_markdown(markdown, "Unparsed review"),
                "evidence": None,
                "proposed_change": None,
                "raw_text": body.strip() or markdown,
                "evidence_quality": metadata["evidence_quality"],
                "status": "needs_more_context",
            }
        ], errors
    findings: list[dict] = []
    if len(heading_matches) > MAX_FINDINGS_PER_REVIEW:
        metadata["truncated_findings"] = True
        errors.append("truncated_findings")
    for index, match in enumerate(heading_matches[:MAX_FINDINGS_PER_REVIEW]):
        next_start = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(body)
        block = body[match.start() : next_start].strip()
        title = match.group(0).replace("###", "", 1).strip().strip("*").strip() or f"Finding {index + 1}"
        severity = (field(block, "Severity") or "info").lower()
        if severity not in SEVERITIES:
            errors.append(f"unknown_severity:{severity}")
            severity = "info"
        evidence = section(block, "Evidence", "Proposed change")
        proposed_change = section(block, "Proposed change")
        status = "pending"
        raw_text = None
        if not evidence and not proposed_change:
            status = "needs_more_context"
            raw_text = block
            errors.append(f"malformed_finding:{index + 1}")
        findings.append(
            {
                "severity": severity,
                "area": normalize_area(field(block, "Area")),
                "title": (field(block, "Title") or title)[:220],
                "evidence": evidence,
                "proposed_change": proposed_change,
                "raw_text": raw_text,
                "evidence_quality": normalize_evidence_quality(field(block, "Evidence quality") or field(block, "Evidence Quality") or metadata.get("evidence_quality")),
                "status": status,
            }
        )
    return metadata, findings, errors
