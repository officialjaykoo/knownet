import io
import json
import sqlite3
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app
from knownet_api.routes.maintenance import _extract_snapshot, _restore_backup_data


def _isolate_settings(monkeypatch, tmp_path):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))


def test_snapshot_is_tar_gz_with_manifest_and_no_recursive_backups(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "ops-page", "title": "Ops Page"})
        assert created.status_code == 200
        backup_dir = app.state.settings.data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "knownet-snapshot-old.tar.gz").write_bytes(b"not included")

        snapshot = client.post("/api/maintenance/snapshots")
        assert snapshot.status_code == 200
        data = snapshot.json()["data"]
        assert data["format"] == "tar.gz"
        assert data["name"].endswith(".tar.gz")

        with tarfile.open(data["path"], "r:gz") as archive:
            names = archive.getnames()
            assert "knownet-snapshot.json" in names
            assert "data/knownet.db" in names
            assert "data/pages/ops-page.md" in names
            assert all("\\" not in name for name in names)
            assert "data/backups/knownet-snapshot-old.tar.gz" not in names
            manifest = json.loads(archive.extractfile("knownet-snapshot.json").read().decode("utf-8"))  # type: ignore[union-attr]
            assert manifest["kind"] == "knownet.snapshot"
            assert manifest["sha256"]["data/knownet.db"]
    get_settings.cache_clear()


def test_restore_snapshot_restores_pages_and_keeps_backups(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        created = client.post("/api/pages", json={"slug": "restore-me", "title": "Restore Me"})
        assert created.status_code == 200
        snapshot = client.post("/api/maintenance/snapshots")
        assert snapshot.status_code == 200
        snapshot_name = snapshot.json()["data"]["name"]

        page_path = app.state.settings.data_dir / "pages" / "restore-me.md"
        page_path.write_text("broken", encoding="utf-8")
        restored = client.post("/api/maintenance/restore", json={"snapshot_name": snapshot_name})
        assert restored.status_code == 200
        assert page_path.read_text(encoding="utf-8").startswith("---\n")
        assert (app.state.settings.data_dir / "backups" / snapshot_name).exists()
    get_settings.cache_clear()


def test_restore_backup_data_removes_partial_restored_state(tmp_path):
    data_dir = tmp_path / "data"
    backup_dir = data_dir / "tmp" / "restore-backup-test"
    sqlite_path = data_dir / "knownet.db"

    (backup_dir / "pages").mkdir(parents=True)
    (backup_dir / "pages" / "original.md").write_text("original", encoding="utf-8")
    (backup_dir / "knownet.db").write_text("original-db", encoding="utf-8")

    (data_dir / "pages").mkdir(parents=True)
    (data_dir / "pages" / "partial.md").write_text("partial", encoding="utf-8")
    (data_dir / "inbox").mkdir(parents=True)
    (data_dir / "inbox" / "partial.md").write_text("partial", encoding="utf-8")
    sqlite_path.write_text("partial-db", encoding="utf-8")

    _restore_backup_data(data_dir, sqlite_path, backup_dir)

    assert (data_dir / "pages" / "original.md").read_text(encoding="utf-8") == "original"
    assert not (data_dir / "pages" / "partial.md").exists()
    assert not (data_dir / "inbox").exists()
    assert sqlite_path.read_text(encoding="utf-8") == "original-db"


def test_extract_snapshot_rejects_symlink_members(tmp_path):
    snapshot_path = tmp_path / "bad-snapshot.tar.gz"
    restore_dir = tmp_path / "restore"
    manifest = {"kind": "knownet.snapshot", "schema_version": 1, "sha256": {}}

    with tarfile.open(snapshot_path, "w:gz") as archive:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        manifest_info = tarfile.TarInfo("knownet-snapshot.json")
        manifest_info.size = len(manifest_bytes)
        archive.addfile(manifest_info, fileobj=io.BytesIO(manifest_bytes))

        link_info = tarfile.TarInfo("data/pages/linked.md")
        link_info.type = tarfile.SYMTYPE
        link_info.linkname = "../../outside.md"
        archive.addfile(link_info)

    try:
        _extract_snapshot(snapshot_path, restore_dir)
    except Exception as error:
        assert getattr(error, "status_code", None) == 400
        assert error.detail["code"] == "restore_failed"
    else:
        raise AssertionError("Expected symlink member to be rejected")


def test_maintenance_lock_blocks_mutations_and_can_force_release(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        db_path = app.state.settings.sqlite_path
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "INSERT INTO maintenance_locks (id, operation, status, actor_type, actor_id, meta, created_at, updated_at) "
                "VALUES (?, 'restore', 'active', 'local', 'local', '{}', ?, ?)",
                ("lock_test", old, old),
            )
            connection.commit()

        blocked = client.post("/api/messages", json={"content": "blocked during maintenance"})
        assert blocked.status_code == 423

        locks = client.get("/api/maintenance/locks")
        assert locks.status_code == 200
        assert locks.json()["data"]["locks"][0]["id"] == "lock_test"

        released = client.post("/api/maintenance/locks/lock_test/release")
        assert released.status_code == 200
        assert released.json()["data"]["status"] == "force_released"

        unblocked = client.post("/api/messages", json={"content": "allowed after release"})
        assert unblocked.status_code == 200
    get_settings.cache_clear()


def test_health_summary_reports_degraded_without_snapshot(tmp_path, monkeypatch):
    _isolate_settings(monkeypatch, tmp_path)
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert "overall_status" in health.json()["data"]

        summary = client.get("/health/summary")
        assert summary.status_code == 200
        assert "checked_at" in summary.json()["data"]
        data = summary.json()["data"]
        assert "backup.missing" in data["issues"]
        backup_detail = next(item for item in data["issue_details"] if item["code"] == "backup.missing")
        assert backup_detail["severity"] == "setup_needed"
        assert "first snapshot" in backup_detail["action"]
    get_settings.cache_clear()
