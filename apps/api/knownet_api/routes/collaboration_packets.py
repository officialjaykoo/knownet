from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from ..db.sqlite import fetch_all, fetch_one
from ..services.packet_contract import PROFILE_SECTION_RULES
from ..services.project_snapshot import profile_char_budget


DEFAULT_EXPERIMENT_PACKET_SLUGS = [
    "claude-experiment-request-template",
    "access-fallback-protocol",
    "boundary-enforcement-protocol",
    "evidence-quality-registry",
    "findings-state-machine",
]

PACKET_SECTION_PRIORITY = {
    "access-fallback-protocol": {"fallback_order", "delivery_requirement", "trust_labels", "operator_actions"},
    "boundary-enforcement-protocol": {"violation_types", "response_policy", "observation_vs_assertion", "refusal_template"},
    "evidence-quality-registry": {"labels", "default_rules", "allowed_use_by_label", "release_use"},
    "findings-state-machine": {"states", "transition_rules", "evidence_quality_transition_rule", "ai_state_quality_rule"},
    "claude-experiment-request-template": {"request_shape", "split_request_rule", "parser_ready_finding", "pre_post_checks"},
}


def strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end != -1:
            return markdown[end + 5 :].lstrip()
    return markdown


def packet_excerpt(markdown: str, *, max_chars: int) -> str:
    text = strip_frontmatter(markdown).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit("\n", 1)[0].strip()
    return (cut or text[:max_chars].strip()) + "\n\n[truncated for packet]"


def packet_sections(markdown: str) -> list[dict[str, str]]:
    text = strip_frontmatter(markdown).strip()
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if not matches:
        return [{"heading": "body", "key": "body", "text": text}]
    sections = [{"heading": "intro", "key": "intro", "text": text[: matches[0].start()].strip()}]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(1).strip()
        key = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
        sections.append({"heading": heading, "key": key, "text": text[match.start() : end].strip()})
    return [section for section in sections if section["text"]]


def packet_excerpt_for_slug(slug: str, markdown: str, *, max_chars: int) -> str:
    priorities = PACKET_SECTION_PRIORITY.get(slug)
    if not priorities:
        return packet_excerpt(markdown, max_chars=max_chars)
    sections = packet_sections(markdown)
    selected = [section["text"] for section in sections if section["key"] in priorities]
    if not selected:
        return packet_excerpt(markdown, max_chars=max_chars)
    text = "\n\n".join(selected)
    if len(text) <= max_chars:
        return text
    return packet_excerpt(text, max_chars=max_chars)


def validate_packet_slugs(slugs: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", slug.strip().lower()).strip("-")
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


async def packet_preflight(sqlite_path: Path, vault_id: str) -> dict:
    rows = await fetch_one(
        sqlite_path,
        "SELECT "
        "(SELECT COUNT(*) FROM pages WHERE vault_id = ? AND status = 'active') AS pages, "
        "(SELECT COUNT(*) FROM ai_state_pages WHERE vault_id = ?) AS ai_state_pages, "
        "(SELECT COUNT(*) FROM graph_nodes WHERE vault_id = ? AND node_type = 'unresolved') AS unresolved_nodes, "
        "(SELECT COUNT(*) FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context')) AS pending_findings",
        (vault_id, vault_id, vault_id, vault_id),
    )
    return rows or {"pages": 0, "ai_state_pages": 0, "unresolved_nodes": 0, "pending_findings": 0}


async def project_snapshot_delta(sqlite_path: Path, vault_id: str, since: str | None) -> dict | None:
    if not since:
        return None
    try:
        datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "project_snapshot_invalid_since", "message": "since must be an ISO-8601 timestamp", "details": {"since": since}}) from error
    pages = await fetch_all(sqlite_path, "SELECT id, slug, title, status, updated_at FROM pages WHERE vault_id = ? AND updated_at > ? ORDER BY updated_at DESC LIMIT 25", (vault_id, since))
    findings = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.severity, f.area, f.title, f.status, f.evidence_quality, f.updated_at, r.source_agent "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.updated_at > ? ORDER BY f.updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    tasks = await fetch_all(
        sqlite_path,
        "SELECT t.id, t.finding_id, t.status, t.priority, t.updated_at, f.title "
        "FROM finding_tasks t JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND t.updated_at > ? ORDER BY t.updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    runs = await fetch_all(
        sqlite_path,
        "SELECT id, provider, model, status, response_json, trace_id, packet_trace_id, updated_at FROM model_review_runs WHERE vault_id = ? AND updated_at > ? ORDER BY updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    failed_runs = [row for row in runs if row.get("status") == "failed"]
    return {
        "since": since,
        "pages": pages,
        "findings": findings,
        "finding_tasks": tasks,
        "model_runs": runs,
        "summary": {
            "changed_nodes": len(pages),
            "new_or_updated_findings": len(findings),
            "changed_tasks": len(tasks),
            "model_runs": len(runs),
            "failed_runs": len(failed_runs),
        },
    }


async def resolve_snapshot_since(settings: Any, payload: Any, profile: str) -> tuple[str | None, dict | None, list[str]]:
    warnings: list[str] = []
    since = payload.since
    since_packet = None
    if payload.since_packet_id:
        since_packet = await fetch_one(settings.sqlite_path, "SELECT * FROM project_snapshot_packets WHERE id = ? AND vault_id = ?", (payload.since_packet_id, payload.vault_id))
        if not since_packet:
            if not payload.allow_since_packet_fallback:
                raise HTTPException(status_code=404, detail={"code": "project_snapshot_since_packet_not_found", "message": "since_packet_id was not found", "details": {"since_packet_id": payload.since_packet_id}})
            warnings.append("since_packet_missing_full_snapshot")
        else:
            since = since_packet["created_at"]
            if since_packet["profile"] != profile:
                warnings.append("profile_mismatch_delta")
    return since, since_packet, warnings


