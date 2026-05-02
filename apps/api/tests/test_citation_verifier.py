import asyncio

import aiosqlite

from knownet_api.services.citation_verifier import CitationVerifier


class _FakeRustCore:
    async def request(self, cmd, params):
        assert cmd == "update_citation_validation_status"
        async with aiosqlite.connect(params["sqlite_path"]) as connection:
            await connection.execute(
                "UPDATE citations SET validation_status = ? WHERE id = ?",
                (params["status"], params["citation_id"]),
            )
            await connection.commit()
        return {"citation_id": params["citation_id"], "validation_status": params["status"]}


async def _seed_db(sqlite_path, message_path):
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute("CREATE TABLE messages (id TEXT, path TEXT)")
        await connection.execute(
            "CREATE TABLE citations (id INTEGER PRIMARY KEY AUTOINCREMENT, page_id TEXT, revision_id TEXT, citation_key TEXT, validation_status TEXT)"
        )
        await connection.execute("INSERT INTO messages (id, path) VALUES ('msg_1', ?)", (str(message_path),))
        await connection.execute(
            "INSERT INTO citations (page_id, revision_id, citation_key, validation_status) VALUES ('page_1', 'rev_1', 'msg_1', 'unchecked')"
        )
        await connection.execute(
            "INSERT INTO citations (page_id, revision_id, citation_key, validation_status) VALUES ('page_1', 'rev_1', 'msg_missing', 'unchecked')"
        )
        await connection.commit()


def test_citation_verifier_updates_statuses(tmp_path):
    sqlite_path = tmp_path / "knownet.db"
    message_path = tmp_path / "msg.md"
    message_path.write_text("---\nid: msg_1\n---\n\nNEAT topology growth test", encoding="utf-8")
    asyncio.run(_seed_db(sqlite_path, message_path))

    verifier = CitationVerifier(sqlite_path=sqlite_path, rust=_FakeRustCore())
    result = asyncio.run(
        verifier.verify_page(
            page_id="page_1",
            revision_id="rev_1",
            page_markdown="# NEAT\n\nNEAT topology growth test [^msg_1]",
        )
    )

    statuses = {item["citation_key"]: item["validation_status"] for item in result["statuses"]}
    assert statuses["msg_1"] == "supported"
    assert statuses["msg_missing"] == "unsupported"


def test_verify_index_reports_bad_citations(tmp_path):
    import asyncio
    from types import SimpleNamespace

    import aiosqlite
    from fastapi.testclient import TestClient
    from knownet_api.main import app

    async def seed(sqlite_path):
        async with aiosqlite.connect(sqlite_path) as connection:
            await connection.execute(
                "CREATE TABLE pages (id TEXT, slug TEXT, path TEXT, current_revision_id TEXT)"
            )
            await connection.execute("CREATE TABLE sections (page_id TEXT, revision_id TEXT)")
            await connection.execute("CREATE TABLE messages (id TEXT)")
            await connection.execute(
                "CREATE TABLE citations (page_id TEXT, revision_id TEXT, citation_key TEXT, validation_status TEXT)"
            )
            await connection.execute(
                "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, action TEXT, actor_type TEXT, actor_id TEXT, session_id TEXT, ip_hash TEXT, user_agent_hash TEXT, target_type TEXT, target_id TEXT, before_revision_id TEXT, after_revision_id TEXT, model_provider TEXT, model_name TEXT, model_version TEXT, prompt_version TEXT, metadata_json TEXT)"
            )
            await connection.execute("INSERT INTO messages (id) VALUES ('msg_1')")
            await connection.execute(
                "INSERT INTO citations VALUES ('page_1', 'rev_1', 'msg_1', 'unsupported')"
            )
            await connection.execute(
                "INSERT INTO citations VALUES ('page_1', 'rev_1', 'msg_missing', 'unchecked')"
            )
            await connection.commit()

    sqlite_path = tmp_path / "knownet.db"
    data_dir = tmp_path / "data"
    (data_dir / "pages").mkdir(parents=True)
    asyncio.run(seed(sqlite_path))
    app.state.settings = SimpleNamespace(
        sqlite_path=sqlite_path,
        data_dir=data_dir,
        public_mode=False,
        admin_token=None,
    )
    client = TestClient(app)

    response = client.get("/api/maintenance/verify-index")

    assert response.status_code == 200
    codes = {issue["code"] for issue in response.json()["data"]["issues"]}
    assert "citation_unsupported" in codes
    assert "citation_source_missing" in codes
