import json
import re
from pathlib import Path
from typing import Any

import aiosqlite


def _read_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].strip()
    body = text[end + 4 :].lstrip()
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields, body


def build_ai_state_for_page(page_path: Path) -> dict[str, Any]:
    text = page_path.read_text(encoding="utf-8")
    frontmatter, body = _read_frontmatter(text)
    title = frontmatter.get("title") or page_path.stem.replace("-", " ").title()
    slug = frontmatter.get("slug") or page_path.stem
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    headings = [line.lstrip("#").strip() for line in lines if line.startswith("#")]
    summary_source = " ".join(lines[:6])
    summary = re.sub(r"\s+", " ", summary_source).strip()
    if not summary:
        summary = title
    return {
        "page_id": f"page_{slug.replace('-', '_')}",
        "slug": slug,
        "title": title,
        "source_path": str(page_path),
        "state_json": {
            "schema_version": 1,
            "summary": summary,
            "sections": [{"heading": heading} for heading in headings],
            "source": {"slug": slug},
        },
    }


async def ensure_legacy_ai_state_schema(sqlite_path: Path) -> None:
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS suggestions (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
              message_id TEXT NOT NULL,
              path TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_state_pages (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              page_id TEXT NOT NULL,
              slug TEXT NOT NULL,
              title TEXT NOT NULL,
              source_path TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              state_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(vault_id, page_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ai_state_pages_vault_updated
              ON ai_state_pages(vault_id, updated_at);
            """
        )
        await connection.commit()
