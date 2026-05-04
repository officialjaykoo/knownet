from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..security import (
    Actor,
    authenticate_agent_token,
    ensure_text_size,
    record_agent_access,
    require_admin_access,
    require_actor,
    require_review_access,
    require_write_access,
    utc_now,
)
from ..routes.operator import build_ai_state_quality, build_provider_matrix
from ..services.packet_contract import (
    OUTPUT_MODES,
    PACKET_CONTRACT_VERSION,
    PROFILE_SECTION_RULES,
    SNAPSHOT_PROFILES,
    build_packet_contract,
    contract_shape,
    explicit_stale_context_suppression,
    packet_contract_markdown,
    validate_packet_contract,
)
from ..services.project_snapshot import (
    DEFAULT_PROJECT_SNAPSHOT_FOCUS,
    ai_context,
    do_not_suggest_rules,
    do_not_reopen,
    important_changes,
    next_action_hints,
    node_card,
    packet_issues,
    packet_summary,
    profile_char_budget,
    profile_hard_limits,
    project_snapshot_focus,
    snapshot_diff_summary,
    snapshot_self_test,
    target_agent_policy,
)
from ..services.rust_core import RustCoreError

try:
    import frontmatter
except Exception:  # pragma: no cover - fallback is for minimally installed dev envs.
    frontmatter = None


router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

SEVERITIES = {"critical", "high", "medium", "low", "info"}
AREAS = {"API": "API", "UI": "UI", "Rust": "Rust", "Security": "Security", "Data": "Data", "Ops": "Ops", "Docs": "Docs"}
AREA_NORMALIZE = {key.lower(): value for key, value in AREAS.items()}
EVIDENCE_QUALITIES = {"direct_access", "context_limited", "inferred", "operator_verified", "unspecified"}
DECISION_STATUSES = {"accepted", "rejected", "deferred", "needs_more_context"}
MAX_REVIEW_BYTES = 256 * 1024
MAX_FINDINGS_PER_REVIEW = 50
SECRET_ASSIGNMENT_NAMES = ("ADMIN_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "API_KEY", "SECRET", "PASSWORD")
SECRET_JSON_KEYS = ("token", "secret", "password", "key")
FORBIDDEN_BUNDLE_PATH_NAMES = {"backups", "inbox", "sessions", "users"}
EXCLUDED_SECTIONS = [
    ".env files and API key values",
    "knownet.db and *.db files",
    "data/backups/",
    "data/inbox/ raw pending messages",
    "data/tmp/",
    "sessions and users table contents",
    "audit_events IP hashes and session_meta",
    "raw citation evidence snapshots",
]
SECRET_ASSIGNMENT_RE = re.compile(r"^\s*(ADMIN_TOKEN|OPENAI_API_KEY|GEMINI_API_KEY|DEEPSEEK_API_KEY|API_KEY|SECRET|PASSWORD)\s*=", re.IGNORECASE)


class ImportReviewRequest(BaseModel):
    vault_id: str = "local-default"
    markdown: str = Field(min_length=1)
    source_agent: str | None = Field(default=None, max_length=80)
    source_model: str | None = Field(default=None, max_length=120)
    page_id: str | None = Field(default=None, max_length=120)


class FindingDecisionRequest(BaseModel):
    status: str
    decision_note: str | None = Field(default=None, max_length=2000)


class ImplementationRecordRequest(BaseModel):
    commit_sha: str | None = Field(default=None, max_length=80)
    changed_files: list[str] = Field(default_factory=list, max_length=100)
    verification: str = Field(min_length=1, max_length=4000)
    notes: str | None = Field(default=None, max_length=2000)


class FindingTaskRequest(BaseModel):
    priority: str = Field(default="normal", max_length=40)
    owner: str | None = Field(default=None, max_length=120)
    task_prompt: str | None = Field(default=None, max_length=4000)
    expected_verification: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


class ImplementationEvidenceRequest(BaseModel):
    commit_sha: str | None = Field(default=None, max_length=80)
    changed_files: list[str] = Field(default_factory=list, max_length=100)
    verification: str = Field(min_length=1, max_length=4000)
    notes: str | None = Field(default=None, max_length=2000)
    dry_run: bool = True
    include_git_status: bool = False


class SimpleImplementationEvidenceRequest(BaseModel):
    implemented: bool = True
    commit: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)
    changed_files: list[str] = Field(default_factory=list, max_length=100)
    dry_run: bool = False
    include_git_status: bool = False


class ContextBundleRequest(BaseModel):
    vault_id: str = "local-default"
    page_ids: list[str] = Field(default_factory=list, max_length=50)
    include_graph_summary: bool = True


class ProjectSnapshotPacketRequest(BaseModel):
    vault_id: str = "local-default"
    target_agent: str = Field(default="external_ai", max_length=80)
    focus: str = Field(default=DEFAULT_PROJECT_SNAPSHOT_FOCUS, min_length=1, max_length=1200)
    profile: str = Field(default="overview", max_length=40)
    output_mode: str = Field(default="top_findings", max_length=40)
    include_recent_tasks: int = Field(default=8, ge=1, le=20)
    include_recent_runs: int = Field(default=5, ge=1, le=20)
    since: str | None = Field(default=None, max_length=40)
    since_packet_id: str | None = Field(default=None, max_length=80)
    allow_since_packet_fallback: bool = False
    quality_acknowledged: bool = False


class ExperimentPacketRequest(BaseModel):
    vault_id: str = "local-default"
    experiment_name: str = Field(default="External AI experiment", min_length=1, max_length=180)
    task: str = Field(default="Perform the requested experiment step only.", min_length=1, max_length=2000)
    target_agent: str = Field(default="external_ai", max_length=80)
    node_slugs: list[str] = Field(default_factory=list, max_length=12)
    minimum_inline_context: str | None = Field(default=None, max_length=6000)
    scenarios: list[str] = Field(default_factory=list, max_length=50)
    output_mode: str = Field(default="top_findings", max_length=40)
    output_schema: str | None = Field(default=None, max_length=4000)
    max_node_chars: int = Field(default=1200, ge=400, le=4000)


class ExperimentPacketResponseRequest(BaseModel):
    response_markdown: str = Field(min_length=1, max_length=256 * 1024)
    source_agent: str = Field(default="external_ai", max_length=80)
    source_model: str | None = Field(default=None, max_length=120)


DEFAULT_EXPERIMENT_PACKET_SLUGS = [
    "claude-experiment-request-template",
    "access-fallback-protocol",
    "boundary-enforcement-protocol",
    "evidence-quality-registry",
    "findings-state-machine",
]

PACKET_SECTION_PRIORITY = {
    "access-fallback-protocol": {"fallback_order", "delivery_requirement", "trust_labels", "operator_actions"},
    "boundary-enforcement-protocol": {"violation_types", "response_policy", "observation_vs_assertion", "refusal_template"},
    "evidence-quality-registry": {"labels", "default_rules", "allowed_use_by_label", "release_use"},
    "findings-state-machine": {"states", "transition_rules", "evidence_quality_transition_rule", "ai_state_quality_rule"},
    "claude-experiment-request-template": {"request_shape", "split_request_rule", "parser_ready_finding", "pre_post_checks"},
}


def _title_from_markdown(markdown: str, fallback: str = "Agent review") -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()[:180]
    return fallback


def _parse_frontmatter(markdown: str) -> tuple[dict, str]:
    if frontmatter:
        post = frontmatter.loads(markdown)
        return dict(post.metadata), post.content
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end != -1:
            raw = markdown[4:end]
            meta: dict[str, str] = {}
            for line in raw.splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip("\"'")
            return meta, markdown[end + 5 :]
    return {}, markdown


def _field(block: str, name: str) -> str | None:
    match = re.search(rf"(?im)^\s*(?:\*\*)?{re.escape(name)}\s*:\s*(?:\*\*)?\s*(.+?)\s*$", block)
    return match.group(1).strip() if match else None


def _section(block: str, start: str, end: str | None = None) -> str | None:
    if end:
        pattern = rf"(?is)^\s*(?:\*\*)?{re.escape(start)}\s*:\s*(?:\*\*)?\s*\n(.*?)(?=^\s*(?:\*\*)?{re.escape(end)}\s*:\s*(?:\*\*)?\s*$|\Z)"
    else:
        pattern = rf"(?is)^\s*(?:\*\*)?{re.escape(start)}\s*:\s*(?:\*\*)?\s*\n(.*)\Z"
    match = re.search(pattern, block, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _normalize_area(value: str | None) -> str:
    if not value:
        return "Docs"
    return AREA_NORMALIZE.get(value.strip().lower(), "Docs")


def _normalize_evidence_quality(value: str | None) -> str:
    if not value:
        return "unspecified"
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized if normalized in EVIDENCE_QUALITIES else "unspecified"


def _finding_dedupe_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _extract_json_payload(text: str) -> dict | None:
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    match = re.search(r"(?is)```json\s*(\{.*?\})\s*```", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _parse_compact_review_json(data: dict, metadata: dict) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    output_mode = str(data.get("output_mode") or metadata.get("output_mode") or "top_findings").strip()
    if output_mode not in OUTPUT_MODES:
        errors.append(f"unsupported_output_mode:{output_mode}")
        output_mode = "top_findings"
    metadata["output_mode"] = output_mode
    findings_raw = data.get("findings") or data.get("implementation_candidates") or []
    if isinstance(findings_raw, dict):
        findings_raw = [findings_raw]
    if not isinstance(findings_raw, list):
        errors.append("compact_findings_not_list")
        findings_raw = []
    max_findings = int(OUTPUT_MODES[output_mode]["max_findings"])
    if output_mode == "decision_only" and findings_raw:
        errors.append("decision_only_does_not_accept_findings")
        findings_raw = []
    if len(findings_raw) > max_findings:
        errors.append(f"too_many_findings:{len(findings_raw)}>{max_findings}")
    findings: list[dict] = []
    for index, item in enumerate(findings_raw[:max_findings]):
        if not isinstance(item, dict):
            errors.append(f"compact_finding_not_object:{index + 1}")
            continue
        title = str(item.get("title") or item.get("candidate") or f"Finding {index + 1}").strip()[:220]
        evidence = item.get("evidence") or item.get("why") or item.get("reason")
        proposed_change = item.get("proposed_change") or item.get("implementation_shape") or item.get("change")
        if not evidence or not proposed_change:
            errors.append(f"compact_finding_missing_required_fields:{index + 1}")
        findings.append(
            {
                "severity": str(item.get("severity") or "info").lower() if str(item.get("severity") or "info").lower() in SEVERITIES else "info",
                "area": _normalize_area(str(item.get("area") or "Docs")),
                "title": title,
                "evidence": str(evidence or "Compact response did not include evidence."),
                "proposed_change": str(proposed_change or "Ask the provider to resend this item with a concrete proposed_change."),
                "raw_text": None,
                "evidence_quality": _normalize_evidence_quality(str(item.get("evidence_quality") or metadata.get("evidence_quality"))),
                "status": "pending",
            }
        )
    unsupported_sections = data.get("unsupported_sections") or data.get("extra_sections") or []
    if unsupported_sections:
        errors.append("unsupported_sections_present")
    if errors:
        metadata["ai_feedback_prompt"] = (
            "Revise the response to match the packet output contract. "
            f"Errors: {', '.join(errors)}. Return only supported compact findings."
        )
    return findings, errors


def _review_dry_run_result(markdown: str) -> dict:
    metadata, findings, parser_errors = parse_review_markdown(markdown)
    feedback = metadata.get("ai_feedback_prompt")
    import_ready = bool(findings) and not parser_errors
    return {
        "metadata": metadata,
        "finding_count": len(findings),
        "findings": findings,
        "parser_errors": parser_errors,
        "truncated_findings": bool(metadata.get("truncated_findings")),
        "import_ready": import_ready,
        "rejection_reason": None if import_ready else "parser_errors" if parser_errors else "no_findings",
        "ai_feedback_prompt": feedback,
    }


async def _finding_duplicate_groups(sqlite_path: Path, *, vault_id: str, statuses: set[str] | None = None, limit: int = 500) -> list[dict]:
    statuses = statuses or {"pending", "needs_more_context", "accepted", "deferred"}
    placeholders = ",".join("?" for _ in statuses)
    rows = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.review_id, f.severity, f.area, f.title, f.status, f.evidence_quality, f.updated_at, r.source_agent, r.title AS review_title "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        f"WHERE r.vault_id = ? AND f.status IN ({placeholders}) "
        "ORDER BY f.updated_at DESC LIMIT ?",
        (vault_id, *sorted(statuses), limit),
    )
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = _finding_dedupe_key(row.get("title"))
        if not key:
            continue
        groups.setdefault(key, []).append(row)
    result = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        items = sorted(items, key=lambda item: (severity_rank.get(item.get("severity"), 5), item.get("updated_at") or ""), reverse=False)
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


async def _finding_duplicate_candidates(sqlite_path: Path, *, vault_id: str, findings: list[dict]) -> list[dict]:
    if not findings:
        return []
    groups = await _finding_duplicate_groups(sqlite_path, vault_id=vault_id)
    by_key = {group["dedupe_key"]: group for group in groups}
    candidates = []
    for finding in findings:
        key = _finding_dedupe_key(finding.get("title"))
        if key in by_key:
            candidates.append({"title": finding.get("title"), "dedupe_key": key, "existing": by_key[key]})
    return candidates


async def ensure_collaboration_schema(sqlite_path: Path) -> None:
    from ..db.sqlite import execute

    await execute(
        sqlite_path,
        "CREATE TABLE IF NOT EXISTS finding_tasks ("
        "id TEXT PRIMARY KEY, finding_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'open', "
        "priority TEXT NOT NULL DEFAULT 'normal', owner TEXT, task_prompt TEXT NOT NULL, expected_verification TEXT, "
        "notes TEXT, created_by TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "FOREIGN KEY(finding_id) REFERENCES collaboration_findings(id))",
        (),
    )
    await execute(sqlite_path, "CREATE INDEX IF NOT EXISTS idx_finding_tasks_status ON finding_tasks(status, priority, updated_at)", ())
    await execute(
        sqlite_path,
        "CREATE TABLE IF NOT EXISTS experiment_packets ("
        "id TEXT PRIMARY KEY, vault_id TEXT NOT NULL DEFAULT 'local-default', experiment_name TEXT NOT NULL, "
        "target_agent TEXT NOT NULL, content_hash TEXT NOT NULL, content_path TEXT NOT NULL, node_slugs TEXT NOT NULL DEFAULT '[]', "
        "scenarios TEXT NOT NULL DEFAULT '[]', preflight_json TEXT NOT NULL DEFAULT '{}', created_by TEXT, created_at TEXT NOT NULL)",
        (),
    )
    await execute(
        sqlite_path,
        "CREATE TABLE IF NOT EXISTS experiment_packet_responses ("
        "id TEXT PRIMARY KEY, packet_id TEXT NOT NULL, source_agent TEXT NOT NULL, source_model TEXT, response_markdown TEXT NOT NULL, "
        "dry_run_json TEXT NOT NULL DEFAULT '{}', imported_review_id TEXT, created_at TEXT NOT NULL)",
        (),
    )
    await execute(sqlite_path, "CREATE INDEX IF NOT EXISTS idx_experiment_packets_vault_created ON experiment_packets(vault_id, created_at)", ())
    await execute(sqlite_path, "CREATE INDEX IF NOT EXISTS idx_experiment_packet_responses_packet ON experiment_packet_responses(packet_id, created_at)", ())
    await execute(
        sqlite_path,
        "CREATE TABLE IF NOT EXISTS project_snapshot_packets ("
        "id TEXT PRIMARY KEY, vault_id TEXT NOT NULL DEFAULT 'local-default', target_agent TEXT NOT NULL, "
        "profile TEXT NOT NULL DEFAULT 'overview', output_mode TEXT NOT NULL DEFAULT 'top_findings', focus TEXT NOT NULL, "
        "content_hash TEXT NOT NULL, content_path TEXT NOT NULL, warnings_json TEXT NOT NULL DEFAULT '[]', "
        "snapshot_quality_json TEXT NOT NULL DEFAULT '{}', contract_version TEXT NOT NULL DEFAULT 'p19.v1', "
        "created_by TEXT, created_at TEXT NOT NULL)",
        (),
    )
    await execute(sqlite_path, "CREATE INDEX IF NOT EXISTS idx_project_snapshot_packets_vault_created ON project_snapshot_packets(vault_id, created_at)", ())

    existing = await fetch_all(sqlite_path, "PRAGMA table_info(collaboration_findings)", ())
    if not existing:
        return
    columns = {row["name"] for row in existing}
    if "evidence_quality" not in columns:
        await execute(sqlite_path, "ALTER TABLE collaboration_findings ADD COLUMN evidence_quality TEXT NOT NULL DEFAULT 'unspecified'", ())
    rows = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.evidence_quality, r.source_agent, r.source_model, r.meta "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE f.evidence_quality IS NULL OR f.evidence_quality = 'unspecified'",
        (),
    )
    for row in rows:
        quality = "unspecified"
        try:
            meta = json.loads(row.get("meta") or "{}")
        except json.JSONDecodeError:
            meta = {}
        frontmatter = meta.get("frontmatter") if isinstance(meta, dict) else {}
        if isinstance(frontmatter, dict):
            quality = _normalize_evidence_quality(frontmatter.get("evidence_quality"))
        if quality != "unspecified":
            await execute(sqlite_path, "UPDATE collaboration_findings SET evidence_quality = ? WHERE id = ?", (quality, row["id"]))


