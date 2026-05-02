from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

import aiosqlite
import httpx
from fastapi import HTTPException

from ..config import Settings
from ..db.sqlite import fetch_all, fetch_one
from ..security import utc_now


MODEL_REVIEW_RUN_STATUSES = {"queued", "running", "dry_run_ready", "imported", "failed", "cancelled"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
AREAS = {"API", "UI", "Rust", "Security", "Data", "Ops", "Docs"}
ACTIVE_STATUSES = {"queued", "running"}
SECRET_ASSIGNMENT_RE = re.compile(r"^\s*(ADMIN_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|DEEPSEEK_API_KEY|MINIMAX_API_KEY|GLM_API_KEY|ZAI_API_KEY|Z_AI_API_KEY|API_KEY|SECRET|PASSWORD)\s*=", re.IGNORECASE)
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


class MockModelReviewAdapter:
    def __init__(self, *, provider_id: str) -> None:
        self.provider_id = provider_id

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        context = request.get("context") or {}
        summary = context.get("summary") or {}
        pages = context.get("pages") or []
        findings = context.get("open_findings") or []
        page_count = summary.get("pages", len(pages)) if isinstance(summary, dict) else len(pages)
        return {
            "review_title": f"{self.provider_id.title()} mock review of KnowNet model context",
            "overall_assessment": "Mock adapter verified that this provider path can build sanitized context, parse model-shaped JSON, and stop at dry-run.",
            "findings": [
                {
                    "title": f"{self.provider_id.title()} provider path should keep operator import mandatory",
                    "severity": "low",
                    "area": "Ops",
                    "evidence": f"The mock run received page_count={page_count}, sampled_pages={len(pages)}, open_findings={len(findings)} and returned dry-run-ready data only.",
                    "proposed_change": "Keep the shared model-runner dry-run and operator import gate for every provider.",
                    "confidence": 0.8,
                }
            ],
            "summary": "Mock result only. No provider network call was made.",
        }


GEMINI_REVIEW_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "review_title": {"type": "STRING"},
        "overall_assessment": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "findings": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "severity": {"type": "STRING", "enum": ["critical", "high", "medium", "low", "info"]},
                    "area": {"type": "STRING", "enum": ["API", "UI", "Rust", "Security", "Data", "Ops", "Docs"]},
                    "evidence": {"type": "STRING"},
                    "proposed_change": {"type": "STRING"},
                    "confidence": {"type": "NUMBER"},
                },
                "required": ["title", "severity", "area", "evidence", "proposed_change"],
                "propertyOrdering": ["title", "severity", "area", "evidence", "proposed_change", "confidence"],
            },
        },
    },
    "required": ["review_title", "overall_assessment", "summary", "findings"],
    "propertyOrdering": ["review_title", "overall_assessment", "findings", "summary"],
}


def build_gemini_review_prompt(request: dict[str, Any]) -> str:
    run_request = request.get("request") or {}
    context = request.get("context") or {}
    focus = run_request.get("review_focus") or "Review the current KnowNet state for concrete risks that should be fixed before broader external AI use."
    return "\n".join(
        [
            "You are an external AI reviewer for KnowNet.",
            "KnowNet is an AI collaboration knowledge base. You receive a sanitized, structured context snapshot only.",
            "",
            "Rules:",
            "- Return JSON only, matching the requested schema.",
            "- Do not ask for raw database files, local filesystem paths, secrets, backups, sessions, users, or raw tokens.",
            "- Focus on actionable implementation, API, data, security, ops, or docs findings.",
            "- Prefer 1 to 5 high-signal findings. Do not invent facts beyond the provided context.",
            "- Evidence must cite fields or observations from the provided context, not private assumptions.",
            "- Proposed change must be concrete enough for Codex to implement or verify.",
            "",
            f"Review focus: {focus}",
            "",
            "Sanitized KnowNet context JSON:",
            _json_dumps(context),
        ]
    )


