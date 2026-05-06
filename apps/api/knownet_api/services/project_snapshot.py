from __future__ import annotations

from pathlib import Path
from typing import Any

from ..db.sqlite import fetch_all
from .packet_contract import PROFILE_CHAR_BUDGETS, PROFILE_HARD_LIMITS
from .provenance import compact_provenance, validate_provenance_safe


DEFAULT_PROJECT_SNAPSHOT_FOCUS = (
    "Review current KnowNet state and suggest the next highest-leverage action."
)

PROFILE_DEFAULT_FOCUS = {
    "overview": "Summarize the current KnowNet state and return only the highest-leverage next action.",
    "stability": "Identify the top 3 stability risks only. Focus on provider failures, health, backlog, and fallback behavior.",
    "performance": "Identify the top 3 speed risks only. Focus on provider latency, search fallback, model-run duration, and graph/index freshness.",
    "security": "Identify the top 3 security risks only. Focus on access boundaries, public mode, evidence quality, auth, and secret exposure.",
    "implementation": "Select exactly one next implementation candidate for Codex, with expected verification.",
    "provider_review": "Review provider runner health, request shapes, failures, and timeout/security risks only.",
}

COMMON_DO_NOT_SUGGEST = [
    "Do not recommend full release_check for daily packet work.",
    "Do not request raw SQLite, backup archives, .env files, filesystem paths, shell access, sessions, users, or tokens.",
    "Do not repeat already represented finding titles unless the proposed change is materially different.",
    "Do not turn context_limited findings into release blockers without operator verification.",
]

PROFILE_DO_NOT_SUGGEST = {
    "stability": ["Do not discuss broad UI redesign unless it directly affects service stability."],
    "performance": ["Do not propose provider benchmark work without a measurable latency signal."],
    "security": ["Do not ask for secrets to verify whether secret handling is safe."],
    "implementation": ["Do not propose more than one implementation candidate.", "Do not create work from low-confidence context_limited advice."],
    "provider_review": ["Do not review unrelated application pages or task UI details."],
}


def project_snapshot_focus(profile: str, target_agent: str, focus: str) -> str:
    normalized = (focus or "").strip()
    if normalized and normalized != DEFAULT_PROJECT_SNAPSHOT_FOCUS:
        return normalized
    base = PROFILE_DEFAULT_FOCUS.get(profile, PROFILE_DEFAULT_FOCUS["overview"])
    if target_agent.lower() in {"gemini", "deepseek", "qwen", "kimi", "glm", "minimax"}:
        return f"{base} Keep the response short and import-ready."
    return base


def target_agent_policy(target_agent: str) -> dict[str, Any]:
    normalized = target_agent.strip().lower()
    if normalized in {"gemini", "deepseek", "qwen", "kimi", "glm", "minimax"}:
        return {"max_recent_tasks": 5, "max_recent_runs": 4, "max_important_changes": 6, "compact": True}
    if normalized == "codex":
        return {"max_recent_tasks": 12, "max_recent_runs": 6, "max_important_changes": 10, "compact": False}
    return {"max_recent_tasks": 8, "max_recent_runs": 5, "max_important_changes": 8, "compact": False}


def profile_hard_limits(profile: str) -> dict[str, Any]:
    return PROFILE_HARD_LIMITS.get(profile, PROFILE_HARD_LIMITS["overview"])


def profile_char_budget(profile: str) -> int:
    return PROFILE_CHAR_BUDGETS.get(profile, PROFILE_CHAR_BUDGETS["overview"])


def do_not_suggest_rules(profile: str) -> list[str]:
    rules = list(COMMON_DO_NOT_SUGGEST)
    rules.extend(PROFILE_DO_NOT_SUGGEST.get(profile, []))
    return rules


def detail_url(kind: str, item_id: str | None) -> str | None:
    if not item_id:
        return None
    if kind == "finding":
        return f"/api/collaboration/findings/{item_id}"
    if kind == "finding_task":
        return f"/api/collaboration/finding-tasks/{item_id}"
    if kind == "model_run":
        return f"/api/model-runs/{item_id}"
    if kind == "page":
        return f"/api/pages/{item_id}"
    return None


