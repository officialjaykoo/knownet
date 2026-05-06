import hashlib
import io
import json
import sqlite3
import tarfile
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from shutil import copy2, move, rmtree
from typing import Any
from uuid import uuid4

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..audit import write_audit_event
from ..config import REPO_ROOT
from ..db.sqlite import execute, fetch_all, fetch_one
from ..paths import PAGE_DIR_NAME, page_storage_dir
from ..security import Actor, require_admin_access, utc_now
from ..services.search_index import rebuild_pages_fts, search_index_status, verify_pages_fts
from ..status import operation_failure_status

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


SNAPSHOT_DIRS = (PAGE_DIR_NAME, "revisions", "suggestions", "inbox", "sources", "experiment-packets", "project-snapshot-packets")
LOCK_ACTIVE_STATUSES = ("active", "running")
VERIFY_INDEX_WARNING_CODES = {"agent_token_expired_cleanup_candidate"}


class RestoreRequest(BaseModel):
    snapshot_name: str


async def ensure_phase6_schema(sqlite_path: Path) -> None:
    await execute(
        sqlite_path,
        "CREATE TABLE IF NOT EXISTS maintenance_locks ("
        "id TEXT PRIMARY KEY, operation TEXT NOT NULL, status TEXT NOT NULL, actor_type TEXT NOT NULL, "
        "actor_id TEXT NOT NULL, meta TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        (),
    )
    await execute(
        sqlite_path,
        "CREATE TABLE IF NOT EXISTS maintenance_runs ("
        "id TEXT PRIMARY KEY, operation TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, "
        "completed_at TEXT, report TEXT NOT NULL DEFAULT '{}')",
        (),
    )


async def active_maintenance_lock(sqlite_path: Path) -> dict[str, Any] | None:
    await ensure_phase6_schema(sqlite_path)
    return await fetch_one(
        sqlite_path,
        "SELECT id, operation, status, actor_type, actor_id, meta, created_at, updated_at "
        "FROM maintenance_locks WHERE status IN ('active', 'running') ORDER BY created_at LIMIT 1",
        (),
    )


def _snapshot_name() -> str:
    stamp = utc_now().replace(":", "").replace("-", "").replace(".", "")[:15]
    return f"knownet-snapshot-{stamp}-{uuid4().hex[:8]}.tar.gz"


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _add_bytes_to_tar(archive: tarfile.TarFile, arcname: str, content: bytes) -> None:
    info = tarfile.TarInfo(arcname)
    info.size = len(content)
    info.mtime = int(time.time())
    archive.addfile(info, io.BytesIO(content))


def _safe_snapshot_path(backup_dir: Path, snapshot_name: str) -> Path:
    if "/" in snapshot_name or "\\" in snapshot_name or not snapshot_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail={"code": "snapshot_not_found", "message": "Invalid snapshot name", "details": {}})
    path = (backup_dir / snapshot_name).resolve()
    if backup_dir.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail={"code": "snapshot_not_found", "message": "Invalid snapshot name", "details": {}})
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "snapshot_not_found", "message": "Snapshot not found", "details": {"snapshot_name": snapshot_name}})
    return path


async def _record_run(sqlite_path: Path, run_id: str, operation: str, status: str, report: dict[str, Any], *, started_at: str | None = None) -> None:
    now = utc_now()
    await execute(
        sqlite_path,
        "INSERT INTO maintenance_runs (id, operation, status, started_at, completed_at, report) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET status = excluded.status, completed_at = excluded.completed_at, report = excluded.report",
        (run_id, operation, status, started_at or now, now if status not in {"running", "active"} else None, json.dumps(report)),
    )


async def _create_lock(settings, actor: Actor, operation: str, meta: dict[str, Any] | None = None) -> str:
    await ensure_phase6_schema(settings.sqlite_path)
    existing = await active_maintenance_lock(settings.sqlite_path)
    if existing:
        raise HTTPException(status_code=423, detail={"code": "maintenance_locked", "message": "Maintenance operation is already active", "details": existing})
    lock_id = f"lock_{uuid4().hex[:12]}"
    now = utc_now()
    await execute(
        settings.sqlite_path,
        "INSERT INTO maintenance_locks (id, operation, status, actor_type, actor_id, meta, created_at, updated_at) VALUES (?, ?, 'active', ?, ?, ?, ?, ?)",
        (lock_id, operation, actor.actor_type, actor.actor_id, json.dumps(meta or {}), now, now),
    )
    return lock_id


async def _release_lock(settings, lock_id: str, status: str = "released") -> None:
    await execute(
        settings.sqlite_path,
        "UPDATE maintenance_locks SET status = ?, updated_at = ? WHERE id = ?",
        (status, utc_now(), lock_id),
    )


def _iter_snapshot_files(data_dir: Path, sqlite_path: Path) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    for dirname in SNAPSHOT_DIRS:
        root = data_dir / dirname
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files.append((path, _posix(Path("data") / dirname / path.relative_to(root))))
    if sqlite_path.exists():
        files.append((sqlite_path, "data/knownet.db"))
    return files


