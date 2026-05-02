import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_graph_rebuild_creates_page_and_link_edges(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        alpha = client.post("/api/pages", json={"slug": "alpha", "title": "Alpha"})
        beta = client.post("/api/pages", json={"slug": "beta", "title": "Beta"})
        assert alpha.status_code == 200
        assert beta.status_code == 200

        db_path = app.state.settings.sqlite_path
        with sqlite3.connect(db_path) as connection:
            revision_id = connection.execute(
                "SELECT current_revision_id FROM pages WHERE id = ?",
                ("page_alpha",),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO links (page_id, revision_id, source_path, raw, target, display, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'unresolved', ?)",
                ("page_alpha", revision_id, "alpha.md", "Beta", "Beta", None, "now"),
            )
            connection.commit()

        rebuilt = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt.status_code == 200
        assert rebuilt.json()["data"]["failed"] == 0

        graph = client.get("/api/graph", params={"node_type": "page", "limit": 10})
        assert graph.status_code == 200
        data = graph.json()["data"]
        assert data["truncated"] is False
        assert data["total_node_count"] >= 2
        node_ids = {node["id"] for node in data["nodes"]}
        assert {"page:page_alpha", "page:page_beta"}.issubset(node_ids)
        assert any(edge["edge_type"] == "page_link" for edge in data["edges"])

        neighborhood = client.get("/api/graph/neighborhood/page:page_alpha")
        assert neighborhood.status_code == 200
        assert any(node["id"] == "page:page_beta" for node in neighborhood.json()["data"]["nodes"])
    get_settings.cache_clear()


def test_graph_layout_and_depth_errors(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "layout-page", "title": "Layout Page"})
        assert created.status_code == 200
        rebuilt = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt.status_code == 200

        too_deep = client.get("/api/graph/neighborhood/page:page_layout_page", params={"depth": 3})
        assert too_deep.status_code == 422
        assert too_deep.json()["detail"]["code"] == "graph_depth_exceeded"

        saved = client.post(
            "/api/graph/layout/nodes",
            json={
                "layout_key": "vault:local-default:default",
                "node_id": "page:page_layout_page",
                "x": 12.0,
                "y": 18.0,
                "pinned": True,
            },
        )
        assert saved.status_code == 200
        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            row = connection.execute(
                "SELECT pinned FROM graph_layout_cache WHERE node_id = ?",
                ("page:page_layout_page",),
            ).fetchone()
        assert row == (1,)
    get_settings.cache_clear()


