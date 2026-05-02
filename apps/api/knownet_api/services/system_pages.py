from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite
from fastapi import HTTPException

from ..db.sqlite import fetch_all, fetch_one


ONBOARDING_START_PAGES = [
    {
        "slug": "start-here-for-external-ai-agents",
        "title": "Start Here For External AI Agents",
        "required": True,
        "reason": "First entry point: product purpose, agent role, safe read order, and contribution boundaries.",
    },
    {
        "slug": "what-knownet-is-and-is-not",
        "title": "What KnowNet Is And Is Not",
        "required": True,
        "reason": "Clarifies the product boundary before an agent suggests unrelated features.",
    },
    {
        "slug": "external-ai-first-30-minutes",
        "title": "External AI First 30 Minutes",
        "required": True,
        "reason": "Gives a bounded first-session checklist and API order.",
    },
    {
        "slug": "how-to-contribute-safely",
        "title": "How To Contribute Safely",
        "required": True,
        "reason": "Explains dry-run, finding format, scope limits, and safe handoff.",
    },
    {
        "slug": "current-priorities-for-ai-contributors",
        "title": "Current Priorities For AI Contributors",
        "required": True,
        "reason": "Shows what kind of help is valuable right now.",
    },
]

MANAGED_SEED_PAGES = [
    {
        "slug": "knownet-overview",
        "description": "Phase 8 seed page: product overview and current project shape.",
    },
    {
        "slug": "current-implementation-state",
        "description": "Phase 8 seed page: current implementation state for external agents.",
    },
    {
        "slug": "architecture-boundaries",
        "description": "Phase 8 seed page: component boundaries and ownership.",
    },
    {
        "slug": "known-risks-and-review-targets",
        "description": "Phase 8 seed page: known risks and review focus areas.",
    },
    {
        "slug": "ai-review-writing-guide",
        "description": "Phase 8 seed page: finding format and review expectations.",
    },
    {
        "slug": "context-bundle-policy",
        "description": "Phase 8 seed page: context bundle include/exclude policy.",
    },
    {
        "slug": "codex-operating-notes",
        "description": "Phase 8 seed page: Codex operating guidance.",
    },
    {
        "slug": "development-direction",
        "description": "Phase 8 seed page: current development direction.",
    },
    {
        "slug": "quality-hardening-roadmap",
        "description": "Phase 8 seed page: quality hardening priorities.",
    },
    {
        "slug": "operational-security-and-access",
        "description": "Phase 8 seed page: operational security and access model.",
    },
    {
        "slug": "review-to-code-loop",
        "description": "Phase 8 seed page: review to implementation workflow.",
    },
    {
        "slug": "ai-agent-collaboration-flow",
        "description": "Phase 8 seed page: AI agent collaboration workflow.",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def system_fields(row: dict | None) -> dict:
    if not row:
        return {"system_kind": None, "system_tier": None, "system_locked": False}
    return {
        "system_kind": row.get("system_kind") or row.get("kind"),
        "system_tier": row.get("system_tier") or row.get("tier"),
        "system_locked": bool(row.get("system_locked") if "system_locked" in row else row.get("locked")),
    }


async def ensure_system_pages_schema(sqlite_path: Path) -> None:
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS system_pages (
              page_id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              tier INTEGER NOT NULL DEFAULT 1,
              locked INTEGER NOT NULL DEFAULT 1,
              owner TEXT NOT NULL DEFAULT 'system',
              description TEXT,
              registered_at_phase TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_system_pages_kind
              ON system_pages(kind, tier, locked);
            """
        )
        await connection.commit()


async def register_onboarding_pages(sqlite_path: Path) -> None:
    await ensure_system_pages_schema(sqlite_path)
    now = utc_now()
    slugs = [item["slug"] for item in ONBOARDING_START_PAGES]
    rows = await fetch_all(
        sqlite_path,
        "SELECT id, slug FROM pages WHERE status = 'active' AND slug IN ({})".format(",".join("?" for _ in slugs)),
        tuple(slugs),
    )
    reason_by_slug = {item["slug"]: item["reason"] for item in ONBOARDING_START_PAGES}
    async with aiosqlite.connect(sqlite_path) as connection:
        for row in rows:
            await connection.execute(
                "INSERT INTO system_pages (page_id, kind, tier, locked, owner, description, registered_at_phase, created_at, updated_at) "
                "VALUES (?, 'onboarding', 1, 1, 'system', ?, 'phase_14', ?, ?) "
                "ON CONFLICT(page_id) DO UPDATE SET kind = excluded.kind, tier = excluded.tier, locked = excluded.locked, "
                "owner = excluded.owner, description = excluded.description, registered_at_phase = excluded.registered_at_phase, updated_at = excluded.updated_at",
                (row["id"], reason_by_slug.get(row["slug"]), now, now),
            )
        await connection.commit()


async def register_managed_seed_pages(sqlite_path: Path) -> None:
    await ensure_system_pages_schema(sqlite_path)
    now = utc_now()
    slugs = [item["slug"] for item in MANAGED_SEED_PAGES]
    rows = await fetch_all(
        sqlite_path,
        "SELECT id, slug FROM pages WHERE status = 'active' AND slug IN ({})".format(",".join("?" for _ in slugs)),
        tuple(slugs),
    )
    description_by_slug = {item["slug"]: item["description"] for item in MANAGED_SEED_PAGES}
    async with aiosqlite.connect(sqlite_path) as connection:
        for row in rows:
            await connection.execute(
                "INSERT INTO system_pages (page_id, kind, tier, locked, owner, description, registered_at_phase, created_at, updated_at) "
                "VALUES (?, 'managed', 2, 0, 'admin', ?, 'phase_14', ?, ?) "
                "ON CONFLICT(page_id) DO UPDATE SET kind = excluded.kind, tier = excluded.tier, locked = excluded.locked, "
                "owner = excluded.owner, description = excluded.description, registered_at_phase = excluded.registered_at_phase, updated_at = excluded.updated_at",
                (row["id"], description_by_slug.get(row["slug"]), now, now),
            )
        await connection.commit()


async def system_rows_for_page_ids(sqlite_path: Path, page_ids: Iterable[str]) -> dict[str, dict]:
    ids = [page_id for page_id in page_ids if page_id]
    if not ids:
        return {}
    rows = await fetch_all(
        sqlite_path,
        "SELECT page_id, kind AS system_kind, tier AS system_tier, locked AS system_locked "
        "FROM system_pages WHERE page_id IN ({})".format(",".join("?" for _ in ids)),
        tuple(ids),
    )
    return {row["page_id"]: system_fields(row) for row in rows}


async def locked_system_page_by_slug(sqlite_path: Path, slug: str) -> dict | None:
    return await fetch_one(
        sqlite_path,
        "SELECT p.id AS page_id, p.slug, sp.kind AS system_kind, sp.tier AS system_tier, sp.locked AS system_locked "
        "FROM pages p JOIN system_pages sp ON sp.page_id = p.id "
        "WHERE p.slug = ? AND sp.locked = 1",
        (slug,),
    )


async def locked_system_page_by_id(sqlite_path: Path, page_id: str) -> dict | None:
    return await fetch_one(
        sqlite_path,
        "SELECT p.id AS page_id, p.slug, sp.kind AS system_kind, sp.tier AS system_tier, sp.locked AS system_locked "
        "FROM pages p JOIN system_pages sp ON sp.page_id = p.id "
        "WHERE p.id = ? AND sp.locked = 1",
        (page_id,),
    )


async def raise_if_system_page_locked(sqlite_path: Path, *, slug: str | None = None, page_id: str | None = None) -> None:
    await ensure_system_pages_schema(sqlite_path)
    row = None
    if page_id:
        row = await locked_system_page_by_id(sqlite_path, page_id)
    if not row and slug:
        row = await locked_system_page_by_slug(sqlite_path, slug)
    if not row and slug not in {item["slug"] for item in ONBOARDING_START_PAGES}:
        return
    details = {
        "slug": row["slug"] if row else slug,
        "page_id": row["page_id"] if row else page_id,
        "kind": row["system_kind"] if row else "onboarding",
        "tier": row["system_tier"] if row else 1,
    }
    raise HTTPException(
        status_code=423,
        detail={
            "code": "system_page_locked",
            "message": "System page is locked",
            "details": details,
        },
    )
