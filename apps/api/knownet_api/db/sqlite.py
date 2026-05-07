from pathlib import Path
from typing import Any
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite


async def connect(sqlite_path: Path, *, read_only: bool = False) -> aiosqlite.Connection:
    uri = f"file:{sqlite_path}?mode=ro" if read_only else str(sqlite_path)
    connection = await aiosqlite.connect(uri, uri=read_only)
    connection.row_factory = aiosqlite.Row
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("PRAGMA busy_timeout = 5000")
    if not read_only:
        await connection.execute("PRAGMA journal_mode = WAL")
    return connection


@asynccontextmanager
async def transaction(sqlite_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    connection = await connect(sqlite_path)
    try:
        await connection.execute("BEGIN")
        yield connection
        await connection.commit()
    except Exception:
        await connection.rollback()
        raise
    finally:
        await connection.close()


async def fetch_one(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    connection = await connect(sqlite_path, read_only=True)
    try:
        async with connection.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
    finally:
        await connection.close()


async def fetch_all(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    connection = await connect(sqlite_path, read_only=True)
    try:
        async with connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    finally:
        await connection.close()


async def execute(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> None:
    connection = await connect(sqlite_path)
    try:
        await connection.execute(query, params)
        await connection.commit()
    finally:
        await connection.close()
