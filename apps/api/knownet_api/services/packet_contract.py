from __future__ import annotations

from typing import Any


PACKET_CONTRACT_VERSION = "p20.v1"

PACKET_CONTRACT_SECTIONS = [
    "packet_metadata",
    "role_and_access_boundaries",
    "operator_question",
    "relevant_state",
    "hard_limits",
    "stale_context_suppression",
    "output_contract",
    "import_contract",
    "task_template_contract",
]

SNAPSHOT_PROFILES = {
    "overview",
    "stability",
    "performance",
    "security",
    "implementation",
    "provider_review",
}

OUTPUT_MODES: dict[str, dict[str, Any]] = {
    "top_findings": {
        "max_findings": 5,
        "description": "Return import-ready Finding blocks only.",
        "forbidden_sections": ["long narrative review", "release decision", "raw access request"],
    },
    "decision_only": {
        "max_findings": 0,
        "description": "Return allow/refuse/escalate with a short reason.",
        "forbidden_sections": ["importable findings", "implementation plan", "long narrative review"],
    },
    "implementation_candidates": {
        "max_findings": 1,
        "description": "Return one implementation candidate with expected files, verification hint, and confidence.",
        "forbidden_sections": ["multiple candidates", "release blocker claim", "raw code access request"],
    },
    "provider_risk_check": {
        "max_findings": 3,
        "description": "Return provider stability, speed, or security risks only.",
        "forbidden_sections": ["unrelated UI advice", "broad project review", "raw provider token request"],
    },
}


PROFILE_SECTION_RULES: dict[str, dict[str, list[str]]] = {
    "overview": {
        "include": ["current_state", "accepted_findings", "finding_tasks", "model_runs"],
        "exclude": ["raw page bodies", "raw DB paths", "secrets", "backup contents"],
    },
    "stability": {
        "include": ["current_state", "stability_risks", "model_runs"],
        "exclude": ["broad UI state", "long docs history", "low-severity implemented findings"],
    },
    "performance": {
        "include": ["current_state", "performance_signals", "model_runs"],
        "exclude": ["security narrative", "unrelated accepted findings", "full review bodies"],
    },
    "security": {
        "include": ["current_state", "security_signals"],
        "exclude": ["provider benchmarking detail", "performance-only findings", "raw tokens"],
    },
    "implementation": {
        "include": ["implementation_work", "finding_tasks"],
        "exclude": ["pending low-confidence advice", "broad provider matrix detail", "release speculation"],
    },
    "provider_review": {
        "include": ["provider_summary", "model_runs"],
        "exclude": ["unrelated page narrative", "implementation task details", "backup restore detail"],
    },
}

PROFILE_HARD_LIMITS: dict[str, dict[str, Any]] = {
    "overview": {"max_findings": 3, "max_important_changes": 8, "max_recent_tasks": 8, "max_recent_runs": 5},
    "stability": {"max_findings": 3, "max_important_changes": 8, "max_recent_tasks": 4, "max_recent_runs": 6},
    "performance": {"max_findings": 3, "max_important_changes": 8, "max_recent_tasks": 4, "max_recent_runs": 6},
    "security": {"max_findings": 3, "max_important_changes": 8, "max_recent_tasks": 5, "max_recent_runs": 4},
    "implementation": {"max_findings": 1, "max_important_changes": 10, "max_recent_tasks": 10, "max_recent_runs": 4},
    "provider_review": {"max_findings": 3, "max_important_changes": 6, "max_recent_tasks": 3, "max_recent_runs": 5},
}

PROFILE_CHAR_BUDGETS: dict[str, int] = {
    "overview": 12000,
    "stability": 8000,
    "performance": 8000,
    "security": 8000,
    "implementation": 10000,
    "provider_review": 6000,
}

