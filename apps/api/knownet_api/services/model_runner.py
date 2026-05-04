from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from fastapi import HTTPException

from ..config import Settings
from ..db.sqlite import fetch_all, fetch_one
from .model_output import _dedupe_key
from .packet_contract import PACKET_CONTRACT_VERSION, PACKET_PROTOCOL_VERSION, PACKET_SCHEMA_REF, build_packet_contract, contract_shape, explicit_stale_context_suppression, packet_trace, validate_packet_contract, validate_packet_schema_core
from .project_snapshot import finding_summary, node_card
from ..security import utc_now


SECRET_ASSIGNMENT_RE = re.compile(r"^\s*(ADMIN_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|DEEPSEEK_API_KEY|MINIMAX_API_KEY|KIMI_API_KEY|MOONSHOT_API_KEY|GLM_API_KEY|ZAI_API_KEY|Z_AI_API_KEY|API_KEY|SECRET|PASSWORD)\s*=", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"']+")
FORBIDDEN_TEXT_MARKERS = (
    "token_hash",
    "raw_token",
    ".env",
    ".db",
    "backups/",
    "backups\\",
    "inbox/",
    "inbox\\",
)


class ModelProviderAdapter(Protocol):
    provider_id: str

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class SafeContext:
    context: dict[str, Any]
    summary: dict[str, Any]
    estimated_tokens: int
    chars: int


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4 + 1)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _reject_forbidden_text(text: str, *, label: str) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if SECRET_ASSIGNMENT_RE.match(line):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "model_context_secret_detected",
                    "message": "Secret assignment detected in model context",
                    "details": {"label": label, "line": line_number},
                },
            )
    lowered = text.lower()
    for marker in FORBIDDEN_TEXT_MARKERS:
        if marker in lowered:
            raise HTTPException(
                status_code=422,
                detail={"code": "model_context_secret_detected", "message": "Forbidden marker detected in model context", "details": {"label": label, "marker": marker}},
            )
    if LOCAL_PATH_RE.search(text):
        raise HTTPException(
            status_code=422,
            detail={"code": "model_context_path_detected", "message": "Local filesystem path detected in model context", "details": {"label": label}},
        )


def sanitize_for_model(value: Any, *, label: str = "context") -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"source_path", "path", "token_hash", "raw_token", "password_hash", "session_meta", "ip_hash", "user_agent_hash"}:
                continue
            if any(part in key_text for part in ("secret", "password", "token", "api_key")):
                raise HTTPException(
                    status_code=422,
                    detail={"code": "model_context_secret_detected", "message": "Forbidden JSON key detected in model context", "details": {"label": f"{label}.{key}"}},
                )
            sanitized[str(key)] = sanitize_for_model(child, label=f"{label}.{key}")
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_model(child, label=f"{label}[]") for child in value]
    if isinstance(value, str):
        _reject_forbidden_text(value, label=label)
        return value
    return value


def _slim_state(state: dict[str, Any]) -> dict[str, Any]:
    keep_keys = (
        "summary",
        "current_state",
        "known_issues",
        "review_targets",
        "verification",
        "next_actions",
        "boundaries",
        "non_goals",
        "status",
    )
    slim = {key: state[key] for key in keep_keys if key in state}
    if not slim:
        for key, value in list(state.items())[:6]:
            if key != "source":
                slim[key] = value
    return slim


