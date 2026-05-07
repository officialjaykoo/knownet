from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from ..db.sqlite import fetch_all, fetch_one, transaction


MODEL_REVIEW_RUN_STATUSES = {"queued", "running", "dry_run_ready", "imported", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running"}


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=True, sort_keys=True)


def _json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def assert_no_active_run(sqlite_path, provider: str, *, db_version: str = "v2") -> None:
    active = await fetch_one(
        sqlite_path,
        "SELECT id, status FROM provider_runs WHERE provider = ? AND status IN ('queued', 'running') ORDER BY updated_at DESC LIMIT 1",
        (provider,),
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "model_run_already_active",
                "message": "A model run is already queued or running",
                "details": {"run_id": active["id"], "status": active["status"]},
            },
        )


async def store_provider_run_v2(
    sqlite_path,
    *,
    run_id: str,
    provider: str,
    model: str,
    prompt_profile: str,
    vault_id: str,
    status: str,
    context_summary: dict[str, Any],
    request_json: dict[str, Any],
    response_json: dict[str, Any],
    input_tokens: int | None,
    output_tokens: int | None,
    trace_id: str | None,
    packet_trace_id: str | None,
    created_by: str,
    created_at: str,
) -> None:
    async with transaction(sqlite_path) as connection:
        await connection.execute(
            """
            INSERT INTO provider_runs
              (id, provider, model, prompt_profile, vault_id, status, context_summary_json,
               trace_id, packet_trace_id, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                provider,
                model,
                prompt_profile,
                vault_id,
                status,
                _json_dumps(context_summary),
                trace_id,
                packet_trace_id,
                created_by,
                created_at,
                created_at,
            ),
        )
        await connection.execute(
            """
            INSERT INTO provider_run_metrics
              (run_id, input_tokens, output_tokens, duration_ms, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, input_tokens, output_tokens, response_json.get("duration_ms"), created_at),
        )
        for artifact_type, payload in (("request", request_json), ("response", response_json)):
            await connection.execute(
                """
                INSERT INTO provider_run_artifacts
                  (id, run_id, artifact_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"artifact_{uuid4().hex[:12]}", run_id, artifact_type, _json_dumps(payload), created_at),
            )


async def update_provider_run_v2(
    sqlite_path,
    run_id: str,
    *,
    status: str | None,
    response_json: dict[str, Any] | None,
    review_id: str | None,
    error_code: str | None,
    error_message: str | None,
    updated_at: str,
) -> None:
    existing = await provider_run_v2(sqlite_path, run_id)
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "model_run_not_found", "message": "Model run not found", "details": {"run_id": run_id}})
    response = response_json if response_json is not None else existing.get("response", {})
    async with transaction(sqlite_path) as connection:
        await connection.execute(
            """
            UPDATE provider_runs
               SET status = ?,
                   review_id = COALESCE(?, review_id),
                   error_code = ?,
                   error_message = ?,
                   updated_at = ?
             WHERE id = ?
            """,
            (status or existing["status"], review_id, error_code, error_message, updated_at, run_id),
        )
        await connection.execute(
            """
            INSERT INTO provider_run_metrics (run_id, input_tokens, output_tokens, duration_ms, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              output_tokens = COALESCE(excluded.output_tokens, provider_run_metrics.output_tokens),
              duration_ms = COALESCE(excluded.duration_ms, provider_run_metrics.duration_ms),
              updated_at = excluded.updated_at
            """,
            (run_id, existing.get("input_tokens"), existing.get("output_tokens"), response.get("duration_ms"), updated_at),
        )
        await connection.execute("DELETE FROM provider_run_artifacts WHERE run_id = ? AND artifact_type = 'response'", (run_id,))
        await connection.execute(
            """
            INSERT INTO provider_run_artifacts
              (id, run_id, artifact_type, payload_json, created_at)
            VALUES (?, ?, 'response', ?, ?)
            """,
            (f"artifact_{uuid4().hex[:12]}", run_id, _json_dumps(response), updated_at),
        )


async def update_provider_run_output_tokens_v2(sqlite_path, run_id: str, output_tokens: int | None, *, updated_at: str) -> None:
    async with transaction(sqlite_path) as connection:
        await connection.execute(
            """
            INSERT INTO provider_run_metrics (run_id, output_tokens, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET output_tokens = excluded.output_tokens, updated_at = excluded.updated_at
            """,
            (run_id, output_tokens, updated_at),
        )
        await connection.execute("UPDATE provider_runs SET updated_at = ? WHERE id = ?", (updated_at, run_id))


async def provider_run_v2(sqlite_path, run_id: str) -> dict[str, Any] | None:
    row = await fetch_one(
        sqlite_path,
        """
        SELECT pr.*, m.input_tokens, m.output_tokens, m.estimated_cost_usd, m.duration_ms
          FROM provider_runs pr
          LEFT JOIN provider_run_metrics m ON m.run_id = pr.id
         WHERE pr.id = ?
        """,
        (run_id,),
    )
    if not row:
        return None
    return await _with_artifacts(sqlite_path, row)


async def list_provider_runs_v2(sqlite_path, *, provider: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if provider:
        where.append("pr.provider = ?")
        params.append(provider)
    if status:
        where.append("pr.status = ?")
        params.append(status)
    sql = """
        SELECT pr.*, m.input_tokens, m.output_tokens, m.estimated_cost_usd, m.duration_ms
          FROM provider_runs pr
          LEFT JOIN provider_run_metrics m ON m.run_id = pr.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY pr.updated_at DESC LIMIT ?"
    rows = await fetch_all(sqlite_path, sql, (*params, limit))
    return [await _with_artifacts(sqlite_path, row) for row in rows]


async def _with_artifacts(sqlite_path, row: dict[str, Any]) -> dict[str, Any]:
    artifacts = await fetch_all(
        sqlite_path,
        "SELECT artifact_type, payload_json FROM provider_run_artifacts WHERE run_id = ? ORDER BY created_at",
        (row["id"],),
    )
    request_json: dict[str, Any] = {}
    response_json: dict[str, Any] = {}
    for artifact in artifacts:
        if artifact["artifact_type"] == "request":
            request_json = _json_loads(artifact["payload_json"])
        elif artifact["artifact_type"] == "response":
            response_json = _json_loads(artifact["payload_json"])
    if row.get("duration_ms") is not None:
        response_json.setdefault("duration_ms", row.get("duration_ms"))
    return {
        **row,
        "context_summary_json": row.get("context_summary_json") or "{}",
        "request_json": _json_dumps(request_json),
        "response_json": _json_dumps(response_json),
    }
