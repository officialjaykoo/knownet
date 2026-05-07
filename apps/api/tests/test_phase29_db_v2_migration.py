from __future__ import annotations

import sqlite3
from pathlib import Path

from knownet_api.db.v2_migrate import create_v2_from_current
from knownet_api.db.v2_promote import promote_live_db


ROOT = Path(__file__).resolve().parents[3]
SCHEMA = ROOT / "apps" / "api" / "knownet_api" / "db" / "schema.sql"


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _seed_current_db(path: Path) -> None:
    with _connect(path) as connection:
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        now = "2026-05-08T00:00:00Z"
        connection.execute(
            "INSERT INTO vaults (id, name, created_at) VALUES (?, ?, ?)",
            ("local-default", "Local", now),
        )
        connection.execute(
            """
            INSERT INTO pages (id, vault_id, title, slug, path, current_revision_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("page_1", "local-default", "Page", "page", "pages/page.md", "rev_1", "active", now, now),
        )
        connection.execute(
            """
            INSERT INTO revisions (id, vault_id, page_id, path, author_type, change_note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("rev_1", "local-default", "page_1", "pages/page.md", "operator", "seed", now),
        )
        connection.execute(
            """
            INSERT INTO collaboration_reviews
              (id, vault_id, title, source_agent, source_model, review_type, status, meta, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("review_1", "local-default", "Review", "deepseek", "deepseek-v4", "agent_review", "accepted", "{}", now, now),
        )
        connection.execute(
            """
            INSERT INTO collaboration_findings
              (id, review_id, severity, area, title, evidence, proposed_change, raw_text,
               evidence_quality, status, source_path, source_start_line, source_end_line,
               source_snippet, source_location_status, decision_note, decided_by, decided_at,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "finding_1",
                "review_1",
                "high",
                "Ops",
                "Retry missing",
                "Provider failed once.",
                "Add backoff.",
                "raw",
                "operator_verified",
                "accepted",
                "apps/api/file.py",
                10,
                12,
                "raise RuntimeError()",
                "accepted",
                "ok",
                "operator",
                now,
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO finding_tasks
              (id, finding_id, status, priority, task_prompt, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("task_1", "finding_1", "open", "high", "Implement retry", now, now),
        )
        connection.execute(
            """
            INSERT INTO project_snapshot_packets
              (id, vault_id, target_agent, profile, output_mode, focus, content_hash,
               content_path, warnings_json, snapshot_quality_json, contract_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("packet_1", "local-default", "multi_ai", "overview", "top_findings", "db", "hash_1", "packets/p.md", "[]", "{}", "p26.v1", now),
        )
        connection.execute(
            """
            INSERT INTO model_review_runs
              (id, provider, model, prompt_profile, vault_id, status, context_summary_json,
               request_json, response_json, input_tokens, output_tokens, estimated_cost_usd,
               review_id, trace_id, packet_trace_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run_1",
                "deepseek",
                "deepseek-v4",
                "stability",
                "local-default",
                "imported",
                "{}",
                '{"messages":[]}',
                '{"content":"ok"}',
                10,
                20,
                0.01,
                "review_1",
                "trace_1",
                "packet_trace_1",
                now,
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_log
              (vault_id, created_at, action, actor_type, actor_id, target_type, target_id, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("local-default", now, "legacy_action", "operator", "operator", "page", "page_1", "{}"),
        )


def test_create_v2_from_current_splits_core_entities(tmp_path):
    source = tmp_path / "knownet.db"
    target = tmp_path / "knownet-v2.db"
    _seed_current_db(source)

    report = create_v2_from_current(source, target)

    assert report.integrity_check == "ok"
    assert report.copied["pages"] == 1
    assert report.copied["reviews"] == 1
    assert report.copied["findings"] == 1
    assert report.copied["provider_runs"] == 1

    with _connect(target) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM finding_evidence").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM finding_locations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM finding_decisions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM packets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM provider_run_metrics").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM provider_run_artifacts").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] >= 1
        assert connection.execute("SELECT COUNT(*) FROM pages_fts").fetchone()[0] == 0
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'audit_log'").fetchone() is None
        migration = connection.execute("SELECT version, name, checksum FROM schema_migrations").fetchone()
        assert migration["version"] == 1
        assert migration["name"] == "v2_clean_schema"


def test_promote_live_db_replaces_live_db_after_candidate_verification(tmp_path):
    source = tmp_path / "knownet.db"
    candidate = tmp_path / "knownet-v2.db"
    backup_dir = tmp_path / "backups"
    _seed_current_db(source)

    report = promote_live_db(
        source,
        candidate_path=candidate,
        backup_dir=backup_dir,
        apply=True,
        overwrite_candidate=True,
    )

    assert report.applied is True
    assert report.verification["integrity_check"] == "ok"
    assert not candidate.exists()
    backup_path = Path(report.backup or "")
    assert backup_path.exists()

    with _connect(source) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "collaboration_findings" not in tables
        assert "findings" in tables
        assert connection.execute("SELECT COUNT(*) FROM findings").fetchone()[0] == 1

    with _connect(backup_path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'collaboration_findings'").fetchone() is not None