def parse_review_markdown(markdown: str) -> tuple[dict, list[dict], list[str]]:
    metadata, body = _parse_frontmatter(markdown)
    errors: list[str] = []
    metadata.setdefault("type", "agent_review")
    metadata.setdefault("status", "pending_review")
    metadata.setdefault("source_agent", "unknown")
    metadata["evidence_quality"] = _normalize_evidence_quality(metadata.get("evidence_quality"))
    compact_json = _extract_json_payload(body)
    if compact_json:
        findings, compact_errors = _parse_compact_review_json(compact_json, metadata)
        return metadata, findings, compact_errors

    heading_matches = list(re.finditer(r"(?im)^(?:###\s+finding\b.*|\*\*Finding\b.*\*\*)\s*$", body))
    if not heading_matches:
        errors.append("no_finding_headings")
        return metadata, [
            {
                "severity": "info",
                "area": "Docs",
                "title": _title_from_markdown(markdown, "Unparsed review"),
                "evidence": None,
                "proposed_change": None,
                "raw_text": body.strip() or markdown,
                "evidence_quality": metadata["evidence_quality"],
                "status": "needs_more_context",
            }
        ], errors

    findings: list[dict] = []
    if len(heading_matches) > MAX_FINDINGS_PER_REVIEW:
        metadata["truncated_findings"] = True
        errors.append("truncated_findings")
    for index, match in enumerate(heading_matches[:MAX_FINDINGS_PER_REVIEW]):
        next_start = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(body)
        block = body[match.start() : next_start].strip()
        title = match.group(0).replace("###", "", 1).strip().strip("*").strip() or f"Finding {index + 1}"
        severity = (_field(block, "Severity") or "info").lower()
        if severity not in SEVERITIES:
            errors.append(f"unknown_severity:{severity}")
            severity = "info"
        area = _normalize_area(_field(block, "Area"))
        explicit_title = _field(block, "Title")
        evidence = _section(block, "Evidence", "Proposed change")
        proposed_change = _section(block, "Proposed change")
        evidence_quality = _normalize_evidence_quality(_field(block, "Evidence quality") or _field(block, "Evidence Quality") or metadata.get("evidence_quality"))
        status = "pending"
        raw_text = None
        if not evidence and not proposed_change:
            status = "needs_more_context"
            raw_text = block
            errors.append(f"malformed_finding:{index + 1}")
        findings.append(
            {
                "severity": severity,
                "area": area,
                "title": (explicit_title or title)[:220],
                "evidence": evidence,
                "proposed_change": proposed_change,
                "raw_text": raw_text,
                "evidence_quality": evidence_quality,
                "status": status,
            }
        )
    return metadata, findings, errors


def _http_from_rust(error: RustCoreError) -> HTTPException:
    status = 404 if error.code.endswith("_not_found") else 409 if "invalid_status" in error.code else 500
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details})


def _task_prompt_from_finding(row: dict) -> str:
    parts = [
        f"Implement accepted KnowNet finding: {row['title']}",
        f"Finding id: {row['id']}",
        f"Severity: {row['severity']}",
        f"Area: {row['area']}",
        f"Evidence quality: {row.get('evidence_quality') or 'unspecified'}",
    ]
    if row.get("evidence"):
        parts.append(f"Evidence: {row['evidence']}")
    if row.get("proposed_change"):
        parts.append(f"Requested change: {row['proposed_change']}")
    parts.append("Keep the change scoped. Record implementation evidence after verification.")
    return "\n\n".join(parts)


def _verification_from_finding(row: dict) -> str:
    area = str(row.get("area") or "").lower()
    if area == "docs":
        return "Run targeted docs/schema checks or explain why no executable check applies."
    if area in {"api", "security", "ops", "data"}:
        return "Run targeted API tests for the changed route/service and verify-index when collaboration state changes."
    if area == "ui":
        return "Run the web build and any targeted UI checks for the changed surface."
    if area == "rust":
        return "Run the targeted Rust test or cargo test for the affected crate."
    return "Run the smallest targeted verification that proves the finding is handled."


def _priority_from_finding(row: dict) -> str:
    return "high" if row.get("severity") in {"critical", "high"} else "normal"


def _should_auto_create_task(row: dict) -> bool:
    return row.get("severity") in {"critical", "high"} and row.get("evidence_quality") in {"direct_access", "operator_verified"}


def _implementation_task_template(row: dict) -> dict:
    finding_id = row["finding_id"] if row.get("finding_id") else row["id"]
    return {
        "endpoint": f"/api/collaboration/findings/{finding_id}/implementation-evidence",
        "method": "POST",
        "body": {
            "dry_run": True,
            "changed_files": [],
            "verification": row.get("expected_verification") or _verification_from_finding(row),
            "notes": "Targeted implementation evidence.",
        },
    }


def _simple_evidence_template(finding_id: str) -> dict:
    return {
        "endpoint": f"/api/collaboration/findings/{finding_id}/evidence",
        "method": "POST",
        "body": {"implemented": True, "commit": None, "note": "Implemented and verified with targeted checks."},
    }


def _task_creation_template(row: dict) -> dict:
    return {
        "endpoint": f"/api/collaboration/findings/{row['id']}/task",
        "method": "POST",
        "body": {
            "priority": _priority_from_finding(row),
            "owner": "codex",
            "task_prompt": _task_prompt_from_finding(row),
            "expected_verification": _verification_from_finding(row),
        },
    }


async def _upsert_finding_task(
    sqlite_path: Path,
    *,
    finding: dict,
    actor: Actor,
    priority: str,
    owner: str | None,
    task_prompt: str,
    expected_verification: str,
    notes: str | None,
) -> dict:
    from ..db.sqlite import execute

    existing = await fetch_one(sqlite_path, "SELECT id FROM finding_tasks WHERE finding_id = ?", (finding["id"],))
    task_id = existing["id"] if existing else f"task_{uuid4().hex[:12]}"
    now = utc_now()
    if existing:
        await execute(
            sqlite_path,
            "UPDATE finding_tasks SET priority = ?, owner = ?, task_prompt = ?, expected_verification = ?, notes = ?, updated_at = ? WHERE finding_id = ?",
            (priority, owner, task_prompt, expected_verification, notes, now, finding["id"]),
        )
    else:
        await execute(
            sqlite_path,
            "INSERT INTO finding_tasks (id, finding_id, status, priority, owner, task_prompt, expected_verification, notes, created_by, created_at, updated_at) "
            "VALUES (?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, finding["id"], priority, owner, task_prompt, expected_verification, notes, actor.actor_id, now, now),
        )
    task = await fetch_one(sqlite_path, "SELECT * FROM finding_tasks WHERE id = ?", (task_id,))
    return task


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _clean_changed_file(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if not value:
        raise HTTPException(status_code=422, detail={"code": "implementation_file_empty", "message": "Changed file path is empty", "details": {}})
    if re.match(r"^[A-Za-z]:", value) or value.startswith("/") or value.startswith("//") or ".." in value.split("/"):
        raise HTTPException(status_code=422, detail={"code": "implementation_file_forbidden_path", "message": "Changed files must be repository-relative paths", "details": {"path": path}})
    lowered = value.lower()
    forbidden = (".env", ".db", "data/backups/", "data/inbox/", "data/sessions", "knownet.db", "users")
    if any(term in lowered for term in forbidden):
        raise HTTPException(status_code=422, detail={"code": "implementation_file_forbidden_path", "message": "Changed file path references forbidden data", "details": {"path": value}})
    return value


def _clean_changed_files(paths: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for path in paths:
        value = _clean_changed_file(path)
        if value not in seen:
            seen.add(value)
            cleaned.append(value)
    return cleaned


def _git_changed_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(_repo_root()), "status", "--short", "--porcelain=v1"],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="ignore",
            timeout=8,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1].strip()
        raw = raw.strip('"')
        if raw:
            files.append(raw)
    return _clean_changed_files(files[:100])


