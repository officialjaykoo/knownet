import time

import pytest
from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


@pytest.mark.smoke
def test_smoke_message_to_snapshot(tmp_path, monkeypatch):
    get_settings.cache_clear()
    data_dir = tmp_path / "smoke-test"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    with TestClient(app) as client:
        health = client.get("/health/summary")
        assert health.status_code == 200
        assert health.json()["data"]["overall_status"] != "attention_required"

        created = client.post("/api/messages", json={"content": "Phase 6 smoke test note"})
        assert created.status_code == 200
        job_id = created.json()["data"]["job_id"]

        job = None
        for _ in range(30):
            response = client.get(f"/api/jobs/{job_id}")
            assert response.status_code == 200
            job = response.json()["data"]
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.2)
        assert job and job["status"] == "completed"

        suggestion_id = job["suggestion"]["id"]
        applied = client.post(f"/api/suggestions/{suggestion_id}/apply", json={})
        assert applied.status_code == 200
        page_id = f"page_{applied.json()['data']['slug'].replace('-', '_')}"

        graph = client.post("/api/graph/rebuild", json={"scope": "vault"})
        assert graph.status_code == 200
        graph_data = client.get("/api/graph", params={"node_type": "page"})
        assert any(node["id"] == f"page:{page_id}" for node in graph_data.json()["data"]["nodes"])

        snapshot = client.post("/api/maintenance/snapshots")
        assert snapshot.status_code == 200
        assert snapshot.json()["data"]["name"].endswith(".tar.gz")

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200
        assert "issues" in verify.json()["data"]
    get_settings.cache_clear()
