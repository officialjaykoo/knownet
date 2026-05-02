import pytest
from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app

pytestmark = pytest.mark.slow


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_import_graph_snapshot_restore_operational_flow(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    source_dir = tmp_path / "long-running-vault"
    source_dir.mkdir()
    (source_dir / "Project Alpha.md").write_text(
        "# Project Alpha\n\n"
        "Alpha is the operating hub for [[Project Beta]] and [[Citation Review]].\n\n"
        "## Decisions\n\n"
        "Keep local-first backups before large imports. [^msg-alpha]\n\n"
        "[^msg-alpha]: Imported operational note.",
        encoding="utf-8",
    )
    (source_dir / "Project Beta.md").write_text(
        "# Project Beta\n\n"
        "Beta links back to [[Project Alpha]] and tracks [[Restore Drill]].\n\n"
        "## Worklog\n\n"
        "Graph rebuild should stay idempotent after repeated imports.",
        encoding="utf-8",
    )
    (source_dir / "Restore Drill.md").write_text(
        "# Restore Drill\n\n"
        "Restore drills prove that snapshots can recover Markdown and SQLite together.\n\n"
        "- Check graph after restore\n"
        "- Run verify-index\n",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        imported = client.post(
            "/api/maintenance/obsidian/import",
            json={"source_dir": str(source_dir), "dry_run": False},
        )
        assert imported.status_code == 200
        import_data = imported.json()["data"]
        assert import_data["summary"]["create"] == 3
        assert import_data["summary"]["failed"] == 0

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