def finding_summary(row: dict[str, Any]) -> dict[str, Any]:
    finding_id = row.get("id") or row.get("finding_id")
    provenance = compact_provenance(
        source_type="finding",
        source_id=finding_id,
        source_finding_id=finding_id,
        evidence_quality=row.get("evidence_quality"),
        updated_at=row.get("updated_at"),
    )
    return {
        "id": finding_id,
        "title": row.get("title"),
        "severity": row.get("severity"),
        "area": row.get("area"),
        "status": row.get("status") or row.get("finding_status"),
        "evidence_quality": row.get("evidence_quality"),
        "source_agent": row.get("source_agent"),
        "action_route": row.get("action_route") or action_route(row),
        "detail_url": detail_url("finding", finding_id),
        "provenance": provenance,
    }


def task_summary(row: dict[str, Any]) -> dict[str, Any]:
    task_id = row.get("id") or row.get("task_id")
    provenance = compact_provenance(
        source_type="finding_task",
        source_id=task_id,
        source_finding_id=row.get("finding_id"),
        evidence_quality=row.get("evidence_quality"),
        updated_at=row.get("updated_at"),
    )
    return {
        "id": task_id,
        "finding_id": row.get("finding_id"),
        "title": row.get("title"),
        "status": row.get("status") or row.get("task_status"),
        "priority": row.get("priority") or row.get("task_priority"),
        "owner": row.get("owner") or row.get("task_owner"),
        "evidence_quality": row.get("evidence_quality"),
        "action_route": row.get("action_route") or action_route(row),
        "detail_url": detail_url("finding_task", task_id),
        "provenance": provenance,
    }