async def _review_with_findings(sqlite_path: Path, review_id: str) -> dict:
    review = await fetch_one(sqlite_path, "SELECT * FROM collaboration_reviews WHERE id = ?", (review_id,))
    if not review:
        raise HTTPException(status_code=404, detail={"code": "collaboration_review_not_found", "message": "Review not found", "details": {"review_id": review_id}})
    findings = await fetch_all(sqlite_path, "SELECT * FROM collaboration_findings WHERE review_id = ? ORDER BY created_at, id", (review_id,))
    records = await fetch_all(
        sqlite_path,
        "SELECT * FROM implementation_records WHERE finding_id IN (SELECT id FROM collaboration_findings WHERE review_id = ?) ORDER BY created_at",
        (review_id,),
    )
    return {"review": review, "findings": findings, "implementation_records": records}


async def _rebuild_collaboration_graph(request: Request, vault_id: str) -> dict:
    try:
        return await request.app.state.rust_core.request(
            "rebuild_graph_for_vault",
            {
                "sqlite_path": str(request.app.state.settings.sqlite_path),
                "vault_id": vault_id,
                "rebuilt_at": utc_now(),
            },
        )
    except RustCoreError as error:
        return {"status": "failed", "code": error.code, "message": error.message}


def _assert_no_forbidden_json_keys(value, path: str = "data") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_JSON_KEYS):
                raise HTTPException(
                    status_code=422,
                    detail={"code": "context_bundle_secret_detected", "message": "Forbidden secret-like JSON key detected", "details": {"path": f"{path}.{key}"}},
                )
            _assert_no_forbidden_json_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_json_keys(child, f"{path}[{index}]")


def _assert_allowed_bundle_path(path_text: str, *, page_id: str | None = None) -> None:
    normalized = path_text.replace("\\", "/").lower()
    parts = [part for part in normalized.split("/") if part]
    forbidden = any(part in FORBIDDEN_BUNDLE_PATH_NAMES for part in parts)
    forbidden = forbidden or any(part == ".env" or part.endswith(".db") for part in parts)
    if forbidden:
        raise HTTPException(
            status_code=400,
            detail={"code": "context_bundle_forbidden_path", "message": "Forbidden path in context bundle", "details": {"path": path_text, "page_id": page_id}},
        )


def _assert_no_secret_text(text: str, settings, *, page_id: str | None = None) -> None:
    token = settings.admin_token or ""
    if token and len(token) >= settings.admin_token_min_chars and token in text:
        raise HTTPException(
            status_code=422,
            detail={"code": "context_bundle_secret_detected", "message": "Configured admin token detected", "details": {"page_id": page_id}},
        )
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if SECRET_ASSIGNMENT_RE.match(line):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "context_bundle_secret_detected",
                    "message": "Secret assignment detected",
                    "details": {"page_id": page_id, "line": line_number},
                },
            )


@router.post("/reviews")
async def import_review(payload: ImportReviewRequest, request: Request, dry_run: bool = False):
    settings = request.app.state.settings
    agent = None
    if (request.headers.get("authorization") or "").lower().startswith("bearer kn_agent_"):
        agent = await authenticate_agent_token(request, settings)
        if "reviews:create" not in agent.scopes or agent.role not in {"agent_reviewer", "agent_contributor"}:
            await record_agent_access(settings.sqlite_path, agent=agent, action="review.import", status="denied", meta={"reason": "scope_or_role"})
            raise HTTPException(status_code=403, detail={"code": "agent_scope_forbidden", "message": "Agent cannot create reviews", "details": {}})
        actor = agent.actor
    else:
        actor = await require_write_access(await require_actor(request, settings))
    ensure_text_size(payload.markdown, MAX_REVIEW_BYTES, "markdown")
    metadata, findings, parser_errors = parse_review_markdown(payload.markdown)
    if payload.source_agent:
        metadata["source_agent"] = payload.source_agent
    elif agent:
        metadata["source_agent"] = agent.agent_name
    if payload.source_model:
        metadata["source_model"] = payload.source_model
    elif agent and agent.agent_model:
        metadata["source_model"] = agent.agent_model
    if not findings:
        raise HTTPException(status_code=422, detail={"code": "collaboration_no_findings", "message": "No findings found", "details": {}})
    duplicate_candidates = await _finding_duplicate_candidates(settings.sqlite_path, vault_id=payload.vault_id or actor.vault_id, findings=findings)
    if dry_run:
        if agent:
            await record_agent_access(
                settings.sqlite_path,
                agent=agent,
                action="review.dry_run",
                status="ok",
                meta={"finding_count": len(findings), "parser_errors": parser_errors, "truncated_findings": bool(metadata.get("truncated_findings")), "duplicate_candidate_count": len(duplicate_candidates)},
            )
        return {
            "ok": True,
            "data": {
                "dry_run": True,
                "metadata": metadata,
                "finding_count": len(findings),
                "findings": findings,
                "duplicate_candidates": duplicate_candidates,
                "parser_errors": parser_errors,
                "truncated_findings": bool(metadata.get("truncated_findings")),
            },
        }

    review_id = f"review_{uuid4().hex[:12]}"
    now = utc_now()
    source_agent = payload.source_agent or str(metadata.get("source_agent") or "unknown")
    source_model = payload.source_model or metadata.get("source_model")
    title = _title_from_markdown(payload.markdown)
    meta = {
        "frontmatter": metadata,
        "parser_errors": parser_errors,
        "markdown_path": f"data/pages/reviews/{review_id}.md",
    }
    try:
        review = await request.app.state.rust_core.request(
            "create_collaboration_review",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "review_id": review_id,
                "vault_id": payload.vault_id or actor.vault_id,
                "title": title,
                "source_agent": source_agent,
                "source_model": source_model,
                "review_type": "agent_review",
                "page_id": payload.page_id,
                "markdown": payload.markdown,
                "meta": json.dumps(meta, ensure_ascii=True, sort_keys=True),
                "created_at": now,
            },
        )
        created_findings = []
        for finding in findings:
            created = await request.app.state.rust_core.request(
                "create_collaboration_finding",
                {
                    "sqlite_path": str(settings.sqlite_path),
                    "finding_id": f"finding_{uuid4().hex[:12]}",
                    "review_id": review_id,
                    "created_at": now,
                    **finding,
                },
            )
            created_findings.append(created)
    except RustCoreError as error:
        raise _http_from_rust(error) from error

    graph_rebuild = await _rebuild_collaboration_graph(request, payload.vault_id or actor.vault_id)
    await write_audit_event(
        settings.sqlite_path,
        action="review.import",
        actor=actor,
        target_type="collaboration_review",
        target_id=review_id,
        metadata={"source_agent": source_agent, "findings": len(created_findings), "parser_errors": parser_errors, "duplicate_candidate_count": len(duplicate_candidates), "graph_rebuild": graph_rebuild},
    )
    if agent:
        await record_agent_access(settings.sqlite_path, agent=agent, action="review.import", status="ok", target_type="collaboration_review", target_id=review_id, meta={"finding_count": len(created_findings)})
    return {"ok": True, "data": {"review": review, "findings": created_findings, "graph_rebuild": graph_rebuild}}


@router.get("/reviews")
async def list_reviews(
    request: Request,
    vault_id: str = "local-default",
    status: str | None = "pending_review",
    source_agent: str | None = None,
    area: str | None = None,
    limit: int = 50,
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    limit = min(max(limit, 1), 200)
    where = ["r.vault_id = ?"]
    params: list = [vault_id]
    if status:
        where.append("r.status = ?")
        params.append(status)
    if source_agent:
        where.append("r.source_agent = ?")
        params.append(source_agent)
    if area:
        where.append("EXISTS (SELECT 1 FROM collaboration_findings f WHERE f.review_id = r.id AND f.area = ?)")
        params.append(area)
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT r.*, "
        "(SELECT COUNT(*) FROM collaboration_findings f WHERE f.review_id = r.id) AS finding_count, "
        "(SELECT COUNT(*) FROM collaboration_findings f WHERE f.review_id = r.id AND f.status = 'pending') AS pending_count "
        f"FROM collaboration_reviews r WHERE {' AND '.join(where)} ORDER BY r.updated_at DESC LIMIT ?",
        (*params, limit),
    )
    return {"ok": True, "data": {"reviews": rows, "actor_role": actor.role}}


@router.get("/reviews/{review_id}")
async def get_review(review_id: str, request: Request, actor: Actor = Depends(require_review_access)):
    return {"ok": True, "data": await _review_with_findings(request.app.state.settings.sqlite_path, review_id)}


