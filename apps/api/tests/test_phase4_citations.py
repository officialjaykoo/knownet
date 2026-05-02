import sqlite3
import time

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_suggestion_apply_creates_citation_audit(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/messages", json={"content": "NEAT topology growth citation audit test"})
        assert created.status_code == 200
        job_id = created.json()["data"]["job_id"]

        job = None
        for _ in range(20):
            response = client.get(f"/api/jobs/{job_id}")
            assert response.status_code == 200
            job = response.json()["data"]
            if job["status"] in {"completed", "failed"}:
                break
            time.sleep(0.2)
        assert job is not None
        assert job["status"] == "completed"

        suggestion_id = job["suggestion"]["id"]
        applied = client.post(f"/api/suggestions/{suggestion_id}/apply", json={})
        assert applied.status_code == 200
        applied_data = applied.json()["data"]
        assert isinstance(applied_data["citation_warnings"], list)
        assert applied_data["citation_audit"]["created"] >= 1

        audits = client.get("/api/citations/audits")
        assert audits.status_code == 200
        rows = audits.json()["data"]["audits"]
        assert rows
        assert rows[0]["citation_key"] == created.json()["data"]["message_id"]
        assert rows[0]["claim_hash"]
        assert rows[0]["claim_text"]

        marked = client.post(
            f"/api/citations/audits/{rows[0]['id']}/needs-review",
            json={"reason": "manual spot check"},
        )
        assert marked.status_code == 200
        assert marked.json()["data"]["status"] == "needs_review"

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        event = connection.execute(
            "SELECT to_status, reason FROM citation_audit_events WHERE citation_audit_id = ? ORDER BY id DESC LIMIT 1",
            (rows[0]["id"],),
        ).fetchone()
        assert event == ("needs_review", "manual spot check")
    get_settings.cache_clear()


def test_verify_index_reports_missing_citation_audit(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        db_path = app.state.settings.sqlite_path
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "INSERT INTO citations (page_id, revision_id, citation_key, validation_status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("page_missing_audit", "rev_1", "msg_missing", "unchecked", "now"),
            )
            connection.commit()

        verify = client.get("/api/maintenance/verify-index")
        assert verify.status_code == 200
        codes = {item["code"] for item in verify.json()["data"]["issues"]}
        assert "citation_audit_missing" in codes
    get_settings.cache_clear()
