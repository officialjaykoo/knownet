from __future__ import annotations

import json
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import execute, fetch_all, fetch_one
from ..routes.collaboration import _rebuild_collaboration_graph, parse_review_markdown
from ..security import Actor, require_admin_access, utc_now
from ..services.model_runner import (
    DeepSeekApiAdapter,
    GeminiApiAdapter,
    GeminiMockAdapter,
    GlmApiAdapter,
    KimiApiAdapter,
    MiniMaxApiAdapter,
    MockModelReviewAdapter,
    QwenApiAdapter,
    assert_no_active_run,
    build_safe_context,
    estimate_tokens,
    model_output_to_markdown,
    normalize_model_output,
    sanitize_error_message,
)
from ..services.rust_core import RustCoreError


router = APIRouter(prefix="/api/model-runs", tags=["model-runs"])


class GeminiReviewRunRequest(BaseModel):
    vault_id: str = "local-default"
    prompt_profile: str = Field(default="gemini_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_findings: int = Field(default=20, ge=1, le=50)
    slim_context: bool = True
    mock: bool = True


class DeepSeekReviewRunRequest(BaseModel):
    vault_id: str = "local-default"
    prompt_profile: str = Field(default="deepseek_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_findings: int = Field(default=20, ge=1, le=50)
    slim_context: bool = True
    mock: bool = True


class MiniMaxReviewRunRequest(BaseModel):
    vault_id: str = "local-default"
    prompt_profile: str = Field(default="minimax_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_findings: int = Field(default=20, ge=1, le=50)
    slim_context: bool = True
    mock: bool = True


class KimiReviewRunRequest(BaseModel):
    vault_id: str = "local-default"
    prompt_profile: str = Field(default="kimi_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_findings: int = Field(default=20, ge=1, le=50)
    slim_context: bool = True
    mock: bool = True


class QwenReviewRunRequest(BaseModel):
    vault_id: str = "local-default"
    prompt_profile: str = Field(default="qwen_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_findings: int = Field(default=20, ge=1, le=50)
    slim_context: bool = True
    mock: bool = True


class GlmReviewRunRequest(BaseModel):
    vault_id: str = "local-default"
    prompt_profile: str = Field(default="glm_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=20, ge=1, le=50)
    max_findings: int = Field(default=20, ge=1, le=50)
    slim_context: bool = True
    mock: bool = True


class ReviewNowRequest(BaseModel):
    vault_id: str = "local-default"
    provider: str = Field(default="auto", max_length=40)
    prompt_profile: str = Field(default="fast_lane_external_reviewer_v1", max_length=120)
    review_focus: str | None = Field(default=None, max_length=800)
    max_pages: int = Field(default=10, ge=1, le=50)
    max_findings: int = Field(default=15, ge=1, le=50)
    slim_context: bool = True
    prefer_live: bool = True
    allow_mock_fallback: bool = True
    auto_import: bool = False


def _json_loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _run_row(row: dict) -> dict:
    data = dict(row)
    data["context_summary"] = _json_loads(data.pop("context_summary_json", "{}"), {})
    data["request"] = _json_loads(data.pop("request_json", "{}"), {})
    data["response"] = _json_loads(data.pop("response_json", "{}"), {})
    return data


async def _store_run(
    settings,
    *,
    run_id: str,
    provider: str,
    model: str,
    prompt_profile: str,
    vault_id: str,
    status: str,
    context_summary: dict,
    request_json: dict,
    response_json: dict,
    input_tokens: int | None,
    output_tokens: int | None,
    created_by: str,
) -> None:
    now = utc_now()
    await execute(
        settings.sqlite_path,
        "INSERT INTO model_review_runs (id, provider, model, prompt_profile, vault_id, status, context_summary_json, request_json, response_json, input_tokens, output_tokens, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            provider,
            model,
            prompt_profile,
            vault_id,
            status,
            json.dumps(context_summary, ensure_ascii=True, sort_keys=True),
            json.dumps(request_json, ensure_ascii=True, sort_keys=True),
            json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            input_tokens,
            output_tokens,
            created_by,
            now,
            now,
        ),
    )


async def _update_run(settings, run_id: str, *, status: str | None = None, response_json: dict | None = None, review_id: str | None = None, error_code: str | None = None, error_message: str | None = None) -> None:
    existing = await fetch_one(settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "model_run_not_found", "message": "Model run not found", "details": {"run_id": run_id}})
    await execute(
        settings.sqlite_path,
        "UPDATE model_review_runs SET status = ?, response_json = ?, review_id = COALESCE(?, review_id), error_code = ?, error_message = ?, updated_at = ? WHERE id = ?",
        (
            status or existing["status"],
            json.dumps(response_json if response_json is not None else _json_loads(existing["response_json"], {}), ensure_ascii=True, sort_keys=True),
            review_id,
            error_code,
            sanitize_error_message(error_message),
            utc_now(),
            run_id,
        ),
    )


async def _import_response_as_review(request: Request, run: dict, actor: Actor) -> dict:
    settings = request.app.state.settings
    response = run["response"]
    markdown = response.get("review_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise HTTPException(status_code=409, detail={"code": "model_run_response_missing", "message": "Model run has no review markdown", "details": {"run_id": run["id"]}})
    metadata, findings, parser_errors = parse_review_markdown(markdown)
    if not findings:
        raise HTTPException(status_code=422, detail={"code": "collaboration_no_findings", "message": "No findings found", "details": {}})
    review_id = f"review_{uuid4().hex[:12]}"
    now = utc_now()
    source_agent = "gemini-mock" if run["provider"] == "gemini" and response.get("mock") else run["provider"]
    source_model = run["model"]
    meta = {
        "frontmatter": metadata,
        "parser_errors": parser_errors,
        "model_run_id": run["id"],
        "provider": run["provider"],
        "prompt_profile": run["prompt_profile"],
        "context_summary": run["context_summary"],
        "markdown_path": f"data/pages/reviews/{review_id}.md",
    }
    try:
        review = await request.app.state.rust_core.request(
            "create_collaboration_review",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "review_id": review_id,
                "vault_id": run["vault_id"] or actor.vault_id,
                "title": response.get("normalized_output", {}).get("review_title") or "Model review",
                "source_agent": source_agent,
                "source_model": source_model,
                "review_type": "agent_review",
                "page_id": None,
                "markdown": markdown,
                "meta": json.dumps(meta, ensure_ascii=True, sort_keys=True),
                "created_at": now,
            },
        )
        created_findings = []
        for finding in findings:
            created = await request.app.state.rust_core.request(
                "create_collaboration_finding",
                {
                    "sqlite_path": str(settings.sqlite_path),
                    "finding_id": f"finding_{uuid4().hex[:12]}",
                    "review_id": review_id,
                    "created_at": now,
                    **finding,
                },
            )
            created_findings.append(created)
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    graph_rebuild = await _rebuild_collaboration_graph(request, run["vault_id"] or actor.vault_id)
    await _update_run(settings, run["id"], status="imported", response_json={**response, "import": {"review_id": review_id, "finding_count": len(created_findings)}}, review_id=review_id)
    await write_audit_event(
        settings.sqlite_path,
        action="model_run.import",
        actor=actor,
        target_type="model_review_run",
        target_id=run["id"],
        metadata={"provider": run["provider"], "review_id": review_id, "finding_count": len(created_findings), "graph_rebuild": graph_rebuild},
    )
    return {"review": review, "findings": created_findings, "graph_rebuild": graph_rebuild}


async def _create_provider_review_run(
    *,
    provider: str,
    model: str,
    payload,
    request: Request,
    actor: Actor,
    adapter,
    source_agent: str,
) -> dict:
    settings = request.app.state.settings
    await assert_no_active_run(settings.sqlite_path, provider)
    run_id = f"modelrun_{uuid4().hex[:12]}"
    max_findings = getattr(payload, "max_findings", 20)
    slim_context = getattr(payload, "slim_context", True)
    context = await build_safe_context(settings, vault_id=payload.vault_id, max_pages=payload.max_pages, max_findings=max_findings, slim=slim_context)
    request_json = {
        "provider": provider,
        "model": model,
        "prompt_profile": payload.prompt_profile,
        "review_focus": payload.review_focus,
        "max_pages": payload.max_pages,
        "max_findings": max_findings,
        "slim_context": slim_context,
        "mock": payload.mock,
        "operator_import_required": settings.gemini_require_operator_import,
    }
    await _store_run(
        settings,
        run_id=run_id,
        provider=provider,
        model=model,
        prompt_profile=payload.prompt_profile,
        vault_id=payload.vault_id,
        status="running",
        context_summary=context.summary,
        request_json=request_json,
        response_json={"stage": "running", "mock": payload.mock},
        input_tokens=context.estimated_tokens,
        output_tokens=None,
        created_by=actor.actor_id,
    )
    started = time.perf_counter()
    try:
        raw_output = await adapter.generate_review({"request": request_json, "context": context.context})
        duration_ms = int((time.perf_counter() - started) * 1000)
        normalized = normalize_model_output(raw_output)
        markdown = model_output_to_markdown(normalized, source_agent=source_agent, source_model=model)
        metadata, findings, parser_errors = parse_review_markdown(markdown)
        response_json = {
            "mock": payload.mock,
            "duration_ms": duration_ms,
            "normalized_output": normalized,
            "review_markdown": markdown,
            "dry_run": {
                "metadata": metadata,
                "finding_count": len(findings),
                "findings": findings,
                "parser_errors": parser_errors,
                "truncated_findings": bool(metadata.get("truncated_findings")),
            },
        }
        await _update_run(settings, run_id, status="dry_run_ready", response_json=response_json)
    except HTTPException as error:
        duration_ms = int((time.perf_counter() - started) * 1000)
        error_detail = error.detail if isinstance(error.detail, dict) else {}
        await _update_run(
            settings,
            run_id,
            status="failed",
            response_json={"stage": "failed", "mock": payload.mock, "duration_ms": duration_ms},
            error_code=error_detail.get("code") or "model_run_failed",
            error_message=error_detail.get("message") or str(error.detail),
        )
        raise
    output_tokens = estimate_tokens(json.dumps(response_json.get("normalized_output", {}), ensure_ascii=False))
    await execute(settings.sqlite_path, "UPDATE model_review_runs SET output_tokens = ?, updated_at = ? WHERE id = ?", (output_tokens, utc_now(), run_id))
    run = await fetch_one(settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    await write_audit_event(
        settings.sqlite_path,
        action="model_run.create",
        actor=actor,
        target_type="model_review_run",
        target_id=run_id,
        metadata={"provider": provider, "mock": payload.mock, "status": "dry_run_ready", "finding_count": response_json["dry_run"]["finding_count"]},
    )
    return {"ok": True, "data": {"run": _run_row(run), "dry_run": response_json["dry_run"]}}


@router.post("/gemini/reviews")
async def create_gemini_review_run(payload: GeminiReviewRunRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    if not payload.mock:
        if not settings.gemini_runner_enabled:
            raise HTTPException(status_code=503, detail={"code": "gemini_disabled", "message": "Gemini runner is disabled. Use mock=true until a real provider is enabled.", "details": {}})
        if not settings.gemini_api_key:
            raise HTTPException(status_code=503, detail={"code": "gemini_api_key_missing", "message": "GEMINI_API_KEY is required for non-mock Gemini runs", "details": {}})
    adapter = (
        GeminiMockAdapter()
        if payload.mock
        else GeminiApiAdapter(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
            response_mime_type=settings.gemini_response_mime_type,
            thinking_budget=settings.gemini_thinking_budget,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
    )
    return await _create_provider_review_run(provider="gemini", model=settings.gemini_model, payload=payload, request=request, actor=actor, adapter=adapter, source_agent="gemini-mock" if payload.mock else "gemini")


@router.post("/deepseek/reviews")
async def create_deepseek_review_run(payload: DeepSeekReviewRunRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    if not payload.mock:
        if not settings.deepseek_runner_enabled:
            raise HTTPException(status_code=503, detail={"code": "deepseek_disabled", "message": "DeepSeek runner is disabled. Use mock=true until a real provider is enabled.", "details": {}})
        if not settings.deepseek_api_key:
            raise HTTPException(status_code=503, detail={"code": "deepseek_api_key_missing", "message": "DEEPSEEK_API_KEY is required for non-mock DeepSeek runs", "details": {}})
    adapter = (
        MockModelReviewAdapter(provider_id="deepseek")
        if payload.mock
        else DeepSeekApiAdapter(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            model=settings.deepseek_model,
            reasoning_effort=settings.deepseek_reasoning_effort,
            thinking_enabled=settings.deepseek_thinking_enabled,
            timeout_seconds=settings.deepseek_timeout_seconds,
        )
    )
    return await _create_provider_review_run(provider="deepseek", model=settings.deepseek_model, payload=payload, request=request, actor=actor, adapter=adapter, source_agent="deepseek-mock" if payload.mock else "deepseek")


@router.post("/minimax/reviews")
async def create_minimax_review_run(payload: MiniMaxReviewRunRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    if not payload.mock:
        if not settings.minimax_runner_enabled:
            raise HTTPException(status_code=503, detail={"code": "minimax_disabled", "message": "MiniMax runner is disabled. Use mock=true until a real provider is enabled.", "details": {}})
        if not settings.minimax_api_key:
            raise HTTPException(status_code=503, detail={"code": "minimax_api_key_missing", "message": "MINIMAX_API_KEY is required for non-mock MiniMax runs", "details": {}})
    adapter = (
        MockModelReviewAdapter(provider_id="minimax")
        if payload.mock
        else MiniMaxApiAdapter(
            api_key=settings.minimax_api_key,
            base_url=settings.minimax_base_url,
            model=settings.minimax_model,
            max_tokens=settings.minimax_max_tokens,
            reasoning_split=settings.minimax_reasoning_split,
            timeout_seconds=settings.minimax_timeout_seconds,
        )
    )
    return await _create_provider_review_run(provider="minimax", model=settings.minimax_model, payload=payload, request=request, actor=actor, adapter=adapter, source_agent="minimax-mock" if payload.mock else "minimax")


@router.post("/kimi/reviews")
async def create_kimi_review_run(payload: KimiReviewRunRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    if not payload.mock:
        if not settings.kimi_runner_enabled:
            raise HTTPException(status_code=503, detail={"code": "kimi_disabled", "message": "Kimi runner is disabled. Use mock=true until a real provider is enabled.", "details": {}})
        if not settings.kimi_api_key:
            raise HTTPException(status_code=503, detail={"code": "kimi_api_key_missing", "message": "KIMI_API_KEY is required for non-mock Kimi runs", "details": {}})
    adapter = (
        MockModelReviewAdapter(provider_id="kimi")
        if payload.mock
        else KimiApiAdapter(
            api_key=settings.kimi_api_key,
            base_url=settings.kimi_base_url,
            model=settings.kimi_model,
            max_tokens=settings.kimi_max_tokens,
            thinking_enabled=settings.kimi_thinking_enabled,
            timeout_seconds=settings.kimi_timeout_seconds,
        )
    )
    return await _create_provider_review_run(provider="kimi", model=settings.kimi_model, payload=payload, request=request, actor=actor, adapter=adapter, source_agent="kimi-mock" if payload.mock else "kimi")


@router.post("/qwen/reviews")
async def create_qwen_review_run(payload: QwenReviewRunRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    if not payload.mock:
        if not settings.qwen_runner_enabled:
            raise HTTPException(status_code=503, detail={"code": "qwen_disabled", "message": "Qwen runner is disabled. Use mock=true until a real provider is enabled.", "details": {}})
        if not settings.qwen_api_key:
            raise HTTPException(status_code=503, detail={"code": "qwen_api_key_missing", "message": "QWEN_API_KEY is required for non-mock Qwen runs", "details": {}})
    adapter = (
        MockModelReviewAdapter(provider_id="qwen")
        if payload.mock
        else QwenApiAdapter(
            api_key=settings.qwen_api_key,
            base_url=settings.qwen_base_url,
            model=settings.qwen_model,
            max_tokens=settings.qwen_max_tokens,
            enable_search=settings.qwen_enable_search,
            timeout_seconds=settings.qwen_timeout_seconds,
        )
    )
    return await _create_provider_review_run(provider="qwen", model=settings.qwen_model, payload=payload, request=request, actor=actor, adapter=adapter, source_agent="qwen-mock" if payload.mock else "qwen")


@router.post("/glm/reviews")
async def create_glm_review_run(payload: GlmReviewRunRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    if not payload.mock:
        if not settings.glm_runner_enabled:
            raise HTTPException(status_code=503, detail={"code": "glm_disabled", "message": "GLM runner is disabled. Use mock=true until a real provider is enabled.", "details": {}})
        if not settings.glm_api_key:
            raise HTTPException(status_code=503, detail={"code": "glm_api_key_missing", "message": "GLM_API_KEY is required for non-mock GLM runs", "details": {}})
    adapter = (
        MockModelReviewAdapter(provider_id="glm")
        if payload.mock
        else GlmApiAdapter(
            api_key=settings.glm_api_key,
            base_url=settings.glm_base_url,
            model=settings.glm_model,
            max_tokens=settings.glm_max_tokens,
            thinking_enabled=settings.glm_thinking_enabled,
            timeout_seconds=settings.glm_timeout_seconds,
        )
    )
    return await _create_provider_review_run(provider="glm", model=settings.glm_model, payload=payload, request=request, actor=actor, adapter=adapter, source_agent="glm-mock" if payload.mock else "glm")


@router.post("/review-now")
async def run_ai_review_now(payload: ReviewNowRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    provider = payload.provider.strip().lower()
    if provider not in {"auto", "gemini"}:
        raise HTTPException(status_code=409, detail={"code": "review_now_provider_unsupported", "message": "Fast lane currently supports Gemini or auto", "details": {"provider": payload.provider}})

    live_available = bool(settings.gemini_runner_enabled and settings.gemini_api_key)
    use_live = payload.prefer_live and live_available
    if payload.prefer_live and not live_available and not payload.allow_mock_fallback:
        missing = []
        if not settings.gemini_runner_enabled:
            missing.append("GEMINI_RUNNER_ENABLED")
        if not settings.gemini_api_key:
            missing.append("GEMINI_API_KEY")
        raise HTTPException(
            status_code=503,
            detail={"code": "gemini_fast_lane_unavailable", "message": "Gemini fast lane needs runner enabled and API key configured", "details": {"missing": missing}},
        )

    run_payload = GeminiReviewRunRequest(
        vault_id=payload.vault_id,
        prompt_profile=payload.prompt_profile,
        review_focus=payload.review_focus or "Fast lane AI review: inspect current KnowNet state and return parser-ready findings only for actionable issues.",
        max_pages=payload.max_pages,
        max_findings=payload.max_findings,
        slim_context=payload.slim_context,
        mock=not use_live,
    )
    adapter = (
        GeminiApiAdapter(
            api_key=settings.gemini_api_key,
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
            response_mime_type=settings.gemini_response_mime_type,
            thinking_budget=settings.gemini_thinking_budget,
            timeout_seconds=settings.gemini_timeout_seconds,
        )
        if use_live
        else GeminiMockAdapter()
    )
    created = await _create_provider_review_run(
        provider="gemini",
        model=settings.gemini_model,
        payload=run_payload,
        request=request,
        actor=actor,
        adapter=adapter,
        source_agent="gemini" if use_live else "gemini-mock",
    )
    run = created["data"]["run"]
    import_result = None
    if payload.auto_import:
        import_result = await _import_response_as_review(request, run, actor)
        refreshed = await fetch_one(settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run["id"],))
        run = _run_row(refreshed)
    await write_audit_event(
        settings.sqlite_path,
        action="model_run.review_now",
        actor=actor,
        target_type="model_review_run",
        target_id=run["id"],
        metadata={"provider": "gemini", "live": use_live, "auto_import": payload.auto_import, "mock_fallback": not use_live},
    )
    return {
        "ok": True,
        "data": {
            "fast_lane": True,
            "provider": "gemini",
            "live": use_live,
            "mock_fallback": not use_live,
            "run": run,
            "dry_run": created["data"]["dry_run"],
            "import": import_result,
            "next_step": "triage_imported_findings" if import_result else "import_or_triage_dry_run",
        },
    }


@router.get("")
async def list_model_runs(request: Request, provider: str | None = None, status: str | None = None, limit: int = 50, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    limit = min(max(limit, 1), 200)
    where = []
    params: list = []
    if provider:
        where.append("provider = ?")
        params.append(provider)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM model_review_runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    rows = await fetch_all(settings.sqlite_path, sql, (*params, limit))
    return {"ok": True, "data": {"runs": [_run_row(row) for row in rows], "actor_role": actor.role}}


@router.get("/{run_id}")
async def get_model_run(run_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    row = await fetch_one(request.app.state.settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "model_run_not_found", "message": "Model run not found", "details": {"run_id": run_id}})
    return {"ok": True, "data": {"run": _run_row(row), "actor_role": actor.role}}


@router.post("/{run_id}/dry-run")
async def dry_run_model_review(run_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    row = await fetch_one(request.app.state.settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "model_run_not_found", "message": "Model run not found", "details": {"run_id": run_id}})
    run = _run_row(row)
    markdown = run["response"].get("review_markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise HTTPException(status_code=409, detail={"code": "model_run_response_missing", "message": "Model run has no review markdown", "details": {"run_id": run_id}})
    metadata, findings, parser_errors = parse_review_markdown(markdown)
    return {
        "ok": True,
        "data": {
            "dry_run": True,
            "metadata": metadata,
            "finding_count": len(findings),
            "findings": findings,
            "parser_errors": parser_errors,
            "truncated_findings": bool(metadata.get("truncated_findings")),
            "actor_role": actor.role,
        },
    }


@router.post("/{run_id}/import")
async def import_model_review(run_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    row = await fetch_one(request.app.state.settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "model_run_not_found", "message": "Model run not found", "details": {"run_id": run_id}})
    run = _run_row(row)
    if run["status"] != "dry_run_ready":
        raise HTTPException(status_code=409, detail={"code": "model_run_not_importable", "message": "Only dry_run_ready model runs can be imported", "details": {"run_id": run_id, "status": run["status"]}})
    result = await _import_response_as_review(request, run, actor)
    refreshed = await fetch_one(request.app.state.settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    return {"ok": True, "data": {"run": _run_row(refreshed), **result}}


@router.post("/{run_id}/cancel")
async def cancel_model_run(run_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    row = await fetch_one(settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "model_run_not_found", "message": "Model run not found", "details": {"run_id": run_id}})
    if row["status"] not in {"queued", "running", "dry_run_ready"}:
        raise HTTPException(status_code=409, detail={"code": "model_run_not_cancellable", "message": "Model run cannot be cancelled from this status", "details": {"status": row["status"]}})
    await _update_run(settings, run_id, status="cancelled")
    await write_audit_event(settings.sqlite_path, action="model_run.cancel", actor=actor, target_type="model_review_run", target_id=run_id, metadata={"provider": row["provider"]})
    refreshed = await fetch_one(settings.sqlite_path, "SELECT * FROM model_review_runs WHERE id = ?", (run_id,))
    return {"ok": True, "data": {"run": _run_row(refreshed)}}
