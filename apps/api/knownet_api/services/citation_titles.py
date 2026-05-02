from __future__ import annotations

import re
from pathlib import Path

import aiosqlite

from ..db.sqlite import fetch_all


def _strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    return markdown[end + 5 :] if end != -1 else markdown


def _title_from_source_file(path: str | None) -> str | None:
    if not path:
        return None
    source_path = Path(path)
    if not source_path.exists():
        return None
    text = _strip_frontmatter(source_path.read_text(encoding="utf-8"))
    for line in text.splitlines():
        clean = re.sub(r"^[#>*\-\s]+", "", line).strip()
        if clean:
            return clean[:120]
    return None


def _fallback_title(citation_key: str) -> str:
    match = re.match(r"^msg[_-](\d{8})[_-](\d{6})", citation_key)
    if match:
        date, time = match.groups()
        return f"Message {date[:4]}-{date[4:6]}-{date[6:8]} {time[:2]}:{time[2:4]}"
    return citation_key


async def ensure_citation_display_titles(sqlite_path: Path) -> None:
    async with aiosqlite.connect(sqlite_path) as connection:
        columns = await connection.execute_fetchall("PRAGMA table_info(citations)")
        names = {row[1] for row in columns}
        if "display_title" not in names:
            await connection.execute("ALTER TABLE citations ADD COLUMN display_title TEXT")
            await connection.commit()


async def backfill_citation_display_titles(sqlite_path: Path) -> int:
    await ensure_citation_display_titles(sqlite_path)
    rows = await fetch_all(
        sqlite_path,
        "SELECT c.citation_key, m.path AS message_path "
        "FROM citations c LEFT JOIN messages m ON m.id = c.citation_key "
        "WHERE c.display_title IS NULL OR TRIM(c.display_title) = '' "
        "GROUP BY c.citation_key, m.path",
        (),
    )
    updated = 0
    async with aiosqlite.connect(sqlite_path) as connection:
        for row in rows:
            title = _title_from_source_file(row["message_path"]) or _fallback_title(row["citation_key"])
            cursor = await connection.execute(
                "UPDATE citations SET display_title = ? WHERE citation_key = ? AND (display_title IS NULL OR TRIM(display_title) = '')",
                (title, row["citation_key"]),
            )
            updated += cursor.rowcount if cursor.rowcount else 0
        await connection.commit()
    return updated

