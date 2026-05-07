from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DB_DIR = Path(__file__).resolve().parent
V2_SCHEMA_PATH = DB_DIR / "v2_schema.sql"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row["name"]) for row in rows}


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def row_count(connection: sqlite3.Connection, table: str) -> int:
    if not table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"])


def apply_schema(connection: sqlite3.Connection, schema_path: Path = V2_SCHEMA_PATH) -> str:
    schema = schema_path.read_text(encoding="utf-8")
    connection.executescript(schema)
    checksum = sha256_text(schema)
    connection.execute(
        "INSERT OR REPLACE INTO schema_migrations (version, name, applied_at, checksum) VALUES (?, ?, ?, ?)",
        (1, "v2_clean_schema", utc_now(), checksum),
    )
    return checksum


def copy_intersection(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    source_table: str,
    target_table: str | None = None,
    *,
    exclude: set[str] | None = None,
) -> int:
    target_table = target_table or source_table
    if not table_exists(source, source_table) or not table_exists(target, target_table):
        return 0
    source_columns = table_columns(source, source_table)
    target_columns = table_columns(target, target_table)
    columns = sorted((source_columns & target_columns) - (exclude or set()))
    if not columns:
        return 0
    selected = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    inserted = 0
    for row in source.execute(f"SELECT {selected} FROM {source_table}").fetchall():
        target.execute(
            f"INSERT OR REPLACE INTO {target_table} ({selected}) VALUES ({placeholders})",
            tuple(row[column] for column in columns),
        )
        inserted += 1
    return inserted


def _json_has_payload(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text and text not in {"{}", "[]", "null"})