def model_run_summary(row: dict[str, Any]) -> dict[str, Any]:
    run_id = row.get("id")
    request_json = row.get("request") if isinstance(row.get("request"), dict) else {}
    response_json = row.get("response") if isinstance(row.get("response"), dict) else {}
    if not request_json and isinstance(row.get("request_json"), str):
        request_json = _json_loads(row.get("request_json"), {})
    if not response_json and isinstance(row.get("response_json"), str):
        response_json = _json_loads(row.get("response_json"), {})
    duration_ms = response_json.get("duration_ms") if isinstance(response_json, dict) else None
    evidence_quality = "context_limited" if request_json.get("mock") else "direct_access"
    provenance = compact_provenance(
        source_type="model_run",
        source_id=run_id,
        source_packet_trace_id=row.get("packet_trace_id"),
        source_model_run_id=run_id,
        source_model_run_trace_id=row.get("trace_id"),
        evidence_quality=evidence_quality,
        updated_at=row.get("updated_at"),
    )
    return {
        "id": run_id,
        "provider": row.get("provider"),
        "model": row.get("model"),
        "status": row.get("status"),
        "prompt_profile": row.get("prompt_profile"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "trace_id": row.get("trace_id"),
        "packet_trace_id": row.get("packet_trace_id"),
        "duration_ms": duration_ms,
        "error_code": row.get("error_code"),
        "error_message": row.get("error_message"),
        "evidence_quality": evidence_quality,
        "updated_at": row.get("updated_at"),
        "detail_url": detail_url("model_run", run_id),
        "provenance": provenance,
    }


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        import json

        return json.loads(value)
    except Exception:
        return fallback


def packet_summary(
    *,
    accepted_rows: list[dict[str, Any]],
    task_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    important: dict[str, Any],
) -> dict[str, Any]:
    return {
        "accepted_findings": [finding_summary(row) for row in accepted_rows],
        "finding_tasks": [task_summary(row) for row in task_rows],
        "model_runs": [model_run_summary(row) for row in run_rows],
        "important_findings": [finding_summary(row) for row in important.get("high_severity_findings", [])],
        "important_tasks": [task_summary(row) for row in important.get("actionable_tasks", [])],
        "failed_model_runs": [model_run_summary(row) for row in important.get("failed_model_runs", [])],
    }


def packet_issues(*, warnings: list[str], health: dict | None, quality: dict, preflight: dict, high_open_findings: int, provider_matrix: dict) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def param_schema(params: dict[str, Any]) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, bool):
                value_type = "boolean"
            elif isinstance(value, int) and not isinstance(value, bool):
                value_type = "integer"
            elif isinstance(value, float):
                value_type = "number"
            elif isinstance(value, list):
                value_type = "array"
            elif isinstance(value, dict):
                value_type = "object"
            elif value is None:
                value_type = "null"
            else:
                value_type = "string"
            properties[key] = {"type": value_type}
        return {
            "type": "object",
            "properties": properties,
            "required": sorted(properties),
            "additionalProperties": False,
        }

    def add(code: str, action_template: str, action_params: dict[str, Any] | None = None, severity: str = "medium") -> None:
        params = action_params or {}
        issues.append(
            {
                "code": code,
                "severity": severity,
                "action_template": action_template,
                "action_params": params,
                "action_input_schema": param_schema(params),
            }
        )

    if health and health.get("overall_status") not in {"ok", "expected_degraded"}:
        add("health.degraded", "inspect_health_issue", {"status": health.get("overall_status")})
    if quality.get("overall_status") == "warn":
        add("ai_state_quality.warn", "triage_ai_state_warnings", {"summary": quality.get("summary", {})}, "low")
    if quality.get("overall_status") == "fail":
        add("ai_state_quality.fail", "triage_ai_state_failures", {"summary": quality.get("summary", {})}, "high")
    if int(preflight.get("pending_findings") or 0) > 10:
        add("findings.too_many_pending", "compress_review_queue", {"pending_findings": preflight.get("pending_findings")})
    if high_open_findings:
        add("findings.high_severity_open", "verify_or_route_high_severity_findings", {"count": high_open_findings}, "high")
    failed_providers = (provider_matrix or {}).get("failed") or 0
    if failed_providers:
        add("provider_matrix.failed", "inspect_failed_provider_runs", {"failed": failed_providers})
    for warning in warnings:
        if warning == "oversized_packet":
            add("packet.oversized", "switch_to_narrower_profile_or_acknowledge", {}, "low")
        elif warning == "profile_mismatch_delta":
            add("packet.profile_mismatch_delta", "regenerate_full_packet_or_acknowledge_delta", {}, "low")
        elif warning == "stale_delta":
            add("packet.stale_delta", "request_full_snapshot_if_context_missing", {}, "low")
    seen: set[str] = set()
    unique = []
    for issue in issues:
        if issue["code"] not in seen:
            seen.add(issue["code"])
            unique.append(issue)
    return unique


def ai_context(*, profile: str, target_agent: str, focus: str, output_mode: str) -> dict[str, Any]:
    return {
        "role": f"{profile}_reviewer",
        "target_agent": target_agent,
        "task": focus,
        "output_mode": output_mode,
        "read_order": ["ai_context", "next_action_hints", "issues", "packet_summary", "contract"],
        "style": "Keep the answer short, evidence-tagged, and import-ready.",
    }