ROLE_AND_ACCESS_BOUNDARIES: dict[str, list[str]] = {
    "allowed": ["read_packet_state", "write_findings_draft", "propose_tasks"],
    "refused": ["admin_token", "raw_db", "shell", "secrets", "backup", "session", "snapshot_delete"],
    "escalate_on": ["system_state_assertion", "unverified_live_claim", "role_boundary_ambiguity"],
}


def role_boundary_narrative(boundaries: dict[str, list[str]] | None = None) -> list[str]:
    source = boundaries or ROLE_AND_ACCESS_BOUNDARIES
    return [
        f"Allowed: {', '.join(source.get('allowed') or [])}.",
        f"Refused: {', '.join(source.get('refused') or [])}.",
        f"Escalate on: {', '.join(source.get('escalate_on') or [])}.",
    ]


def explicit_stale_context_suppression(*, suppressed_before: str | None = None, reason: str | None = None) -> dict[str, Any]:
    if suppressed_before:
        return {
            "active": True,
            "suppressed_before": suppressed_before,
            "reason": reason or "delta packet; prior state excluded",
        }
    return {"active": False}


def contract_shape(contract: dict[str, Any]) -> dict[str, Any]:
    sections = [key for key in PACKET_CONTRACT_SECTIONS if key in contract]
    missing = [key for key in PACKET_CONTRACT_SECTIONS if key not in contract]
    extra = sorted(key for key in contract if key not in PACKET_CONTRACT_SECTIONS and key not in {"profile_hard_limits", "target_agent_overrides"})
    return {
        "contract_version": contract.get("packet_metadata", {}).get("contract_version"),
        "sections": sections,
        "missing_sections": missing,
        "extra_sections": extra,
        "valid": not missing and not extra,
    }


def validate_packet_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    shape = contract_shape(contract)
    if shape["contract_version"] != PACKET_CONTRACT_VERSION:
        errors.append(f"unsupported_contract_version:{shape['contract_version']}")
    for section in shape["missing_sections"]:
        errors.append(f"missing_contract_section:{section}")
    for section in shape["extra_sections"]:
        errors.append(f"unsupported_contract_section:{section}")
    boundaries = contract.get("role_and_access_boundaries")
    if not isinstance(boundaries, dict):
        errors.append("role_boundaries_not_structured")
    else:
        for key in ("allowed", "refused", "escalate_on"):
            if not isinstance(boundaries.get(key), list) or not boundaries.get(key):
                errors.append(f"role_boundaries_missing:{key}")
        narrative = boundaries.get("narrative")
        if not isinstance(narrative, list) or not narrative or len(narrative) > 3:
            errors.append("role_boundaries_narrative_invalid")
    stale = contract.get("stale_context_suppression")
    if not isinstance(stale, dict):
        errors.append("stale_context_suppression_missing")
    elif stale.get("active") is False:
        if set(stale.keys()) != {"active"}:
            errors.append("stale_context_suppression_false_has_extra_fields")
    elif stale.get("active") is True:
        if not stale.get("suppressed_before") or not stale.get("reason"):
            errors.append("stale_context_suppression_true_missing_fields")
    else:
        errors.append("stale_context_suppression_invalid_active")
    return errors


def output_contract(output_mode: str, *, mostly_context_limited: bool = False) -> dict[str, Any]:
    mode = OUTPUT_MODES.get(output_mode, OUTPUT_MODES["top_findings"])
    return {
        "output_mode": output_mode if output_mode in OUTPUT_MODES else "top_findings",
        "max_findings": mode["max_findings"],
        "description": mode["description"],
        "forbidden_sections": mode["forbidden_sections"],
        "version_mismatch_rule": "If contract_version is unsupported, escalate instead of guessing.",
        "context_limited_release_rule": (
            "This packet is mostly context_limited. Findings may flag review work, but must not become release blockers without operator verification."
            if mostly_context_limited
            else "context_limited findings may flag review work, but must not become release blockers without operator verification."
        ),
    }