def migrate_reviews_and_findings(source: sqlite3.Connection, target: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    if table_exists(source, "reviews"):
        counts["reviews"] = copy_intersection(source, target, "reviews")
        counts["findings"] = copy_intersection(source, target, "findings")
        counts["finding_evidence"] = copy_intersection(source, target, "finding_evidence")
        counts["finding_locations"] = copy_intersection(source, target, "finding_locations")
        counts["finding_decisions"] = copy_intersection(source, target, "finding_decisions")
        return {key: value for key, value in counts.items() if value}
    counts["reviews"] = copy_intersection(source, target, "collaboration_reviews", "reviews")
    if not table_exists(source, "collaboration_findings"):
        return counts

    review_by_id = {
        row["id"]: row
        for row in source.execute("SELECT id, source_agent, source_model FROM collaboration_reviews").fetchall()
    } if table_exists(source, "collaboration_reviews") else {}
    finding_rows = source.execute("SELECT * FROM collaboration_findings").fetchall()
    for row in finding_rows:
        target.execute(
            """
            INSERT OR REPLACE INTO findings
              (id, review_id, severity, area, title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["review_id"],
                row["severity"],
                row["area"],
                row["title"],
                row["status"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        review = review_by_id.get(row["review_id"])
        target.execute(
            """
            INSERT OR REPLACE INTO finding_evidence
              (id, finding_id, evidence, proposed_change, raw_text, evidence_quality,
               source_agent, source_model, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{row['id']}:evidence:1",
                row["id"],
                row["evidence"],
                row["proposed_change"],
                row["raw_text"],
                row["evidence_quality"],
                review["source_agent"] if review else None,
                review["source_model"] if review else None,
                row["created_at"],
                row["updated_at"],
            ),
        )
        if row["source_path"]:
            target.execute(
                """
                INSERT OR REPLACE INTO finding_locations
                  (id, finding_id, source_path, source_start_line, source_end_line,
                   source_snippet, source_location_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{row['id']}:location:1",
                    row["id"],
                    row["source_path"],
                    row["source_start_line"],
                    row["source_end_line"],
                    row["source_snippet"],
                    row["source_location_status"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
        if row["status"] != "pending" or row["decision_note"] or row["decided_by"] or row["decided_at"]:
            target.execute(
                """
                INSERT OR REPLACE INTO finding_decisions
                  (id, finding_id, status, decision_note, decided_by, decided_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{row['id']}:decision:current",
                    row["id"],
                    row["status"],
                    row["decision_note"],
                    row["decided_by"],
                    row["decided_at"],
                    row["updated_at"],
                ),
            )
    counts["findings"] = len(finding_rows)
    counts["finding_evidence"] = row_count(target, "finding_evidence")
    counts["finding_locations"] = row_count(target, "finding_locations")
    counts["finding_decisions"] = row_count(target, "finding_decisions")
    return counts


def migrate_packets(source: sqlite3.Connection, target: sqlite3.Connection) -> dict[str, int]:
    if table_exists(source, "packets"):
        return {
            "snapshots": copy_intersection(source, target, "snapshots"),
            "packets": copy_intersection(source, target, "packets"),
            "packet_sources": copy_intersection(source, target, "packet_sources"),
            "node_cards": copy_intersection(source, target, "node_cards"),
        }
    if not table_exists(source, "project_snapshot_packets"):
        return {}
    rows = source.execute("SELECT * FROM project_snapshot_packets").fetchall()
    for row in rows:
        snapshot_id = f"snapshot:{row['id']}"
        target.execute(
            """
            INSERT OR REPLACE INTO snapshots
              (id, vault_id, state_hash, summary_json, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                row["vault_id"],
                row["content_hash"],
                row["snapshot_quality_json"],
                row["created_by"],
                row["created_at"],
            ),
        )
        target.execute(
            """
            INSERT OR REPLACE INTO packets
              (id, snapshot_id, vault_id, target_agent, profile, output_mode, focus,
               content_hash, content_path, contract_version, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                snapshot_id,
                row["vault_id"],
                row["target_agent"],
                row["profile"],
                row["output_mode"],
                row["focus"],
                row["content_hash"],
                row["content_path"],
                row["contract_version"],
                row["created_by"],
                row["created_at"],
            ),
        )
        target.execute(
            """
            INSERT OR REPLACE INTO packet_sources
              (id, packet_id, source_type, source_id, content_hash, source_path, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"{row['id']}:content",
                row["id"],
                "generated_packet",
                row["id"],
                row["content_hash"],
                row["content_path"],
                json.dumps({"warnings": row["warnings_json"]}, ensure_ascii=True),
                row["created_at"],
            ),
        )
    return {
        "snapshots": row_count(target, "snapshots"),
        "packets": row_count(target, "packets"),
        "packet_sources": row_count(target, "packet_sources"),
    }


def migrate_model_runs(source: sqlite3.Connection, target: sqlite3.Connection) -> dict[str, int]:
    if table_exists(source, "provider_runs"):
        return {
            "provider_runs": copy_intersection(source, target, "provider_runs"),
            "provider_run_metrics": copy_intersection(source, target, "provider_run_metrics"),
            "provider_run_artifacts": copy_intersection(source, target, "provider_run_artifacts"),
        }
    if not table_exists(source, "model_review_runs"):
        return {}
    rows = source.execute("SELECT * FROM model_review_runs").fetchall()
    for row in rows:
        target.execute(
            """
            INSERT OR REPLACE INTO provider_runs
              (id, provider, model, prompt_profile, vault_id, status, context_summary_json,
               review_id, trace_id, packet_trace_id, error_code, error_message, created_by,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["provider"],
                row["model"],
                row["prompt_profile"],
                row["vault_id"],
                row["status"],
                row["context_summary_json"],
                row["review_id"],
                row["trace_id"],
                row["packet_trace_id"],
                row["error_code"],
                row["error_message"],
                row["created_by"],
                row["created_at"],
                row["updated_at"],
            ),
        )
        target.execute(
            """
            INSERT OR REPLACE INTO provider_run_metrics
              (run_id, input_tokens, output_tokens, estimated_cost_usd, duration_ms, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row["id"], row["input_tokens"], row["output_tokens"], row["estimated_cost_usd"], None, row["updated_at"]),
        )
        if _json_has_payload(row["request_json"]):
            target.execute(
                """
                INSERT OR REPLACE INTO provider_run_artifacts
                  (id, run_id, artifact_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"{row['id']}:request", row["id"], "request", row["request_json"], row["created_at"]),
            )
        if _json_has_payload(row["response_json"]):
            target.execute(
                """
                INSERT OR REPLACE INTO provider_run_artifacts
                  (id, run_id, artifact_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"{row['id']}:response", row["id"], "response", row["response_json"], row["updated_at"]),
            )
    return {
        "provider_runs": row_count(target, "provider_runs"),
        "provider_run_metrics": row_count(target, "provider_run_metrics"),
        "provider_run_artifacts": row_count(target, "provider_run_artifacts"),
    }


def migrate_audit_log(source: sqlite3.Connection, target: sqlite3.Connection) -> int:
    if not table_exists(source, "audit_log"):
        return 0
    inserted = 0
    existing = {
        (row["created_at"], row["action"], row["target_type"], row["target_id"])
        for row in target.execute("SELECT created_at, action, target_type, target_id FROM audit_events").fetchall()
    }
    for row in source.execute("SELECT * FROM audit_log").fetchall():
        key = (row["created_at"], row["action"], row["target_type"], row["target_id"])
        if key in existing:
            continue
        target.execute(
            """
            INSERT INTO audit_events
              (vault_id, actor_type, actor_id, action, target_type, target_id, request_id, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["vault_id"],
                row["actor_type"],
                row["actor_id"] or "unknown",
                row["action"],
                row["target_type"],
                row["target_id"],
                row["session_id"],
                row["metadata_json"],
                row["created_at"],
            ),
        )
        inserted += 1
    return inserted


@dataclass
class MigrationReport:
    source: str
    target: str
    schema_checksum: str
    copied: dict[str, int]
    rebuilt_empty: list[str]
    legacy_skipped: list[str]
    integrity_check: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "schema_checksum": self.schema_checksum,
            "copied": self.copied,
            "rebuilt_empty": self.rebuilt_empty,
            "legacy_skipped": self.legacy_skipped,
            "integrity_check": self.integrity_check,
        }


