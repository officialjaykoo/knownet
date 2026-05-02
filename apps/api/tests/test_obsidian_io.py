from pathlib import Path
import tarfile
from types import SimpleNamespace

import aiosqlite
from fastapi.testclient import TestClient

from knownet_api.config import get_settings
from knownet_api.main import app


async def _seed_audit_db(sqlite_path):
    async with aiosqlite.connect(sqlite_path) as connection:
        await connection.execute(
            "CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, action TEXT, actor_type TEXT, actor_id TEXT, session_id TEXT, ip_hash TEXT, user_agent_hash TEXT, target_type TEXT, target_id TEXT, before_revision_id TEXT, after_revision_id TEXT, model_provider TEXT, model_name TEXT, model_version TEXT, prompt_version TEXT, metadata_json TEXT)"
        )
        await connection.commit()


def test_obsidian_import_dry_run_and_export(tmp_path):
    import asyncio

    sqlite_path = tmp_path / "knownet.db"
    asyncio.run(_seed_audit_db(sqlite_path))
    source_dir = tmp_path / "vault"
    source_dir.mkdir()
    (source_dir / "Note One.md").write_text("# Note One\n\n[[Missing Page]]", encoding="utf-8")
    data_dir = tmp_path / "data"
    (data_dir / "pages").mkdir(parents=True)
    (data_dir / "pages" / "sample.md").write_text("# Sample", encoding="utf-8")

    app.state.settings = SimpleNamespace(
        sqlite_path=sqlite_path,
        data_dir=data_dir,
        public_mode=False,
        admin_token=None,
        write_requests_per_minute=20,
    )
    client = TestClient(app)

    imported = client.post("/api/maintenance/obsidian/import", json={"source_dir": str(source_dir), "dry_run": True})
    assert imported.status_code == 200
    assert imported.json()["data"]["summary"]["create"] == 1
    assert not (data_dir / "pages" / "note-one.md").exists()

    exported = client.post("/api/maintenance/obsidian/export")
    assert exported.status_code == 200
    export_path = Path(exported.json()["data"]["path"])
    assert export_path.name.endswith(".tar.gz")
    with tarfile.open(export_path, "r:gz") as archive:
        names = archive.getnames()
        assert "vault/sample.md" in names
        assert "manifest.json" in names


def test_obsidian_import_writes_canonical_state_through_rust(tmp_path, monkeypatch):
    get_settings.cache_clear()
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("SQLITE_PATH", str(data_dir / "knownet.db"))
    source_dir = tmp_path / "vault"
    source_dir.mkdir()
    (source_dir / "Imported Note.md").write_text("# Imported Note\n\n[[Other]]", encoding="utf-8")

    with TestClient(app) as client:
        imported = client.post(
            "/api/maintenance/obsidian/import",
            json={"source_dir": str(source_dir), "dry_run": False},
        )

        assert imported.status_code == 200
        data = imported.json()["data"]
        assert data["summary"]["create"] == 1
        assert data["summary"]["failed"] == 0
        assert data["actions"][0]["write_status"]["status"] == "created"
        assert data["actions"][0]["index_status"]["status"] == "indexed"
        assert (data_dir / "pages" / "imported-note.md").exists()
        assert (data_dir / "revisions" / "page_imported_note" / "rev_import_imported_note.md").exists()
    get_settings.cache_clear()
