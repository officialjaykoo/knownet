from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from fastapi import HTTPException

from ..config import Settings
from ..db.sqlite import fetch_all, fetch_one
from .model_output import _dedupe_key
from .packet_contract import PACKET_CONTRACT_VERSION, PACKET_PROTOCOL_VERSION, PACKET_SCHEMA_REF, build_packet_contract, contract_shape, explicit_stale_context_suppression, packet_trace, validate_packet_contract, validate_packet_schema_core
from .project_snapshot import finding_summary, node_card
from .ignore_policy import assert_safe_json_keys, assert_safe_text
from ..security import utc_now


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
    assert_safe_text(text, code="model_context_secret_detected", message="Forbidden marker detected in model context", label=label)


def sanitize_for_model(value: Any, *, label: str = "context") -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key).lower()
            if key_text in {"source_path", "path", "token_hash", "raw_token", "password_hash", "session_meta", "ip_hash", "user_agent_hash"}:
                continue
            assert_safe_json_keys({key: None}, code="model_context_secret_detected", message="Forbidden JSON key detected in model context", label=label)
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
    return await _build_safe_context_v2(settings, vault_id=vault_id, max_pages=max_pages, max_findings=max_findings, slim=slim)


async def _build_safe_context_v2(settings: Settings, *, vault_id: str, max_pages: int, max_findings: int, slim: bool) -> SafeContext:
    counts = await fetch_one(
        settings.sqlite_path,
        "SELECT "
        "(SELECT COUNT(*) FROM pages WHERE vault_id = ? AND status = 'active') AS pages, "
        "0 AS structured_state_pages, "
        "(SELECT COUNT(*) FROM reviews WHERE vault_id = ?) AS reviews, "
        "(SELECT COUNT(*) FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ?) AS findings, "
        "(SELECT COUNT(*) FROM graph_nodes WHERE vault_id = ?) AS graph_nodes",
        (vault_id, vault_id, vault_id, vault_id),
    )
    pages = await fetch_all(
        settings.sqlite_path,
        "SELECT id AS page_id, slug, title, updated_at, current_revision_id, NULL AS content_hash, 'page' AS system_kind, NULL AS system_tier FROM pages WHERE vault_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT ?",
        (vault_id, max_pages),
    )
    safe_pages = [
        {
            "page_id": row["page_id"],
            "slug": row["slug"],
            "title": row["title"],
            "content_hash": row.get("content_hash"),
            "current_revision_id": row.get("current_revision_id"),
            "updated_at": row["updated_at"],
            "system_kind": row.get("system_kind"),
            "system_tier": row.get("system_tier"),
            "state": {"summary": row["title"], "status": "active"},
            "source_ref": str(PurePosixPath("pages") / f"{row['slug']}.md"),
        }
        for row in pages
    ]
    findings = await fetch_all(
        settings.sqlite_path,
        """
        SELECT f.id, f.severity, f.area, f.title, f.status,
               COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               r.id AS review_id, r.title AS review_title
          FROM findings f
          JOIN reviews r ON r.id = f.review_id
          LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
         WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context','accepted','deferred')
         ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, f.updated_at DESC LIMIT 50
        """,
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
        """
        SELECT f.title, f.status
          FROM findings f
          JOIN reviews r ON r.id = f.review_id
         WHERE r.vault_id = ? ORDER BY f.updated_at DESC LIMIT 120
        """,
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
        raise HTTPException(status_code=500, detail={"code": "provider_fast_lane_contract_invalid", "message": "Generated provider packet contract is invalid", "details": {"errors": contract_errors}})
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
                attributes={"knownet.packet.kind": "provider_fast_lane", "knownet.packet.profile": "provider_review", "knownet.vault_id": vault_id},
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
            "summary": counts or {},
            "packet_summary": {"open_findings": [finding_summary(row) for row in deduped_findings]},
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
                "canonical_state": "SQLite v2 structured records exposed through scoped APIs.",
                "daily_verification": "Prefer targeted tests and API smoke checks. Do not recommend full release_check unless release verification is explicitly requested.",
            },
        },
        label="model_context",
    )
    text = _json_dumps(context)
    schema_errors = validate_packet_schema_core(context)
    if schema_errors:
        raise HTTPException(status_code=500, detail={"code": "provider_fast_lane_packet_schema_invalid", "message": "Generated provider packet failed packet schema validation", "details": {"errors": schema_errors}})
    _reject_forbidden_text(text, label="model_context")
    if len(text) > settings.gemini_max_context_chars:
        raise HTTPException(status_code=413, detail={"code": "model_context_too_large", "message": "Model context exceeds configured character budget", "details": {"max_chars": settings.gemini_max_context_chars}})
    tokens = estimate_tokens(text)
    if tokens > settings.gemini_max_context_tokens:
        raise HTTPException(status_code=413, detail={"code": "model_context_too_large", "message": "Model context exceeds configured token budget", "details": {"max_tokens": settings.gemini_max_context_tokens, "estimated_tokens": tokens}})
    summary = {
        "vault_id": vault_id,
        "page_count": len(safe_pages),
        "revision_ids": sorted({str(page.get("current_revision_id")) for page in safe_pages if page.get("current_revision_id")})[:100],
        "content_hashes": [page["content_hash"] for page in safe_pages if page.get("content_hash")],
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
