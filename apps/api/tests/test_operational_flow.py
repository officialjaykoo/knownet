import asyncio

import pytest
from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app

pytestmark = pytest.mark.slow


def _page_markdown(*, slug: str, title: str, page_id: str, body: str) -> str:
    return (
        "---\n"
        "schema_version: 1\n"
        f"id: {page_id}\n"
        f"title: {title}\n"
        f"slug: {slug}\n"
        "status: active\n"
        "created_at: 2026-05-02T00:00:00Z\n"
        "updated_at: 2026-05-02T00:00:00Z\n"
        "---\n\n"
        f"{body}"
    )


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def _admin_headers():
    token = get_settings().admin_token
    return {"x-knownet-admin-token": token} if token else {}


def test_page_graph_snapshot_restore_operational_flow(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)

    with TestClient(app) as client:
        headers = _admin_headers()
        slug = "restore-drill"
        page_id = "page_restore_drill"
        created = client.post("/api/pages", json={"slug": slug, "title": "Restore Drill"}, headers=headers)
        assert created.status_code == 200

        page_path = app.state.settings.data_dir / "pages" / f"{slug}.md"
        page_path.write_text(
            _page_markdown(
                slug=slug,
                title="Restore Drill",
                page_id=page_id,
                body=(
                    "# Restore Drill\n\n"
                    "Restore drills prove that snapshots can recover pages and SQLite together.\n\n"
                    "- Check graph after restore\n"
                    "- Run verify-index\n"
                ),
            ),
            encoding="utf-8",
        )
        asyncio.run(
            app.state.rust_core.request(
                "index_page",
                {
                    "sqlite_path": str(app.state.settings.sqlite_path),
                    "path": str(page_path),
                    "page_id": page_id,
                    "revision_id": created.json()["data"]["revision_id"],
                    "indexed_at": "2026-05-02T00:00:00Z",
                },
            )
        )

        rebuilt = client.post("/api/graph/rebuild", json={"scope": "vault"}, headers=headers)
        assert rebuilt.status_code == 200
        assert rebuilt.json()["data"]["failed"] == 0

        graph = client.get("/api/graph", params={"node_type": "page", "limit": 50})
        assert graph.status_code == 200
        graph_data = graph.json()["data"]
        node_ids = {node["id"] for node in graph_data["nodes"]}
        assert "page:page_restore_drill" in node_ids

        snapshot = client.post("/api/maintenance/snapshots", headers=headers)
        assert snapshot.status_code == 200
        snapshot_name = snapshot.json()["data"]["name"]
        assert snapshot_name.endswith(".tar.gz")

        assert page_path.exists()
        page_path.write_text("# Corrupted\n\nThis should be restored.", encoding="utf-8")

        restored = client.post("/api/maintenance/restore", json={"snapshot_name": snapshot_name}, headers=headers)
        assert restored.status_code == 200
        assert "Restore Drill" in page_path.read_text(encoding="utf-8")

        locks = client.get("/api/maintenance/locks", headers=headers)
        assert locks.status_code == 200
        assert locks.json()["data"]["locks"] == []

        verify = client.get("/api/maintenance/verify-index", headers=headers)
        assert verify.status_code == 200
        issue_codes = {issue["code"] for issue in verify.json()["data"]["issues"]}
        assert "page_file_missing" not in issue_codes

        rebuilt_after_restore = client.post("/api/graph/rebuild", json={"scope": "vault"}, headers=headers)
        assert rebuilt_after_restore.status_code == 200
        assert rebuilt_after_restore.json()["data"]["failed"] == 0

        restored_graph = client.get("/api/graph", params={"node_type": "page", "limit": 20})
        assert restored_graph.status_code == 200
        restored_node_ids = {node["id"] for node in restored_graph.json()["data"]["nodes"]}
        assert "page:page_restore_drill" in restored_node_ids
    get_settings.cache_clear()
