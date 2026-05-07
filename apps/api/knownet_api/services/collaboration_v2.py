from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..db.sqlite import fetch_all, fetch_one, transaction


def v2_enabled(settings: Any) -> bool:
    _ = settings
    return True


def skipped_v2_graph_rebuild(reason: str = "v2_runtime_pending_graph_rewrite") -> dict[str, Any]:
    return {"status": "skipped", "reason": reason}


async def write_review_markdown(data_dir: Path, review_id: str, markdown: str) -> Path:
    review_dir = data_dir / "pages" / "reviews"
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / f"{review_id}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


async def create_review(
    sqlite_path: Path,
    *,
    data_dir: Path,
    review_id: str,
    vault_id: str,
    title: str,
    source_agent: str,
    source_model: str | None,
    review_type: str,
    page_id: str | None,
    markdown: str,
    meta: dict[str, Any],
    findings: list[dict[str, Any]],
    created_at: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    await write_review_markdown(data_dir, review_id, markdown)
    meta = dict(meta)
    meta["markdown_path"] = f"data/pages/reviews/{review_id}.md"
    async with transaction(sqlite_path) as connection:
        await connection.execute(
            """
            INSERT INTO reviews
              (id, vault_id, title, source_agent, source_model, review_type, status, page_id, meta, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?)
            """,
            (
                review_id,
                vault_id,
                title,
                source_agent,
                source_model,
                review_type,
                page_id,
                json.dumps(meta, ensure_ascii=True, sort_keys=True),
                created_at,
                created_at,
            ),
        )
        for finding in findings:
            finding_id = finding.get("id") or f"finding_{uuid4().hex[:12]}"
            await connection.execute(
                """
                INSERT INTO findings
                  (id, review_id, severity, area, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    review_id,
                    finding.get("severity") or "info",
                    finding.get("area") or "Docs",
                    finding.get("title") or "Untitled finding",
                    finding.get("status") or "pending",
                    created_at,
                    created_at,
                ),
            )
            await connection.execute(
                """
                INSERT INTO finding_evidence
                  (id, finding_id, evidence, proposed_change, raw_text, evidence_quality, source_agent, source_model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evidence_{uuid4().hex[:12]}",
                    finding_id,
                    finding.get("evidence"),
                    finding.get("proposed_change"),
                    finding.get("raw_text"),
                    finding.get("evidence_quality") or "unspecified",
                    source_agent,
                    source_model,
                    created_at,
                    created_at,
                ),
            )
            if finding.get("source_path"):
                await connection.execute(
                    """
                    INSERT INTO finding_locations
                      (id, finding_id, source_path, source_start_line, source_end_line, source_snippet, source_location_status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"location_{uuid4().hex[:12]}",
                        finding_id,
                        finding.get("source_path"),
                        finding.get("source_start_line"),
                        finding.get("source_end_line"),
                        finding.get("source_snippet"),
                        finding.get("source_location_status") or "accepted",
                        created_at,
                        created_at,
                    ),
                )
    return await review_with_findings(sqlite_path, review_id)


def _finding_select() -> str:
    return """
        SELECT
          f.*,
          fe.evidence,
          fe.proposed_change,
          fe.raw_text,
          COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
          fl.source_path,
          fl.source_start_line,
          fl.source_end_line,
          fl.source_snippet,
          COALESCE(fl.source_location_status, 'omitted') AS source_location_status,
          r.vault_id,
          r.title AS review_title,
          r.source_agent,
          r.source_model
        FROM findings f
        JOIN reviews r ON r.id = f.review_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        LEFT JOIN finding_locations fl ON fl.finding_id = f.id
    """


async def review_with_findings(sqlite_path: Path, review_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    review = await fetch_one(sqlite_path, "SELECT * FROM reviews WHERE id = ?", (review_id,))
    if not review:
        return None, []
    findings = await fetch_all(
        sqlite_path,
        _finding_select() + " WHERE f.review_id = ? ORDER BY f.created_at, f.id",
        (review_id,),
    )
    return review, findings


async def review_detail(sqlite_path: Path, review_id: str) -> dict[str, Any] | None:
    review, findings = await review_with_findings(sqlite_path, review_id)
    if not review:
        return None
    records = await fetch_all(
        sqlite_path,
        "SELECT * FROM implementation_records WHERE finding_id IN (SELECT id FROM findings WHERE review_id = ?) ORDER BY created_at",
        (review_id,),
    )
    return {"review": review, "findings": findings, "implementation_records": records}


async def list_reviews(
    sqlite_path: Path,
    *,
    vault_id: str,
    status: str | None,
    source_agent: str | None,
    area: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    where = ["r.vault_id = ?"]
    params: list[Any] = [vault_id]
    if status:
        where.append("r.status = ?")
        params.append(status)
    if source_agent:
        where.append("r.source_agent = ?")
        params.append(source_agent)
    if area:
        where.append("EXISTS (SELECT 1 FROM findings f WHERE f.review_id = r.id AND f.area = ?)")
        params.append(area)
    return await fetch_all(
        sqlite_path,
        "SELECT r.*, "
        "(SELECT COUNT(*) FROM findings f WHERE f.review_id = r.id) AS finding_count, "
        "(SELECT COUNT(*) FROM findings f WHERE f.review_id = r.id AND f.status = 'pending') AS pending_count "
        f"FROM reviews r WHERE {' AND '.join(where)} ORDER BY r.updated_at DESC LIMIT ?",
        (*params, limit),
    )


async def finding(sqlite_path: Path, finding_id: str) -> dict[str, Any] | None:
    return await fetch_one(sqlite_path, _finding_select() + " WHERE f.id = ?", (finding_id,))


async def duplicate_groups(sqlite_path: Path, *, vault_id: str, statuses: set[str], limit: int, dedupe_key) -> list[dict[str, Any]]:
    placeholders = ",".join("?" for _ in statuses)
    rows = await fetch_all(
        sqlite_path,
        """
        SELECT f.id, f.review_id, f.severity, f.area, f.title, f.status,
               COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               f.updated_at, r.source_agent, r.title AS review_title
        FROM findings f
        JOIN reviews r ON r.id = f.review_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        """ + f"WHERE r.vault_id = ? AND f.status IN ({placeholders}) ORDER BY f.updated_at DESC LIMIT ?",
        (vault_id, *sorted(statuses), limit),
    )
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = dedupe_key(row.get("title"))
        if key:
            groups.setdefault(key, []).append(row)
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    result: list[dict[str, Any]] = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        items = sorted(items, key=lambda item: (severity_rank.get(item.get("severity"), 5), item.get("updated_at") or ""))
        result.append(
            {
                "dedupe_key": key,
                "title": items[0].get("title"),
                "count": len(items),
                "statuses": sorted({item.get("status") for item in items if item.get("status")}),
                "highest_severity": items[0].get("severity"),
                "canonical_finding_id": items[0].get("id"),
                "findings": items[:10],
            }
        )
    return sorted(result, key=lambda group: (-group["count"], group.get("highest_severity") or "", group.get("title") or ""))


async def decide_finding(
    sqlite_path: Path,
    *,
    finding_id: str,
    status: str,
    decision_note: str | None,
    decided_by: str,
    decided_at: str,
) -> dict[str, Any] | None:
    existing = await fetch_one(sqlite_path, "SELECT id, review_id FROM findings WHERE id = ?", (finding_id,))
    if not existing:
        return None
    async with transaction(sqlite_path) as connection:
        await connection.execute(
            """
            INSERT INTO finding_decisions
              (id, finding_id, status, decision_note, decided_by, decided_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (f"decision_{uuid4().hex[:12]}", finding_id, status, decision_note, decided_by, decided_at, decided_at),
        )
        await connection.execute("UPDATE findings SET status = ?, updated_at = ? WHERE id = ?", (status, decided_at, finding_id))
        pending = await connection.execute_fetchall(
            "SELECT COUNT(*) AS count FROM findings WHERE review_id = ? AND status = 'pending'",
            (existing["review_id"],),
        )
        review_status = "triaged" if pending and int(pending[0]["count"] or 0) == 0 else "pending_review"
        await connection.execute("UPDATE reviews SET status = ?, updated_at = ? WHERE id = ?", (review_status, decided_at, existing["review_id"]))
    return {
        "finding_id": finding_id,
        "review_id": existing["review_id"],
        "status": status,
        "decision_note": decision_note,
        "decided_by": decided_by,
        "decided_at": decided_at,
    }


async def upsert_task(
    sqlite_path: Path,
    *,
    finding: dict[str, Any],
    actor_id: str,
    priority: str,
    owner: str | None,
    task_prompt: str,
    expected_verification: str,
    notes: str | None,
    updated_at: str,
) -> dict[str, Any]:
    existing = await fetch_one(sqlite_path, "SELECT id FROM tasks WHERE finding_id = ?", (finding["id"],))
    task_id = existing["id"] if existing else f"task_{uuid4().hex[:12]}"
    async with transaction(sqlite_path) as connection:
        if existing:
            await connection.execute(
                "UPDATE tasks SET priority = ?, owner = ?, task_prompt = ?, expected_verification = ?, notes = ?, updated_at = ? WHERE finding_id = ?",
                (priority, owner, task_prompt, expected_verification, notes, updated_at, finding["id"]),
            )
        else:
            await connection.execute(
                """
                INSERT INTO tasks
                  (id, finding_id, status, priority, owner, task_prompt, expected_verification, notes, created_by, created_at, updated_at)
                VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, finding["id"], priority, owner, task_prompt, expected_verification, notes, actor_id, updated_at, updated_at),
            )
    task = await fetch_one(sqlite_path, "SELECT * FROM tasks WHERE id = ?", (task_id,))
    if not task:
        raise RuntimeError(f"v2 task was not persisted: {task_id}")
    return task


async def list_tasks(sqlite_path: Path, *, status: str, limit: int) -> list[dict[str, Any]]:
    where = "" if status == "all" else "WHERE t.status = ?"
    params: tuple[Any, ...] = (limit,) if status == "all" else (status, limit)
    return await fetch_all(
        sqlite_path,
        """
        SELECT t.*, f.review_id, f.severity, f.area, f.title,
               COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               f.status AS finding_status, r.title AS review_title, r.source_agent, r.source_model
        FROM tasks t
        JOIN findings f ON f.id = t.finding_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        JOIN reviews r ON r.id = f.review_id
        """ + f"{where} "
        "ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, t.updated_at DESC LIMIT ?",
        params,
    )


async def task(sqlite_path: Path, task_id: str) -> dict[str, Any] | None:
    return await fetch_one(
        sqlite_path,
        """
        SELECT t.*, f.review_id, f.severity, f.area, f.title,
               COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               f.status AS finding_status, r.title AS review_title, r.source_agent, r.source_model
        FROM tasks t
        JOIN findings f ON f.id = t.finding_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        JOIN reviews r ON r.id = f.review_id
        WHERE t.id = ?
        """,
        (task_id,),
    )


async def packet_preflight(sqlite_path: Path, vault_id: str) -> dict[str, Any]:
    row = await fetch_one(
        sqlite_path,
        "SELECT "
        "(SELECT COUNT(*) FROM pages WHERE vault_id = ? AND status = 'active') AS pages, "
        "0 AS structured_state_pages, "
        "(SELECT COUNT(*) FROM graph_nodes WHERE vault_id = ? AND node_type = 'unresolved') AS unresolved_nodes, "
        "(SELECT COUNT(*) FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context')) AS pending_findings",
        (vault_id, vault_id, vault_id),
    )
    return row or {"pages": 0, "structured_state_pages": 0, "unresolved_nodes": 0, "pending_findings": 0}


async def ai_state_quality(sqlite_path: Path, vault_id: str) -> dict[str, Any]:
    preflight = await packet_preflight(sqlite_path, vault_id)
    pages = int(preflight.get("pages") or 0)
    pending = int(preflight.get("pending_findings") or 0)
    findings = await _count(sqlite_path, "SELECT COUNT(*) AS count FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ?", (vault_id,))
    reviews = await _count(sqlite_path, "SELECT COUNT(*) AS count FROM reviews WHERE vault_id = ?", (vault_id,))
    status = "ok"
    checks = []
    empty_state = {
        "active": pages == 0 and findings == 0 and reviews == 0,
        "reason": "fresh_install" if pages == 0 and findings == 0 and reviews == 0 else None,
        "operator_question": "Is this a fresh install, or should pages/reviews already exist?" if pages == 0 and findings == 0 and reviews == 0 else None,
    }
    if pages == 0:
        status = "warn" if empty_state["active"] else "fail"
        checks.append({"code": "structured_state.empty_pages", "status": status, "data": {"pages": 0, "structured_state_pages": 0, "empty_state": empty_state}})
    elif pending > 10:
        status = "warn"
        checks.append({"code": "ai_state.pending_findings", "status": "warn", "data": {"pending_findings": pending}})
    else:
        checks.append({"code": "ai_state.v2_runtime", "status": "ok", "data": {"pages": pages, "pending_findings": pending}})
    return {
        "overall_status": status,
        "checks": checks,
        "summary": {
            "pages": pages,
            "structured_state_pages": 0,
            "findings": findings,
            "pending_findings": pending,
            "deferred_high": await _count(sqlite_path, "SELECT COUNT(*) AS count FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status = 'deferred' AND f.severity IN ('critical','high')", (vault_id,)),
            "reviews": reviews,
        },
        "empty_state": empty_state,
    }


async def _count(sqlite_path: Path, query: str, params: tuple[Any, ...]) -> int:
    row = await fetch_one(sqlite_path, query, params)
    return int(row["count"] or 0) if row else 0


async def provider_matrix_summary(sqlite_path: Path) -> dict[str, Any]:
    rows = await fetch_all(
        sqlite_path,
        "SELECT provider, status, COUNT(*) AS count FROM provider_runs GROUP BY provider, status",
        (),
    )
    summary = {"total": 0, "failed": 0, "succeeded": 0, "running": 0}
    providers: dict[str, dict[str, int]] = {}
    for row in rows:
        provider = str(row.get("provider") or "unknown")
        status = str(row.get("status") or "unknown")
        count = int(row.get("count") or 0)
        providers.setdefault(provider, {})[status] = count
        summary["total"] += count
        if status == "failed":
            summary["failed"] += count
        elif status in {"succeeded", "success", "completed"}:
            summary["succeeded"] += count
        elif status in {"running", "queued"}:
            summary["running"] += count
    return {"summary": summary, "providers": providers}


async def resolve_snapshot_since(sqlite_path: Path, *, packet_id: str | None, vault_id: str, profile: str, allow_fallback: bool) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    if not packet_id:
        return None, None, warnings
    packet = await fetch_one(sqlite_path, "SELECT * FROM packets WHERE id = ? AND vault_id = ?", (packet_id, vault_id))
    if not packet:
        if not allow_fallback:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail={"code": "project_snapshot_since_packet_not_found", "message": "since_packet_id was not found", "details": {"since_packet_id": packet_id}})
        return None, None, ["since_packet_missing_full_snapshot"]
    if packet["profile"] != profile:
        warnings.append("profile_mismatch_delta")
    return packet["created_at"], packet, warnings


async def project_snapshot_delta(sqlite_path: Path, vault_id: str, since: str | None) -> dict[str, Any] | None:
    if not since:
        return None
    pages = await fetch_all(sqlite_path, "SELECT id, slug, title, status, updated_at FROM pages WHERE vault_id = ? AND updated_at > ? ORDER BY updated_at DESC LIMIT 25", (vault_id, since))
    findings = await fetch_all(
        sqlite_path,
        """
        SELECT f.id, f.severity, f.area, f.title, f.status,
               COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               f.updated_at, r.source_agent
        FROM findings f
        JOIN reviews r ON r.id = f.review_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        WHERE r.vault_id = ? AND f.updated_at > ? ORDER BY f.updated_at DESC LIMIT 25
        """,
        (vault_id, since),
    )
    tasks = await fetch_all(
        sqlite_path,
        "SELECT t.id, t.finding_id, t.status, t.priority, t.updated_at, f.title FROM tasks t JOIN findings f ON f.id = t.finding_id JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND t.updated_at > ? ORDER BY t.updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    runs = await fetch_all(
        sqlite_path,
        "SELECT id, provider, model, status, trace_id, packet_trace_id, updated_at FROM provider_runs WHERE vault_id = ? AND updated_at > ? ORDER BY updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    failed_runs = [row for row in runs if row.get("status") == "failed"]
    return {
        "since": since,
        "pages": pages,
        "findings": findings,
        "tasks": tasks,
        "model_runs": runs,
        "summary": {
            "changed_nodes": len(pages),
            "new_or_updated_findings": len(findings),
            "changed_tasks": len(tasks),
            "model_runs": len(runs),
            "failed_runs": len(failed_runs),
        },
    }


async def packet_source_rows(sqlite_path: Path, *, vault_id: str, task_limit: int, run_limit: int) -> dict[str, list[dict[str, Any]]]:
    task_rows = await fetch_all(
        sqlite_path,
        """
        SELECT t.id, t.finding_id, t.status, t.priority, t.owner,
               f.severity, f.area, f.title, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality
        FROM tasks t
        JOIN findings f ON f.id = t.finding_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        JOIN reviews r ON r.id = f.review_id
        WHERE r.vault_id = ? ORDER BY t.updated_at DESC LIMIT ?
        """,
        (vault_id, task_limit),
    )
    accepted_rows = await fetch_all(
        sqlite_path,
        """
        SELECT f.id, f.severity, f.area, f.title, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               f.status, r.source_agent
        FROM findings f
        JOIN reviews r ON r.id = f.review_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        WHERE r.vault_id = ? AND f.status = 'accepted' ORDER BY f.updated_at DESC LIMIT ?
        """,
        (vault_id, task_limit),
    )
    run_rows = await fetch_all(
        sqlite_path,
        "SELECT pr.id, pr.provider, pr.model, pr.prompt_profile, pr.status, pr.review_id, m.input_tokens, m.output_tokens, pr.trace_id, pr.packet_trace_id, pr.error_code, pr.error_message, pr.updated_at FROM provider_runs pr LEFT JOIN provider_run_metrics m ON m.run_id = pr.id WHERE pr.vault_id = ? ORDER BY pr.updated_at DESC LIMIT ?",
        (vault_id, run_limit),
    )
    return {"tasks": task_rows, "accepted": accepted_rows, "runs": run_rows}


async def node_rows(sqlite_path: Path, *, vault_id: str, delta: dict[str, Any] | None) -> list[dict[str, Any]]:
    if delta and delta.get("pages"):
        ids = [row["id"] for row in delta["pages"][:5]]
        placeholders = ",".join("?" for _ in ids)
        return await fetch_all(
            sqlite_path,
            f"SELECT id, slug, title, updated_at, NULL AS content_hash, 'page' AS system_kind FROM pages WHERE vault_id = ? AND id IN ({placeholders})",
            (vault_id, *ids),
        )
    return await fetch_all(
        sqlite_path,
        "SELECT id, slug, title, updated_at, NULL AS content_hash, 'page' AS system_kind FROM pages WHERE vault_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 5",
        (vault_id,),
    )


async def important_changes(sqlite_path: Path, *, vault_id: str, since: str | None, limit: int, action_route) -> dict[str, Any]:
    finding_filter = "AND f.updated_at > ?" if since else ""
    finding_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    findings = await fetch_all(
        sqlite_path,
        """
        SELECT f.id, f.severity, f.area, f.title, f.status, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality,
               f.updated_at, r.source_agent
        FROM findings f
        JOIN reviews r ON r.id = f.review_id
        LEFT JOIN finding_evidence fe ON fe.finding_id = f.id
        """ + f"WHERE r.vault_id = ? AND f.severity IN ('critical','high') AND f.status IN ('pending','needs_more_context','accepted','deferred') {finding_filter} ORDER BY f.updated_at DESC LIMIT ?",
        finding_params,
    )
    findings = [{**row, "action_route": action_route(row)} for row in findings]
    task_filter = "AND t.updated_at > ?" if since else ""
    task_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    tasks = await fetch_all(
        sqlite_path,
        "SELECT t.id, t.finding_id, t.status, t.priority, t.updated_at, f.title, f.severity, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality FROM tasks t JOIN findings f ON f.id = t.finding_id LEFT JOIN finding_evidence fe ON fe.finding_id = f.id JOIN reviews r ON r.id = f.review_id "
        + f"WHERE r.vault_id = ? AND t.status IN ('open','in_progress','blocked') {task_filter} ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, t.updated_at DESC LIMIT ?",
        task_params,
    )
    tasks = [{**row, "action_route": action_route(row)} for row in tasks]
    run_filter = "AND updated_at > ?" if since else ""
    run_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    failed_runs = await fetch_all(
        sqlite_path,
        f"SELECT id, provider, model, status, error_code, error_message, trace_id, packet_trace_id, updated_at FROM provider_runs WHERE vault_id = ? AND status = 'failed' {run_filter} ORDER BY updated_at DESC LIMIT ?",
        run_params,
    )
    evidence_filter = "AND i.created_at > ?" if since else ""
    evidence_params: tuple[Any, ...] = (vault_id, since, limit) if since else (vault_id, limit)
    implementation_evidence = await fetch_all(
        sqlite_path,
        "SELECT i.id, i.finding_id, i.commit_sha, i.changed_files, i.verification, i.created_at, f.title FROM implementation_records i LEFT JOIN findings f ON f.id = i.finding_id LEFT JOIN reviews r ON r.id = f.review_id "
        + f"WHERE COALESCE(r.vault_id, ?) = ? {evidence_filter} ORDER BY i.created_at DESC LIMIT ?",
        (vault_id, *evidence_params),
    )
    return {
        "since": since,
        "high_severity_findings": findings,
        "actionable_tasks": tasks,
        "failed_model_runs": failed_runs,
        "implementation_evidence": implementation_evidence,
        "summary": {
            "high_severity_findings": len(findings),
            "actionable_tasks": len(tasks),
            "failed_model_runs": len(failed_runs),
            "implementation_evidence": len(implementation_evidence),
        },
    }


async def do_not_reopen(sqlite_path: Path, *, vault_id: str, limit: int = 12) -> dict[str, Any]:
    implemented = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.title, f.severity, f.area, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality, f.updated_at FROM findings f JOIN reviews r ON r.id = f.review_id LEFT JOIN finding_evidence fe ON fe.finding_id = f.id WHERE r.vault_id = ? AND f.status = 'implemented' ORDER BY f.updated_at DESC LIMIT ?",
        (vault_id, limit),
    )
    resolved = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.title, f.status, d.decision_note, f.updated_at FROM findings f JOIN reviews r ON r.id = f.review_id LEFT JOIN finding_decisions d ON d.finding_id = f.id AND d.status = f.status WHERE r.vault_id = ? AND f.status IN ('rejected','deferred') ORDER BY f.updated_at DESC LIMIT ?",
        (vault_id, limit),
    )
    return {"implemented_findings": implemented, "resolved_or_deferred_findings": resolved, "summary": {"implemented": len(implemented), "resolved_or_deferred": len(resolved)}}


async def high_open_count(sqlite_path: Path, vault_id: str) -> int:
    return await _count(
        sqlite_path,
        "SELECT COUNT(*) AS count FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context','accepted','deferred') AND f.severity IN ('critical','high')",
        (vault_id,),
    )


async def store_project_packet(
    sqlite_path: Path,
    *,
    snapshot_id: str,
    packet_id: str,
    vault_id: str,
    target_agent: str,
    profile: str,
    output_mode: str,
    focus: str,
    content_hash: str,
    content_path: str,
    contract_version: str,
    created_by: str,
    created_at: str,
    summary: dict[str, Any],
    node_cards: list[dict[str, Any]],
) -> None:
    async with transaction(sqlite_path) as connection:
        await connection.execute(
            "INSERT INTO snapshots (id, vault_id, state_hash, summary_json, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, vault_id, content_hash, json.dumps(summary, ensure_ascii=True, sort_keys=True), created_by, created_at),
        )
        await connection.execute(
            "INSERT INTO packets (id, snapshot_id, vault_id, target_agent, profile, output_mode, focus, content_hash, content_path, contract_version, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (packet_id, snapshot_id, vault_id, target_agent, profile, output_mode, focus, content_hash, content_path, contract_version, created_by, created_at),
        )
        await connection.execute(
            "INSERT INTO packet_sources (id, packet_id, source_type, source_id, content_hash, source_path, meta, created_at) VALUES (?, ?, 'snapshot', ?, ?, ?, ?, ?)",
            (f"packet_source_{uuid4().hex[:12]}", packet_id, snapshot_id, content_hash, content_path, json.dumps({"profile": profile}, ensure_ascii=True), created_at),
        )
        for card in node_cards:
            await connection.execute(
                "INSERT INTO node_cards (id, packet_id, node_id, title, node_type, short_summary, detail_url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"node_card_{uuid4().hex[:12]}",
                    packet_id,
                    card.get("id") or card.get("node_id"),
                    card.get("title") or "Untitled node",
                    card.get("type") or card.get("node_type"),
                    card.get("short_summary"),
                    card.get("detail_url") or card.get("link"),
                    created_at,
                ),
            )


async def packet_content_path(sqlite_path: Path, *, packet_id: str, vault_id: str | None = None) -> str | None:
    if vault_id:
        row = await fetch_one(sqlite_path, "SELECT content_path FROM packets WHERE id = ? AND vault_id = ?", (packet_id, vault_id))
    else:
        row = await fetch_one(sqlite_path, "SELECT content_path FROM packets WHERE id = ?", (packet_id,))
    return str(row["content_path"]) if row and row.get("content_path") else None
