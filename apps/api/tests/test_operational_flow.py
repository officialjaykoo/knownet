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


def test_page_graph_snapshot_restore_operational_flow(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created_pages = {}
        for slug, title in (
            ("project-alpha", "Project Alpha"),
            ("project-beta", "Project Beta"),
            ("restore-drill", "Restore Drill"),
        ):
            created = client.post("/api/pages", json={"slug": slug, "title": title})
            assert created.status_code == 200
            created_pages[slug] = created.json()["data"]

        page_markdown = {
            "project-alpha": _page_markdown(
                slug="project-alpha",
                title="Project Alpha",
                page_id="page_project_alpha",
                body=(
                    "# Project Alpha\n\n"
                    "Alpha is the operating hub for [[Project Beta]] and [[Citation Review]].\n\n"
                    "## Decisions\n\n"
                    "Keep .tar.gz snapshots before large maintenance work. [^msg-alpha]\n\n"
                    "[^msg-alpha]: Operational source."
                ),
            ),
            "project-beta": _page_markdown(
                slug="project-beta",
                title="Project Beta",
                page_id="page_project_beta",
                body=(
                    "# Project Beta\n\n"
                    "Beta links back to [[Project Alpha]] and tracks [[Restore Drill]].\n\n"
                    "## Worklog\n\n"
                    "Graph rebuild should stay idempotent after repeated page updates."
                ),
            ),
            "restore-drill": _page_markdown(
                slug="restore-drill",
                title="Restore Drill",
                page_id="page_restore_drill",
                body=(
                    "# Restore Drill\n\n"
                    "Restore drills prove that snapshots can recover pages and SQLite together.\n\n"
                    "- Check graph after restore\n"
                    "- Run verify-index\n"
                ),
            ),
        }
        for slug, markdown in page_markdown.items():
            page_path = app.state.settings.data_dir / "pages" / f"{slug}.md"
            page_path.write_text(markdown, encoding="utf-8")
            page_id = f"page_{slug.replace('-', '_')}"
            asyncio.run(
                app.state.rust_core.request(
                    "index_page",
                    {
                        "sqlite_path": str(app.state.settings.sqlite_path),
                        "path": str(page_path),
                        "page_id": page_id,
                        "revision_id": created_pages[slug]["revision_id"],
                        "indexed_at": "2026-05-02T00:00:00Z",
                    },
                )
            )

        rebuilt = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt.status_code == 200
        assert rebuilt.json()["data"]["failed"] == 0

        graph = client.get("/api/graph", params={"node_type": "page,unresolved,tag", "limit": 50})
        assert graph.status_code == 200
        graph_data = graph.json()["data"]
        node_ids = {node["id"] for node in graph_data["nodes"]}
        assert {"page:page_project_alpha", "page:page_project_beta", "page:page_restore_drill"}.issubset(node_ids)
        assert any(edge["edge_type"] == "page_link" for edge in graph_data["edges"])

        snapshot = client.post("/api/maintenance/snapshots")
        assert snapshot.status_code == 200
        snapshot_name = snapshot.json()["data"]["name"]
        assert snapshot_name.endswith(".tar.gz")

        alpha_path = app.state.settings.data_dir / "pages" / "project-alpha.md"
        beta_path = app.state.settings.data_dir / "pages" / "project-beta.md"
        assert alpha_path.exists()
        assert beta_path.exists()
        alpha_path.write_text("# Corrupted\n\nThis should be restored.", encoding="utf-8")
        beta_path.unlink()

        restored = client.post("/api/maintenance/restore", json={"snapshot_name": snapshot_name})
        assert restored.status_code == 200
        assert "Project Alpha" in alpha_path.read_text(encoding="utf-8")
        assert beta_path.exists()

        locks = client.get("/api/maintenance/locks")
        assert locks.status_code == 200
        assert locks.json()["data"]["locks"] == []

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200
        issue_codes = {issue["code"] for issue in verify.json()["data"]["issues"]}
        assert "page_file_missing" not in issue_codes

        rebuilt_after_restore = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt_after_restore.status_code == 200
        assert rebuilt_after_restore.json()["data"]["failed"] == 0

        restored_graph = client.get("/api/graph", params={"node_type": "page", "limit": 20})
        assert restored_graph.status_code == 200
        restored_node_ids = {node["id"] for node in restored_graph.json()["data"]["nodes"]}
        assert {"page:page_project_alpha", "page:page_project_beta", "page:page_restore_drill"}.issubset(restored_node_ids)
    get_settings.cache_clear()