@router.post("/findings/{finding_id}/decision")
async def decide_finding(
    finding_id: str,
    payload: FindingDecisionRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    if payload.status not in DECISION_STATUSES:
        raise HTTPException(status_code=409, detail={"code": "collaboration_invalid_status", "message": "Invalid finding status", "details": {"status": payload.status}})
    settings = request.app.state.settings
    existing = await fetch_one(settings.sqlite_path, "SELECT id, review_id FROM collaboration_findings WHERE id = ?", (finding_id,))
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    try:
        result = await request.app.state.rust_core.request(
            "update_finding_decision",
            {
                "sqlite_path": str(settings.sqlite_path),
                "finding_id": finding_id,
                "status": payload.status,
                "decision_note": payload.decision_note,
                "decided_by": actor.actor_id,
                "decided_at": utc_now(),
            },
        )
        pending = await fetch_one(
            settings.sqlite_path,
            "SELECT COUNT(*) AS count FROM collaboration_findings WHERE review_id = ? AND status = 'pending'",
            (existing["review_id"],),
        )
        review_status = "triaged" if pending and pending["count"] == 0 else "pending_review"
        await request.app.state.rust_core.request(
            "update_collaboration_review_status",
            {
                "sqlite_path": str(settings.sqlite_path),
                "review_id": existing["review_id"],
                "status": review_status,
                "updated_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise _http_from_rust(error) from error
    auto_task = None
    if payload.status == "accepted":
        accepted_finding = await fetch_one(
            settings.sqlite_path,
            "SELECT f.*, r.vault_id, r.title AS review_title, r.source_agent, r.source_model "
            "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE f.id = ?",
            (finding_id,),
        )
        if accepted_finding and _should_auto_create_task(accepted_finding):
            priority = _priority_from_finding(accepted_finding)
            auto_task = await _upsert_finding_task(
                settings.sqlite_path,
                finding=accepted_finding,
                actor=actor,
                priority=priority,
                owner="codex",
                task_prompt=_task_prompt_from_finding(accepted_finding),
                expected_verification=_verification_from_finding(accepted_finding),
                notes="Auto-created when the finding was accepted.",
            )
    graph_rebuild = await _rebuild_collaboration_graph(request, actor.vault_id)
    await write_audit_event(
        settings.sqlite_path,
        action=f"finding.{payload.status}",
        actor=actor,
        target_type="collaboration_finding",
        target_id=finding_id,
        metadata={"decision_note": payload.decision_note, "auto_task_id": auto_task["id"] if auto_task else None, "graph_rebuild": graph_rebuild},
    )
    return {"ok": True, "data": {**result, "auto_task": auto_task, "graph_rebuild": graph_rebuild}}


@router.post("/findings/{finding_id}/implementation")
async def record_implementation(
    finding_id: str,
    payload: ImplementationRecordRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    return await _record_implementation_result(
        finding_id,
        commit_sha=payload.commit_sha,
        changed_files=payload.changed_files,
        verification=payload.verification,
        notes=payload.notes,
        request=request,
        actor=actor,
    )


async def _record_implementation_result(
    finding_id: str,
    *,
    commit_sha: str | None,
    changed_files: list[str],
    verification: str,
    notes: str | None,
    request: Request,
    actor: Actor,
):
    from ..db.sqlite import execute

    if commit_sha and not re.match(r"^[A-Fa-f0-9]{7,40}$", commit_sha):
        raise HTTPException(status_code=422, detail={"code": "implementation_record_invalid_commit", "message": "Invalid commit hash", "details": {}})
    cleaned_files = _clean_changed_files(changed_files)
    settings = request.app.state.settings
    record_id = f"impl_{uuid4().hex[:12]}"
    try:
        result = await request.app.state.rust_core.request(
            "create_implementation_record",
            {
                "sqlite_path": str(settings.sqlite_path),
                "record_id": record_id,
                "finding_id": finding_id,
                "commit_sha": commit_sha,
                "changed_files": json.dumps(cleaned_files, ensure_ascii=True),
                "verification": verification,
                "notes": notes,
                "created_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise _http_from_rust(error) from error
    now = utc_now()
    task = await fetch_one(settings.sqlite_path, "SELECT id FROM finding_tasks WHERE finding_id = ?", (finding_id,))
    if task:
        await execute(settings.sqlite_path, "UPDATE finding_tasks SET status = 'done', updated_at = ? WHERE finding_id = ?", (now, finding_id))
    graph_rebuild = await _rebuild_collaboration_graph(request, actor.vault_id)
    await write_audit_event(
        settings.sqlite_path,
        action="implementation.record",
        actor=actor,
        target_type="collaboration_finding",
        target_id=finding_id,
        metadata={"record_id": record_id, "commit_sha": commit_sha, "changed_files": cleaned_files, "task_id": task["id"] if task else None, "graph_rebuild": graph_rebuild},
    )
    return {"ok": True, "data": {**result, "changed_files": cleaned_files, "task_id": task["id"] if task else None, "graph_rebuild": graph_rebuild}}


@router.post("/findings/{finding_id}/implementation-evidence")
async def record_implementation_evidence(
    finding_id: str,
    payload: ImplementationEvidenceRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    finding = await fetch_one(settings.sqlite_path, "SELECT id, status, title FROM collaboration_findings WHERE id = ?", (finding_id,))
    if not finding:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    changed_files = payload.changed_files or (_git_changed_files() if payload.include_git_status else [])
    cleaned_files = _clean_changed_files(changed_files)
    if payload.commit_sha and not re.match(r"^[A-Fa-f0-9]{7,40}$", payload.commit_sha):
        raise HTTPException(status_code=422, detail={"code": "implementation_record_invalid_commit", "message": "Invalid commit hash", "details": {}})
    task = await fetch_one(settings.sqlite_path, "SELECT * FROM finding_tasks WHERE finding_id = ?", (finding_id,))
    draft = {
        "finding_id": finding_id,
        "finding_status": finding["status"],
        "title": finding["title"],
        "commit_sha": payload.commit_sha,
        "changed_files": cleaned_files,
        "verification": payload.verification,
        "notes": payload.notes,
        "task_id": task["id"] if task else None,
        "would_mark_task_done": bool(task),
        "would_mark_finding_implemented": True,
    }
    if payload.dry_run:
        await write_audit_event(
            settings.sqlite_path,
            action="implementation_evidence.dry_run",
            actor=actor,
            target_type="collaboration_finding",
            target_id=finding_id,
            metadata={"changed_files": cleaned_files, "task_id": task["id"] if task else None},
        )
        return {"ok": True, "data": {"dry_run": True, "draft": draft}}
    result = await _record_implementation_result(
        finding_id,
        commit_sha=payload.commit_sha,
        changed_files=cleaned_files,
        verification=payload.verification,
        notes=payload.notes,
        request=request,
        actor=actor,
    )
    return {"ok": True, "data": {"dry_run": False, "draft": draft, "record": result["data"]}}


@router.post("/findings/{finding_id}/evidence")
async def record_simple_evidence(
    finding_id: str,
    payload: SimpleImplementationEvidenceRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    if not payload.implemented:
        raise HTTPException(status_code=409, detail={"code": "implementation_evidence_not_implemented", "message": "Use the full evidence endpoint for blocked or partial work", "details": {}})
    verification = payload.note.strip() if payload.note else "Implemented and verified with targeted checks."
    evidence_payload = ImplementationEvidenceRequest(
        commit_sha=payload.commit,
        changed_files=payload.changed_files,
        verification=verification,
        notes=payload.note,
        dry_run=payload.dry_run,
        include_git_status=payload.include_git_status,
    )
    return await record_implementation_evidence(finding_id, evidence_payload, request, actor)


@router.get("/finding-queue")
async def list_finding_queue(
    request: Request,
    vault_id: str = "local-default",
    status: str = "accepted",
    limit: int = 50,
    actor: Actor = Depends(require_review_access),
):
    if status not in {"accepted", "needs_more_context", "deferred"}:
        raise HTTPException(status_code=409, detail={"code": "finding_queue_invalid_status", "message": "Invalid queue status", "details": {"status": status}})
    limit = max(1, min(limit, 100))
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT f.*, r.vault_id, r.title AS review_title, r.source_agent, r.source_model, "
        "t.id AS task_id, t.status AS task_status, t.priority AS task_priority, t.owner AS task_owner, "
        "t.task_prompt, t.expected_verification, t.updated_at AS task_updated_at, "
        "(SELECT COUNT(*) FROM implementation_records i WHERE i.finding_id = f.id) AS implementation_count "
        "FROM collaboration_findings f "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        "LEFT JOIN finding_tasks t ON t.finding_id = f.id "
        "WHERE r.vault_id = ? AND f.status = ? "
        "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, f.updated_at DESC "
        "LIMIT ?",
        (vault_id, status, limit),
    )
    queue = []
    for row in rows:
        generated_prompt = _task_prompt_from_finding(row)
        generated_verification = _verification_from_finding(row)
        queue.append(
            {
                **row,
                "task_prompt": row.get("task_prompt") or generated_prompt,
                "expected_verification": row.get("expected_verification") or generated_verification,
                "has_task": bool(row.get("task_id")),
                "actionable": row.get("implementation_count", 0) == 0,
            }
        )
    return {"ok": True, "data": {"queue": queue, "actor_role": actor.role}}


@router.get("/finding-duplicates")
async def list_finding_duplicates(
    request: Request,
    vault_id: str = "local-default",
    status_scope: str = "open",
    limit: int = 500,
    actor: Actor = Depends(require_review_access),
):
    if status_scope == "open":
        statuses = {"pending", "needs_more_context", "accepted", "deferred"}
    elif status_scope == "pending":
        statuses = {"pending", "needs_more_context"}
    elif status_scope == "accepted":
        statuses = {"accepted"}
    else:
        raise HTTPException(status_code=409, detail={"code": "finding_duplicates_invalid_scope", "message": "Invalid duplicate scope", "details": {"status_scope": status_scope}})
    groups = await _finding_duplicate_groups(request.app.state.settings.sqlite_path, vault_id=vault_id, statuses=statuses, limit=max(20, min(limit, 1000)))
    return {
        "ok": True,
        "data": {
            "duplicate_groups": groups,
            "duplicate_group_count": len(groups),
            "candidate_finding_count": sum(group["count"] for group in groups),
            "status_scope": status_scope,
            "actor_role": actor.role,
        },
    }


@router.get("/findings/{finding_id}")
async def get_finding(
    finding_id: str,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    row = await fetch_one(
        request.app.state.settings.sqlite_path,
        "SELECT f.*, r.vault_id, r.title AS review_title, r.source_agent, r.source_model "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE f.id = ?",
        (finding_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    return {"ok": True, "data": {"finding": row, "actor_role": actor.role}}


@router.get("/finding-tasks")
async def list_finding_tasks(
    request: Request,
    status: str = "open",
    limit: int = 50,
    actor: Actor = Depends(require_review_access),
):
    if status not in {"open", "in_progress", "done", "blocked", "all"}:
        raise HTTPException(status_code=409, detail={"code": "finding_task_invalid_status", "message": "Invalid task status", "details": {"status": status}})
    limit = max(1, min(limit, 100))
    where = "" if status == "all" else "WHERE t.status = ?"
    params: tuple = (limit,) if status == "all" else (status, limit)
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT t.*, f.review_id, f.severity, f.area, f.title, f.evidence_quality, f.status AS finding_status, "
        "r.title AS review_title, r.source_agent, r.source_model "
        "FROM finding_tasks t "
        "JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        f"{where} "
        "ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, t.updated_at DESC "
        "LIMIT ?",
        params,
    )
    return {"ok": True, "data": {"tasks": rows, "actor_role": actor.role}}


@router.get("/finding-tasks/{task_id}")
async def get_finding_task(
    task_id: str,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    row = await fetch_one(
        request.app.state.settings.sqlite_path,
        "SELECT t.*, f.review_id, f.severity, f.area, f.title, f.evidence_quality, f.status AS finding_status, "
        "r.title AS review_title, r.source_agent, r.source_model "
        "FROM finding_tasks t "
        "JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE t.id = ?",
        (task_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "finding_task_not_found", "message": "Finding task not found", "details": {"task_id": task_id}})
    return {"ok": True, "data": {"task": row, "actor_role": actor.role}}


@router.get("/patch-suggestion")
async def patch_suggestion(
    finding_id: str,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    finding = await fetch_one(request.app.state.settings.sqlite_path, "SELECT id, title, status FROM collaboration_findings WHERE id = ?", (finding_id,))
    if not finding:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    return {
        "ok": True,
        "data": {
            "status": "unsupported_until_implemented",
            "finding": finding,
            "safety_contract": {
                "requires_local_code_context": True,
                "external_ai_raw_code_access": False,
                "exposes_secrets": False,
                "returns_unified_diff_only_after_operator_request": True,
            },
            "actor_role": actor.role,
        },
    }


@router.get("/next-action")
async def next_action(
    request: Request,
    vault_id: str = "local-default",
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    task = await fetch_one(
        settings.sqlite_path,
        "SELECT t.*, f.review_id, f.severity, f.area, f.title, f.evidence, f.proposed_change, f.evidence_quality, f.status AS finding_status, "
        "r.title AS review_title, r.source_agent, r.source_model "
        "FROM finding_tasks t "
        "JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND t.status IN ('open','in_progress') "
        "ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, "
        "CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, t.updated_at DESC LIMIT 1",
        (vault_id,),
    )
    if task:
        return {
            "ok": True,
            "data": {
                "action_type": "implement_finding_task",
                "priority": task["priority"],
                "finding_id": task["finding_id"],
                "task_id": task["id"],
                "title": task["title"],
                "task_prompt": task["task_prompt"],
                "expected_verification": task["expected_verification"],
                "evidence_quality": task["evidence_quality"],
                "source": {"review_id": task["review_id"], "review_title": task["review_title"], "source_agent": task["source_agent"]},
                "after_implementation": {
                    "endpoint": f"/api/collaboration/findings/{task['finding_id']}/implementation-evidence",
                    "method": "POST",
                    "dry_run_first": True,
                },
                "task_template": _implementation_task_template(task),
                "simple_evidence_template": _simple_evidence_template(task["finding_id"]),
                "actor_role": actor.role,
            },
        }

    counts = await fetch_one(
        settings.sqlite_path,
        "SELECT "
        "(SELECT COUNT(*) FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context')) AS pending_findings, "
        "(SELECT COUNT(*) FROM collaboration_reviews WHERE vault_id = ? AND status = 'pending_review') AS pending_reviews, "
        "(SELECT COUNT(*) FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status = 'accepted') AS accepted_findings",
        (vault_id, vault_id, vault_id),
    )
    pending_findings = int(counts["pending_findings"] or 0) if counts else 0
    pending_reviews = int(counts["pending_reviews"] or 0) if counts else 0
    accepted_findings = int(counts["accepted_findings"] or 0) if counts else 0

    finding = await fetch_one(
        settings.sqlite_path,
        "SELECT f.*, r.vault_id, r.title AS review_title, r.source_agent, r.source_model, "
        "(SELECT COUNT(*) FROM implementation_records i WHERE i.finding_id = f.id) AS implementation_count "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status = 'accepted' "
        "ORDER BY CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, f.updated_at DESC LIMIT 1",
        (vault_id,),
    )
    if finding:
        return {
            "ok": True,
            "data": {
                "action_type": "create_task_from_accepted_finding",
                "priority": "high" if finding["severity"] in {"critical", "high"} else "normal",
                "finding_id": finding["id"],
                "title": finding["title"],
                "task_prompt": _task_prompt_from_finding(finding),
                "expected_verification": _verification_from_finding(finding),
                "evidence_quality": finding["evidence_quality"],
                "source": {"review_id": finding["review_id"], "review_title": finding["review_title"], "source_agent": finding["source_agent"]},
                "next_endpoint": f"/api/collaboration/findings/{finding['id']}/task",
                "method": "POST",
                "task_template": _task_creation_template(finding),
                "reason": "Backlog-aware routing: convert accepted work before asking Gemini for more advice.",
                "actor_role": actor.role,
            },
        }

    duplicate_groups = await _finding_duplicate_groups(settings.sqlite_path, vault_id=vault_id, statuses={"pending", "needs_more_context", "accepted", "deferred"}, limit=500)
    if duplicate_groups or pending_findings >= 10 or pending_reviews >= 5:
        return {
            "ok": True,
            "data": {
                "action_type": "compress_review_queue",
                "priority": "high" if duplicate_groups or pending_findings >= 20 else "normal",
                "title": "Compress and triage external AI findings",
                "detail": f"Backlog has {pending_reviews} pending review(s), {pending_findings} pending/needs-more-context finding(s), and {len(duplicate_groups)} duplicate title group(s). Reduce noise before asking Gemini for another review.",
                "next_endpoint": "/api/collaboration/finding-duplicates",
                "method": "GET",
                "fallback_endpoint": "/api/collaboration/reviews",
                "task_template": {"endpoint": "/api/collaboration/finding-duplicates", "method": "GET", "body": None},
                "actor_role": actor.role,
            },
        }

    if settings.gemini_runner_enabled and settings.gemini_api_key:
        return {
            "ok": True,
            "data": {
                "action_type": "run_ai_review_now",
                "priority": "normal",
                "title": "Run Gemini fast-lane review",
                "detail": f"Gemini is configured. Use the server-side fast lane before packet fallback; queue has {accepted_findings} accepted finding(s), {pending_reviews} pending review(s), and {pending_findings} pending/needs-more-context finding(s).",
                "next_endpoint": "/api/model-runs/review-now",
                "method": "POST",
                "payload": {
                    "provider": "gemini",
                    "prefer_live": True,
                    "allow_mock_fallback": False,
                    "auto_import": False,
                    "max_pages": 10,
                    "max_findings": 15,
                    "slim_context": True,
                },
                "task_template": {
                    "endpoint": "/api/model-runs/review-now",
                    "method": "POST",
                    "body": {
                        "provider": "gemini",
                        "prefer_live": True,
                        "allow_mock_fallback": False,
                        "auto_import": False,
                        "max_pages": 10,
                        "max_findings": 15,
                        "slim_context": True,
                    },
                },
                "actor_role": actor.role,
            },
        }

    if pending_findings or pending_reviews:
        return {
            "ok": True,
            "data": {
                "action_type": "triage_review_findings",
                "priority": "normal",
                "title": "Triage pending external AI findings",
                "detail": f"{pending_reviews} pending review(s), {pending_findings} pending/needs-more-context finding(s).",
                "next_endpoint": "/api/collaboration/reviews",
                "method": "GET",
                "task_template": {"endpoint": "/api/collaboration/reviews", "method": "GET", "body": None},
                "actor_role": actor.role,
            },
        }
    return {
        "ok": True,
        "data": {
            "action_type": "generate_project_snapshot",
            "priority": "low",
            "title": "No actionable finding task is queued",
            "detail": "Generate a project snapshot packet for external AI review or create new accepted findings.",
            "next_endpoint": "/api/collaboration/project-snapshot-packets",
            "method": "POST",
            "task_template": {
                "endpoint": "/api/collaboration/project-snapshot-packets",
                "method": "POST",
                "body": {
                    "vault_id": vault_id,
                    "target_agent": "external_ai",
                    "focus": "Identify the next highest-leverage implementation action.",
                },
            },
            "actor_role": actor.role,
        },
    }


@router.post("/findings/{finding_id}/task")
async def create_finding_task(
    finding_id: str,
    payload: FindingTaskRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    await ensure_collaboration_schema(settings.sqlite_path)
    finding = await fetch_one(
        settings.sqlite_path,
        "SELECT f.*, r.vault_id, r.title AS review_title, r.source_agent, r.source_model "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE f.id = ?",
        (finding_id,),
    )
    if not finding:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    if finding["status"] != "accepted":
        raise HTTPException(
            status_code=409,
            detail={"code": "finding_task_requires_accepted", "message": "Only accepted findings can become implementation tasks", "details": {"status": finding["status"]}},
        )
    priority = payload.priority.strip().lower() if payload.priority else "normal"
    if priority not in {"urgent", "high", "normal", "low"}:
        raise HTTPException(status_code=409, detail={"code": "finding_task_invalid_priority", "message": "Invalid task priority", "details": {"priority": payload.priority}})
    task_prompt = payload.task_prompt.strip() if payload.task_prompt else _task_prompt_from_finding(finding)
    expected_verification = payload.expected_verification.strip() if payload.expected_verification else _verification_from_finding(finding)
    task = await _upsert_finding_task(
        settings.sqlite_path,
        finding=finding,
        actor=actor,
        priority=priority,
        owner=payload.owner,
        task_prompt=task_prompt,
        expected_verification=expected_verification,
        notes=payload.notes,
    )
    await write_audit_event(
        settings.sqlite_path,
        action="finding.task_upsert",
        actor=actor,
        target_type="collaboration_finding",
        target_id=finding_id,
        metadata={"task_id": task["id"], "priority": priority},
    )
    return {"ok": True, "data": {"task": task, "finding": finding}}


def _strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end != -1:
            return markdown[end + 5 :].lstrip()
    return markdown


def _packet_excerpt(markdown: str, *, max_chars: int) -> str:
    text = _strip_frontmatter(markdown).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit("\n", 1)[0].strip()
    return (cut or text[:max_chars].strip()) + "\n\n[truncated for packet]"


def _packet_sections(markdown: str) -> list[dict[str, str]]:
    text = _strip_frontmatter(markdown).strip()
    matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if not matches:
        return [{"heading": "body", "key": "body", "text": text}]
    sections = [{"heading": "intro", "key": "intro", "text": text[: matches[0].start()].strip()}]
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(1).strip()
        key = re.sub(r"[^a-z0-9]+", "_", heading.lower()).strip("_")
        sections.append({"heading": heading, "key": key, "text": text[match.start() : end].strip()})
    return [section for section in sections if section["text"]]


def _packet_excerpt_for_slug(slug: str, markdown: str, *, max_chars: int) -> str:
    priorities = PACKET_SECTION_PRIORITY.get(slug)
    if not priorities:
        return _packet_excerpt(markdown, max_chars=max_chars)
    sections = _packet_sections(markdown)
    selected = [section["text"] for section in sections if section["key"] in priorities]
    if not selected:
        return _packet_excerpt(markdown, max_chars=max_chars)
    text = "\n\n".join(selected)
    if len(text) <= max_chars:
        return text
    return _packet_excerpt(text, max_chars=max_chars)


def _validate_packet_slugs(slugs: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", slug.strip().lower()).strip("-")
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


async def _packet_preflight(sqlite_path: Path, vault_id: str) -> dict:
    rows = await fetch_one(
        sqlite_path,
        "SELECT "
        "(SELECT COUNT(*) FROM pages WHERE vault_id = ? AND status = 'active') AS pages, "
        "(SELECT COUNT(*) FROM ai_state_pages WHERE vault_id = ?) AS ai_state_pages, "
        "(SELECT COUNT(*) FROM graph_nodes WHERE vault_id = ? AND node_type = 'unresolved') AS unresolved_nodes, "
        "(SELECT COUNT(*) FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context')) AS pending_findings",
        (vault_id, vault_id, vault_id, vault_id),
    )
    return rows or {"pages": 0, "ai_state_pages": 0, "unresolved_nodes": 0, "pending_findings": 0}


async def _project_snapshot_delta(sqlite_path: Path, vault_id: str, since: str | None) -> dict | None:
    if not since:
        return None
    try:
        datetime.fromisoformat(since.replace("Z", "+00:00"))
    except ValueError as error:
        raise HTTPException(status_code=422, detail={"code": "project_snapshot_invalid_since", "message": "since must be an ISO-8601 timestamp", "details": {"since": since}}) from error
    pages = await fetch_all(
        sqlite_path,
        "SELECT id, slug, title, status, updated_at FROM pages WHERE vault_id = ? AND updated_at > ? ORDER BY updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    findings = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.severity, f.area, f.title, f.status, f.evidence_quality, f.updated_at, r.source_agent "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.updated_at > ? ORDER BY f.updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    tasks = await fetch_all(
        sqlite_path,
        "SELECT t.id, t.finding_id, t.status, t.priority, t.updated_at, f.title "
        "FROM finding_tasks t JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND t.updated_at > ? ORDER BY t.updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    runs = await fetch_all(
        sqlite_path,
        "SELECT id, provider, model, status, response_json, updated_at FROM model_review_runs WHERE vault_id = ? AND updated_at > ? ORDER BY updated_at DESC LIMIT 25",
        (vault_id, since),
    )
    failed_runs = [row for row in runs if row.get("status") == "failed"]
    return {
        "since": since,
        "pages": pages,
        "findings": findings,
        "finding_tasks": tasks,
        "model_runs": runs,
        "delta_summary": {
            "changed_nodes": len(pages),
            "new_or_updated_findings": len(findings),
            "changed_tasks": len(tasks),
            "model_runs": len(runs),
            "failed_runs": len(failed_runs),
        },
    }


async def _resolve_snapshot_since(settings, payload: ProjectSnapshotPacketRequest, profile: str) -> tuple[str | None, dict | None, list[str]]:
    warnings: list[str] = []
    since = payload.since
    since_packet = None
    if payload.since_packet_id:
        since_packet = await fetch_one(settings.sqlite_path, "SELECT * FROM project_snapshot_packets WHERE id = ? AND vault_id = ?", (payload.since_packet_id, payload.vault_id))
        if not since_packet:
            if not payload.allow_since_packet_fallback:
                raise HTTPException(status_code=404, detail={"code": "project_snapshot_since_packet_not_found", "message": "since_packet_id was not found", "details": {"since_packet_id": payload.since_packet_id}})
            warnings.append("since_packet_missing_full_snapshot")
        else:
            since = since_packet["created_at"]
            if since_packet["profile"] != profile:
                warnings.append("profile_mismatch_delta")
    return since, since_packet, warnings


def _snapshot_quality(
    *,
    content: str,
    profile: str,
    warnings: list[str],
    preflight: dict,
    accepted_rows: list[dict],
    task_rows: list[dict],
    duplicate_groups: list[dict],
    delta: dict | None,
    quality_acknowledged: bool,
) -> dict:
    quality_warnings = list(warnings)
    pending = int(preflight.get("pending_findings") or 0)
    if pending > 10:
        quality_warnings.append("too_many_pending_findings")
    if duplicate_groups:
        quality_warnings.append("duplicate_noise")
    evidence_values = [str(row.get("evidence_quality") or "unspecified") for row in [*accepted_rows, *task_rows]]
    if evidence_values:
        context_limited = sum(1 for value in evidence_values if value == "context_limited")
        if context_limited / max(1, len(evidence_values)) >= 0.6:
            quality_warnings.append("mostly_context_limited")
    else:
        context_limited = 0
    char_budget = profile_char_budget(profile)
    if len(content) > char_budget:
        quality_warnings.append("oversized_packet")
    if delta is not None and not any(delta[key] for key in ("pages", "findings", "finding_tasks", "model_runs")):
        quality_warnings.append("stale_delta")
    unique = []
    seen = set()
    for warning in quality_warnings:
        if warning not in seen:
            seen.add(warning)
            unique.append(warning)
    score = max(0, 100 - len(unique) * 12 - min(20, len(content) // 6000))
    detail = {
        "pending_findings": pending,
        "duplicate_groups": len(duplicate_groups),
        "evidence_items": len(evidence_values),
        "context_limited_ratio": round(context_limited / max(1, len(evidence_values)), 2) if evidence_values else 0,
        "content_chars": len(content),
        "profile": profile,
        "profile_char_budget": char_budget,
        "delta_empty": bool(delta is not None and not any(delta[key] for key in ("pages", "findings", "finding_tasks", "model_runs"))),
    }
    warning_details = {
        "too_many_pending_findings": f"{pending} pending/needs-more-context findings",
        "duplicate_noise": f"{len(duplicate_groups)} duplicate finding title group(s)",
        "mostly_context_limited": f"{detail['context_limited_ratio']} context-limited evidence ratio",
        "oversized_packet": f"{len(content)} packet characters exceeds {char_budget} char budget for {profile}",
        "stale_delta": "No changed pages, findings, tasks, or model runs in the requested delta",
    }
    return {
        "score": score,
        "warnings": unique,
        "details": detail,
        "warning_details": {warning: warning_details.get(warning, warning) for warning in unique},
        "advisory_only": True,
        "acknowledgement_required_for_ui_send": bool(unique),
        "acknowledged": quality_acknowledged,
    }


def _profile_allows(profile: str, section: str) -> bool:
    rules = PROFILE_SECTION_RULES.get(profile, PROFILE_SECTION_RULES["overview"])
    return section in rules["include"]


async def _packet_row(sqlite_path: Path, packet_id: str) -> dict:
    packet = await fetch_one(sqlite_path, "SELECT * FROM experiment_packets WHERE id = ?", (packet_id,))
    if not packet:
        raise HTTPException(status_code=404, detail={"code": "experiment_packet_not_found", "message": "Experiment packet not found", "details": {"packet_id": packet_id}})
    return packet


def _packet_warning_list(health: dict | None, quality: dict, preflight: dict, high_open_findings: int) -> list[str]:
    warnings: list[str] = []
    if health and health.get("overall_status") not in {"healthy", "ok"}:
        warnings.append(f"health_{health.get('overall_status')}")
    if quality.get("overall_status") == "fail":
        warnings.append("ai_state_quality_fail")
    elif quality.get("overall_status") == "warn":
        warnings.append("ai_state_quality_warn")
    if int(preflight.get("pending_findings") or 0) > 10:
        warnings.append("many_pending_findings")
    if high_open_findings:
        warnings.append("high_severity_open_findings")
    return warnings


def _json_line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@router.post("/project-snapshot-packets")
async def create_project_snapshot_packet(payload: ProjectSnapshotPacketRequest, request: Request, actor: Actor = Depends(require_review_access)):
    settings = request.app.state.settings
    await ensure_collaboration_schema(settings.sqlite_path)
    profile = payload.profile.strip().lower() or "overview"
    if profile not in SNAPSHOT_PROFILES:
        raise HTTPException(status_code=422, detail={"code": "project_snapshot_invalid_profile", "message": "Unknown project snapshot profile", "details": {"profile": payload.profile, "allowed": sorted(SNAPSHOT_PROFILES)}})
    output_mode = payload.output_mode.strip().lower() or "top_findings"
    if output_mode not in OUTPUT_MODES:
        raise HTTPException(status_code=422, detail={"code": "project_snapshot_invalid_output_mode", "message": "Unknown packet output mode", "details": {"output_mode": payload.output_mode, "allowed": sorted(OUTPUT_MODES)}})
    focus = project_snapshot_focus(profile, payload.target_agent, payload.focus)
    target_policy = target_agent_policy(payload.target_agent)
    hard_limits = profile_hard_limits(profile)
    task_limit = min(payload.include_recent_tasks, int(target_policy["max_recent_tasks"]), int(hard_limits["max_recent_tasks"]))
    run_limit = min(payload.include_recent_runs, int(target_policy["max_recent_runs"]), int(hard_limits["max_recent_runs"]))
    health = await request.app.state.app_health_payload() if hasattr(request.app.state, "app_health_payload") else None
    quality = await build_ai_state_quality(settings, vault_id=payload.vault_id)
    matrix = await build_provider_matrix(settings)
    preflight = await _packet_preflight(settings.sqlite_path, payload.vault_id)
    since, since_packet, delta_warnings = await _resolve_snapshot_since(settings, payload, profile)
    delta = await _project_snapshot_delta(settings.sqlite_path, payload.vault_id, since)
    release_summary = {
        "release_ready": quality.get("overall_status") != "fail" and not (health and health.get("overall_status") == "attention_required"),
        "health": health.get("overall_status") if health else "unknown",
        "ai_state_quality": quality.get("overall_status"),
        "provider_matrix": matrix.get("summary", {}),
    }
    high_open = await fetch_one(
        settings.sqlite_path,
        "SELECT COUNT(*) AS count FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context','accepted','deferred') AND f.severity IN ('critical','high')",
        (payload.vault_id,),
    )
    task_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT t.id, t.finding_id, t.status, t.priority, t.owner, f.severity, f.area, f.title, f.evidence_quality "
        "FROM finding_tasks t JOIN collaboration_findings f ON f.id = t.finding_id "
        "JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? ORDER BY t.updated_at DESC LIMIT ?",
        (payload.vault_id, task_limit),
    )
    accepted_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT f.id, f.severity, f.area, f.title, f.evidence_quality, f.status, r.source_agent "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        "WHERE r.vault_id = ? AND f.status = 'accepted' ORDER BY f.updated_at DESC LIMIT ?",
        (payload.vault_id, task_limit),
    )
    run_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT id, provider, model, prompt_profile, status, review_id, input_tokens, output_tokens, updated_at "
        "FROM model_review_runs ORDER BY updated_at DESC LIMIT ?",
        (run_limit,),
    )
    if delta and delta.get("pages"):
        delta_page_ids = [row["id"] for row in delta["pages"][:5]]
        placeholders = ",".join("?" for _ in delta_page_ids)
        node_rows = await fetch_all(
            settings.sqlite_path,
            f"SELECT p.id, p.slug, p.title, sp.kind AS system_kind FROM pages p LEFT JOIN system_pages sp ON sp.page_id = p.id WHERE p.vault_id = ? AND p.id IN ({placeholders})",
            (payload.vault_id, *delta_page_ids),
        )
    else:
        node_rows = await fetch_all(
            settings.sqlite_path,
            "SELECT p.id, p.slug, p.title, sp.kind AS system_kind "
            "FROM pages p LEFT JOIN system_pages sp ON sp.page_id = p.id "
            "WHERE p.vault_id = ? AND p.status = 'active' "
            "ORDER BY p.updated_at DESC LIMIT 5",
            (payload.vault_id,),
        )
    snapshot_node_cards = [node_card(row, short_summary=f"Recent {row.get('system_kind') or 'page'} node for {profile} packet.") for row in node_rows]
    duplicate_groups = await _finding_duplicate_groups(settings.sqlite_path, vault_id=payload.vault_id, statuses={"pending", "needs_more_context", "accepted", "deferred"}, limit=500)
    warnings = _packet_warning_list(health, quality, preflight, int(high_open["count"] or 0) if high_open else 0) + delta_warnings
    important = await important_changes(settings.sqlite_path, vault_id=payload.vault_id, since=since, limit=min(int(target_policy["max_important_changes"]), int(hard_limits["max_important_changes"])))
    diff_summary = snapshot_diff_summary(important, delta)
    no_reopen = await do_not_reopen(settings.sqlite_path, vault_id=payload.vault_id)
    do_not_suggest = do_not_suggest_rules(profile)
    summary_payload = packet_summary(accepted_rows=accepted_rows, task_rows=task_rows, run_rows=run_rows, important=important)
    ai_context_payload = ai_context(profile=profile, target_agent=payload.target_agent, focus=focus, output_mode=output_mode)
    pre_issues = packet_issues(warnings=warnings, health=health, quality=quality, preflight=preflight, high_open_findings=int(high_open["count"] or 0) if high_open else 0, provider_matrix=matrix.get("summary", {}))
    pre_hints = next_action_hints(important, pre_issues)
    packet_id = f"snapshot_{uuid4().hex[:12]}"
    generated_at = utc_now()
    mostly_context_limited = any(row.get("evidence_quality") == "context_limited" for row in [*accepted_rows, *task_rows])
    contract = build_packet_contract(
        packet_kind="project_snapshot",
        target_agent=payload.target_agent,
        operator_question=focus,
        output_mode=output_mode,
        profile=profile,
        mostly_context_limited=mostly_context_limited,
        stale_context_suppression=explicit_stale_context_suppression(
            suppressed_before=since,
            reason="delta packet; prior state excluded" if since else None,
        ),
        target_agent_overrides=target_policy,
    )
    contract_validation_errors = validate_packet_contract(contract)
    if contract_validation_errors:
        raise HTTPException(status_code=500, detail={"code": "project_snapshot_contract_invalid", "message": "Generated packet contract is invalid", "details": {"errors": contract_validation_errors}})
    sections = [
        "# KnowNet Project Snapshot Packet",
        "",
        "## Packet Metadata",
        "",
        f"- packet_id: {packet_id}",
        f"- contract_version: {PACKET_CONTRACT_VERSION}",
        f"- generated_at: {generated_at}",
        f"- target_agent: {payload.target_agent}",
        f"- vault_id: {payload.vault_id}",
        f"- profile: {profile}",
        f"- output_mode: {output_mode}",
        "- evidence_quality_default: context_limited unless direct KnowNet API access is used",
        "",
        "## Operator Focus",
        "",
        focus.strip(),
        "",
        *packet_contract_markdown(contract),
        "",
        "## Current State Summary",
        "",
        f"- health: {health.get('overall_status') if health else 'unknown'}",
        f"- ai_state_quality: {quality.get('overall_status')}",
        f"- release_ready_estimate: {release_summary['release_ready']}",
        f"- preflight: {_json_line(preflight)}",
        f"- provider_matrix: {_json_line(matrix.get('summary', {}))}",
        f"- warnings: {_json_line(warnings)}",
    ]
    sections.extend(["", "## AI Context", ""])
    sections.append(f"- role: {ai_context_payload['role']}")
    sections.append(f"- task: {ai_context_payload['task']}")
    sections.append(f"- read_order: {_json_line(ai_context_payload['read_order'])}")
    sections.extend(["", "## Next Action Hints", ""])
    for hint in pre_hints or ["No immediate action hint."]:
        sections.append(f"- {hint}")
    sections.extend(["", "## Issues", ""])
    for issue in pre_issues or [{"code": "none", "action_template": "no_action", "action_params": {}}]:
        sections.append(f"- {issue['code']}: {issue['action_template']} {_json_line(issue.get('action_params') or {})}")
    if delta:
        sections.append(f"- delta_since: {delta['since']}")
        sections.append(f"- delta_summary: {_json_line(delta['delta_summary'])}")
        sections.append(f"- delta_counts: {_json_line({key: len(delta[key]) for key in ('pages', 'findings', 'finding_tasks', 'model_runs')})}")
    sections.extend(["", "## Node Cards", ""])
    sections.append("```json")
    sections.append(json.dumps(snapshot_node_cards, ensure_ascii=False, indent=2))
    sections.append("```")
    sections.extend(["", "## Snapshot Diff Summary", ""])
    for item in diff_summary:
        sections.append(f"- {item}")
    sections.extend(["", "## Important Changes", ""])
    sections.append(f"- summary: {_json_line(important['summary'])}")
    for key, label in (
        ("high_severity_findings", "high severity finding"),
        ("actionable_tasks", "actionable task"),
        ("failed_model_runs", "failed model run"),
        ("implementation_evidence", "implementation evidence"),
    ):
        rows = important[key]
        for row in rows[:4]:
            title = row.get("title") or row.get("model") or row.get("verification") or row.get("id")
            status = row.get("status") or row.get("severity") or row.get("provider") or "recorded"
            route = row.get("action_route")
            sections.append(f"- {label}: {row['id']} [{status}{f'/{route}' if route else ''}] {title}")
    sections.extend(["", "## Known Done / Do Not Reopen", ""])
    sections.append(f"- summary: {_json_line(no_reopen['summary'])}")
    for row in no_reopen["implemented_findings"][:5]:
        sections.append(f"- implemented: {row['id']} [{row['severity']}/{row['area']}] {row['title']}")
    for row in no_reopen["resolved_or_deferred_findings"][:5]:
        sections.append(f"- {row['status']}: {row['id']} {row['title']}")
    sections.extend(["", "## Do Not Suggest", ""])
    for rule in do_not_suggest:
        sections.append(f"- {rule}")
    if _profile_allows(profile, "accepted_findings") or profile == "overview":
        sections.extend(["", "## Recent Accepted Findings", ""])
        if accepted_rows:
            for row in accepted_rows:
                sections.append(f"- {row['id']} [{row['severity']}/{row['area']}/{row['evidence_quality']}]: {row['title']}")
        else:
            sections.append("- none")
    if _profile_allows(profile, "finding_tasks") or _profile_allows(profile, "implementation_work") or profile == "overview":
        sections.extend(["", "## Recent Finding Tasks", ""])
        if task_rows:
            for row in task_rows:
                owner = row["owner"] or "unassigned"
                sections.append(f"- {row['id']} -> {row['finding_id']} [{row['status']}/{row['priority']}/{owner}]: {row['title']}")
        else:
            sections.append("- none")
    if _profile_allows(profile, "model_runs") or profile == "overview":
        sections.extend(["", "## Recent Model Runs", ""])
        if run_rows:
            for row in run_rows:
                sections.append(f"- {row['id']} [{row['provider']}/{row['status']}]: {row['model']} updated_at={row['updated_at']}")
        else:
            sections.append("- none")
    if _profile_allows(profile, "stability_risks"):
        sections.extend(["", "## Stability Signals", ""])
        sections.append(f"- health: {health.get('overall_status') if health else 'unknown'}")
        sections.append(f"- high_open_findings: {int(high_open['count'] or 0) if high_open else 0}")
        sections.append(f"- provider_failures: {matrix.get('summary', {}).get('failed', 0)}")
    if _profile_allows(profile, "performance_signals"):
        sections.extend(["", "## Performance Signals", ""])
        sections.append(f"- provider_matrix: {_json_line(matrix.get('summary', {}))}")
        sections.append(f"- sampled_model_runs: {len(run_rows)}")
    if _profile_allows(profile, "security_signals"):
        sections.extend(["", "## Security Signals", ""])
        sections.append(f"- public_mode: {settings.public_mode}")
        sections.append("- forbidden_access: raw DB/filesystem/secrets/shell/backups/sessions/users")
        sections.append(f"- evidence_quality_mix: {_json_line({value: sum(1 for row in accepted_rows if row.get('evidence_quality') == value) for value in sorted(EVIDENCE_QUALITIES)})}")
    if delta:
        sections.extend(["", "## Delta Since Last Snapshot", ""])
        for key, label in (("pages", "pages"), ("findings", "findings"), ("finding_tasks", "finding tasks"), ("model_runs", "model runs")):
            rows = delta[key]
            sections.append(f"- {label}: {len(rows)}")
            for row in rows[:8]:
                title = row.get("title") or row.get("model") or row.get("slug") or row.get("id")
                status = row.get("status") or row.get("provider") or "updated"
                sections.append(f"  - {row['id']} [{status}] {title} updated_at={row.get('updated_at')}")
    sections.extend(
        [
            "",
            "## Machine Readable JSON",
            "",
            "```json",
            json.dumps(
                {
                    "packet_id": packet_id,
                    "contract_version": PACKET_CONTRACT_VERSION,
                    "generated_at": generated_at,
                    "vault_id": payload.vault_id,
                    "focus": payload.focus,
                    "effective_focus": focus,
                    "profile": profile,
                    "output_mode": output_mode,
                    "contract": contract,
                    "contract_shape": contract_shape(contract),
                    "packet_schema_version": PACKET_CONTRACT_VERSION,
                    "ai_context": ai_context_payload,
                    "next_action_hints": "computed_after_render",
                    "issues": "computed_after_render",
                    "packet_summary": summary_payload,
                    "target_agent_policy": target_policy,
                    "profile_hard_limits": hard_limits,
                    "health": health,
                    "ai_state_quality": {"overall_status": quality.get("overall_status"), "summary": quality.get("summary", {})},
                    "release_summary": release_summary,
                    "provider_matrix": matrix.get("summary", {}),
                    "preflight": preflight,
                    "delta": delta,
                    "delta_summary": delta.get("delta_summary") if delta else None,
                    "since_packet": dict(since_packet) if since_packet else None,
                    "important_changes": important,
                    "snapshot_diff_summary": diff_summary,
                    "do_not_reopen": no_reopen,
                    "do_not_suggest": do_not_suggest,
                    "warnings": warnings,
                    "snapshot_self_test": "computed_after_render",
                    "snapshot_quality": "computed_after_render",
                    "accepted_findings": accepted_rows,
                    "finding_tasks": task_rows,
                    "model_runs": run_rows,
                    "node_cards": snapshot_node_cards,
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
        ]
    )
    content = "\n".join(sections)
    _assert_no_secret_text(content, settings)
    snapshot_quality = _snapshot_quality(
        content=content,
        profile=profile,
        warnings=warnings,
        preflight=preflight,
        accepted_rows=accepted_rows,
        task_rows=task_rows,
        duplicate_groups=duplicate_groups,
        delta=delta,
        quality_acknowledged=payload.quality_acknowledged,
    )
    issues = packet_issues(
        warnings=snapshot_quality["warnings"],
        health=health,
        quality=quality,
        preflight=preflight,
        high_open_findings=int(high_open["count"] or 0) if high_open else 0,
        provider_matrix=matrix.get("summary", {}),
    )
    action_hints = next_action_hints(important, issues)
    self_test = snapshot_self_test(
        content=content,
        contract=contract,
        profile=profile,
        required_sections=["## Packet Contract", "## Important Changes", "## Do Not Suggest"],
    )
    content = content.replace(
        '"snapshot_self_test": "computed_after_render"',
        '"snapshot_self_test": ' + json.dumps(self_test, ensure_ascii=False, indent=2),
    )
    content = content.replace(
        '"snapshot_quality": "computed_after_render"',
        '"snapshot_quality": ' + json.dumps(snapshot_quality, ensure_ascii=False, indent=2),
    )
    content = content.replace(
        '"issues": "computed_after_render"',
        '"issues": ' + json.dumps(issues, ensure_ascii=False, indent=2),
    )
    content = content.replace(
        '"next_action_hints": "computed_after_render"',
        '"next_action_hints": ' + json.dumps(action_hints, ensure_ascii=False, indent=2),
    )
    if "mostly_context_limited" in snapshot_quality["warnings"]:
        contract = build_packet_contract(
            packet_kind="project_snapshot",
            target_agent=payload.target_agent,
            operator_question=focus,
            output_mode=output_mode,
            profile=profile,
            mostly_context_limited=True,
            stale_context_suppression=explicit_stale_context_suppression(
                suppressed_before=since,
                reason="delta packet; prior state excluded" if since else None,
            ),
            target_agent_overrides=target_policy,
        )
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    packet_dir = settings.data_dir / "project-snapshot-packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"{packet_id}.md"
    packet_path.write_text(content, encoding="utf-8")
    from ..db.sqlite import execute

    await execute(
        settings.sqlite_path,
        "INSERT INTO project_snapshot_packets (id, vault_id, target_agent, profile, output_mode, focus, content_hash, content_path, warnings_json, snapshot_quality_json, contract_version, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            packet_id,
            payload.vault_id,
            payload.target_agent,
            profile,
            output_mode,
            focus,
            content_hash,
            str(packet_path).replace("\\", "/"),
            json.dumps(warnings, ensure_ascii=True),
            json.dumps(snapshot_quality, ensure_ascii=True),
            PACKET_CONTRACT_VERSION,
            actor.actor_id,
            generated_at,
        ),
    )
    await write_audit_event(
        settings.sqlite_path,
        action="project_snapshot_packet.create",
        actor=actor,
        target_type="project_snapshot_packet",
        target_id=packet_id,
        metadata={"content_hash": content_hash, "warnings": warnings, "focus": focus, "since": since, "since_packet_id": payload.since_packet_id, "profile": profile, "contract_version": PACKET_CONTRACT_VERSION},
    )
    return {
        "ok": True,
        "data": {
            "packet_id": packet_id,
            "content": content,
            "content_hash": content_hash,
            "storage_path": f"project-snapshot-packets/{packet_id}.md",
            "read_url": f"/api/collaboration/project-snapshot-packets/{packet_id}",
            "preflight": preflight,
            "delta": delta,
            "since_packet": dict(since_packet) if since_packet else None,
            "warnings": warnings,
            "snapshot_quality": snapshot_quality,
            "snapshot_self_test": self_test,
            "contract": contract,
            "contract_shape": contract_shape(contract),
            "packet_schema_version": PACKET_CONTRACT_VERSION,
            "ai_context": ai_context_payload,
            "next_action_hints": action_hints,
            "issues": issues,
            "packet_summary": summary_payload,
            "node_cards": snapshot_node_cards,
            "delta_summary": delta.get("delta_summary") if delta else None,
            "profile": profile,
            "output_mode": output_mode,
            "effective_focus": focus,
            "target_agent_policy": target_policy,
            "profile_hard_limits": hard_limits,
            "important_changes": important,
            "snapshot_diff_summary": diff_summary,
            "do_not_reopen": no_reopen,
            "do_not_suggest": do_not_suggest,
            "contract_version": PACKET_CONTRACT_VERSION,
            "copy_ready": True,
        },
    }


@router.get("/project-snapshot-packets/{packet_id}")
async def get_project_snapshot_packet(packet_id: str, request: Request, actor: Actor = Depends(require_review_access)):
    if not re.match(r"^snapshot_[a-f0-9]{12}$", packet_id):
        raise HTTPException(status_code=404, detail={"code": "project_snapshot_packet_not_found", "message": "Project snapshot packet not found", "details": {"packet_id": packet_id}})
    path = request.app.state.settings.data_dir / "project-snapshot-packets" / f"{packet_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "project_snapshot_packet_not_found", "message": "Project snapshot packet not found", "details": {"packet_id": packet_id}})
    content = path.read_text(encoding="utf-8")
    return {"ok": True, "data": {"packet_id": packet_id, "content": content, "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(), "copy_ready": True}}


@router.post("/experiment-packets")
async def create_experiment_packet(payload: ExperimentPacketRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    output_mode = payload.output_mode.strip().lower() or "top_findings"
    if output_mode not in OUTPUT_MODES:
        raise HTTPException(status_code=422, detail={"code": "experiment_packet_invalid_output_mode", "message": "Unknown packet output mode", "details": {"output_mode": payload.output_mode, "allowed": sorted(OUTPUT_MODES)}})
    slugs = _validate_packet_slugs(payload.node_slugs or DEFAULT_EXPERIMENT_PACKET_SLUGS)
    if not slugs:
        raise HTTPException(status_code=422, detail={"code": "experiment_packet_empty_nodes", "message": "Select at least one node", "details": {}})
    placeholders = ",".join("?" for _ in slugs)
    rows = await fetch_all(
        settings.sqlite_path,
        f"SELECT p.id, p.slug, p.title, p.path, sp.kind AS system_kind FROM pages p LEFT JOIN system_pages sp ON sp.page_id = p.id WHERE p.vault_id = ? AND p.status = 'active' AND p.slug IN ({placeholders})",
        (payload.vault_id, *slugs),
    )
    by_slug = {row["slug"]: row for row in rows}
    missing = [slug for slug in slugs if slug not in by_slug]
    if missing:
        raise HTTPException(status_code=404, detail={"code": "experiment_packet_node_missing", "message": "Selected node was not found", "details": {"missing_slugs": missing}})

    preflight = await _packet_preflight(settings.sqlite_path, payload.vault_id)
    contract = build_packet_contract(
        packet_kind="experiment_packet",
        target_agent=payload.target_agent,
        operator_question=payload.task,
        output_mode=output_mode,
        profile="overview",
    )
    contract_validation_errors = validate_packet_contract(contract)
    if contract_validation_errors:
        raise HTTPException(status_code=500, detail={"code": "experiment_packet_contract_invalid", "message": "Generated packet contract is invalid", "details": {"errors": contract_validation_errors}})
    sections = [
        f"# {payload.experiment_name}",
        "",
        "## Packet Metadata",
        "",
        f"- contract_version: {PACKET_CONTRACT_VERSION}",
        f"- generated_at: {utc_now()}",
        f"- generated_for: {payload.target_agent}",
        f"- vault_id: {payload.vault_id}",
        f"- output_mode: {output_mode}",
        f"- evidence_quality_default: context_limited unless live KnowNet access succeeds",
        f"- preflight_pages: {preflight['pages']}",
        f"- preflight_ai_state_pages: {preflight['ai_state_pages']}",
        f"- preflight_unresolved_nodes: {preflight['unresolved_nodes']}",
        f"- preflight_pending_findings: {preflight['pending_findings']}",
        "",
        "## Task",
        "",
        payload.task.strip(),
        "",
        *packet_contract_markdown(contract),
        "",
        "## AI Context",
        "",
        f"- role: experiment_reviewer",
        f"- task: {payload.task.strip()}",
        f"- output_mode: {output_mode}",
        "- read_order: [\"ai_context\", \"node_cards\", \"inline_core_context\", \"response_contract\"]",
        "",
        "## Node Cards",
        "",
        "computed_after_node_read",
        "",
        "## Inline Core Context",
        "",
    ]
    if payload.minimum_inline_context and payload.minimum_inline_context.strip():
        _assert_no_secret_text(payload.minimum_inline_context, settings)
        sections.extend(
            [
                "### Operator-Supplied Minimum Inline Context",
                "",
                payload.minimum_inline_context.strip(),
                "",
            ]
        )
    included_nodes: list[dict] = []
    node_cards: list[dict] = []
    for slug in slugs:
        row = by_slug[slug]
        path = Path(row["path"]).resolve()
        data_dir = settings.data_dir.resolve()
        if data_dir not in path.parents:
            raise HTTPException(status_code=400, detail={"code": "experiment_packet_forbidden_path", "message": "Node path is outside data directory", "details": {"slug": slug}})
        _assert_allowed_bundle_path(str(path.relative_to(data_dir)), page_id=row["id"])
        raw_content = path.read_text(encoding="utf-8")
        content = _packet_excerpt_for_slug(slug, raw_content, max_chars=payload.max_node_chars)
        _assert_no_secret_text(content, settings, page_id=row["id"])
        card = node_card(row, short_summary=re.sub(r"\s+", " ", content).strip()[:240])
        node_cards.append(card)
        included_nodes.append({"page_id": row["id"], "slug": slug, "title": row["title"], "node_card": card})
        sections.extend([f"### Node: {row['title']}", "", f"slug: {slug}", "", content, ""])

    node_card_lines = ["```json", json.dumps(node_cards, ensure_ascii=False, indent=2), "```"]
    marker = sections.index("computed_after_node_read")
    sections[marker : marker + 1] = node_card_lines

    if payload.scenarios:
        sections.extend(["## Scenarios", ""])
        for index, scenario in enumerate(payload.scenarios, start=1):
            sections.append(f"{index}. {scenario.strip()}")
        sections.append("")

    sections.extend(
        [
            "## Response Contract",
            "",
            payload.output_schema.strip()
            if payload.output_schema
            else "Return the requested schema only. Keep decision tables separate from importable findings. Use parser-ready Finding blocks only for items that should be imported.",
            "",
            "## Importable Finding Format",
            "",
            "```txt",
            "### Finding",
            "",
            "Title: <specific title>",
            "Severity: low|medium|high|critical",
            "Area: API|UI|Rust|Security|Data|Ops|Docs",
            "Evidence quality: direct_access|context_limited|inferred|operator_verified",
            "",
            "Evidence:",
            "<observed evidence and access limitation>",
            "",
            "Proposed change:",
            "<one concrete change>",
            "```",
            "",
        ]
    )
    content = "\n".join(sections).strip() + "\n"
    _assert_no_secret_text(content, settings)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    packet_id = f"packet_{uuid4().hex[:12]}"
    packet_dir = settings.data_dir / "experiment-packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"{packet_id}.md"
    packet_path.write_text(content, encoding="utf-8")
    from ..db.sqlite import execute

    await execute(
        settings.sqlite_path,
        "INSERT INTO experiment_packets (id, vault_id, experiment_name, target_agent, content_hash, content_path, node_slugs, scenarios, preflight_json, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            packet_id,
            payload.vault_id,
            payload.experiment_name,
            payload.target_agent,
            content_hash,
            str(packet_path).replace("\\", "/"),
            json.dumps(slugs, ensure_ascii=True),
            json.dumps(payload.scenarios, ensure_ascii=False),
            json.dumps(preflight, ensure_ascii=True),
            actor.actor_id,
            utc_now(),
        ),
    )
    await write_audit_event(
        settings.sqlite_path,
        action="experiment_packet.create",
        actor=actor,
        target_type="experiment_packet",
        target_id=packet_id,
        metadata={"experiment_name": payload.experiment_name, "node_slugs": slugs, "scenario_count": len(payload.scenarios), "content_hash": content_hash},
    )
    return {
        "ok": True,
        "data": {
            "packet_id": packet_id,
            "content": content,
            "content_hash": content_hash,
            "content_path": str(packet_path).replace("\\", "/"),
            "read_url": f"/api/collaboration/experiment-packets/{packet_id}",
            "included_nodes": included_nodes,
            "preflight": preflight,
            "contract_version": PACKET_CONTRACT_VERSION,
            "packet_schema_version": PACKET_CONTRACT_VERSION,
            "contract": contract,
            "contract_shape": contract_shape(contract),
            "ai_context": {
                "role": "experiment_reviewer",
                "target_agent": payload.target_agent,
                "task": payload.task.strip(),
                "output_mode": output_mode,
                "read_order": ["ai_context", "node_cards", "inline_core_context", "response_contract"],
            },
            "node_cards": node_cards,
            "copy_ready": True,
        },
    }


@router.get("/experiment-packets/{packet_id}")
async def get_experiment_packet(packet_id: str, request: Request, actor: Actor = Depends(require_review_access)):
    packet = await _packet_row(request.app.state.settings.sqlite_path, packet_id)
    path = Path(packet["content_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "experiment_packet_file_missing", "message": "Experiment packet file is missing", "details": {"packet_id": packet_id}})
    return {
        "ok": True,
        "data": {
            **packet,
            "node_slugs": json.loads(packet["node_slugs"] or "[]"),
            "scenarios": json.loads(packet["scenarios"] or "[]"),
            "preflight": json.loads(packet["preflight_json"] or "{}"),
            "content": path.read_text(encoding="utf-8"),
        },
    }


@router.post("/experiment-packets/{packet_id}/responses/dry-run")
async def dry_run_experiment_packet_response(packet_id: str, payload: ExperimentPacketResponseRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    await _packet_row(settings.sqlite_path, packet_id)
    ensure_text_size(payload.response_markdown, MAX_REVIEW_BYTES, "response_markdown")
    dry_run = _review_dry_run_result(payload.response_markdown)
    response_id = f"packetresp_{uuid4().hex[:12]}"
    from ..db.sqlite import execute

    await execute(
        settings.sqlite_path,
        "INSERT INTO experiment_packet_responses (id, packet_id, source_agent, source_model, response_markdown, dry_run_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (response_id, packet_id, payload.source_agent, payload.source_model, payload.response_markdown, json.dumps(dry_run, ensure_ascii=True), utc_now()),
    )
    await write_audit_event(
        settings.sqlite_path,
        action="experiment_packet_response.dry_run",
        actor=actor,
        target_type="experiment_packet",
        target_id=packet_id,
        metadata={"response_id": response_id, "finding_count": dry_run["finding_count"], "parser_errors": dry_run["parser_errors"], "import_ready": dry_run["import_ready"]},
    )
    return {"ok": True, "data": {"response_id": response_id, "packet_id": packet_id, **dry_run}}


@router.post("/experiment-packets/{packet_id}/responses/{response_id}/import")
async def import_experiment_packet_response(packet_id: str, response_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    settings = request.app.state.settings
    packet = await _packet_row(settings.sqlite_path, packet_id)
    response = await fetch_one(settings.sqlite_path, "SELECT * FROM experiment_packet_responses WHERE id = ? AND packet_id = ?", (response_id, packet_id))
    if not response:
        raise HTTPException(status_code=404, detail={"code": "experiment_packet_response_not_found", "message": "Experiment packet response not found", "details": {"response_id": response_id}})
    if response.get("imported_review_id"):
        raise HTTPException(status_code=409, detail={"code": "experiment_packet_response_already_imported", "message": "Experiment packet response is already imported", "details": {"review_id": response["imported_review_id"]}})

    markdown = response["response_markdown"]
    dry_run = _review_dry_run_result(markdown)
    metadata = dry_run["metadata"]
    findings = dry_run["findings"]
    parser_errors = dry_run["parser_errors"]
    if parser_errors:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "experiment_packet_response_parser_errors",
                "message": "Response must pass dry-run parser before import",
                "details": {
                    "parser_errors": parser_errors,
                    "ai_feedback_prompt": dry_run.get("ai_feedback_prompt"),
                },
            },
        )
    if not findings:
        raise HTTPException(status_code=422, detail={"code": "collaboration_no_findings", "message": "No findings found", "details": {}})
    review_id = f"review_{uuid4().hex[:12]}"
    now = utc_now()
    source_agent = response["source_agent"] or str(metadata.get("source_agent") or "unknown")
    source_model = response.get("source_model") or metadata.get("source_model")
    meta = {
        "frontmatter": metadata,
        "parser_errors": parser_errors,
        "markdown_path": f"data/pages/reviews/{review_id}.md",
        "experiment_packet": {
            "packet_id": packet_id,
            "response_id": response_id,
            "content_hash": packet["content_hash"],
            "experiment_name": packet["experiment_name"],
        },
    }
    try:
        review = await request.app.state.rust_core.request(
            "create_collaboration_review",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "review_id": review_id,
                "vault_id": packet["vault_id"] or actor.vault_id,
                "title": _title_from_markdown(markdown, f"Experiment response: {packet['experiment_name']}"),
                "source_agent": source_agent,
                "source_model": source_model,
                "review_type": "agent_review",
                "page_id": None,
                "markdown": markdown,
                "meta": json.dumps(meta, ensure_ascii=True, sort_keys=True),
                "created_at": now,
            },
        )
        created_findings = []
        for finding in findings:
            created = await request.app.state.rust_core.request(
                "create_collaboration_finding",
                {
                    "sqlite_path": str(settings.sqlite_path),
                    "finding_id": f"finding_{uuid4().hex[:12]}",
                    "review_id": review_id,
                    "created_at": now,
                    **finding,
                },
            )
            created_findings.append(created)
    except RustCoreError as error:
        raise _http_from_rust(error) from error

    from ..db.sqlite import execute

    await execute(settings.sqlite_path, "UPDATE experiment_packet_responses SET imported_review_id = ? WHERE id = ?", (review_id, response_id))
    graph_rebuild = await _rebuild_collaboration_graph(request, packet["vault_id"] or actor.vault_id)
    await write_audit_event(
        settings.sqlite_path,
        action="experiment_packet_response.import",
        actor=actor,
        target_type="experiment_packet",
        target_id=packet_id,
        metadata={"response_id": response_id, "review_id": review_id, "finding_count": len(created_findings), "parser_errors": parser_errors, "graph_rebuild": graph_rebuild},
    )
    return {"ok": True, "data": {"review": review, "findings": created_findings, "graph_rebuild": graph_rebuild}}


@router.post("/context-bundles")
async def create_context_bundle(payload: ContextBundleRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    if not payload.page_ids:
        raise HTTPException(status_code=422, detail={"code": "context_bundle_empty_selection", "message": "Select at least one page", "details": {}})
    settings = request.app.state.settings
    placeholders = ",".join("?" for _ in payload.page_ids)
    rows = await fetch_all(
        settings.sqlite_path,
        f"SELECT id, slug, title, path FROM pages WHERE vault_id = ? AND status = 'active' AND id IN ({placeholders}) ORDER BY title",
        (payload.vault_id, *payload.page_ids),
    )
    if not rows:
        raise HTTPException(status_code=422, detail={"code": "context_bundle_empty_selection", "message": "No active pages selected", "details": {}})
    _assert_no_forbidden_json_keys({"vault_id": payload.vault_id, "page_ids": payload.page_ids, "include_graph_summary": payload.include_graph_summary})

    sections = [
        "# KnowNet Context Bundle",
        f"generated_at: {utc_now()}",
        f"pages_included: {len(rows)}",
        "generated_for: external AI review",
        "warning: Do not include secrets in this bundle.",
        "",
    ]
    collaboration_summary = await fetch_all(
        settings.sqlite_path,
        "SELECT r.id AS review_id, r.title AS review_title, r.status AS review_status, "
        "f.id AS finding_id, f.severity, f.area, f.status AS finding_status, "
        "ir.id AS implementation_record_id "
        "FROM collaboration_reviews r "
        "LEFT JOIN collaboration_findings f ON f.review_id = r.id "
        "LEFT JOIN implementation_records ir ON ir.finding_id = f.id "
        "WHERE r.vault_id = ? "
        "ORDER BY r.updated_at DESC, f.updated_at DESC LIMIT 50",
        (payload.vault_id,),
    )
    if collaboration_summary:
        summary_rows = [dict(row) for row in collaboration_summary]
        _assert_no_forbidden_json_keys({"structured_records": summary_rows})
        sections.extend(
            [
                "## Structured Collaboration Summary",
                "",
                "```json",
                json.dumps(summary_rows, ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    for row in rows:
        path = Path(row["path"]).resolve()
        data_dir = settings.data_dir.resolve()
        if data_dir not in path.parents:
            raise HTTPException(status_code=400, detail={"code": "context_bundle_forbidden_path", "message": "Page path is outside data directory", "details": {"page_id": row["id"]}})
        _assert_allowed_bundle_path(str(path.relative_to(data_dir)), page_id=row["id"])
        content = _strip_frontmatter(path.read_text(encoding="utf-8"))
        _assert_no_secret_text(content, settings, page_id=row["id"])
        sections.extend(["---", "", f"## Page: {row['title']}", f"slug: {row['slug']}", "", content.strip(), ""])

        audits = await fetch_all(
            settings.sqlite_path,
            "SELECT citation_key, status, verifier_type, reason FROM citation_audits WHERE page_id = ? ORDER BY updated_at DESC LIMIT 20",
            (row["id"],),
        )
        if audits:
            sections.extend(["### Citation Audit Summary"])
            for audit in audits:
                reason = (audit["reason"] or "").replace("\n", " ")[:160]
                sections.append(f"- {audit['citation_key']}: {audit['status']} ({audit['verifier_type']}) - {reason}")
            sections.append("")

    if payload.include_graph_summary:
        graph_counts = await fetch_one(
            settings.sqlite_path,
            "SELECT (SELECT COUNT(*) FROM graph_nodes WHERE vault_id = ?) AS nodes, "
            "(SELECT COUNT(*) FROM graph_edges WHERE vault_id = ?) AS edges",
            (payload.vault_id, payload.vault_id),
        )
        sections.extend(["---", "", "## Graph Summary", f"nodes: {graph_counts['nodes'] if graph_counts else 0}", f"edges: {graph_counts['edges'] if graph_counts else 0}", ""])

    content = "\n".join(sections).strip() + "\n"
    _assert_no_secret_text(content, settings)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    filename = f"knownet-context-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}.md"
    manifest_id = f"bundle_{uuid4().hex[:12]}"
    try:
        included_sections = ["pages", "structured_records", "citation_summary", "graph_summary" if payload.include_graph_summary else "no_graph"]
        manifest_payload = {
            "manifest_id": manifest_id,
            "vault_id": payload.vault_id,
            "filename": filename,
            "selected_pages": payload.page_ids,
            "included_sections": included_sections,
            "excluded_sections": EXCLUDED_SECTIONS,
            "content_hash": content_hash,
            "created_by": actor.actor_id,
        }
        _assert_no_forbidden_json_keys(manifest_payload)
        manifest = await request.app.state.rust_core.request(
            "create_context_bundle_manifest",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "manifest_id": manifest_id,
                "vault_id": payload.vault_id,
                "filename": filename,
                "content": content,
                "selected_pages": json.dumps(payload.page_ids, ensure_ascii=True),
                "included_sections": json.dumps(included_sections, ensure_ascii=True),
                "excluded_sections": json.dumps(EXCLUDED_SECTIONS, ensure_ascii=True),
                "content_hash": content_hash,
                "created_by": actor.actor_id,
                "created_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise _http_from_rust(error) from error
    await write_audit_event(
        settings.sqlite_path,
        action="context_bundle.create",
        actor=actor,
        target_type="context_bundle",
        target_id=manifest_id,
        metadata={"page_count": len(rows), "content_hash": content_hash},
    )
    return {"ok": True, "data": {"manifest": manifest, "content": content}}