def _snapshot_file_bytes(path: Path, arcname: str, tmp_dir: Path) -> bytes:
    if arcname != "data/knownet.db":
        return path.read_bytes()
    snapshot_db = tmp_dir / f"snapshot-db-{uuid4().hex[:12]}.db"
    copy2(path, snapshot_db)
    try:
        connection = sqlite3.connect(snapshot_db)
        try:
            table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'maintenance_locks'"
            ).fetchone()
            if table:
                connection.execute(
                    "UPDATE maintenance_locks SET status = 'released', updated_at = ? WHERE status IN ('active', 'running')",
                    (utc_now(),),
                )
                connection.commit()
        finally:
            connection.close()
        return snapshot_db.read_bytes()
    finally:
        snapshot_db.unlink(missing_ok=True)
        snapshot_db.with_suffix(".db-wal").unlink(missing_ok=True)
        snapshot_db.with_suffix(".db-shm").unlink(missing_ok=True)


async def _create_snapshot_archive(request: Request, actor: Actor, *, prefix: str = "knownet-snapshot") -> dict[str, Any]:
    settings = request.app.state.settings
    data_dir = settings.data_dir
    backup_dir = data_dir / "backups"
    tmp_dir = data_dir / "tmp"
    backup_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    name = _snapshot_name() if prefix == "knownet-snapshot" else _snapshot_name().replace("knownet-snapshot", prefix, 1)
    snapshot_path = backup_dir / name
    tmp_snapshot_path = tmp_dir / f"{name}.tmp"
    hashes: dict[str, str] = {}
    included_files = 0
    try:
        with tarfile.open(tmp_snapshot_path, "w:gz") as archive:
            for path, arcname in _iter_snapshot_files(data_dir, settings.sqlite_path):
                content = _snapshot_file_bytes(path, arcname, tmp_dir)
                hashes[arcname] = _sha256_bytes(content)
                _add_bytes_to_tar(archive, arcname, content)
                included_files += 1
            manifest = {
                "kind": "knownet.snapshot",
                "schema_version": 1,
                "created_at": utc_now(),
                "app_version": "0.1.0",
                "phase": 6,
                "sqlite_path": "data/knownet.db",
                "included_files": included_files,
                "sha256": hashes,
            }
            _add_bytes_to_tar(archive, "knownet-snapshot.json", json.dumps(manifest, indent=2).encode("utf-8"))
        if tmp_snapshot_path.stat().st_size > settings.backup_max_bytes:
            tmp_snapshot_path.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail={"code": "backup_too_large", "message": "Snapshot exceeds size limit", "details": {"max_bytes": settings.backup_max_bytes}})
        tmp_snapshot_path.replace(snapshot_path)
    except HTTPException:
        raise
    except Exception as error:
        tmp_snapshot_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail={"code": "backup_failed", "message": str(error), "details": {}}) from error

    await _apply_snapshot_retention(backup_dir, settings.backup_retention_count)
    result = {
        "name": snapshot_path.name,
        "path": _posix(snapshot_path),
        "size_bytes": snapshot_path.stat().st_size,
        "included_files": included_files,
        "format": "tar.gz",
    }
    await write_audit_event(
        settings.sqlite_path,
        action="maintenance.snapshot_created",
        actor=actor,
        target_type="snapshot",
        target_id=snapshot_path.name,
        metadata=result,
    )
    return result


