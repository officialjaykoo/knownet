from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .v2_migrate import MigrationReport, create_v2_from_current
from .v2_runtime import verify_v2_schema


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass
class PromotionReport:
    source: str
    candidate: str
    backup: str | None
    applied: bool
    migration: dict[str, Any]
    verification: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "candidate": self.candidate,
            "backup": self.backup,
            "applied": self.applied,
            "migration": self.migration,
            "verification": self.verification,
        }


def default_candidate_path(source_path: Path) -> Path:
    return source_path.with_name("knownet-v2.db")


def default_backup_path(source_path: Path, backup_dir: Path | None = None) -> Path:
    directory = backup_dir or source_path.parent / "backups"
    return directory / f"knownet-pre-v2-live-{utc_stamp()}.db"


def _assert_safe_paths(source_path: Path, candidate_path: Path, backup_path: Path | None) -> None:
    source = source_path.resolve()
    candidate = candidate_path.resolve()
    if source == candidate:
        raise ValueError("candidate_path must be different from source_path")
    if backup_path and source == backup_path.resolve():
        raise ValueError("backup_path must be different from source_path")


async def _verify_candidate(candidate_path: Path) -> dict[str, Any]:
    return await verify_v2_schema(candidate_path)


def _move_candidate_into_place(source_path: Path, candidate_path: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise FileExistsError(f"Backup already exists: {backup_path}")
    if not source_path.exists():
        raise FileNotFoundError(f"Live DB does not exist: {source_path}")
    if not candidate_path.exists():
        raise FileNotFoundError(f"Candidate v2 DB does not exist: {candidate_path}")

    moved_source = False
    try:
        shutil.move(str(source_path), str(backup_path))
        moved_source = True
        shutil.move(str(candidate_path), str(source_path))
    except Exception:
        if moved_source and backup_path.exists() and not source_path.exists():
            shutil.move(str(backup_path), str(source_path))
        raise


def promote_live_db(
    source_path: Path,
    *,
    candidate_path: Path | None = None,
    backup_path: Path | None = None,
    backup_dir: Path | None = None,
    apply: bool = False,
    overwrite_candidate: bool = False,
) -> PromotionReport:
    source_path = source_path.resolve()
    candidate_path = (candidate_path or default_candidate_path(source_path)).resolve()
    backup_path = (backup_path or default_backup_path(source_path, backup_dir)).resolve()
    _assert_safe_paths(source_path, candidate_path, backup_path)

    migration_report: MigrationReport = create_v2_from_current(
        source_path,
        candidate_path,
        overwrite=overwrite_candidate,
    )
    verification = asyncio.run(_verify_candidate(candidate_path))
    applied = False
    if apply:
        _move_candidate_into_place(source_path, candidate_path, backup_path)
        verification = asyncio.run(_verify_candidate(source_path))
        applied = True

    return PromotionReport(
        source=str(source_path),
        candidate=str(candidate_path),
        backup=str(backup_path) if applied else None,
        applied=applied,
        migration=migration_report.as_dict(),
        verification=verification,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and optionally promote a clean KnowNet v2 SQLite DB.")
    parser.add_argument("--source", required=True, type=Path, help="Current live knownet.db path.")
    parser.add_argument("--candidate", type=Path, help="Temporary v2 DB path. Defaults to knownet-v2.db next to source.")
    parser.add_argument("--backup", type=Path, help="Final live DB backup path used when --apply is set.")
    parser.add_argument("--backup-dir", type=Path, help="Directory for generated pre-promotion backups.")
    parser.add_argument("--apply", action="store_true", help="Replace source with the verified v2 candidate.")
    parser.add_argument("--overwrite-candidate", action="store_true", help="Overwrite an existing candidate v2 DB.")
    args = parser.parse_args()

    report = promote_live_db(
        args.source,
        candidate_path=args.candidate,
        backup_path=args.backup,
        backup_dir=args.backup_dir,
        apply=args.apply,
        overwrite_candidate=args.overwrite_candidate,
    )
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
