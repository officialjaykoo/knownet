import time
import sqlite3

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_message_to_suggestion_to_page(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["data"]["rust_daemon"] == "ok"

        created = client.post(
            "/api/messages",
            json={"content": "NEAT input feature growth test"},
        )
        assert created.status_code == 200
        job_id = created.json()["data"]["job_id"]

        job = None
        for _ in range(20):
            response = client.get(f"/api/jobs/{job_id}")
            assert response.status_code == 200
            job = response.json()["data"]
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.3)

        assert job is not None
        assert job["status"] == "completed"
        assert job["suggestion"]

        suggestion_id = job["suggestion"]["id"]
        suggestion = client.get(f"/api/suggestions/{suggestion_id}")
        assert suggestion.status_code == 200
        assert "NEAT input feature growth test" in suggestion.json()["data"]["markdown"]

        applied = client.post(f"/api/suggestions/{suggestion_id}/apply", json={})
        assert applied.status_code == 200
        slug = applied.json()["data"]["slug"]
        revision_id = applied.json()["data"]["revision_id"]

        page = client.get(f"/api/pages/{slug}")
        assert page.status_code == 200
        assert page.json()["data"]["slug"] == slug

        stale_restore = client.post(
            f"/api/pages/{slug}/revisions/{revision_id}/restore",
            json={"expected_current_revision_id": "rev_stale"},
        )
        assert stale_restore.status_code == 409
        assert stale_restore.json()["detail"]["code"] == "page_revision_conflict"

        restored = client.post(
            f"/api/pages/{slug}/revisions/{revision_id}/restore",
            json={"expected_current_revision_id": revision_id},
        )
        assert restored.status_code == 200
        assert restored.json()["data"]["status"] == "restored"

        settings = get_settings()
        with sqlite3.connect(settings.sqlite_path) as connection:
            section_count = connection.execute(
                "SELECT COUNT(*) FROM sections WHERE page_id = ? AND revision_id = ?",
                (f"page_{slug.replace('-', '_')}", revision_id),
            ).fetchone()[0]
        assert section_count > 0

        search = client.get("/api/search", params={"q": "NEAT"})
        assert search.status_code == 200
        assert search.json()["data"]["results"]
        assert isinstance(search.json()["data"]["duration_ms"], int)

        semantic = client.post("/api/search/semantic", json={"q": "NEAT"})
        assert semantic.status_code == 200
        assert semantic.json()["data"]["status"] == "degraded"
        assert semantic.json()["data"]["fallback"] == "keyword"
        assert isinstance(semantic.json()["data"]["duration_ms"], int)

        embedding = client.get("/api/maintenance/embedding/status")
        assert embedding.status_code == 200
        assert embedding.json()["data"]["status"] == "unavailable"

        seed = client.post("/api/maintenance/seed/dry-run")
        assert seed.status_code == 200
        assert seed.json()["data"]["actions"]

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200
        assert "issues" in verify.json()["data"]

        migrate = client.post("/api/maintenance/migrate")
        assert migrate.status_code == 200
        assert migrate.json()["data"]["status"] == "noop"
    get_settings.cache_clear()