def next_action_hints(important: dict[str, Any], issues: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    hints: list[str] = []
    for issue in issues[:2]:
        hints.append(f"{issue['code']}: use {issue['action_template']}")
    for row in important.get("high_severity_findings", [])[:limit]:
        hints.append(f"{row.get('id')}: {row.get('title')} -> {row.get('action_route') or action_route(row)}")
    for row in important.get("actionable_tasks", [])[: max(0, limit - len(hints))]:
        hints.append(f"{row.get('id')}: implement task for {row.get('finding_id')}")
    return hints[:limit]


def node_card(row: dict[str, Any], *, short_summary: str | None = None) -> dict[str, Any]:
    source_id = row.get("id") or row.get("page_id")
    provenance = compact_provenance(
        source_type="node_card",
        source_id=source_id,
        evidence_quality=row.get("evidence_quality"),
        updated_at=row.get("updated_at"),
    )
    errors = validate_provenance_safe(provenance)
    return {
        "id": row.get("id") or row.get("page_id"),
        "title": row.get("title"),
        "type": row.get("system_kind") or "page",
        "slug": row.get("slug"),
        "short_summary": (short_summary or row.get("short_summary") or "").strip()[:280],
        "content_hash": row.get("content_hash"),
        "link": f"/pages/{row.get('slug')}" if row.get("slug") else None,
        "detail_url": detail_url("page", row.get("slug")),
        "provenance": provenance,
        "provenance_warnings": errors,
    }


def source_manifest(node_cards: list[dict[str, Any]], *, generated_at: str) -> dict[str, Any]:
    sources = []
    for card in node_cards:
        sources.append(
            {
                "id": card.get("id"),
                "type": card.get("type") or "page",
                "slug": card.get("slug"),
                "title": card.get("title"),
                "content_hash": card.get("content_hash"),
                "updated_at": (card.get("provenance") or {}).get("updated_at"),
                "links": {"detail": {"href": card.get("detail_url")}},
            }
        )
    return {"id": f"manifest:{generated_at}", "type": "source_manifest", "generated_at": generated_at, "sources": sources}


def action_route(row: dict[str, Any]) -> str:
    evidence_quality = row.get("evidence_quality")
    severity = row.get("severity")
    status = row.get("status")
    if status in {"implemented", "rejected"}:
        return "ignore"
    if evidence_quality in {"direct_access", "operator_verified"} and severity in {"critical", "high"}:
        return "implement"
    if evidence_quality == "context_limited":
        return "verify"
    if status in {"needs_more_context", "deferred"}:
        return "ask_operator"
    return "verify"


async def do_not_reopen(sqlite_path: Path, *, vault_id: str, limit: int = 12) -> dict[str, Any]:
    implemented = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.title, f.severity, f.area, f.evidence_quality, f.updated_at "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status = 'implemented' ORDER BY f.updated_at DESC LIMIT ?",
        (vault_id, limit),
    )
    resolved = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.title, f.status, f.decision_note, f.updated_at "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status IN ('rejected','deferred') ORDER BY f.updated_at DESC LIMIT ?",
        (vault_id, limit),
    )
    return {"implemented_findings": implemented, "resolved_or_deferred_findings": resolved, "summary": {"implemented": len(implemented), "resolved_or_deferred": len(resolved)}}


def snapshot_diff_summary(important: dict[str, Any], delta: dict[str, Any] | None) -> list[str]:
    summary: list[str] = []
    if delta:
        counts = {key: len(delta.get(key) or []) for key in ("pages", "findings", "finding_tasks", "model_runs")}
        changed = ", ".join(f"{key}={value}" for key, value in counts.items() if value)
        summary.append(f"Delta contains {changed or 'no changed state'} since {delta['since']}.")
    important_summary = important.get("summary") or {}
    if important_summary.get("failed_model_runs"):
        summary.append(f"{important_summary['failed_model_runs']} failed model run(s) need provider review.")
    if important_summary.get("high_severity_findings"):
        summary.append(f"{important_summary['high_severity_findings']} high-severity open finding(s) need verification or implementation routing.")
    if important_summary.get("actionable_tasks"):
        summary.append(f"{important_summary['actionable_tasks']} open/in-progress task(s) are available for Codex.")
    if important_summary.get("implementation_evidence"):
        summary.append(f"{important_summary['implementation_evidence']} implementation evidence record(s) were added recently.")
    return summary or ["No high-signal changes were detected for this profile."]


