from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request

from ..db.sqlite import fetch_all, fetch_one
from ..security import Actor, require_admin_access, utc_now
from ..services import collaboration_v2
from ..services.model_output import sanitize_error_message
from ..services.provider_registry import provider_capabilities, provider_capability_map


router = APIRouter(prefix="/api/operator", tags=["operator"])


def _count(row: dict | None) -> int:
    return int(row["count"]) if row and row["count"] is not None else 0


def _status_rank(status: str) -> int:
    return {"fail": 0, "warn": 1, "pass": 2}.get(status, 1)


def _worst_status(checks: list[dict[str, Any]]) -> str:
    if not checks:
        return "warn"
    return min((str(check["status"]) for check in checks), key=_status_rank)


def _check(code: str, status: str, title: str, detail: str, action: str | None = None, data: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "status": status,
        "title": title,
        "detail": detail,
        "action": action,
        "data": data or {},
    }


async def build_ai_state_quality(settings, *, vault_id: str = "local-default") -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    if not Path(settings.sqlite_path).exists():
        checks.append(
            _check(
                "sqlite_missing",
                "fail",
                "SQLite database is missing",
                "KnowNet cannot inspect canonical AI-readable state without knownet.db.",
                "Restore from snapshot or initialize the local database.",
            )
        )
        return {"overall_status": "fail", "checks": checks, "checked_at": utc_now()}
    quality = await collaboration_v2.ai_state_quality(settings.sqlite_path, vault_id)
    return {**quality, "checked_at": utc_now()}


