import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.routes import search as search_route


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    monkeypatch.setenv("LOCAL_EMBEDDING_AUTO_LOAD", "false")


def test_rebuild_fts_indexes_active_markdown_pages(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        settings = get_settings()
        created = client.post("/api/pages", json={"slug": "fts-alpha", "title": "FTS Alpha"})
        assert created.status_code == 200
        path = settings.data_dir / "pages" / "fts-alpha.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n\nUniquePhaseTwentyFourTerm\n", encoding="utf-8")

        with sqlite3.connect(settings.sqlite_path) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE name = 'pages_fts'")}
        assert "pages_fts" in tables

        rebuild = client.post("/api/maintenance/search/rebuild-fts")
        assert rebuild.status_code == 200
        data = rebuild.json()["data"]
        assert data["indexed"] >= 1
        assert data["failed"] == 0
        assert data["search"]["fts"] == "ready"

        search = client.get("/api/search", params={"q": "UniquePhaseTwentyFourTerm"})
        assert search.status_code == 200
        payload = search.json()["data"]
        assert payload["search_source"] == "fts"
        assert payload["results"][0]["slug"] == "fts-alpha"
        assert payload["results"][0]["match_type"] == "fts"
    get_settings.cache_clear()


def test_fts_query_without_terms_falls_back_without_500(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "fallback-page", "title": "Fallback Page"})
        assert created.status_code == 200

        search = client.get("/api/search", params={"q": "\"'()"})
        assert search.status_code == 200
        data = search.json()["data"]
        assert data["search_source"] == "like_markdown_scan"
        assert data["fallback"] == "keyword"
        assert data["fallback_reason"] == "empty_fts_query"
    get_settings.cache_clear()


def test_fts_unavailable_falls_back_without_500(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)

    async def unavailable(_sqlite_path):
        return {"fts": "unavailable", "indexed_pages": 0, "fallback": "like_markdown_scan", "reason": "test_unavailable"}

    monkeypatch.setattr(search_route, "search_index_status", unavailable)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "like-fallback", "title": "Like Fallback"})
        assert created.status_code == 200

        search = client.get("/api/search", params={"q": "Fallback"})
        assert search.status_code == 200
        data = search.json()["data"]
        assert data["search_source"] == "like_markdown_scan"
        assert data["fallback_reason"] == "test_unavailable"
        assert any(row["slug"] == "like-fallback" for row in data["results"])
    get_settings.cache_clear()


def test_page_tombstone_removes_page_from_fts(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "remove-from-fts", "title": "Remove From FTS"})
        assert created.status_code == 200
        before = client.get("/api/search", params={"q": "Remove"})
        assert before.status_code == 200
        assert any(row["slug"] == "remove-from-fts" for row in before.json()["data"]["results"])

        deleted = client.delete("/api/pages/remove-from-fts")
        assert deleted.status_code == 200
        after = client.get("/api/search", params={"q": "Remove"})
        assert after.status_code == 200
        assert all(row["slug"] != "remove-from-fts" for row in after.json()["data"]["results"])
    get_settings.cache_clear()


def test_health_summary_exposes_search_status(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        health = client.get("/health/summary")
        assert health.status_code == 200
        search = health.json()["data"]["search"]
        assert search["fts"] in {"empty", "ready", "unavailable"}
        assert "indexed_pages" in search
        assert search["fallback"] == "like_markdown_scan"
    get_settings.cache_clear()