async def _apply_snapshot_retention(backup_dir: Path, retention_count: int) -> None:
    snapshots = sorted(backup_dir.glob("knownet-snapshot-*.tar.gz"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in snapshots[max(1, retention_count):]:
        old.unlink(missing_ok=True)


async def _table_exists(sqlite_path: Path, name: str) -> bool:
    row = await fetch_one(sqlite_path, "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))
    return bool(row)


async def _column_exists(sqlite_path: Path, table: str, column: str) -> bool:
    rows = await fetch_all(sqlite_path, f"PRAGMA table_info({table})", ())
    return any(row["name"] == column for row in rows)


@router.get("/embedding/status")
async def embedding_status(request: Request):
    return {"ok": True, "data": request.app.state.embedding_service.health()}


@router.get("/search/fts-status")
async def fts_status(request: Request):
    return {"ok": True, "data": await search_index_status(request.app.state.settings.sqlite_path)}


@router.post("/search/rebuild-fts")
async def rebuild_fts(request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    result = await rebuild_pages_fts(settings.sqlite_path, settings.data_dir)
    await write_audit_event(
        settings.sqlite_path,
        action="maintenance.search.rebuild_fts",
        actor=actor,
        target_type="search_index",
        target_id="pages_fts",
        metadata=result,
    )
    return {"ok": True, "data": result}


@router.get("/search/verify-fts")
async def verify_fts(request: Request, actor: Actor = Depends(require_admin_access)):
    result = await verify_pages_fts(request.app.state.settings.sqlite_path)
    return {"ok": True, "data": result}


@router.get("/snapshots")
async def list_snapshots(request: Request, actor: Actor = Depends(require_admin_access)):
    backup_dir = request.app.state.settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    snapshots = [
        {
            "name": path.name,
            "path": str(path).replace("\\", "/"),
            "size_bytes": path.stat().st_size,
            "modified_at": path.stat().st_mtime,
        }
        for path in sorted(backup_dir.glob("knownet-snapshot-*.tar.gz"), reverse=True)
    ]
    return {"ok": True, "data": {"snapshots": snapshots}}


@router.post("/snapshots")
async def create_snapshot(request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    lock_id = await _create_lock(settings, actor, "backup")
    run_id = f"run_{uuid4().hex[:12]}"
    await _record_run(settings.sqlite_path, run_id, "backup", "running", {"lock_id": lock_id})
    try:
        result = await _create_snapshot_archive(request, actor)
        await _record_run(settings.sqlite_path, run_id, "backup", "completed", result)
    except Exception as error:
        await _record_run(settings.sqlite_path, run_id, "backup", "failed", {"error": str(error)})
        await _release_lock(settings, lock_id, "failed")
        raise
    await _release_lock(settings, lock_id)
    return {"ok": True, "data": result}


@router.get("/locks")
async def list_maintenance_locks(request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    await ensure_phase6_schema(settings.sqlite_path)
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT id, operation, status, actor_type, actor_id, meta, created_at, updated_at "
        "FROM maintenance_locks WHERE status IN ('active', 'running') ORDER BY created_at",
        (),
    )
    return {"ok": True, "data": {"locks": rows, "actor_role": actor.role}}


@router.post("/locks/{lock_id}/release")
async def release_maintenance_lock(lock_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    await ensure_phase6_schema(settings.sqlite_path)
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, operation, status, created_at FROM maintenance_locks WHERE id = ?",
        (lock_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "maintenance_lock_not_found", "message": "Maintenance lock not found", "details": {"lock_id": lock_id}})
    if row["status"] not in LOCK_ACTIVE_STATUSES:
        return {"ok": True, "data": {"lock_id": lock_id, "status": row["status"]}}
    created_at = row["created_at"].replace("Z", "+00:00")
    age_seconds = 0.0
    with suppress(ValueError):
        created_ts = datetime.fromisoformat(created_at).timestamp()
        age_seconds = time.time() - created_ts
    if age_seconds < 3600:
        raise HTTPException(status_code=409, detail={"code": "maintenance_lock_not_stale", "message": "Lock is not stale yet", "details": {"lock_id": lock_id}})
    if row["operation"] == "restore" and getattr(request.app.state, "restore_active", False):
        raise HTTPException(status_code=409, detail={"code": "restore_in_progress", "message": "Restore is still running", "details": {"lock_id": lock_id}})
    await _release_lock(settings, lock_id, "force_released")
    await _record_run(settings.sqlite_path, f"run_{uuid4().hex[:12]}", "lock_release", "force_released", {"lock_id": lock_id, "released_by": actor.actor_id})
    return {"ok": True, "data": {"lock_id": lock_id, "status": "force_released"}}


def _validate_tar_member(member: tarfile.TarInfo) -> None:
    name = member.name.replace("\\", "/")
    if name.startswith("/") or ".." in Path(name).parts:
        raise HTTPException(status_code=400, detail={"code": "restore_failed", "message": "Snapshot contains unsafe path", "details": {"path": member.name}})
    if not (member.isfile() or member.isdir()):
        raise HTTPException(status_code=400, detail={"code": "restore_failed", "message": "Snapshot contains unsupported tar member", "details": {"path": member.name}})


def _extract_snapshot(snapshot_path: Path, restore_dir: Path) -> dict[str, Any]:
    restore_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(snapshot_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            _validate_tar_member(member)
        manifest_member = archive.extractfile("knownet-snapshot.json")
        if not manifest_member:
            raise HTTPException(status_code=400, detail={"code": "restore_failed", "message": "Snapshot manifest missing", "details": {}})
        manifest = json.loads(manifest_member.read().decode("utf-8"))
        if manifest.get("kind") != "knownet.snapshot" or manifest.get("schema_version") != 1:
            raise HTTPException(status_code=400, detail={"code": "restore_failed", "message": "Unsupported snapshot manifest", "details": {}})
        archive.extractall(restore_dir)
    for arcname, expected_hash in (manifest.get("sha256") or {}).items():
        path = restore_dir / Path(arcname)
        if not path.exists() or _sha256_bytes(path.read_bytes()) != expected_hash:
            raise HTTPException(status_code=400, detail={"code": "restore_failed", "message": "Snapshot hash validation failed", "details": {"path": arcname}})
    return manifest


def _inspect_snapshot(snapshot_path: Path) -> dict[str, Any]:
    with tarfile.open(snapshot_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            _validate_tar_member(member)
        manifest_member = archive.extractfile("knownet-snapshot.json")
        if not manifest_member:
            raise HTTPException(status_code=400, detail={"code": "restore_plan_failed", "message": "Snapshot manifest missing", "details": {}})
        manifest = json.loads(manifest_member.read().decode("utf-8"))
        if manifest.get("kind") != "knownet.snapshot" or manifest.get("schema_version") != 1:
            raise HTTPException(status_code=400, detail={"code": "restore_plan_failed", "message": "Unsupported snapshot manifest", "details": {}})
        file_count = len([member for member in members if member.isfile()])
    return {
        "snapshot": snapshot_path.name,
        "format": "tar.gz",
        "size_bytes": snapshot_path.stat().st_size,
        "manifest": {
            "kind": manifest.get("kind"),
            "schema_version": manifest.get("schema_version"),
            "created_at": manifest.get("created_at"),
            "app_version": manifest.get("app_version"),
            "phase": manifest.get("phase"),
            "included_files": manifest.get("included_files"),
            "hash_count": len(manifest.get("sha256") or {}),
        },
        "file_count": file_count,
        "safe_to_inspect": True,
        "restore_requires_confirmation": True,
    }


def _verify_snapshot_archive(snapshot_path: Path, tmp_dir: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    verify_dir = tmp_dir / f"snapshot-verify-{uuid4().hex[:12]}"
    verify_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    try:
        with tarfile.open(snapshot_path, "r:gz") as archive:
            members = archive.getmembers()
            member_names = {member.name.replace("\\", "/") for member in members if member.isfile()}
            for member in members:
                try:
                    _validate_tar_member(member)
                except HTTPException:
                    issues.append({"code": "snapshot_unsafe_member", "path": member.name})
            if issues:
                return {"status": "invalid", "issues": issues}
            manifest_member = archive.extractfile("knownet-snapshot.json")
            if not manifest_member:
                issues.append({"code": "snapshot_manifest_missing"})
                return {"status": "invalid", "issues": issues}
            manifest = json.loads(manifest_member.read().decode("utf-8"))
            if manifest.get("kind") != "knownet.snapshot" or manifest.get("schema_version") != 1:
                issues.append({"code": "snapshot_manifest_unsupported"})
            archive.extractall(verify_dir)
            for arcname, expected_hash in (manifest.get("sha256") or {}).items():
                path = verify_dir / Path(arcname)
                if arcname not in member_names or not path.exists():
                    issues.append({"code": "snapshot_file_missing", "path": arcname})
                    continue
                if _sha256_bytes(path.read_bytes()) != expected_hash:
                    issues.append({"code": "snapshot_hash_mismatch", "path": arcname})
            db_path = verify_dir / "data" / "knownet.db"
            if not db_path.exists():
                issues.append({"code": "snapshot_db_missing"})
            else:
                connection = sqlite3.connect(db_path)
                try:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                    if not result or result[0] != "ok":
                        issues.append({"code": "snapshot_db_integrity_failed", "result": result[0] if result else None})
                finally:
                    connection.close()
            manifest_page_count = len([name for name in (manifest.get("sha256") or {}) if name.startswith("data/pages/") and name.endswith(".md")])
            archive_page_count = len([name for name in member_names if name.startswith("data/pages/") and name.endswith(".md")])
            if manifest_page_count != archive_page_count:
                issues.append({"code": "snapshot_page_count_mismatch", "manifest_pages": manifest_page_count, "archive_pages": archive_page_count})
    except Exception as error:
        issues.append({"code": "snapshot_verify_failed", "error": str(error)})
    finally:
        if verify_dir.exists():
            rmtree(verify_dir, ignore_errors=True)
    return {
        "status": "valid" if not issues else "invalid",
        "issues": issues,
        "manifest": {
            "kind": manifest.get("kind"),
            "schema_version": manifest.get("schema_version"),
            "created_at": manifest.get("created_at"),
            "included_files": manifest.get("included_files"),
        },
    }


def _move_current_data_to_backup(data_dir: Path, sqlite_path: Path, backup_dir: Path) -> dict[str, Any]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    skipped: list[str] = []
    for dirname in SNAPSHOT_DIRS:
        source = data_dir / dirname
        if not source.exists():
            skipped.append(dirname)
            continue
        target = backup_dir / dirname
        move(str(source), str(target))
        moved.append(dirname)
    if sqlite_path.exists():
        move(str(sqlite_path), str(backup_dir / "knownet.db"))
        moved.append("knownet.db")
    else:
        skipped.append("knownet.db")
    return {"moved": moved, "skipped": skipped}


def _restore_backup_data(data_dir: Path, sqlite_path: Path, backup_dir: Path) -> None:
    for dirname in SNAPSHOT_DIRS:
        target = data_dir / dirname
        if target.exists():
            rmtree(target)
    if sqlite_path.exists():
        sqlite_path.unlink()

    for dirname in SNAPSHOT_DIRS:
        source = backup_dir / dirname
        if source.exists():
            move(str(source), str(data_dir / dirname))
    db_backup = backup_dir / "knownet.db"
    if db_backup.exists():
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        move(str(db_backup), str(sqlite_path))


def _move_restored_data_into_place(restore_data_dir: Path, data_dir: Path, sqlite_path: Path) -> None:
    for dirname in SNAPSHOT_DIRS:
        target = data_dir / dirname
        if target.exists():
            raise HTTPException(status_code=409, detail={"code": "restore_failed", "message": "Target data directory is not empty after backup move", "details": {"path": _posix(target)}})
    if sqlite_path.exists():
        raise HTTPException(status_code=409, detail={"code": "restore_failed", "message": "Target SQLite file still exists after backup move", "details": {"path": _posix(sqlite_path)}})
    for dirname in SNAPSHOT_DIRS:
        source = restore_data_dir / dirname
        if source.exists():
            move(str(source), str(data_dir / dirname))
    db_source = restore_data_dir / "knownet.db"
    if db_source.exists():
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        move(str(db_source), str(sqlite_path))


@router.post("/restore")
async def restore_snapshot(payload: RestoreRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    backup_root = settings.data_dir / "backups"
    snapshot_path = _safe_snapshot_path(backup_root, payload.snapshot_name)
    lock_id = await _create_lock(settings, actor, "restore", {"snapshot": payload.snapshot_name})
    run_id = f"run_{uuid4().hex[:12]}"
    restore_id = uuid4().hex[:12]
    restore_dir = settings.data_dir / "tmp" / f"restore-{restore_id}"
    restore_backup_dir = settings.data_dir / "tmp" / f"restore-backup-{restore_id}"
    request.app.state.restore_active = True
    await _record_run(settings.sqlite_path, run_id, "restore", "running", {"lock_id": lock_id, "snapshot": payload.snapshot_name})
    pre_restore = None
    try:
        if settings.restore_require_snapshot:
            pre_restore = await _create_snapshot_archive(request, actor, prefix="pre-restore")
        manifest = _extract_snapshot(snapshot_path, restore_dir)
        moved = _move_current_data_to_backup(settings.data_dir, settings.sqlite_path, restore_backup_dir)
        try:
            _move_restored_data_into_place(restore_dir / "data", settings.data_dir, settings.sqlite_path)
        except Exception:
            _restore_backup_data(settings.data_dir, settings.sqlite_path, restore_backup_dir)
            await _record_run(settings.sqlite_path, run_id, "restore", "rollback_success", {"snapshot": payload.snapshot_name, "pre_restore": pre_restore})
            raise
        try:
            await request.app.state.rust_core.request("init_db", {"sqlite_path": str(settings.sqlite_path)})
            await request.app.state.rust_core.request("ensure_graph_schema", {"sqlite_path": str(settings.sqlite_path)})
            graph_result = await request.app.state.rust_core.request(
                "rebuild_graph_for_vault",
                {"sqlite_path": str(settings.sqlite_path), "vault_id": actor.vault_id, "rebuilt_at": utc_now()},
            )
            graph = {"status": "rebuilt", "result": graph_result or {}}
        except Exception as error:
            graph = operation_failure_status(error)
        result = {"snapshot": payload.snapshot_name, "pre_restore": pre_restore, "manifest": manifest, "moved": moved, "graph_rebuild": graph}
        await ensure_phase6_schema(settings.sqlite_path)
        await _record_run(settings.sqlite_path, run_id, "restore", "completed", result)
        await write_audit_event(settings.sqlite_path, action="maintenance.restore", actor=actor, target_type="snapshot", target_id=payload.snapshot_name, metadata=result)
    except HTTPException:
        await _release_lock(settings, lock_id, "failed")
        raise
    except Exception as error:
        await _record_run(settings.sqlite_path, run_id, "restore", "failed", {"error": str(error), "snapshot": payload.snapshot_name})
        await _release_lock(settings, lock_id, "failed")
        raise HTTPException(status_code=500, detail={"code": "restore_failed", "message": str(error), "details": {"snapshot": payload.snapshot_name}}) from error
    finally:
        request.app.state.restore_active = False
        if restore_dir.exists():
            rmtree(restore_dir, ignore_errors=True)
    await _release_lock(settings, lock_id)
    return {"ok": True, "data": result}


@router.get("/restore-plan")
async def restore_plan(snapshot_name: str, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    backup_root = settings.data_dir / "backups"
    snapshot_path = _safe_snapshot_path(backup_root, snapshot_name)
    lock = await active_maintenance_lock(settings.sqlite_path)
    plan = _inspect_snapshot(snapshot_path)
    plan["active_lock"] = lock
    plan["pre_restore_snapshot_required"] = settings.restore_require_snapshot
    plan["can_restore_now"] = lock is None
    plan["warnings"] = [
        "Restore replaces current data after creating a pre-restore snapshot when configured.",
        "Run verify-index after restore.",
        "Do not restore while another maintenance lock is active.",
    ]
    return {"ok": True, "data": plan}


@router.get("/snapshots/{snapshot_name}/verify")
async def verify_snapshot(snapshot_name: str, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    snapshot_path = _safe_snapshot_path(settings.data_dir / "backups", snapshot_name)
    result = _verify_snapshot_archive(snapshot_path, settings.data_dir / "tmp")
    return {"ok": True, "data": result}


@router.post("/embedding/prefetch-plan")
async def embedding_prefetch_plan(
    request: Request,
    actor: Actor = Depends(require_admin_access),
):
    plan = request.app.state.embedding_service.prefetch_plan()
    await write_audit_event(
        request.app.state.settings.sqlite_path,
        action="maintenance.embedding_prefetch_plan",
        actor=actor,
        target_type="embedding_model",
        target_id=plan["model"],
        model_name=plan["model"],
        metadata={"status": plan["status"]},
    )
    return {"ok": True, "data": plan}


@router.post("/embedding/load")
async def embedding_load(
    request: Request,
    allow_download: bool = False,
    actor: Actor = Depends(require_admin_access),
):
    status = await request.app.state.embedding_service.load(allow_download=allow_download)
    await write_audit_event(
        request.app.state.settings.sqlite_path,
        action="maintenance.embedding_load",
        actor=actor,
        target_type="embedding_model",
        target_id=status["model"],
        model_name=status["model"],
        metadata={"status": status["status"], "allow_download": allow_download, "reason": status["reason"]},
    )
    return {"ok": True, "data": status}


@router.post("/seed/dry-run")
async def seed_dry_run(
    request: Request,
    path: str = "seeds/knownet-ai-state.yml",
    actor: Actor = Depends(require_admin_access),
):
    requested_path = Path(path)
    repo_root = REPO_ROOT.resolve()
    seed_path = requested_path.resolve() if requested_path.is_absolute() else (repo_root / requested_path).resolve()
    if repo_root not in seed_path.parents and seed_path != repo_root:
        raise HTTPException(status_code=400, detail={"code": "invalid_seed_path", "message": "Seed path must stay inside the repository", "details": {"path": str(seed_path)}})
    if not seed_path.exists():
        raise HTTPException(status_code=404, detail={"code": "file_not_found", "message": "Seed file not found", "details": {"path": str(seed_path)}})

    content = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
    pages = content.get("pages") or []
    pages_dir = page_storage_dir(request.app.state.settings.data_dir)
    actions: list[dict[str, Any]] = []
    for page in pages:
        slug = str(page.get("slug") or "").strip()
        if not slug:
            actions.append({"action": "error", "reason": "missing_slug", "page": page})
            continue
        target = pages_dir / f"{slug}.md"
        actions.append(
            {
                "slug": slug,
                "title": page.get("title") or slug,
                "action": "skip" if target.exists() else "create",
                "path": str(target).replace("\\", "/"),
            }
        )
    await write_audit_event(
        request.app.state.settings.sqlite_path,
        action="maintenance.seed_dry_run",
        actor=actor,
        target_type="seed",
        target_id=str(seed_path).replace("\\", "/"),
        metadata={"actions_count": len(actions)},
    )
    return {"ok": True, "data": {"seed_path": str(seed_path).replace("\\", "/"), "actions": actions}}


@router.get("/verify-index")
async def verify_index(request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    issues: list[dict[str, Any]] = []
    pages_have_status = await _column_exists(settings.sqlite_path, "pages", "status")
    page_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT id, slug, path, current_revision_id FROM pages WHERE status = 'active'"
        if pages_have_status
        else "SELECT id, slug, path, current_revision_id FROM pages",
        (),
    )
    for row in page_rows:
        path = Path(row["path"])
        if not path.exists():
            issues.append({"code": "missing_page_file", "slug": row["slug"], "path": row["path"]})
        section_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT COUNT(*) AS count FROM sections WHERE page_id = ? AND revision_id = ?",
            (row["id"], row["current_revision_id"]),
        )
        if section_rows and section_rows[0]["count"] == 0:
            issues.append({"code": "missing_sections_index", "slug": row["slug"]})

    for path in page_storage_dir(settings.data_dir).glob("*.md"):
        if path.name == ".gitkeep":
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            issues.append({"code": "missing_frontmatter", "path": str(path).replace("\\", "/")})

    active_current_predicate = (
        "(p.id IS NULL OR (p.status = 'active' AND (c.revision_id IS p.current_revision_id OR c.revision_id = p.current_revision_id)))"
        if pages_have_status
        else "(p.id IS NULL OR (c.revision_id IS p.current_revision_id OR c.revision_id = p.current_revision_id))"
    )
    audit_active_current_predicate = (
        "(p.id IS NULL OR (p.status = 'active' AND (ca.revision_id IS p.current_revision_id OR ca.revision_id = p.current_revision_id)))"
        if pages_have_status
        else "(p.id IS NULL OR (ca.revision_id IS p.current_revision_id OR ca.revision_id = p.current_revision_id))"
    )

    citation_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT c.page_id, c.revision_id, c.citation_key, c.validation_status FROM citations c "
        "LEFT JOIN pages p ON p.id = c.page_id "
        f"WHERE {active_current_predicate} AND c.validation_status IN ('unsupported', 'contradicted')",
        (),
    )
    for row in citation_rows:
        issues.append(
            {
                "code": "citation_unsupported",
                "page_id": row["page_id"],
                "revision_id": row["revision_id"],
                "citation_key": row["citation_key"],
                "validation_status": row["validation_status"],
            }
        )

    missing_source_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT c.page_id, c.revision_id, c.citation_key FROM citations c "
        "LEFT JOIN pages p ON p.id = c.page_id "
        "LEFT JOIN messages m ON m.id = c.citation_key "
        f"WHERE {active_current_predicate} AND m.id IS NULL",
        (),
    )
    for row in missing_source_rows:
        issues.append(
            {
                "code": "citation_source_missing",
                "page_id": row["page_id"],
                "revision_id": row["revision_id"],
                "citation_key": row["citation_key"],
            }
        )

    audit_table_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'citation_audits'",
        (),
    )
    if audit_table_rows:
        missing_audit_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT c.page_id, c.revision_id, c.citation_key FROM citations c "
            "LEFT JOIN pages p ON p.id = c.page_id "
            "LEFT JOIN citation_audits ca ON ca.page_id = c.page_id "
            "AND (ca.revision_id IS c.revision_id OR ca.revision_id = c.revision_id) "
            "AND ca.citation_key = c.citation_key "
            f"WHERE {active_current_predicate} AND ca.id IS NULL",
            (),
        )
        for row in missing_audit_rows:
            issues.append(
                {
                    "code": "citation_audit_missing",
                    "page_id": row["page_id"],
                    "revision_id": row["revision_id"],
                    "citation_key": row["citation_key"],
                }
            )

        orphaned_audit_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT ca.id, ca.page_id, ca.revision_id, ca.citation_key FROM citation_audits ca "
            "LEFT JOIN pages p ON p.id = ca.page_id "
            "LEFT JOIN citations c ON c.page_id = ca.page_id "
            "AND (c.revision_id IS ca.revision_id OR c.revision_id = ca.revision_id) "
            "AND c.citation_key = ca.citation_key "
            f"WHERE {audit_active_current_predicate} AND c.citation_key IS NULL",
            (),
        )
        for row in orphaned_audit_rows:
            issues.append(
                {
                    "code": "citation_audit_orphaned",
                    "audit_id": row["id"],
                    "page_id": row["page_id"],
                    "revision_id": row["revision_id"],
                    "citation_key": row["citation_key"],
                }
            )

    graph_table_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'graph_nodes'",
        (),
    )
    if graph_table_rows:
        missing_graph_page_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT p.id, p.slug FROM pages p "
            "LEFT JOIN graph_nodes gn ON gn.id = 'page:' || p.id AND gn.vault_id = p.vault_id "
            "WHERE p.status = 'active' AND gn.id IS NULL",
            (),
        )
        for row in missing_graph_page_rows:
            issues.append({"code": "graph_page_node_missing", "page_id": row["id"], "slug": row["slug"]})

        link_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT l.page_id, l.revision_id, l.target, p.vault_id FROM links l "
            "JOIN pages p ON p.id = l.page_id "
            "WHERE p.status = 'active' AND (l.revision_id IS p.current_revision_id OR l.revision_id = p.current_revision_id)",
            (),
        )
        edge_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT vault_id, from_node_id, meta FROM graph_edges WHERE edge_type = 'page_link'",
            (),
        )
        edge_targets = set()
        for row in edge_rows:
            try:
                meta = yaml.safe_load(row["meta"] or "{}") or {}
            except yaml.YAMLError:
                meta = {}
            edge_targets.add((row["vault_id"], row["from_node_id"], str(meta.get("target") or "").lower()))
        for row in link_rows:
            key = (row["vault_id"], f"page:{row['page_id']}", str(row["target"]).lower())
            if key not in edge_targets:
                issues.append({"code": "graph_link_edge_missing", "page_id": row["page_id"], "target": row["target"]})

        orphaned_graph_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT gn.id, gn.target_type, gn.target_id FROM graph_nodes gn "
            "LEFT JOIN pages p ON gn.target_type = 'page' AND p.id = gn.target_id "
            "LEFT JOIN messages m ON gn.target_type = 'message' AND m.id = gn.target_id "
            "LEFT JOIN citation_audits ca ON gn.target_type = 'citation_audit' AND ca.id = gn.target_id "
            "WHERE (gn.target_type = 'page' AND p.id IS NULL) "
            "OR (gn.target_type = 'message' AND m.id IS NULL) "
            "OR (gn.target_type = 'citation_audit' AND ca.id IS NULL)",
            (),
        )
        for row in orphaned_graph_rows:
            issues.append({"code": "graph_target_missing", "node_id": row["id"], "target_type": row["target_type"], "target_id": row["target_id"]})

    if await _table_exists(settings.sqlite_path, "collaboration_reviews"):
        missing_review_page_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT r.id, r.page_id FROM collaboration_reviews r "
            "LEFT JOIN pages p ON p.id = r.page_id "
            "WHERE r.page_id IS NOT NULL AND p.id IS NULL",
            (),
        )
        for row in missing_review_page_rows:
            issues.append({"code": "collaboration_review_missing_page", "review_id": row["id"], "page_id": row["page_id"]})

    if await _table_exists(settings.sqlite_path, "collaboration_findings"):
        orphan_finding_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT f.id, f.review_id FROM collaboration_findings f "
            "LEFT JOIN collaboration_reviews r ON r.id = f.review_id "
            "WHERE r.id IS NULL",
            (),
        )
        for row in orphan_finding_rows:
            issues.append({"code": "collaboration_finding_orphan", "finding_id": row["id"], "review_id": row["review_id"]})
        if await _column_exists(settings.sqlite_path, "collaboration_findings", "evidence_quality"):
            invalid_quality_rows = await fetch_all(
                settings.sqlite_path,
                "SELECT id, evidence_quality FROM collaboration_findings "
                "WHERE evidence_quality NOT IN ('direct_access','context_limited','inferred','operator_verified','unspecified')",
                (),
            )
            for row in invalid_quality_rows:
                issues.append({"code": "collaboration_finding_invalid_evidence_quality", "finding_id": row["id"], "evidence_quality": row["evidence_quality"]})

    if await _table_exists(settings.sqlite_path, "implementation_records"):
        orphan_record_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT ir.id, ir.finding_id FROM implementation_records ir "
            "LEFT JOIN collaboration_findings f ON f.id = ir.finding_id "
            "WHERE ir.finding_id IS NOT NULL AND f.id IS NULL",
            (),
        )
        for row in orphan_record_rows:
            issues.append({"code": "implementation_record_orphan", "record_id": row["id"], "finding_id": row["finding_id"]})

    if await _table_exists(settings.sqlite_path, "finding_tasks"):
        orphan_task_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT t.id, t.finding_id FROM finding_tasks t "
            "LEFT JOIN collaboration_findings f ON f.id = t.finding_id "
            "WHERE f.id IS NULL",
            (),
        )
        for row in orphan_task_rows:
            issues.append({"code": "finding_task_orphan", "task_id": row["id"], "finding_id": row["finding_id"]})

    if await _table_exists(settings.sqlite_path, "context_bundle_manifests"):
        forbidden_terms = (".env", ".db", "backups/", "inbox/", "sessions", "users")
        bundle_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT id, path, selected_pages, included_sections FROM context_bundle_manifests",
            (),
        )
        for row in bundle_rows:
            values = [str(row["path"] or ""), str(row["selected_pages"] or ""), str(row["included_sections"] or "")]
            normalized = " ".join(values).replace("\\", "/").lower()
            if any(term in normalized for term in forbidden_terms):
                issues.append({"code": "context_bundle_forbidden_reference", "bundle_id": row["id"]})

    if await _table_exists(settings.sqlite_path, "agent_tokens"):
        agent_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT id, scopes, expires_at, revoked_at FROM agent_tokens",
            (),
        )
        now = utc_now()
        for row in agent_rows:
            try:
                scopes = json.loads(row["scopes"] or "[]")
            except json.JSONDecodeError:
                scopes = None
            if not isinstance(scopes, list):
                issues.append({"code": "agent_token_invalid_scope_json", "token_id": row["id"]})
            if row["expires_at"] and row["expires_at"] <= now and not row["revoked_at"]:
                issues.append({"code": "agent_token_expired_cleanup_candidate", "token_id": row["id"]})

    fts_result = await verify_pages_fts(settings.sqlite_path)
    issues.extend(fts_result.get("issues") or [])

    stale_patterns = ("Markdown" + "-first",)
    scan_paths = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "phases" / "PHASE_7_TASKS.md",
        REPO_ROOT / "docs" / "phases" / "PHASE_8_TASKS.md",
        REPO_ROOT / "docs",
        REPO_ROOT / "apps" / "api" / "knownet_api",
        REPO_ROOT / "apps" / "web" / "app",
        REPO_ROOT / "apps" / "web" / "components",
    ]
    for scan_root in scan_paths:
        paths = [scan_root] if scan_root.is_file() else list(scan_root.rglob("*")) if scan_root.exists() else []
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".md", ".py", ".tsx", ".ts", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in stale_patterns:
                if pattern in text:
                    issues.append({"code": "current_terminology_mismatch", "path": _posix(path.relative_to(REPO_ROOT)), "pattern": pattern})

    blocking_issues = [issue for issue in issues if issue.get("code") not in VERIFY_INDEX_WARNING_CODES]
    warnings = [issue for issue in issues if issue.get("code") in VERIFY_INDEX_WARNING_CODES]
    ok = len(blocking_issues) == 0
    await write_audit_event(
        settings.sqlite_path,
        action="maintenance.verify_index",
        actor=actor,
        target_type="index",
        target_id="pages",
        metadata={"ok": ok, "issues_count": len(blocking_issues), "warnings_count": len(warnings)},
    )
    return {"ok": True, "data": {"ok": ok, "issues": blocking_issues, "warnings": warnings}}


@router.post("/citations/verify")
async def verify_citations(request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    result = await request.app.state.citation_verifier.verify_all(data_dir=settings.data_dir)
    await write_audit_event(
        settings.sqlite_path,
        action="maintenance.citations_verify",
        actor=actor,
        target_type="citations",
        target_id="pages",
        metadata=result,
    )
    return {"ok": True, "data": result}