class GeminiApiAdapter:
    provider_id = "gemini"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        prompt = build_gemini_review_prompt(request)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseSchema": GEMINI_REVIEW_RESPONSE_SCHEMA,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    url,
                    headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(
                status_code=504,
                detail={"code": "gemini_timeout", "message": "Gemini API request timed out", "details": {}},
            ) from error
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "gemini_request_failed", "message": sanitize_error_message(str(error)), "details": {}},
            ) from error

        if response.status_code >= 400:
            message = _extract_gemini_error_message(response)
            if response.status_code == 429:
                code = "gemini_rate_limited"
            elif response.status_code in {401, 403}:
                code = "gemini_auth_failed"
            else:
                code = "gemini_request_failed"
            raise HTTPException(
                status_code=502,
                detail={"code": code, "message": sanitize_error_message(message) or "Gemini API request failed", "details": {"status_code": response.status_code}},
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "gemini_invalid_response", "message": "Gemini API response was not JSON", "details": {}},
            ) from error

        text = _extract_gemini_text(payload)
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "gemini_invalid_response", "message": "Gemini API response text was not valid JSON", "details": {}},
            ) from error


def _extract_gemini_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:1000]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(payload)[:1000]


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise HTTPException(status_code=502, detail={"code": "gemini_invalid_response", "message": "Gemini API returned no candidates", "details": {}})
    content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise HTTPException(status_code=502, detail={"code": "gemini_invalid_response", "message": "Gemini API candidate has no parts", "details": {}})
    text_parts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    text = "".join(text_parts).strip()
    if not text:
        raise HTTPException(status_code=502, detail={"code": "gemini_invalid_response", "message": "Gemini API returned empty text", "details": {}})
    return text


def build_openai_compatible_review_messages(request: dict[str, Any], *, provider_name: str) -> list[dict[str, str]]:
    run_request = request.get("request") or {}
    context = request.get("context") or {}
    focus = run_request.get("review_focus") or "Review the current KnowNet state for concrete risks that should be fixed before broader external AI use."
    example = {
        "review_title": f"{provider_name} review of KnowNet",
        "overall_assessment": "Brief assessment.",
        "findings": [
            {
                "title": "Concrete issue title",
                "severity": "medium",
                "area": "API",
                "evidence": "Specific evidence from the provided context.",
                "proposed_change": "Specific change to make.",
                "confidence": 0.8,
            }
        ],
        "summary": "Short summary.",
    }
    system_prompt = "\n".join(
        [
            f"You are {provider_name}, acting as an external AI reviewer for KnowNet.",
            "Return strict JSON only. The word json is intentionally included for JSON mode.",
            "Do not request or reveal raw database files, local filesystem paths, secrets, backups, sessions, users, raw tokens, or token hashes.",
            "Use only the provided sanitized context.",
            "Severity must be one of: critical, high, medium, low, info.",
            "Area must be one of: API, UI, Rust, Security, Data, Ops, Docs.",
            "Output JSON must follow this example shape:",
            json.dumps(example, ensure_ascii=False),
        ]
    )
    user_prompt = "\n".join(
        [
            f"Review focus: {focus}",
            "Prefer 1 to 5 high-signal findings. If no issue exists, return one low/info finding explaining the remaining verification gap.",
            "Sanitized KnowNet context JSON:",
            _json_dumps(context),
        ]
    )
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]


MINIMAX_KNOWNET_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "knownet_state_summary",
            "description": "Read the sanitized KnowNet state summary already prepared for this model run.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knownet_ai_state",
            "description": "Read sampled sanitized ai_state pages from the prepared model-run context.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knownet_list_findings",
            "description": "Read open findings from the prepared model-run context.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}},
                "additionalProperties": False,
            },
        },
    },
]

GLM_KNOWNET_TOOLS = MINIMAX_KNOWNET_TOOLS


