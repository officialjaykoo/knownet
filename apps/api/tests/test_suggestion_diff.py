import asyncio
from types import SimpleNamespace

import aiosqlite

from knownet_api.routes.suggestions import _line_changes


class _FakeRustCore:
    async def request(self, cmd, params):
        assert cmd == "reject_suggestion"
        async with aiosqlite.connect(params["sqlite_path"]) as connection:
            await connection.execute(
                "UPDATE suggestions SET status = 'rejected', updated_at = ? WHERE id = ?",
                (params["rejected_at"], params["suggestion_id"]),
            )
            await connection.commit()
        return {"suggestion_id": params["suggestion_id"], "status": "rejected"}


def test_line_changes_marks_additions_and_removals():
    changes = _line_changes("one\ntwo", "one\nthree")
    assert {"type": "removed", "text": "two"} in changes
    assert {"type": "added", "text": "three"} in changes


async def _seed_reject_db(sqlite_path):
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(
            "CREATE TABLE suggestions (id TEXT, job_id TEXT, message_id TEXT, path TEXT, title TEXT, status TEXT, created_at TEXT, updated_at TEXT)"
        )
        await connection.execute(
            "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, action TEXT, actor_type TEXT, actor_id TEXT, session_id TEXT, ip_hash TEXT, user_agent_hash TEXT, target_type TEXT, target_id TEXT, before_revision_id TEXT, after_revision_id TEXT, model_provider TEXT, model_name TEXT, model_version TEXT, prompt_version TEXT, metadata_json TEXT)"
        )
        await connection.execute(
            "INSERT INTO suggestions VALUES ('sug_1', 'job_1', 'msg_1', 'suggestion.md', 'Suggestion', 'pending', 'now', 'now')"
        )
        await connection.commit()


def test_reject_endpoint_updates_status(tmp_path):
    from fastapi.testclient import TestClient
    from knownet_api.main import app

    sqlite_path = tmp_path / "knownet.db"
    asyncio.run(_seed_reject_db(sqlite_path))

    app.state.settings = SimpleNamespace(
        sqlite_path=sqlite_path,
        write_requests_per_minute=20,
        public_mode=False,
        admin_token=None,
    )
    app.state.rust_core = _FakeRustCore()
    client = TestClient(app)
    response = client.post("/api/suggestions/sug_1/reject", json={"reason": "not useful"})

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "rejected"
