import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_bootstrap_login_and_session_actor(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        bootstrapped = client.post("/api/auth/bootstrap", json={"username": "owner", "password": "strong-password"})
        assert bootstrapped.status_code == 200
        data = bootstrapped.json()["data"]
        assert data["role"] == "owner"
        assert data["session_id"].startswith("sess_")

        me = client.get("/api/auth/me", headers={"authorization": f"Bearer {data['session_id']}"})
        assert me.status_code == 200
        assert me.json()["data"]["role"] == "owner"
        assert me.json()["data"]["vault_id"] == "local-default"

        duplicate = client.post("/api/auth/bootstrap", json={"username": "other", "password": "strong-password"})
        assert duplicate.status_code == 409

        logged_in = client.post("/api/auth/login", json={"username": "owner", "password": "strong-password"})
        assert logged_in.status_code == 200
        session_id = logged_in.json()["data"]["session_id"]

        logout = client.post("/api/auth/logout", headers={"authorization": f"Bearer {session_id}"})
        assert logout.status_code == 200
    get_settings.cache_clear()


def test_session_meta_hashes_user_agent(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    user_agent = "KnownetSecurityTest/1.0"
    with TestClient(app) as client:
        bootstrapped = client.post(
            "/api/auth/bootstrap",
            json={"username": "owner", "password": "strong-password"},
            headers={"user-agent": user_agent},
        )
        assert bootstrapped.status_code == 200
        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT session_meta FROM sessions LIMIT 1").fetchone()
        assert row is not None
        meta = json.loads(row[0])
        assert "ip_hash" in meta
        assert "user_agent_hash" in meta
        assert "user_agent" not in meta
        assert user_agent not in row[0]
    get_settings.cache_clear()


def test_login_lockout_after_repeated_failures(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("AUTH_MAX_FAILED_ATTEMPTS", "2")
    monkeypatch.setenv("AUTH_LOCKOUT_SECONDS", "900")
    with TestClient(app) as client:
        bootstrapped = client.post("/api/auth/bootstrap", json={"username": "owner", "password": "strong-password"})
        assert bootstrapped.status_code == 200

        first = client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"})
        assert first.status_code == 401
        second = client.post("/api/auth/login", json={"username": "owner", "password": "wrong-password"})
        assert second.status_code == 401
        locked = client.post("/api/auth/login", json={"username": "owner", "password": "strong-password"})
        assert locked.status_code == 429
        assert locked.json()["detail"]["code"] == "auth_rate_limited"
    get_settings.cache_clear()


def test_public_mode_rejects_weak_admin_token(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("PUBLIC_MODE", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "short-token")
    monkeypatch.setenv("ADMIN_TOKEN_MIN_CHARS", "32")
    with TestClient(app) as client:
        summary = client.get("/health/summary")
        assert summary.status_code == 200
        assert "security.weak_admin_token" in summary.json()["data"]["issues"]

        me = client.get("/api/auth/me", headers={"x-knownet-admin-token": "short-token"})
        assert me.status_code == 503
        assert me.json()["detail"]["code"] == "security_misconfigured"
    get_settings.cache_clear()


def test_security_headers_present(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        response = client.get("/health/summary")
        assert response.status_code == 200
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-frame-options"] == "DENY"
    get_settings.cache_clear()


def test_phase3_migration_adds_default_vault_columns(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["data"]["security"]["default_vault_id"] == "local-default"

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        vault = connection.execute("SELECT id, name FROM vaults WHERE id = 'local-default'").fetchone()
        assert vault == ("local-default", "Local")
        for table in ["pages", "revisions", "messages", "jobs", "suggestions", "embeddings", "audit_log"]:
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
            assert "vault_id" in columns
    get_settings.cache_clear()


def test_public_message_creates_pending_submission_without_job(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("PUBLIC_MODE", "true")
    with TestClient(app) as client:
        created = client.post("/api/messages", json={"content": "anonymous public note"})
        assert created.status_code == 200
        data = created.json()["data"]
        assert data["status"] == "pending_review"
        assert data["job_id"] is None
        assert data["submission_id"].startswith("sub_")

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        message = connection.execute("SELECT status FROM messages WHERE id = ?", (data["message_id"],)).fetchone()
        assert message == ("pending_review",)
        job_count = connection.execute("SELECT COUNT(*) FROM jobs WHERE target_id = ?", (data["message_id"],)).fetchone()[0]
        assert job_count == 0
        submission = connection.execute("SELECT status, actor_type FROM submissions WHERE id = ?", (data["submission_id"],)).fetchone()
        assert submission == ("pending_review", "anonymous")
    get_settings.cache_clear()


def test_reviewer_can_approve_public_submission(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    monkeypatch.setenv("PUBLIC_MODE", "true")
    with TestClient(app) as client:
        created = client.post("/api/messages", json={"content": "anonymous note for review"})
        assert created.status_code == 200
        submission_id = created.json()["data"]["submission_id"]
        message_id = created.json()["data"]["message_id"]

        owner = client.post("/api/auth/bootstrap", json={"username": "owner", "password": "strong-password"})
        assert owner.status_code == 200
        token = owner.json()["data"]["session_id"]

        queue = client.get("/api/submissions", headers={"authorization": f"Bearer {token}"})
        assert queue.status_code == 200
        assert queue.json()["data"]["submissions"][0]["id"] == submission_id

        approved = client.post(
            f"/api/submissions/{submission_id}/approve",
            json={"note": "looks good"},
            headers={"authorization": f"Bearer {token}"},
        )
        assert approved.status_code == 200
        assert approved.json()["data"]["status"] == "queued"
        job_id = approved.json()["data"]["job_id"]
        assert job_id.startswith("job_")

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        message = connection.execute("SELECT status FROM messages WHERE id = ?", (message_id,)).fetchone()
        assert message == ("queued",)
        job = connection.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
        assert job == ("queued",)
        submission = connection.execute("SELECT status, reviewed_by FROM submissions WHERE id = ?", (submission_id,)).fetchone()
        assert submission[0] == "queued"
        assert submission[1].startswith("user_")
    get_settings.cache_clear()


def test_page_delete_uses_tombstone_and_recover(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "phase3-delete-test", "title": "Phase3 Delete Test"})
        assert created.status_code == 200

        deleted = client.delete("/api/pages/phase3-delete-test")
        assert deleted.status_code == 200
        assert deleted.json()["data"]["status"] == "tombstone"
        tombstone_path = Path(deleted.json()["data"]["path"])
        assert tombstone_path.exists()

        missing = client.get("/api/pages/phase3-delete-test")
        assert missing.status_code == 404
        listed_after_delete = client.get("/api/pages")
        assert listed_after_delete.status_code == 200
        assert all(item["slug"] != "phase3-delete-test" for item in listed_after_delete.json()["data"]["pages"])

        verify_after_delete = client.get("/api/maintenance/verify-index")
        assert verify_after_delete.status_code == 200
        assert all(
            issue.get("slug") != "phase3-delete-test"
            for issue in verify_after_delete.json()["data"]["issues"]
        )

        recovered = client.post("/api/pages/phase3-delete-test/recover")
        assert recovered.status_code == 200
        assert recovered.json()["data"]["status"] == "active"

        page = client.get("/api/pages/phase3-delete-test")
        assert page.status_code == 200

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        status = connection.execute("SELECT status FROM pages WHERE slug = 'phase3-delete-test'").fetchone()
        assert status == ("active",)
    get_settings.cache_clear()


def test_orphan_markdown_file_can_be_tombstoned(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        pages_dir = app.state.settings.data_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        orphan = pages_dir / "orphan-file.md"
        orphan.write_text(
            "---\n"
            "schema_version: 1\n"
            "id: page_orphan_file\n"
            "title: Orphan File\n"
            "slug: orphan-file\n"
            "status: active\n"
            "created_at: now\n"
            "updated_at: now\n"
            "---\n\n"
            "# Orphan File\n",
            encoding="utf-8",
        )

        listed = client.get("/api/pages")
        assert listed.status_code == 200
        assert any(item["slug"] == "orphan-file" for item in listed.json()["data"]["pages"])

        deleted = client.delete("/api/pages/orphan-file")
        assert deleted.status_code == 200
        assert deleted.json()["data"]["orphan_file"] is True
        assert not orphan.exists()
        assert Path(deleted.json()["data"]["path"]).exists()

        listed_after_delete = client.get("/api/pages")
        assert listed_after_delete.status_code == 200
        assert all(item["slug"] != "orphan-file" for item in listed_after_delete.json()["data"]["pages"])
    get_settings.cache_clear()


def test_page_page_returns_citation_sources(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "citation-demo", "title": "Citation Demo"})
        assert created.status_code == 200

        settings = app.state.settings
        page_path = settings.data_dir / "pages" / "citation-demo.md"
        page_path.write_text(
            page_path.read_text(encoding="utf-8")
            + "\nA compact claim points at an inbox message.[^msg_demo_source]\n\n"
            + "[^msg_demo_source]: Source `msg_demo_source`.\n",
            encoding="utf-8",
        )
        inbox_path = settings.data_dir / "inbox" / "msg-demo-source.md"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        inbox_path.write_text(
            "---\nschema_version: 1\nid: msg_demo_source\nstatus: queued\ncreated_at: now\n---\n\n"
            "NEAT uses historical markings to align genomes during crossover.\n",
            encoding="utf-8",
        )
        with sqlite3.connect(settings.sqlite_path) as connection:
            revision_id = connection.execute(
                "SELECT current_revision_id FROM pages WHERE id = ?",
                ("page_citation_demo",),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO messages (id, path, status, created_at, updated_at) VALUES (?, ?, 'queued', 'now', 'now')",
                ("msg_demo_source", str(inbox_path).replace("\\", "/")),
            )
            connection.execute(
                "INSERT INTO citations (page_id, revision_id, citation_key, validation_status, created_at) "
                "VALUES (?, ?, ?, 'unchecked', 'now')",
                ("page_citation_demo", revision_id, "msg_demo_source"),
            )
            connection.commit()

        page = client.get("/api/pages/citation-demo")
        assert page.status_code == 200
        source = page.json()["data"]["citation_sources"][0]
        assert source["key"] == "msg_demo_source"
        assert "historical markings" in source["excerpt"]
        assert source["definition"] == "Source `msg_demo_source`."
    get_settings.cache_clear()


def test_vault_create_membership_and_audit_events(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        owner = client.post("/api/auth/bootstrap", json={"username": "owner", "password": "strong-password"})
        assert owner.status_code == 200
        token = owner.json()["data"]["session_id"]

        created = client.post(
            "/api/vaults",
            json={"name": "Team Vault", "vault_id": "team-vault"},
            headers={"authorization": f"Bearer {token}"},
        )
        assert created.status_code == 200
        assert created.json()["data"]["vault_id"] == "team-vault"

        me = client.get(
            "/api/auth/me",
            headers={"authorization": f"Bearer {token}", "x-knownet-vault": "team-vault"},
        )
        assert me.status_code == 200
        assert me.json()["data"]["vault_id"] == "team-vault"
        assert me.json()["data"]["role"] == "owner"

        vaults = client.get("/api/vaults", headers={"authorization": f"Bearer {token}"})
        assert vaults.status_code == 200
        assert any(item["id"] == "team-vault" for item in vaults.json()["data"]["vaults"])

        db_path = app.state.settings.sqlite_path
    with sqlite3.connect(db_path) as connection:
        membership = connection.execute(
            "SELECT role FROM vault_members WHERE vault_id = 'team-vault' AND user_id = ?",
            (owner.json()["data"]["user_id"],),
        ).fetchone()
        assert membership == ("owner",)
        audit_event = connection.execute(
            "SELECT action, target_id FROM audit_events WHERE action = 'vault.create' AND target_id = 'team-vault'"
        ).fetchone()
        assert audit_event == ("vault.create", "team-vault")
    get_settings.cache_clear()