def _execute_minimax_knownet_tool(context: dict[str, Any], name: str, arguments_json: str | None) -> dict[str, Any]:
    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail={"code": "minimax_invalid_tool_args", "message": "MiniMax returned invalid tool arguments", "details": {"tool": name}})
    if not isinstance(arguments, dict):
        raise HTTPException(status_code=502, detail={"code": "minimax_invalid_tool_args", "message": "MiniMax tool arguments must be a JSON object", "details": {"tool": name}})
    if name == "knownet_state_summary":
        return {"summary": context.get("summary") or {}, "rules": context.get("rules") or {}}
    if name == "knownet_ai_state":
        limit = min(max(int(arguments.get("limit") or 10), 1), 20)
        return {"pages": (context.get("pages") or [])[:limit], "returned_count": len((context.get("pages") or [])[:limit])}
    if name == "knownet_list_findings":
        limit = min(max(int(arguments.get("limit") or 20), 1), 50)
        findings = context.get("open_findings") or []
        return {"findings": findings[:limit], "returned_count": len(findings[:limit])}
    raise HTTPException(status_code=502, detail={"code": "minimax_invalid_tool", "message": "MiniMax requested a tool that is not allowed", "details": {"tool": name}})


class DeepSeekApiAdapter:
    provider_id = "deepseek"

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 90.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        body = {
            "model": self.model,
            "messages": build_openai_compatible_review_messages(request, provider_name="DeepSeek"),
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 4000,
            "stream": False,
            "thinking": {"type": "disabled"},
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "deepseek_timeout", "message": "DeepSeek API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": "deepseek_request_failed", "message": sanitize_error_message(str(error)), "details": {}},
            ) from error

        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "deepseek_rate_limited"
            elif response.status_code in {401, 403}:
                code = "deepseek_auth_failed"
            else:
                code = "deepseek_request_failed"
            raise HTTPException(
                status_code=502,
                detail={"code": code, "message": sanitize_error_message(message) or "DeepSeek API request failed", "details": {"status_code": response.status_code}},
            )

        try:
            payload = response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "deepseek_invalid_response", "message": "DeepSeek API response was not JSON", "details": {}}) from error

        text = _extract_openai_compatible_message_content(payload, provider_code="deepseek")
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "deepseek_invalid_response", "message": "DeepSeek API response content was not valid JSON", "details": {}}) from error


class MiniMaxApiAdapter:
    provider_id = "minimax"

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float = 90.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = build_openai_compatible_review_messages(request, provider_name="MiniMax")
        messages[0]["content"] += "\nYou may use the provided knownet_* tools for read-only context lookup. Final answer must be strict JSON only."
        body = {
            "model": self.model,
            "messages": messages,
            "tools": MINIMAX_KNOWNET_TOOLS,
            "temperature": 0.2,
            "max_tokens": 4000,
            "stream": False,
        }
        first_payload = await self._post_chat(body)
        first_message = _extract_openai_compatible_message(first_payload, provider_code="minimax")
        tool_calls = first_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(first_message)
            context = request.get("context") or {}
            for tool_call in tool_calls[:5]:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                if not isinstance(name, str):
                    raise HTTPException(status_code=502, detail={"code": "minimax_invalid_tool", "message": "MiniMax returned a malformed tool call", "details": {}})
                tool_result = _execute_minimax_knownet_tool(context, name, arguments if isinstance(arguments, str) else "{}")
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json.dumps(tool_result, ensure_ascii=False)})
            final_payload = await self._post_chat({**body, "messages": messages, "tools": MINIMAX_KNOWNET_TOOLS})
            final_message = _extract_openai_compatible_message(final_payload, provider_code="minimax")
            content = str(final_message.get("content") or "").strip()
        else:
            content = str(first_message.get("content") or "").strip()
        content = _strip_think_tags(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            extracted = _extract_json_object_text(content)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            raise HTTPException(status_code=502, detail={"code": "minimax_invalid_response", "message": "MiniMax API response content was not valid JSON", "details": {}}) from error

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "minimax_timeout", "message": "MiniMax API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"code": "minimax_request_failed", "message": sanitize_error_message(str(error)), "details": {}}) from error
        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "minimax_rate_limited"
            elif response.status_code in {401, 403}:
                code = "minimax_auth_failed"
            else:
                code = "minimax_request_failed"
            raise HTTPException(status_code=502, detail={"code": code, "message": sanitize_error_message(message) or "MiniMax API request failed", "details": {"status_code": response.status_code}})
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "minimax_invalid_response", "message": "MiniMax API response was not JSON", "details": {}}) from error


