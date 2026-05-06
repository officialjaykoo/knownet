from __future__ import annotations

import aiosqlite
from fastapi import HTTPException

from ..db.sqlite import fetch_one


MODEL_REVIEW_RUN_STATUSES = {"queued", "running", "dry_run_ready", "imported", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running"}


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
              trace_id TEXT,
              packet_trace_id TEXT,
              error_code TEXT,
              error_message TEXT,
              created_by TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        cursor = await connection.execute("PRAGMA table_info(model_review_runs)")
        columns = {row[1] for row in await cursor.fetchall()}
        for column in ("trace_id", "packet_trace_id", "error_code", "error_message"):
            if column not in columns:
                await connection.execute(f"ALTER TABLE model_review_runs ADD COLUMN {column} TEXT")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_model_review_runs_provider_status ON model_review_runs(provider, status, updated_at)")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_model_review_runs_vault_updated ON model_review_runs(vault_id, updated_at)")
        await connection.execute("CREATE INDEX IF NOT EXISTS idx_model_review_runs_trace ON model_review_runs(trace_id, packet_trace_id)")
        await connection.commit()


async def assert_no_active_run(sqlite_path, provider: str) -> None:
    active = await fetch_one(
        sqlite_path,
        "SELECT id, status FROM model_review_runs WHERE provider = ? AND status IN ('queued', 'running') ORDER BY updated_at DESC LIMIT 1",
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
