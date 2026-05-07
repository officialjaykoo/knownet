from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import aiosqlite

from .v2_migrate import V2_SCHEMA_PATH, utc_now


REQUIRED_V2_TABLES = {
    "reviews",
    "findings",
    "finding_evidence",
    "finding_locations",
    "finding_decisions",
    "tasks",
    "system_pages",
    "snapshots",
    "packets",
    "packet_sources",
    "provider_runs",
    "provider_run_metrics",
    "provider_run_artifacts",
    "schema_migrations",
}


class V2SchemaError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


def expected_v2_checksum(schema_path: Path = V2_SCHEMA_PATH) -> str:
    return hashlib.sha256(schema_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


async def _table_names(connection: aiosqlite.Connection) -> set[str]:
    async with connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
        rows = await cursor.fetchall()
    return {str(row[0]) for row in rows}


async def _schema_migration_checksum(connection: aiosqlite.Connection) -> str | None:
    try:
        async with connection.execute("SELECT checksum FROM schema_migrations ORDER BY version DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
    except aiosqlite.Error:
        return None
    return str(row[0]) if row else None


async def apply_v2_schema(sqlite_path: Path, *, schema_path: Path = V2_SCHEMA_PATH) -> str:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    schema = schema_path.read_text(encoding="utf-8")
    checksum = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.executescript(schema)
        await connection.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
            (1, "v2_clean_schema", utc_now(), checksum),
        )
        await connection.commit()
    return checksum


async def verify_v2_schema(sqlite_path: Path, *, schema_path: Path = V2_SCHEMA_PATH) -> dict[str, Any]:
    if not sqlite_path.exists():
        raise V2SchemaError(
            "v2_db_missing",
            f"v2 DB does not exist: {sqlite_path}",
            details={"sqlite_path": str(sqlite_path)},
        )
    expected_checksum = expected_v2_checksum(schema_path)
    async with aiosqlite.connect(sqlite_path) as connection:
        existing = await _table_names(connection)
        missing = sorted(REQUIRED_V2_TABLES - existing)
        if missing:
            raise V2SchemaError(
                "v2_tables_missing",
                f"v2 tables missing: {missing}. Initialize with v2_schema.sql first.",
                details={"missing": missing},
            )
        actual_checksum = await _schema_migration_checksum(connection)
        if not actual_checksum:
            raise V2SchemaError(
                "v2_schema_migrations_empty",
                "schema_migrations is empty: v2 schema is not initialized.",
            )
        if actual_checksum != expected_checksum:
            raise V2SchemaError(
                "v2_schema_checksum_mismatch",
                "v2 schema checksum mismatch. DB may be from a different schema version.",
                details={"expected": expected_checksum, "actual": actual_checksum},
            )
        async with connection.execute("PRAGMA integrity_check") as cursor:
            integrity = (await cursor.fetchone())[0]
        if integrity != "ok":
            raise V2SchemaError(
                "v2_integrity_check_failed",
                "v2 DB integrity_check failed.",
                details={"integrity_check": integrity},
            )
    return {
        "db_version": "v2",
        "schema_checksum": expected_checksum,
        "required_tables": sorted(REQUIRED_V2_TABLES),
        "integrity_check": "ok",
    }


async def initialize_or_verify_v2_schema(sqlite_path: Path, *, schema_path: Path = V2_SCHEMA_PATH) -> dict[str, Any]:
    if not sqlite_path.exists():
        await apply_v2_schema(sqlite_path, schema_path=schema_path)
    return await verify_v2_schema(sqlite_path, schema_path=schema_path)