def create_v2_from_current(source_path: Path, target_path: Path, *, overwrite: bool = False) -> MigrationReport:
    if not source_path.exists():
        raise FileNotFoundError(f"Source DB does not exist: {source_path}")
    if target_path.exists():
        if not overwrite:
            raise FileExistsError(f"Target DB already exists: {target_path}")
        target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    copied: dict[str, int] = {}
    with connect(source_path) as source, connect(target_path) as target:
        schema_checksum = apply_schema(target)
        target.commit()
        target.execute("BEGIN")
        for table in (
            "pages",
            "revisions",
            "system_pages",
            "citations",
            "citation_audits",
            "implementation_records",
            "maintenance_runs",
            "users",
            "sessions",
            "vaults",
            "vault_members",
            "agent_tokens",
            "agent_access_events",
            "audit_events",
        ):
            count = copy_intersection(source, target, table)
            if count:
                copied[table] = count
        copied["citation_evidence"] = copy_intersection(source, target, "citation_evidence_snapshots", "citation_evidence")
        copied["citation_events"] = copy_intersection(source, target, "citation_audit_events", "citation_events")
        copied["graph_pins"] = copy_intersection(source, target, "graph_node_pins", "graph_pins")
        copied["audit_log_merged"] = migrate_audit_log(source, target)
        copied.update(migrate_reviews_and_findings(source, target))
        copied["tasks"] = copy_intersection(source, target, "tasks") or copy_intersection(source, target, "finding_tasks", "tasks")
        copied.update(migrate_packets(source, target))
        copied.update(migrate_model_runs(source, target))
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        target.commit()

    return MigrationReport(
        source=str(source_path),
        target=str(target_path),
        schema_checksum=schema_checksum,
        copied={key: value for key, value in copied.items() if value},
        rebuilt_empty=[
            "links",
            "sections",
            "embeddings",
            "pages_fts",
            "search_index_meta",
            "ai_state_pages",
            "graph_nodes",
            "graph_edges",
            "graph_layout_cache",
            "generated_packet_content",
            "jobs",
            "job_events",
            "maintenance_locks",
        ],
        legacy_skipped=[
            "messages",
            "suggestions",
            "submissions",
            "ai_actors",
            "context_bundle_manifests",
            "experiment_packets",
        ],
        integrity_check=str(integrity),
    )


def backup_sqlite(source_path: Path, backup_path: Path, *, overwrite: bool = False) -> Path:
    if not source_path.exists():
        raise FileNotFoundError(f"Source DB does not exist: {source_path}")
    if backup_path.exists() and not overwrite:
        raise FileExistsError(f"Backup already exists: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, backup_path)
    return backup_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a clean KnowNet DB v2 file from the current SQLite DB.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.backup:
        backup_sqlite(args.source, args.backup, overwrite=args.overwrite)
    report = create_v2_from_current(args.source, args.target, overwrite=args.overwrite)
    print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    return 0 if report.integrity_check == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
