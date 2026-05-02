from pathlib import Path
from typing import Any

import aiosqlite


async def fetch_one(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    async with aiosqlite.connect(sqlite_path) as connection:
        connection.row_factory = aiosqlite.Row
        async with connection.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def fetch_all(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    async with aiosqlite.connect(sqlite_path) as connection:
        connection.row_factory = aiosqlite.Row
        async with connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def execute(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> None:
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(query, params)
        await connection.commit()