async def build_safe_context(settings: Settings, *, vault_id: str, max_pages: int = 20, max_findings: int = 20, slim: bool = True) -> SafeContext:
    counts = await fetch_one(
        settings.sqlite_path,
        "SELECT "
        "(SELECT COUNT(*) FROM pages WHERE vault_id = ? AND status = 'active') AS pages, "
        "(SELECT COUNT(*) FROM ai_state_pages WHERE vault_id = ?) AS ai_state_pages, "
        "(SELECT COUNT(*) FROM collaboration_reviews WHERE vault_id = ?) AS reviews, "
        "(SELECT COUNT(*) FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ?) AS findings, "
        "(SELECT COUNT(*) FROM graph_nodes WHERE vault_id = ?) AS graph_nodes",
        (vault_id, vault_id, vault_id, vault_id, vault_id),
    )
    pages = await fetch_all(
        settings.sqlite_path,
        "SELECT a.page_id, a.slug, a.title, a.content_hash, a.state_json, a.updated_at, p.current_revision_id, sp.kind AS system_kind, sp.tier AS system_tier "
        "FROM ai_state_pages a "
        "LEFT JOIN pages p ON p.id = a.page_id "
        "LEFT JOIN system_pages sp ON sp.page_id = a.page_id "
        "WHERE a.vault_id = ? ORDER BY a.updated_at DESC LIMIT ?",
        (vault_id, max_pages),
    )
    safe_pages = []
    revision_ids: list[str] = []
    for row in pages:
        state = {}
        try:
            state = json.loads(row["state_json"] or "{}")
        except json.JSONDecodeError:
            state = {"parse_error": True}
        state = sanitize_for_model(state, label=f"ai_state.{row['slug']}")
        if slim and isinstance(state, dict):
            state = _slim_state(state)
        revision_id = row.get("current_revision_id")
        if revision_id:
            revision_ids.append(str(revision_id))
        safe_pages.append(
            {
                "page_id": row["page_id"],
                "slug": row["slug"],
                "title": row["title"],
                "content_hash": row["content_hash"],
                "current_revision_id": revision_id,
                "updated_at": row["updated_at"],
                "system_kind": row.get("system_kind"),
                "system_tier": row.get("system_tier"),
                "state": state,
                "source_ref": str(PurePosixPath("pages") / f"{row['slug']}.md"),
            }
        )
    findings = await fetch_all(
        settings.sqlite_path,
        "SELECT f.id, f.severity, f.area, f.title, f.status, f.evidence_quality, r.id AS review_id, r.title AS review_title "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context','accepted','deferred') "
        "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, f.updated_at DESC LIMIT 50",
        (vault_id,),
    )
    deduped_findings = []
    seen_finding_titles: set[str] = set()
    for finding in findings:
        key = _dedupe_key(str(finding.get("title") or ""))
        if key and key in seen_finding_titles:
            continue
        if key:
            seen_finding_titles.add(key)
        deduped_findings.append(finding)
        if len(deduped_findings) >= max_findings:
            break
    existing_title_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT f.title, f.status FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? ORDER BY f.updated_at DESC LIMIT 120",
        (vault_id,),
    )
    existing_finding_titles = []
    seen_existing: set[str] = set()
    for row in existing_title_rows:
        title = str(row.get("title") or "").strip()
        key = _dedupe_key(title)
        if not title or key in seen_existing:
            continue
        seen_existing.add(key)
        existing_finding_titles.append({"title": title, "status": row.get("status"), "dedupe_key": key})
        if len(existing_finding_titles) >= 50:
            break
    contract = build_packet_contract(
        packet_kind="provider_fast_lane",
        target_agent="external_model",
        operator_question="Review the supplied KnowNet context and return import-ready findings only.",
        output_mode="top_findings",
        profile="provider_review",
        stale_context_suppression=explicit_stale_context_suppression(),
    )
    contract_errors = validate_packet_contract(contract)
    if contract_errors:
        raise HTTPException(
            status_code=500,
            detail={"code": "provider_fast_lane_contract_invalid", "message": "Generated provider packet contract is invalid", "details": {"errors": contract_errors}},
        )
    generated_at = utc_now()
    trace_id = "provider_" + hashlib.sha256(f"{vault_id}:{generated_at}".encode("utf-8")).hexdigest()[:16]
    provider_context_id = "provider_fast_lane_" + hashlib.sha256(f"{vault_id}:{generated_at}:context".encode("utf-8")).hexdigest()[:12]
    context = sanitize_for_model(
        {
            "id": provider_context_id,
            "type": "provider_fast_lane_context",
            "generated_at": generated_at,
            "contract_version": PACKET_CONTRACT_VERSION,
            "protocol_version": PACKET_PROTOCOL_VERSION,
            "schema_ref": PACKET_SCHEMA_REF,
            "links": {"self": {"href": "/api/model-runs/review-now"}},
            "trace": packet_trace(
                trace_id=trace_id,
                name="knownet.provider_fast_lane_context",
                span_kind="CLIENT",
                attributes={
                    "knownet.packet.kind": "provider_fast_lane",
                    "knownet.packet.profile": "provider_review",
                    "knownet.vault_id": vault_id,
                },
            ),
            "contract": contract,
            "contract_shape": contract_shape(contract),
            "ai_context": {
                "role": "provider_review_reviewer",
                "target_agent": "external_model",
                "task": "Review provider-fast-lane KnowNet context and return compact import-ready findings.",
                "read_order": ["ai_context", "node_cards", "packet_summary", "contract"],
            },
            "vault_id": vault_id,
            "purpose": "External model review context. Do not request raw database files, local filesystem paths, secrets, backups, sessions, or users.",
            "protocols": {
                "access_fallback": "If direct access is unavailable, state the limitation and continue only from supplied context.",
                "boundary_enforcement": "Refuse secrets, raw database files, backups, sessions, users, shell access, and unreviewed writes. Escalate ambiguous write or restore requests.",
                "evidence_quality": "Use context_limited unless the model directly observed the system state through the provided API response.",
            },
            "summary": counts or {},
            "packet_summary": {
                "open_findings": [finding_summary(row) for row in deduped_findings],
            },
            "node_cards": [node_card(row, short_summary=str(row.get("state") or "")) for row in safe_pages],
            "pages": safe_pages,
            "open_findings": deduped_findings,
            "stale_suppression": {
                "do_not_repeat_existing_titles": existing_finding_titles,
                "rule": "Do not create a new finding for an issue that is already represented here unless the proposed change is materially different.",
            },
            "rules": {
                "output_format": "Return JSON only with review_title, overall_assessment, findings, and summary.",
                "operator_import_required": True,
                "canonical_state": "SQLite structured records and generated ai_state exposed through scoped APIs.",
                "daily_verification": "Prefer targeted tests and API smoke checks. Do not recommend full release_check unless release verification is explicitly requested.",
            },
        },
        label="model_context",
    )
    text = _json_dumps(context)
    schema_errors = validate_packet_schema_core(context)
    if schema_errors:
        raise HTTPException(
            status_code=500,
            detail={"code": "provider_fast_lane_packet_schema_invalid", "message": "Generated provider packet failed packet schema validation", "details": {"errors": schema_errors}},
        )
    _reject_forbidden_text(text, label="model_context")
    if len(text) > settings.gemini_max_context_chars:
        raise HTTPException(
            status_code=413,
            detail={"code": "model_context_too_large", "message": "Model context exceeds configured character budget", "details": {"max_chars": settings.gemini_max_context_chars}},
        )
    tokens = estimate_tokens(text)
    if tokens > settings.gemini_max_context_tokens:
        raise HTTPException(
            status_code=413,
            detail={"code": "model_context_too_large", "message": "Model context exceeds configured token budget", "details": {"max_tokens": settings.gemini_max_context_tokens, "estimated_tokens": tokens}},
        )
    summary = {
        "vault_id": vault_id,
        "page_count": len(safe_pages),
        "revision_ids": sorted(set(revision_ids))[:100],
        "content_hashes": [page["content_hash"] for page in safe_pages],
        "open_finding_count": len(deduped_findings),
        "existing_finding_title_count": len(existing_finding_titles),
        "context_mode": "slim" if slim else "full",
        "max_pages": max_pages,
        "max_findings": max_findings,
        "estimated_input_tokens": tokens,
        "chars": len(text),
        "context_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "omitted": ["raw markdown bodies", "local filesystem paths", "database files", "secrets", "sessions", "users", "backups", "inbox"],
    }
    return SafeContext(context=context, summary=summary, estimated_tokens=tokens, chars=len(text))