def test_graph_core_signals_and_user_pin_survive_rebuild(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        overview = client.post("/api/pages", json={"slug": "neat-overview", "title": "NEAT Overview"})
        reference = client.post("/api/pages", json={"slug": "neat-reference", "title": "NEAT Reference"})
        notes = client.post("/api/pages", json={"slug": "field-notes", "title": "Field Notes"})
        assert overview.status_code == 200
        assert reference.status_code == 200
        assert notes.status_code == 200

        db_path = app.state.settings.sqlite_path
        with sqlite3.connect(db_path) as connection:
            overview_revision = connection.execute(
                "SELECT current_revision_id FROM pages WHERE id = ?",
                ("page_neat_overview",),
            ).fetchone()[0]
            reference_revision = connection.execute(
                "SELECT current_revision_id FROM pages WHERE id = ?",
                ("page_neat_reference",),
            ).fetchone()[0]
            connection.executemany(
                "INSERT INTO links (page_id, revision_id, source_path, raw, target, display, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'resolved', ?)",
                [
                    ("page_neat_overview", overview_revision, "neat-overview.md", "NEAT Reference", "NEAT Reference", None, "now"),
                    ("page_neat_overview", overview_revision, "neat-overview.md", "Field Notes", "Field Notes", None, "now"),
                    ("page_neat_reference", reference_revision, "neat-reference.md", "NEAT Overview", "NEAT Overview", None, "now"),
                ],
            )
            connection.commit()

        rebuilt = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt.status_code == 200
        graph = client.get("/api/graph", params={"node_type": "page", "limit": 10})
        assert graph.status_code == 200
        nodes = {node["id"]: node for node in graph.json()["data"]["nodes"]}
        assert nodes["page:page_neat_overview"]["meta"]["auto_core"] is True
        assert "title_keyword" in nodes["page:page_neat_overview"]["meta"]["core_reasons"]
        assert "many_outgoing_links" in nodes["page:page_neat_overview"]["meta"]["core_reasons"]

        pinned = client.post("/api/graph/pins/nodes", json={"node_id": "page:page_field_notes", "pinned": True})
        assert pinned.status_code == 200
        graph_after_pin = client.get("/api/graph", params={"node_type": "page", "limit": 10})
        pinned_nodes = {node["id"]: node for node in graph_after_pin.json()["data"]["nodes"]}
        assert pinned_nodes["page:page_field_notes"]["meta"]["user_pinned"] is True
        assert pinned_nodes["page:page_field_notes"]["meta"]["core"] is True

        rebuilt_again = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt_again.status_code == 200
        graph_after_rebuild = client.get("/api/graph", params={"node_type": "page", "limit": 10})
        rebuilt_nodes = {node["id"]: node for node in graph_after_rebuild.json()["data"]["nodes"]}
        assert rebuilt_nodes["page:page_field_notes"]["meta"]["user_pinned"] is True
    get_settings.cache_clear()


def test_page_rebuild_cleans_orphan_unresolved_nodes(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "cleanup", "title": "Cleanup"})
        assert created.status_code == 200
        db_path = app.state.settings.sqlite_path
        with sqlite3.connect(db_path) as connection:
            revision_id = connection.execute(
                "SELECT current_revision_id FROM pages WHERE id = ?",
                ("page_cleanup",),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO links (page_id, revision_id, source_path, raw, target, display, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'unresolved', ?)",
                ("page_cleanup", revision_id, "cleanup.md", "Missing", "Missing", None, "now"),
            )
            connection.commit()

        rebuilt = client.post("/api/graph/rebuild", json={"scope": "page", "page_id": "page_cleanup"})
        assert rebuilt.status_code == 200
        with sqlite3.connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM graph_nodes WHERE id = 'unresolved:missing'").fetchone()[0] == 1
            connection.execute("DELETE FROM links WHERE page_id = ?", ("page_cleanup",))
            connection.commit()

        rebuilt_again = client.post("/api/graph/rebuild", json={"scope": "page", "page_id": "page_cleanup"})
        assert rebuilt_again.status_code == 200
        with sqlite3.connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM graph_nodes WHERE id = 'unresolved:missing'").fetchone()[0] == 0

        missing_page = client.post("/api/graph/rebuild", json={"scope": "page"})
        assert missing_page.status_code == 422
        graph = client.get("/api/graph")
        assert graph.json()["data"]["graph_stale"] is False
    get_settings.cache_clear()


def test_tombstone_removes_page_from_graph_and_preserves_click_slug(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "map-page", "title": "Map Page"})
        assert created.status_code == 200

        rebuilt = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert rebuilt.status_code == 200
        graph = client.get("/api/graph", params={"node_type": "page", "limit": 10})
        assert graph.status_code == 200
        node = next(item for item in graph.json()["data"]["nodes"] if item["id"] == "page:page_map_page")
        assert node["meta"]["slug"] == "map-page"

        deleted = client.delete("/api/pages/map-page")
        assert deleted.status_code == 200

        with sqlite3.connect(app.state.settings.sqlite_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM graph_nodes WHERE id = 'page:page_map_page'",
            ).fetchone()[0] == 0

        graph_after_delete = client.get("/api/graph", params={"node_type": "page", "limit": 10})
        assert graph_after_delete.status_code == 200
        assert all(node["id"] != "page:page_map_page" for node in graph_after_delete.json()["data"]["nodes"])
    get_settings.cache_clear()
