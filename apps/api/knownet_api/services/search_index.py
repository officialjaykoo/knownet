from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from ..db.sqlite import fetch_all, fetch_one
from ..paths import page_storage_dir

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def escape_fts_query(query: str) -> str | None:
    words = re.findall(r"\w+", query, re.UNICODE)
    if not words:
        return None
    return " ".join(f'"{word}"' for word in words)


def _resolve_page_path(data_dir: Path, row: dict[str, Any]) -> Path:
    candidates = []
    stored_value = row.get("path")
    if stored_value:
        stored = Path(stored_value)
        candidates.append(stored)
        if not stored.is_absolute():
            candidates.append(data_dir / stored)
    if row.get("slug"):
        candidates.append(page_storage_dir(data_dir) / f"{row['slug']}.md")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1] if candidates else page_storage_dir(data_dir) / "missing.md"


async def fts5_available(sqlite_path: Path) -> bool:
    try:
        async with aiosqlite.connect(sqlite_path) as connection:
            await connection.execute("CREATE VIRTUAL TABLE temp._knownet_fts5_test USING fts5(x)")
            await connection.execute("DROP TABLE temp._knownet_fts5_test")
            await connection.commit()
        return True
    except Exception:
        logger.warning("SQLite FTS5 is unavailable", exc_info=True)
        return False


async def ensure_search_schema(sqlite_path: Path) -> dict[str, Any]:
    if not await fts5_available(sqlite_path):
        return {"fts": "unavailable", "reason": "fts5_unavailable"}
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS search_index_meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        await connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5("
            "page_id UNINDEXED, "
            "vault_id UNINDEXED, "
            "title, "
            "slug, "
            "body, "
            "tokenize = 'unicode61'"
            ")"
        )
        await connection.commit()
    return await search_index_status(sqlite_path)


async def search_index_status(sqlite_path: Path) -> dict[str, Any]:
    if not sqlite_path.exists():
        return {"fts": "unavailable", "indexed_pages": 0, "fallback": "like_markdown_scan", "reason": "sqlite_missing"}
    if not await fts5_available(sqlite_path):
        return {"fts": "unavailable", "indexed_pages": 0, "fallback": "like_markdown_scan", "reason": "fts5_unavailable"}
    table = await fetch_one(sqlite_path, "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'pages_fts'", ())
    if not table:
        return {"fts": "unavailable", "indexed_pages": 0, "fallback": "like_markdown_scan", "reason": "pages_fts_missing"}
    try:
        row = await fetch_one(sqlite_path, "SELECT COUNT(*) AS count FROM pages_fts", ())
    except Exception as error:
        return {"fts": "unavailable", "indexed_pages": 0, "fallback": "like_markdown_scan", "reason": f"pages_fts_error: {error}"}
    meta = await fetch_one(sqlite_path, "SELECT value, updated_at FROM search_index_meta WHERE key = 'pages_fts.last_rebuild_at'", ())
    count = int(row["count"] if row else 0)
    return {
        "fts": "ready" if count > 0 else "empty",
        "indexed_pages": count,
        "fallback": "like_markdown_scan",
        "last_rebuild_at": meta["value"] if meta else None,
    }


async def rebuild_pages_fts(sqlite_path: Path, data_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    schema = await ensure_search_schema(sqlite_path)
    if schema.get("fts") == "unavailable":
        return {"status": "unavailable", "indexed": 0, "skipped": 0, "failed": 0, "warnings": [schema.get("reason")], "duration_ms": 0}
    rows = await fetch_all(
        sqlite_path,
        "SELECT id, vault_id, title, slug, path FROM pages WHERE status = 'active' ORDER BY updated_at DESC, slug",
        (),
    )
    indexed = 0
    skipped = 0
    failed = 0
    warnings: list[dict[str, Any]] = []
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute("DELETE FROM pages_fts")
        for row in rows:
            path = _resolve_page_path(data_dir, row)
            if not path.exists():
                skipped += 1
                warnings.append({"code": "page_markdown_missing", "page_id": row["id"], "path": str(path).replace("\\", "/")})
                continue
            try:
                body = path.read_text(encoding="utf-8")
                await connection.execute(
                    "INSERT INTO pages_fts(page_id, vault_id, title, slug, body) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], row.get("vault_id") or "local-default", row["title"], row["slug"], body),
                )
                indexed += 1
            except Exception as error:
                failed += 1
                warnings.append({"code": "page_fts_index_failed", "page_id": row["id"], "error": str(error)})
                logger.warning("Failed to index page in FTS", exc_info=True)
        now = utc_now()
        await connection.execute(
            "INSERT INTO search_index_meta(key, value, updated_at) VALUES ('pages_fts.last_rebuild_at', ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (now, now),
        )
        await connection.commit()
    status = await search_index_status(sqlite_path)
    return {
        "status": "ready" if failed == 0 else "partial",
        "indexed": indexed,
        "skipped": skipped,
        "failed": failed,
        "warnings": warnings[:20],
        "search": status,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


async def verify_pages_fts(sqlite_path: Path) -> dict[str, Any]:
    status = await search_index_status(sqlite_path)
    if status.get("fts") == "unavailable":
        return {"ok": False, "status": status, "issues": [{"code": "fts_unavailable", "reason": status.get("reason")}], "summary": {"missing": 0, "orphaned": 0}}
    missing = await fetch_all(
        sqlite_path,
        "SELECT p.id, p.slug FROM pages p LEFT JOIN pages_fts f ON f.page_id = p.id "
        "WHERE p.status = 'active' AND f.page_id IS NULL ORDER BY p.slug LIMIT 100",
        (),
    )
    orphaned = await fetch_all(
        sqlite_path,
        "SELECT f.page_id, f.slug FROM pages_fts f LEFT JOIN pages p ON p.id = f.page_id "
        "WHERE p.id IS NULL OR p.status != 'active' ORDER BY f.slug LIMIT 100",
        (),
    )
    issues = [{"code": "fts_page_missing", "page_id": row["id"], "slug": row["slug"]} for row in missing]
    issues.extend({"code": "fts_page_orphaned", "page_id": row["page_id"], "slug": row["slug"]} for row in orphaned)
    return {
        "ok": not issues,
        "status": status,
        "issues": issues,
        "summary": {"missing": len(missing), "orphaned": len(orphaned), "indexed_pages": status.get("indexed_pages", 0)},
    }


async def sync_page_fts(
    sqlite_path: Path,
    *,
    page_id: str,
    vault_id: str,
    title: str,
    slug: str,
    body: str | None,
    active: bool = True,
) -> dict[str, Any]:
    try:
        schema = await ensure_search_schema(sqlite_path)
        if schema.get("fts") == "unavailable":
            return {"status": "skipped", "reason": schema.get("reason")}
        async with aiosqlite.connect(sqlite_path) as connection:
            await connection.execute("DELETE FROM pages_fts WHERE page_id = ?", (page_id,))
            if active and body is not None:
                await connection.execute(
                    "INSERT INTO pages_fts(page_id, vault_id, title, slug, body) VALUES (?, ?, ?, ?, ?)",
                    (page_id, vault_id, title, slug, body),
                )
            await connection.commit()
        return {"status": "synced" if active else "removed"}
    except Exception as error:
        logger.warning("FTS sync failed for page %s", page_id, exc_info=True)
        return {"status": "failed", "reason": str(error)}


async def remove_page_fts(sqlite_path: Path, page_id: str) -> dict[str, Any]:
    return await sync_page_fts(sqlite_path, page_id=page_id, vault_id="local-default", title="", slug="", body=None, active=False)
