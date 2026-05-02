from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

import aiosqlite
from fastapi import HTTPException

from ..config import Settings
from ..db.sqlite import fetch_all, fetch_one
from ..security import utc_now


MODEL_REVIEW_RUN_STATUSES = {"queued", "running", "dry_run_ready", "imported", "failed", "cancelled"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
AREAS = {"API", "UI", "Rust", "Security", "Data", "Ops", "Docs"}
ACTIVE_STATUSES = {"queued", "running"}
SECRET_ASSIGNMENT_RE = re.compile(r"^\s*(ADMIN_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|API_KEY|SECRET|PASSWORD)\s*=", re.IGNORECASE)
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


def normalize_model_output(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HTTPException(status_code=502, detail={"code": "model_response_invalid", "message": "Model response must be a JSON object", "details": {}})
    findings_in = raw.get("findings")
    if not isinstance(findings_in, list):
        raise HTTPException(status_code=502, detail={"code": "model_response_invalid", "message": "Model response must include findings array", "details": {}})
    findings: list[dict[str, Any]] = []
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


async def ensure_model_runner_schema(sqlite_path) -> None:
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS model_review_runs (
              id TEXT PRIMARY KEY,
              provider TEXT NOT NULL,
              model TEXT NOT NULL,
              prompt_profile TEXT NOT NULL,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              status TEXT NOT NULL,
              context_summary_json TEXT NOT NULL DEFAULT '{}',
              request_json TEXT NOT NULL DEFAULT '{}',
              response_json TEXT NOT NULL DEFAULT '{}',
              input_tokens INTEGER,
              output_tokens INTEGER,
              estimated_cost_usd REAL,
              review_id TEXT,
              error_code TEXT,
              error_message TEXT,
              created_by TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_model_review_runs_provider_status ON model_review_runs(provider, status, updated_at)")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_model_review_runs_vault_updated ON model_review_runs(vault_id, updated_at)")
        await connection.commit()


async def assert_no_active_run(sqlite_path, provider: str) -> None:
    row = await fetch_one(
        sqlite_path,
        "SELECT id, status FROM model_review_runs WHERE provider = ? AND status IN ('queued', 'running') ORDER BY updated_at DESC LIMIT 1",
        (provider,),
    )
    if row:
        raise HTTPException(
            status_code=409,
            detail={"code": "model_run_already_active", "message": "A model run is already queued or running", "details": {"run_id": row["id"], "status": row["status"]}},
        )


async def build_safe_context(settings: Settings, *, vault_id: str, max_pages: int = 20) -> SafeContext:
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
        "SELECT f.id, f.severity, f.area, f.title, f.status, r.id AS review_id, r.title AS review_title "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context','deferred') "
        "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, f.updated_at DESC LIMIT 50",
        (vault_id,),
    )
    context = sanitize_for_model(
        {
            "generated_at": utc_now(),
            "vault_id": vault_id,
            "purpose": "External model review context. Do not request raw database files, local filesystem paths, secrets, backups, sessions, or users.",
            "summary": counts or {},
            "pages": safe_pages,
            "open_findings": findings,
            "rules": {
                "output_format": "Return JSON only with review_title, overall_assessment, findings, and summary.",
                "operator_import_required": True,
                "canonical_state": "SQLite structured records and generated ai_state exposed through scoped APIs.",
            },
        },
        label="model_context",
    )
    text = _json_dumps(context)
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
        "open_finding_count": len(findings),
        "estimated_input_tokens": tokens,
        "chars": len(text),
        "context_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "omitted": ["raw markdown bodies", "local filesystem paths", "database files", "secrets", "sessions", "users", "backups", "inbox"],
    }
    return SafeContext(context=context, summary=summary, estimated_tokens=tokens, chars=len(text))


class GeminiMockAdapter:
    provider_id = "gemini"

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context") or {}
        summary = context.get("summary") or {}
        pages = context.get("pages") or []
        findings = context.get("open_findings") or []
        page_count = summary.get("pages", len(pages)) if isinstance(summary, dict) else len(pages)
        stale_hint = "No active ai_state pages were included." if not pages else f"{len(pages)} ai_state pages were sampled."
        return {
            "review_title": "Gemini mock review of KnowNet model context",
            "overall_assessment": "Gemini mock adapter verified that the shared model-runner context can be built, sanitized, parsed, and held for operator import.",
            "findings": [
                {
                    "title": "Model runner context should stay bounded and sanitized",
                    "severity": "medium",
                    "area": "API",
                    "evidence": f"The mock run received page_count={page_count}, sampled_pages={len(pages)}, open_findings={len(findings)}. {stale_hint}",
                    "proposed_change": "Keep Phase 16 provider adapters behind the shared safe context builder and block direct provider-specific data assembly.",
                    "confidence": 0.84,
                },
                {
                    "title": "Operator import gate should remain mandatory",
                    "severity": "low",
                    "area": "Ops",
                    "evidence": "The mock provider returned findings as dry-run-ready review Markdown instead of creating collaboration records directly.",
                    "proposed_change": "Require an explicit operator import action for every external model result, including future paid providers.",
                    "confidence": 0.78,
                },
            ],
            "summary": "Mock result only. No Gemini network call was made.",
        }


def sanitize_error_message(message: str | None) -> str | None:
    if not message:
        return None
    sanitized = LOCAL_PATH_RE.sub("[local-path]", message)
    sanitized = re.sub(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", sanitized)
    return sanitized[:1000]
