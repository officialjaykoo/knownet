import asyncio
from types import SimpleNamespace

import aiosqlite
from fastapi.testclient import TestClient

from knownet_api.main import app
from knownet_api.services.rust_core import RustCoreError


class _FakeRustCore:
    async def request(self, cmd, params):
        if cmd == "create_page":
            data_dir = params["data_dir"]
            page_path = f"{data_dir}/pages/{params['slug']}.md"
            revision_path = f"{data_dir}/revisions/{params['page_id']}/{params['revision_id']}.md"
            markdown = (
                "---\n"
                "schema_version: 1\n"
                f"id: {params['page_id']}\n"
                f"title: {params['title']}\n"
                f"slug: {params['slug']}\n"
                "status: active\n"
                f"created_at: {params['created_at']}\n"
                f"updated_at: {params['created_at']}\n"
                "---\n\n"
                f"# {params['title']}\n"
            )
            from pathlib import Path

            Path(page_path).parent.mkdir(parents=True, exist_ok=True)
            Path(page_path).write_text(markdown, encoding="utf-8")
            Path(revision_path).parent.mkdir(parents=True, exist_ok=True)
            Path(revision_path).write_text(markdown, encoding="utf-8")
            async with aiosqlite.connect(params["sqlite_path"]) as connection:
                await connection.execute(
                    "INSERT INTO pages (id, title, slug, path, current_revision_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                    (params["page_id"], params["title"], params["slug"], page_path, params["revision_id"], params["created_at"], params["created_at"]),
                )
                await connection.execute(
                    "INSERT INTO revisions (id, page_id, path, author_type, change_note, created_at) VALUES (?, ?, ?, 'human', 'Created from unresolved link', ?)",
                    (params["revision_id"], params["page_id"], revision_path, params["created_at"]),
                )
                await connection.commit()
            return {"slug": params["slug"], "title": params["title"], "path": page_path, "revision_id": params["revision_id"], "revision_path": revision_path}
        return {"cmd": cmd, "failed": 0}


class _FailingIndexRustCore:
    async def request(self, cmd, params):
        if cmd == "create_page":
            return await _FakeRustCore().request(cmd, params)
        if cmd == "index_page":
            raise RustCoreError("index_failed", "Index failed")
        return {"cmd": cmd, "failed": 0}


async def _seed_links(sqlite_path):
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute("CREATE TABLE pages (id TEXT, slug TEXT, title TEXT, path TEXT)")
        await connection.execute(
            "CREATE TABLE links (raw TEXT, target TEXT, display TEXT, status TEXT, revision_id TEXT, page_id TEXT, source_path TEXT)"
        )
        await connection.execute(
            "INSERT INTO pages (id, slug, title, path) VALUES ('page_a', 'a', 'A', 'data/pages/a.md')"
        )
        await connection.execute(
            "INSERT INTO links (raw, target, display, status, revision_id, page_id, source_path) VALUES ('[[b]]', 'b', NULL, 'unresolved', 'rev_1', 'page_a', 'data/pages/a.md')"
        )
        await connection.commit()


def test_page_links_and_backlinks(tmp_path):
    sqlite_path = tmp_path / "knownet.db"
    asyncio.run(_seed_links(sqlite_path))
    app.state.settings = type("Settings", (), {"sqlite_path": sqlite_path})()
    client = TestClient(app)

    links = client.get("/api/pages/a/links")
    assert links.status_code == 200
    assert links.json()["data"]["unresolved"][0]["target"] == "b"

    backlinks = client.get("/api/pages/b/backlinks")
    assert backlinks.status_code == 200
    assert backlinks.json()["data"]["backlinks"][0]["source_slug"] == "a"


async def _seed_create_page_db(sqlite_path):
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(
            "CREATE TABLE pages (id TEXT PRIMARY KEY, title TEXT, slug TEXT UNIQUE, path TEXT, current_revision_id TEXT, status TEXT, created_at TEXT, updated_at TEXT)"
        )
        await connection.execute(
            "CREATE TABLE revisions (id TEXT PRIMARY KEY, page_id TEXT, path TEXT, author_type TEXT, change_note TEXT, created_at TEXT)"
        )
        await connection.execute(
            "CREATE TABLE citations (id TEXT PRIMARY KEY, page_id TEXT, revision_id TEXT, citation_key TEXT, validation_status TEXT, display_title TEXT)"
        )
        await connection.execute(
            "CREATE TABLE messages (id TEXT PRIMARY KEY, path TEXT)"
        )
        await connection.execute(
            "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, action TEXT, actor_type TEXT, actor_id TEXT, session_id TEXT, ip_hash TEXT, user_agent_hash TEXT, target_type TEXT, target_id TEXT, before_revision_id TEXT, after_revision_id TEXT, model_provider TEXT, model_name TEXT, model_version TEXT, prompt_version TEXT, metadata_json TEXT)"
        )
        await connection.commit()


def test_create_page_from_link(tmp_path):
    sqlite_path = tmp_path / "knownet.db"
    data_dir = tmp_path / "data"
    asyncio.run(_seed_create_page_db(sqlite_path))
    app.state.settings = SimpleNamespace(
        sqlite_path=sqlite_path,
        data_dir=data_dir,
        public_mode=False,
        admin_token=None,
        write_requests_per_minute=20,
        max_slug_chars=96,
        max_title_chars=160,
    )
    app.state.rust_core = _FakeRustCore()
    client = TestClient(app)

    created = client.post("/api/pages", json={"slug": "missing-page"})

    assert created.status_code == 200
    data = created.json()["data"]
    assert data["slug"] == "missing-page"
    assert data["index_status"] == {"status": "indexed"}
    assert data["graph_rebuild"]["status"] == "rebuilt"
    assert (data_dir / "pages" / "missing-page.md").exists()


def test_create_page_reports_index_failure(tmp_path):
    sqlite_path = tmp_path / "knownet.db"
    data_dir = tmp_path / "data"
    asyncio.run(_seed_create_page_db(sqlite_path))
    app.state.settings = SimpleNamespace(
        sqlite_path=sqlite_path,
        data_dir=data_dir,
        public_mode=False,
        admin_token=None,
        write_requests_per_minute=20,
        max_slug_chars=96,
        max_title_chars=160,
    )
    app.state.rust_core = _FailingIndexRustCore()
    client = TestClient(app)

    created = client.post("/api/pages", json={"slug": "index-warning"})

    assert created.status_code == 200
    data = created.json()["data"]
    assert data["slug"] == "index-warning"
    assert data["index_status"]["status"] == "failed"
    assert data["index_status"]["code"] == "index_failed"
    assert data["graph_rebuild"] == {"status": "skipped", "reason": "index_not_completed"}