def build_packet_contract(
    *,
    packet_kind: str,
    target_agent: str,
    operator_question: str,
    output_mode: str = "top_findings",
    profile: str = "overview",
    mostly_context_limited: bool = False,
    stale_context_suppression: dict[str, Any] | None = None,
    target_agent_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_limits = PROFILE_HARD_LIMITS.get(profile, PROFILE_HARD_LIMITS["overview"])
    effective_limits = dict(profile_limits)
    if target_agent_overrides:
        for key in ("max_recent_tasks", "max_recent_runs", "max_important_changes"):
            if key in target_agent_overrides:
                effective_limits[key] = min(int(effective_limits.get(key, target_agent_overrides[key])), int(target_agent_overrides[key]))
    effective_limits["char_budget"] = PROFILE_CHAR_BUDGETS.get(profile, PROFILE_CHAR_BUDGETS["overview"])
    boundaries = {key: list(value) for key, value in ROLE_AND_ACCESS_BOUNDARIES.items()}
    return {
        "packet_metadata": {
            "contract_version": PACKET_CONTRACT_VERSION,
            "packet_kind": packet_kind,
            "target_agent": target_agent,
            "profile": profile,
        },
        "role_and_access_boundaries": {**boundaries, "narrative": role_boundary_narrative(boundaries)},
        "operator_question": operator_question,
        "relevant_state": {"profile": profile, "section_rules": PROFILE_SECTION_RULES.get(profile, PROFILE_SECTION_RULES["overview"])},
        "hard_limits": effective_limits,
        "profile_hard_limits": profile_limits,
        "target_agent_overrides": target_agent_overrides or {},
        "stale_context_suppression": stale_context_suppression or explicit_stale_context_suppression(),
        "output_contract": output_contract(output_mode, mostly_context_limited=mostly_context_limited),
        "import_contract": {
            "dry_run_first": True,
            "required_fields": ["title", "severity", "area", "evidence_quality", "evidence", "proposed_change"],
            "allowed_evidence_quality": ["direct_access", "context_limited", "inferred", "operator_verified"],
            "auto_import_requires": ["operator_verified"],
            "auto_task_requires": {"severity": ["critical", "high"], "evidence_quality": ["direct_access", "operator_verified"]},
            "unsupported_sections": "reject_with_ai_feedback_prompt",
            "partial_match_behavior": "warn",
        },
        "task_template_contract": {
            "task_template_is_advisory": True,
            "operator_import_required": True,
            "implementation_evidence_endpoint": "/api/collaboration/findings/{finding_id}/evidence",
        },
    }


def packet_contract_markdown(contract: dict[str, Any]) -> list[str]:
    lines = ["## Packet Contract", ""]
    lines.append(f"- contract_version: {contract['packet_metadata']['contract_version']}")
    lines.append(f"- packet_kind: {contract['packet_metadata']['packet_kind']}")
    lines.append(f"- profile: {contract['packet_metadata']['profile']}")
    lines.append(f"- output_mode: {contract['output_contract']['output_mode']}")
    lines.extend(["", "### Role And Access Boundaries", ""])
    for item in contract["role_and_access_boundaries"]["narrative"]:
        lines.append(f"- {item}")
    lines.extend(["", "### Stale Context Suppression", ""])
    lines.append(f"- active: {contract['stale_context_suppression'].get('active')}")
    if contract["stale_context_suppression"].get("active"):
        lines.append(f"- suppressed_before: {contract['stale_context_suppression'].get('suppressed_before')}")
        lines.append(f"- reason: {contract['stale_context_suppression'].get('reason')}")
    lines.extend(["", "### Output Contract", ""])
    lines.append(f"- max_findings: {contract['output_contract']['max_findings']}")
    lines.append(f"- description: {contract['output_contract']['description']}")
    lines.append(f"- version_mismatch_rule: {contract['output_contract']['version_mismatch_rule']}")
    lines.append(f"- context_limited_release_rule: {contract['output_contract']['context_limited_release_rule']}")
    return lines