def snapshot_self_test(*, content: str, contract: dict[str, Any], profile: str, required_sections: list[str]) -> dict[str, Any]:
    checks = []

    def add(code: str, passed: bool, detail: str) -> None:
        checks.append({"code": code, "status": "pass" if passed else "fail", "detail": detail})

    add("contract_version_present", "contract_version" in content and bool(contract.get("packet_metadata", {}).get("contract_version")), "Packet includes contract_version.")
    add("output_contract_present", "output_contract" in str(contract) and "## Packet Contract" in content, "Packet includes output contract.")
    add("profile_present", f"profile: {profile}" in content, "Packet metadata includes profile.")
    add("secret_markers_absent", all(marker not in content for marker in ("API_KEY=", "ADMIN_TOKEN=", "knownet.db")), "Packet omits obvious secret/raw DB markers.")
    budget = profile_char_budget(profile)
    add("profile_budget_recorded", True, f"Packet has {len(content)} characters; profile budget is {budget}. Oversize is handled by snapshot_quality warnings.")
    boundaries = contract.get("role_and_access_boundaries")
    add(
        "structured_role_boundaries_present",
        isinstance(boundaries, dict)
        and all(isinstance(boundaries.get(key), list) and boundaries.get(key) for key in ("allowed", "refused", "escalate_on"))
        and isinstance(boundaries.get("narrative"), list)
        and 0 < len(boundaries.get("narrative", [])) <= 3,
        "Packet includes structured allowed/refused/escalate_on boundaries and generated narrative.",
    )
    stale = contract.get("stale_context_suppression")
    stale_valid = False
    if isinstance(stale, dict) and stale.get("active") is False and set(stale.keys()) == {"active"}:
        stale_valid = True
    if isinstance(stale, dict) and stale.get("active") is True and stale.get("suppressed_before") and stale.get("reason"):
        stale_valid = True
    add("stale_context_suppression_explicit", stale_valid, "Packet uses one explicit stale_context_suppression state.")
    for section in required_sections:
        add(f"section_present:{section}", section in content, f"Required section {section} is present.")
    return {"overall_status": "pass" if all(check["status"] == "pass" for check in checks) else "fail", "checks": checks}


async def important_changes(sqlite_path: Path, *, vault_id: str, since: str | None, limit: int) -> dict[str, Any]:
    finding_filter = "AND f.updated_at > ?" if since else ""
    finding_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    findings = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.severity, f.area, f.title, f.status, f.evidence_quality, f.updated_at, r.source_agent "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        f"WHERE r.vault_id = ? AND f.severity IN ('critical','high') AND f.status IN ('pending','needs_more_context','accepted','deferred') {finding_filter} "
        "ORDER BY f.updated_at DESC LIMIT ?",
        finding_params,
    )

    task_filter = "AND t.updated_at > ?" if since else ""
    task_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    findings = [{**row, "action_route": action_route(row)} for row in findings]

    tasks = await fetch_all(
        sqlite_path,
        "SELECT t.id, t.finding_id, t.status, t.priority, t.updated_at, f.title, f.severity, f.evidence_quality "
        "FROM finding_tasks t JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        f"WHERE r.vault_id = ? AND t.status IN ('open','in_progress','blocked') {task_filter} "
        "ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.updated_at DESC LIMIT ?",
        task_params,
    )

    run_filter = "AND updated_at > ?" if since else ""
    run_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    failed_runs = await fetch_all(
        sqlite_path,
        f"SELECT id, provider, model, status, error_code, error_message, trace_id, packet_trace_id, updated_at FROM model_review_runs WHERE vault_id = ? AND status = 'failed' {run_filter} ORDER BY updated_at DESC LIMIT ?",
        run_params,
    )

    evidence_filter = "AND i.created_at > ?" if since else ""
    evidence_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    implementation_evidence = await fetch_all(
        sqlite_path,
        "SELECT i.id, i.finding_id, i.commit_sha, i.changed_files, i.verification, i.created_at, f.title "
        "FROM implementation_records i LEFT JOIN collaboration_findings f ON f.id = i.finding_id "
        "LEFT JOIN collaboration_reviews r ON r.id = f.review_id "
        f"WHERE COALESCE(r.vault_id, ?) = ? {evidence_filter} ORDER BY i.created_at DESC LIMIT ?",
        (vault_id, *evidence_params),
    )

    tasks = [{**row, "action_route": action_route(row)} for row in tasks]

    return {
        "since": since,
        "high_severity_findings": findings,
        "actionable_tasks": tasks,
        "failed_model_runs": failed_runs,
        "implementation_evidence": implementation_evidence,
        "summary": {
            "high_severity_findings": len(findings),
            "actionable_tasks": len(tasks),
            "failed_model_runs": len(failed_runs),
            "implementation_evidence": len(implementation_evidence),
        },
    }