async def build_provider_matrix(settings) -> dict[str, Any]:
    if not Path(settings.sqlite_path).exists():
        run_rows = []
    else:
        run_rows = await fetch_all(
            settings.sqlite_path,
            """
            SELECT pr.id, pr.provider, pr.model, pr.status, pr.trace_id, pr.packet_trace_id,
                   pr.error_code, pr.error_message, pr.updated_at, m.duration_ms,
                   COALESCE((SELECT payload_json FROM provider_run_artifacts a WHERE a.run_id = pr.id AND a.artifact_type = 'request' ORDER BY a.created_at DESC LIMIT 1), '{}') AS request_json,
                   COALESCE((SELECT payload_json FROM provider_run_artifacts a WHERE a.run_id = pr.id AND a.artifact_type = 'response' ORDER BY a.created_at DESC LIMIT 1), '{}') AS response_json
              FROM provider_runs pr
              LEFT JOIN provider_run_metrics m ON m.run_id = pr.id
             ORDER BY pr.updated_at DESC LIMIT 500
            """,
            (),
        )
    run_by_provider: dict[str, dict[str, Any]] = {}
    for row in run_rows:
        provider = row["provider"]
        current = run_by_provider.setdefault(
            provider,
            {
                "last_updated_at": None,
                "mock_successful": 0,
                "live_successful": 0,
                "failed_runs": 0,
                "consecutive_failed_runs": 0,
                "has_seen_success": False,
                "latest_failure": None,
            },
        )
        current["last_updated_at"] = current["last_updated_at"] or row["updated_at"]
        request_json = {}
        try:
            request_json = json.loads(row["request_json"] or "{}")
        except json.JSONDecodeError:
            request_json = {}
        response_json = {}
        try:
            response_json = json.loads(row["response_json"] or "{}")
        except json.JSONDecodeError:
            response_json = {}
        is_mock = bool(request_json.get("mock", True))
        if row["status"] in {"dry_run_ready", "imported"}:
            if is_mock:
                current["mock_successful"] += 1
            else:
                current["live_successful"] += 1
            current["has_seen_success"] = True
        if row["status"] == "failed":
            current["failed_runs"] += 1
            if not current["has_seen_success"]:
                current["consecutive_failed_runs"] += 1
            if not current["latest_failure"]:
                current["latest_failure"] = {
                    "run_id": row["id"],
                    "model": row["model"],
                    "error_code": row["error_code"],
                    "error_message": sanitize_error_message(row["error_message"] or ""),
                    "duration_ms": response_json.get("duration_ms") or row.get("duration_ms"),
                    "updated_at": row["updated_at"],
                }

    capabilities = provider_capability_map(settings)

    def entry(provider_id: str, label: str, route_type: str, implemented_surface: str, enabled: bool, has_credentials: bool, model: str | None, local_test_command: str, live_test_command: str | None, safe_scopes: list[str], known_limitations: list[str]) -> dict[str, Any]:
        capability = capabilities.get(provider_id, {})
        run = run_by_provider.get(provider_id)
        mock_successful = int(run["mock_successful"]) if run else 0
        live_successful = int(run["live_successful"]) if run else 0
        failed = int(run["failed_runs"]) if run else 0
        consecutive_failed = int(run["consecutive_failed_runs"]) if run else 0
        if provider_id == "mock":
            verification = "mocked"
        elif live_successful:
            verification = "live_verified"
        elif mock_successful:
            verification = "mocked"
        elif enabled and has_credentials:
            verification = "configured"
        elif failed:
            verification = "failed"
        elif implemented_surface in {"api_adapter", "mock_adapter"}:
            verification = "mocked"
        else:
            verification = "unavailable"
        return {
            "provider_id": provider_id,
            "label": label,
            "route_type": route_type,
            "implemented_surface": implemented_surface,
            "verification_level": verification,
            "last_verified_at": run["last_updated_at"] if run else None,
            "required_config_present": bool(enabled and has_credentials),
            "model": model,
            "local_test_command": local_test_command,
            "live_test_command": live_test_command,
            "safe_scopes": safe_scopes,
            "known_limitations": known_limitations,
            "capability": capability or None,
            "compatibility_class": capability.get("compatibility_class"),
            "openai_compatible": capability.get("openai_compatible"),
            "anthropic_compatible": capability.get("anthropic_compatible"),
            "run_counts": {"mock_successful": mock_successful, "live_successful": live_successful, "failed": failed, "consecutive_failed": consecutive_failed},
            "latest_failure": run["latest_failure"] if run else None,
            "stability_alert": consecutive_failed >= 3,
        }

    providers = [
        entry("gemini", "Gemini API", "server_model_runner", "api_adapter", settings.gemini_runner_enabled, bool(settings.gemini_api_key), settings.gemini_model, "pytest tests/test_phase16_model_runner.py -q", "POST /api/model-runs/gemini/reviews {mock:false}", ["safe_context", "dry_run", "operator_import"], ["live_verified requires a real API call; free tier may rate-limit"]),
        entry("deepseek", "DeepSeek API", "server_model_runner", "api_adapter", settings.deepseek_runner_enabled, bool(settings.deepseek_api_key), settings.deepseek_model, "pytest tests/test_phase16_model_runner.py -q", "POST /api/model-runs/deepseek/reviews {mock:false}", ["safe_context", "dry_run", "operator_import"], ["web chat is fallback only"]),
        entry("qwen", "Qwen/DashScope API", "server_model_runner", "api_adapter", settings.qwen_runner_enabled, bool(settings.qwen_api_key), settings.qwen_model, "pytest tests/test_phase16_model_runner.py -q", "POST /api/model-runs/qwen/reviews {mock:false}", ["safe_context", "dry_run", "operator_import"], ["Qwen-Agent MCP remains separate"]),
        entry("qwen-agent-mcp", "Qwen-Agent MCP", "client_mcp_profile", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual Qwen-Agent MCP registration", ["read_only_mcp"], ["manual client verification required"]),
        entry("kimi", "Kimi API", "server_model_runner", "api_adapter", settings.kimi_runner_enabled, bool(settings.kimi_api_key), settings.kimi_model, "pytest tests/test_phase16_model_runner.py -q", "POST /api/model-runs/kimi/reviews {mock:false}", ["safe_context", "dry_run", "operator_import"], ["Kimi Code MCP remains separate"]),
        entry("kimi-code-mcp", "Kimi Code MCP", "client_mcp_profile", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual Kimi Code MCP registration", ["read_only_mcp"], ["manual client verification required"]),
        entry("minimax", "MiniMax API", "server_model_runner", "api_adapter", settings.minimax_runner_enabled, bool(settings.minimax_api_key), settings.minimax_model, "pytest tests/test_phase16_model_runner.py -q", "POST /api/model-runs/minimax/reviews {mock:false}", ["safe_context", "dry_run", "operator_import"], ["Mini-Agent remains separate"]),
        entry("minimax-agent", "Mini-Agent HTTP/MCP", "client_agent_profile", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual Mini-Agent registration", ["read_only_http", "read_only_mcp"], ["manual client verification required"]),
        entry("glm", "GLM/Z.AI API", "server_model_runner", "api_adapter", settings.glm_runner_enabled, bool(settings.glm_api_key), settings.glm_model, "pytest tests/test_phase16_model_runner.py -q", "POST /api/model-runs/glm/reviews {mock:false}", ["safe_context", "dry_run", "operator_import"], ["coding-tool MCP remains separate"]),
        entry("glm-coding-mcp", "GLM Coding Tool MCP", "client_mcp_profile", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual GLM coding-tool MCP registration", ["read_only_mcp"], ["manual client verification required"]),
        entry("manus", "Manus Custom MCP/API", "https_custom_mcp", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual Manus Custom MCP/API registration", ["read_only_https_mcp"], ["not a localhost desktop client"]),
        entry("claude-desktop", "Claude Desktop MCP", "desktop_mcp", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual Claude Desktop local MCP smoke", ["read_only_mcp"], ["requires local desktop client"]),
        entry("chatgpt-cursor-mcp", "ChatGPT/Cursor MCP", "client_mcp_profile", "config_profile", True, True, None, "python apps/mcp/scripts/validate_client_profiles.py", "manual MCP-capable client smoke", ["read_only_mcp"], ["web chat products may not support localhost MCP"]),
        entry("mock", "Local mock runner", "server_model_runner", "mock_adapter", True, True, "mock", "pytest tests/test_phase16_model_runner.py -q", None, ["safe_context", "dry_run"], ["mock only; never live_verified"]),
    ]
    summary = {
        "live_verified": sum(1 for item in providers if item["verification_level"] == "live_verified"),
        "configured": sum(1 for item in providers if item["verification_level"] == "configured"),
        "mocked": sum(1 for item in providers if item["verification_level"] == "mocked"),
        "failed": sum(1 for item in providers if item["verification_level"] == "failed"),
        "unavailable": sum(1 for item in providers if item["verification_level"] == "unavailable"),
    }
    return {"providers": providers, "summary": summary, "checked_at": utc_now()}


@router.get("/ai-state-quality")
async def ai_state_quality(request: Request, vault_id: str = "local-default", actor: Actor = Depends(require_admin_access)):
    return {"ok": True, "data": await build_ai_state_quality(request.app.state.settings, vault_id=vault_id)}


@router.get("/provider-matrix")
async def provider_matrix(request: Request, actor: Actor = Depends(require_admin_access)):
    return {"ok": True, "data": await build_provider_matrix(request.app.state.settings)}


@router.get("/provider-capabilities")
async def get_provider_capabilities(request: Request, actor: Actor = Depends(require_admin_access)):
    return {"ok": True, "data": {"providers": provider_capabilities(request.app.state.settings), "checked_at": utc_now()}}


@router.get("/release-readiness")
async def release_readiness(request: Request, vault_id: str = "local-default", actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    quality = await build_ai_state_quality(settings, vault_id=vault_id)
    matrix = await build_provider_matrix(settings)
    health = await request.app.state.app_health_payload() if hasattr(request.app.state, "app_health_payload") else None
    blockers: list[str] = []
    warnings: list[str] = []
    if health and health.get("overall_status") == "attention_required":
        blockers.append("health_attention_required")
    if quality["overall_status"] == "fail":
        blockers.append("ai_state_quality_failed")
    if quality["overall_status"] == "warn":
        warnings.append("ai_state_quality_warn")
    if not matrix["summary"].get("live_verified"):
        warnings.append("no_live_provider_verified")
    latest_run = await fetch_one(settings.sqlite_path, "SELECT id, provider, status, updated_at FROM provider_runs ORDER BY updated_at DESC LIMIT 1", ()) if Path(settings.sqlite_path).exists() else None
    return {
        "ok": True,
        "data": {
            "release_ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "health": health,
            "ai_state_quality": {"overall_status": quality["overall_status"], "summary": quality.get("summary", {})},
            "provider_matrix": matrix["summary"],
            "latest_model_run": dict(latest_run) if latest_run else None,
            "checked_at": utc_now(),
        },
    }