def snapshot_quality(*, content: str, profile: str, warnings: list[str], preflight: dict, accepted_rows: list[dict], task_rows: list[dict], duplicate_groups: list[dict], delta: dict | None, quality_acknowledged: bool) -> dict:
    quality_warnings = list(warnings)
    pending = int(preflight.get("pending_findings") or 0)
    if pending > 10:
        quality_warnings.append("too_many_pending_findings")
    if duplicate_groups:
        quality_warnings.append("duplicate_noise")
    evidence_values = [str(row.get("evidence_quality") or "unspecified") for row in [*accepted_rows, *task_rows]]
    if evidence_values:
        context_limited = sum(1 for value in evidence_values if value == "context_limited")
        if context_limited / max(1, len(evidence_values)) >= 0.6:
            quality_warnings.append("mostly_context_limited")
    else:
        context_limited = 0
    char_budget = profile_char_budget(profile)
    if len(content) > char_budget:
        quality_warnings.append("oversized_packet")
    if delta is not None and not any(delta[key] for key in ("pages", "findings", "finding_tasks", "model_runs")):
        quality_warnings.append("stale_delta")
    unique = []
    seen = set()
    for warning in quality_warnings:
        if warning not in seen:
            seen.add(warning)
            unique.append(warning)
    detail = {
        "pending_findings": pending,
        "duplicate_groups": len(duplicate_groups),
        "evidence_items": len(evidence_values),
        "context_limited_ratio": round(context_limited / max(1, len(evidence_values)), 2) if evidence_values else 0,
        "content_chars": len(content),
        "profile": profile,
        "profile_char_budget": char_budget,
        "delta_empty": bool(delta is not None and not any(delta[key] for key in ("pages", "findings", "finding_tasks", "model_runs"))),
    }
    warning_details = {
        "too_many_pending_findings": f"{pending} pending/needs-more-context findings",
        "duplicate_noise": f"{len(duplicate_groups)} duplicate finding title group(s)",
        "mostly_context_limited": f"{detail['context_limited_ratio']} context-limited evidence ratio",
        "oversized_packet": f"{len(content)} packet characters exceeds {char_budget} char budget for {profile}",
        "stale_delta": "No changed pages, findings, tasks, or model runs in the requested delta",
    }
    return {
        "score": max(0, 100 - len(unique) * 12 - min(20, len(content) // 6000)),
        "warnings": unique,
        "details": detail,
        "warning_details": {warning: warning_details.get(warning, warning) for warning in unique},
        "advisory_only": True,
        "acknowledgement_required_for_ui_send": bool(unique),
        "acknowledged": quality_acknowledged,
    }


def profile_allows(profile: str, section: str) -> bool:
    rules = PROFILE_SECTION_RULES.get(profile, PROFILE_SECTION_RULES["overview"])
    return section in rules["include"]


async def packet_row(sqlite_path: Path, packet_id: str) -> dict:
    packet = await fetch_one(sqlite_path, "SELECT * FROM experiment_packets WHERE id = ?", (packet_id,))
    if not packet:
        raise HTTPException(status_code=404, detail={"code": "experiment_packet_not_found", "message": "Experiment packet not found", "details": {"packet_id": packet_id}})
    return packet


def packet_warning_list(health: dict | None, quality: dict, preflight: dict, high_open_findings: int) -> list[str]:
    warnings: list[str] = []
    if health and health.get("overall_status") not in {"healthy", "ok"}:
        warnings.append(f"health_{health.get('overall_status')}")
    if quality.get("overall_status") == "fail":
        warnings.append("ai_state_quality_fail")
    elif quality.get("overall_status") == "warn":
        warnings.append("ai_state_quality_warn")
    if int(preflight.get("pending_findings") or 0) > 10:
        warnings.append("many_pending_findings")
    if high_open_findings:
        warnings.append("high_severity_open_findings")
    return warnings


def json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def resource_links(*, self_href: str, content_href: str | None = None, storage_href: str | None = None, related: list[dict] | None = None) -> dict:
    links: dict = {"self": {"href": self_href}}
    if content_href:
        links["content"] = {"href": content_href}
    if storage_href:
        links["storage"] = {"href": storage_href}
    if related:
        links["related"] = related
    return links


def standard_delta(delta: dict | None) -> dict | None:
    if not delta:
        return None
    return {
        "since": delta.get("since"),
        "summary": delta.get("summary", {}),
        "added": {
            "findings": [row for row in delta.get("findings", []) if str(row.get("status") or "") in {"pending", "needs_more_context", "accepted"}],
            "finding_tasks": [row for row in delta.get("finding_tasks", []) if str(row.get("status") or "") in {"open", "todo", "pending"}],
            "model_runs": delta.get("model_runs", []),
        },
        "changed": {
            "nodes": delta.get("pages", []),
            "findings": delta.get("findings", []),
            "finding_tasks": delta.get("finding_tasks", []),
            "model_runs": delta.get("model_runs", []),
        },
        "removed": {
            "nodes": [row for row in delta.get("pages", []) if row.get("status") in {"archived", "deleted"}],
            "findings": [row for row in delta.get("findings", []) if row.get("status") in {"rejected", "deleted"}],
            "finding_tasks": [row for row in delta.get("finding_tasks", []) if row.get("status") in {"cancelled", "deleted"}],
            "model_runs": [],
        },
    }
