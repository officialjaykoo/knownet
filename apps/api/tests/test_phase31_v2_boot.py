from __future__ import annotations

import asyncio
import sqlite3

import pytest

from knownet_api.config import get_settings
from knownet_api.db.v2_runtime import (
    REQUIRED_V2_TABLES,
    V2SchemaError,
    expected_v2_checksum,
    initialize_or_verify_v2_schema,
    verify_v2_schema,
)


def test_knownet_db_version_env_is_explicit(monkeypatch):
    monkeypatch.setenv("KNOWNET_DB_VERSION", "v2")
    get_settings.cache_clear()
    try:
        assert get_settings().knownet_db_version == "v2"
    finally:
        get_settings.cache_clear()


def test_initialize_or_verify_v2_schema_creates_clean_db(tmp_path):
    db_path = tmp_path / "knownet-v2.db"

    result = asyncio.run(initialize_or_verify_v2_schema(db_path))

    assert result["db_version"] == "v2"
    assert result["schema_checksum"] == expected_v2_checksum()
    assert result["integrity_check"] == "ok"
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert REQUIRED_V2_TABLES <= tables
        assert "collaboration_findings" not in tables
        assert "project_snapshot_packets" not in tables
        assert "model_review_runs" not in tables


def test_verify_v2_schema_fails_loudly_for_missing_tables(tmp_path):
    db_path = tmp_path / "broken-v2.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations (version, name, applied_at, checksum) VALUES (1, 'v2_clean_schema', '2026-05-08T00:00:00Z', ?)",
            (expected_v2_checksum(),),
        )

    with pytest.raises(V2SchemaError) as exc:
        asyncio.run(verify_v2_schema(db_path))

    assert exc.value.code == "v2_tables_missing"
    assert "reviews" in exc.value.details["missing"]


def test_verify_v2_schema_fails_loudly_for_checksum_mismatch(tmp_path):
    db_path = tmp_path / "knownet-v2.db"
    asyncio.run(initialize_or_verify_v2_schema(db_path))
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE schema_migrations SET checksum = 'bad-checksum' WHERE version = 1")

    with pytest.raises(V2SchemaError) as exc:
        asyncio.run(verify_v2_schema(db_path))

    assert exc.value.code == "v2_schema_checksum_mismatch"
    assert exc.value.details["expected"] == expected_v2_checksum()
    assert exc.value.details["actual"] == "bad-checksum"