class GlmApiAdapter:
    provider_id = "glm"

    def __init__(self, *, api_key: str, base_url: str, model: str, timeout_seconds: float = 90.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate_review(self, request: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = build_openai_compatible_review_messages(request, provider_name="GLM/Z.AI")
        messages[0]["content"] += "\nYou may use the provided knownet_* tools for read-only context lookup. Final answer must be strict JSON only."
        body = {
            "model": self.model,
            "messages": messages,
            "tools": GLM_KNOWNET_TOOLS,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 4000,
            "stream": False,
        }
        first_payload = await self._post_chat(body)
        first_message = _extract_openai_compatible_message(first_payload, provider_code="glm")
        tool_calls = first_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(first_message)
            context = request.get("context") or {}
            for tool_call in tool_calls[:5]:
                function = tool_call.get("function") if isinstance(tool_call, dict) else None
                name = function.get("name") if isinstance(function, dict) else None
                arguments = function.get("arguments") if isinstance(function, dict) else None
                if not isinstance(name, str):
                    raise HTTPException(status_code=502, detail={"code": "glm_invalid_tool", "message": "GLM returned a malformed tool call", "details": {}})
                tool_result = _execute_minimax_knownet_tool(context, name, arguments if isinstance(arguments, str) else "{}")
                messages.append({"role": "tool", "tool_call_id": tool_call.get("id"), "content": json.dumps(tool_result, ensure_ascii=False)})
            final_payload = await self._post_chat({**body, "messages": messages, "tools": GLM_KNOWNET_TOOLS})
            final_message = _extract_openai_compatible_message(final_payload, provider_code="glm")
            content = str(final_message.get("content") or "").strip()
        else:
            content = str(first_message.get("content") or "").strip()
        content = _strip_think_tags(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            extracted = _extract_json_object_text(content)
            if extracted:
                try:
                    return json.loads(extracted)
                except json.JSONDecodeError:
                    pass
            raise HTTPException(status_code=502, detail={"code": "glm_invalid_response", "message": "GLM API response content was not valid JSON", "details": {}}) from error

    async def _post_chat(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException as error:
            raise HTTPException(status_code=504, detail={"code": "glm_timeout", "message": "GLM API request timed out", "details": {}}) from error
        except httpx.HTTPError as error:
            raise HTTPException(status_code=502, detail={"code": "glm_request_failed", "message": sanitize_error_message(str(error)), "details": {}}) from error
        if response.status_code >= 400:
            message = _extract_openai_compatible_error_message(response)
            if response.status_code == 429:
                code = "glm_rate_limited"
            elif response.status_code in {401, 403}:
                code = "glm_auth_failed"
            else:
                code = "glm_request_failed"
            raise HTTPException(status_code=502, detail={"code": code, "message": sanitize_error_message(message) or "GLM API request failed", "details": {"status_code": response.status_code}})
        try:
            return response.json()
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=502, detail={"code": "glm_invalid_response", "message": "GLM API response was not JSON", "details": {}}) from error


def _extract_openai_compatible_message(payload: dict[str, Any], *, provider_code: str) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_response", "message": "Provider returned no choices", "details": {}})
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_response", "message": "Provider returned no message", "details": {}})
    return message


def _extract_openai_compatible_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return response.text[:1000]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(payload)[:1000]


def _extract_openai_compatible_message_content(payload: dict[str, Any], *, provider_code: str) -> str:
    message = _extract_openai_compatible_message(payload, provider_code=provider_code)
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=502, detail={"code": f"{provider_code}_invalid_response", "message": "Provider returned empty message content", "details": {}})
    return content.strip()


def _strip_think_tags(text: str) -> str:
    return re.sub(r"(?is)<think>.*?</think>", "", text).strip()


def _extract_json_object_text(text: str) -> str | None:
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
