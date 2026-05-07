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
from .collaboration_review_parser import (
    finding_dedupe_key as _finding_dedupe_key,
    normalize_area as _normalize_area,
    normalize_evidence_quality as _normalize_evidence_quality,
    parse_review_markdown,
    review_dry_run_result as _review_dry_run_result,
    title_from_markdown as _title_from_markdown,
)
from .collaboration_packets import (
    DEFAULT_EXPERIMENT_PACKET_SLUGS,
    packet_excerpt_for_slug as _packet_excerpt_for_slug,
    packet_preflight as _packet_preflight,
    packet_row as _packet_row,
    packet_warning_list as _packet_warning_list,
    project_snapshot_delta as _project_snapshot_delta,
    resolve_snapshot_since as _resolve_snapshot_since,
    resource_links as _resource_links,
    snapshot_quality as _snapshot_quality,
    standard_delta as _standard_delta,
    strip_frontmatter as _strip_frontmatter,
    validate_packet_slugs as _validate_packet_slugs,
)
from .collaboration_task_templates import (
    implementation_task_template as _implementation_task_template,
    priority_from_finding as _priority_from_finding,
    should_auto_create_task as _should_auto_create_task,
    simple_evidence_template as _simple_evidence_template,
    task_creation_template as _task_creation_template,
    task_prompt_from_finding as _task_prompt_from_finding,
    verification_from_finding as _verification_from_finding,
)
from ..services.packet_contract import (
    OUTPUT_MODES,
    PACKET_CONTRACT_VERSION,
    PACKET_PROTOCOL_VERSION,
    PACKET_SCHEMA_REF,
    SNAPSHOT_PROFILES,
    build_packet_contract,
    contract_shape,
    explicit_stale_context_suppression,
    packet_trace,
    packet_contract_markdown,
    validate_packet_contract,
    validate_packet_schema_core,
)
from ..services.project_snapshot import (
    DEFAULT_PROJECT_SNAPSHOT_FOCUS,
    ai_context,
    build_context_questions,
    compact_health,
    compact_limits,
    compact_role_boundaries,
    do_not_suggest_rules,
    do_not_reopen,
    empty_state_signal,
    important_changes,
    node_card,
    omit_empty,
    packet_diff_view,
    packet_fitness_score,
    packet_issues,
    packet_integrity_summary,
    packet_signals,
    packet_summary,
    action_route,
    profile_char_budget,
    profile_hard_limits,
    source_manifest,
    project_snapshot_focus,
    snapshot_diff_summary,
    target_agent_policy,
)
from ..services.ai_review_comparator import compare_ai_reviews
from ..services import collaboration_v2
from ..services.rust_core import RustCoreError

router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

DECISION_STATUSES = {"accepted", "rejected", "deferred", "needs_more_context"}
MAX_REVIEW_BYTES = 256 * 1024
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


class PacketCompareRequest(BaseModel):
    left_packet_id: str | None = Field(default=None, max_length=80)
    right_packet_id: str | None = Field(default=None, max_length=80)
    left_packet: dict | None = None
    right_packet: dict | None = None


class AIReviewComparisonItem(BaseModel):
    source_agent: str = Field(default="external_ai", max_length=80)
    text: str = Field(min_length=1, max_length=256 * 1024)


class AIReviewComparisonRequest(BaseModel):
    reviews: list[AIReviewComparisonItem] = Field(min_length=1, max_length=12)


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


async def _finding_duplicate_groups(sqlite_path: Path, *, vault_id: str, statuses: set[str] | None = None, limit: int = 500) -> list[dict]:
    statuses = statuses or {"pending", "needs_more_context", "accepted", "deferred"}
    placeholders = ",".join("?" for _ in statuses)
    rows = await fetch_all(
        sqlite_path,
        "SELECT f.id, f.review_id, f.severity, f.area, f.title, f.status, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality, f.updated_at, r.source_agent, r.title AS review_title "
        "FROM findings f JOIN reviews r ON r.id = f.review_id "
        "LEFT JOIN finding_evidence fe ON fe.finding_id = f.id "
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


async def _finding_duplicate_groups_for_settings(settings, *, vault_id: str, statuses: set[str] | None = None, limit: int = 500) -> list[dict]:
    statuses = statuses or {"pending", "needs_more_context", "accepted", "deferred"}
    return await collaboration_v2.duplicate_groups(settings.sqlite_path, vault_id=vault_id, statuses=statuses, limit=limit, dedupe_key=_finding_dedupe_key)


async def _finding_duplicate_candidates_for_settings(settings, *, vault_id: str, findings: list[dict]) -> list[dict]:
    if not findings:
        return []
    groups = await _finding_duplicate_groups_for_settings(settings, vault_id=vault_id)
    by_key = {group["dedupe_key"]: group for group in groups}
    candidates = []
    for finding in findings:
        key = _finding_dedupe_key(finding.get("title"))
        if key in by_key:
            candidates.append({"title": finding.get("title"), "dedupe_key": key, "existing": by_key[key]})
    return candidates


def _http_from_rust(error: RustCoreError) -> HTTPException:
    status = 404 if error.code.endswith("_not_found") else 409 if "invalid_status" in error.code else 500
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details})


async def _upsert_task_for_settings(
    settings,
    *,
    finding: dict,
    actor: Actor,
    priority: str,
    owner: str | None,
    task_prompt: str,
    expected_verification: str,
    notes: str | None,
) -> dict:
    return await collaboration_v2.upsert_task(
        settings.sqlite_path,
        finding=finding,
        actor_id=actor.actor_id,
        priority=priority,
        owner=owner,
        task_prompt=task_prompt,
        expected_verification=expected_verification,
        notes=notes,
        updated_at=utc_now(),
    )


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


async def _review_with_findings_for_settings(settings, review_id: str) -> dict:
    detail = await collaboration_v2.review_detail(settings.sqlite_path, review_id)
    if not detail:
        raise HTTPException(status_code=404, detail={"code": "collaboration_review_not_found", "message": "Review not found", "details": {"review_id": review_id}})
    return detail


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
    if dry_run and not findings and metadata.get("context_questions"):
        return {
            "ok": True,
            "data": {
                "dry_run": True,
                "metadata": metadata,
                "finding_count": 0,
                "findings": [],
                "context_questions": metadata.get("context_questions") or [],
                "duplicate_candidates": [],
                "parser_errors": parser_errors,
                "truncated_findings": bool(metadata.get("truncated_findings")),
                "import_ready": False,
            },
        }
    if not findings:
        raise HTTPException(status_code=422, detail={"code": "collaboration_no_findings", "message": "No findings found", "details": {}})
    duplicate_candidates = await _finding_duplicate_candidates_for_settings(settings, vault_id=payload.vault_id or actor.vault_id, findings=findings)
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
                "context_questions": metadata.get("context_questions") or [],
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
    review, created_findings = await collaboration_v2.create_review(
        settings.sqlite_path,
        data_dir=settings.data_dir,
        review_id=review_id,
        vault_id=payload.vault_id or actor.vault_id,
        title=title,
        source_agent=source_agent,
        source_model=source_model,
        review_type="agent_review",
        page_id=payload.page_id,
        markdown=payload.markdown,
        meta=meta,
        findings=findings,
        created_at=now,
    )
    graph_rebuild = collaboration_v2.skipped_v2_graph_rebuild()
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
    rows = await collaboration_v2.list_reviews(
        settings.sqlite_path,
        vault_id=vault_id,
        status=status,
        source_agent=source_agent,
        area=area,
        limit=limit,
    )
    return {"ok": True, "data": {"reviews": rows, "actor_role": actor.role}}


@router.get("/reviews/{review_id}")
async def get_review(review_id: str, request: Request, actor: Actor = Depends(require_review_access)):
    return {"ok": True, "data": await _review_with_findings_for_settings(request.app.state.settings, review_id)}


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
    result = await collaboration_v2.decide_finding(
        settings.sqlite_path,
        finding_id=finding_id,
        status=payload.status,
        decision_note=payload.decision_note,
        decided_by=actor.actor_id,
        decided_at=utc_now(),
    )
    if not result:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    auto_task = None
    if payload.status == "accepted":
        accepted_finding = await collaboration_v2.finding(settings.sqlite_path, finding_id)
        if accepted_finding and _should_auto_create_task(accepted_finding):
            priority = _priority_from_finding(accepted_finding)
            auto_task = await _upsert_task_for_settings(
                settings,
                finding=accepted_finding,
                actor=actor,
                priority=priority,
                owner="codex",
                task_prompt=_task_prompt_from_finding(accepted_finding),
                expected_verification=_verification_from_finding(accepted_finding),
                notes="Auto-created when the finding was accepted.",
            )
    graph_rebuild = collaboration_v2.skipped_v2_graph_rebuild()
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
    if collaboration_v2.v2_enabled(settings):
        from ..db.sqlite import transaction

        now = utc_now()
        existing = await fetch_one(settings.sqlite_path, "SELECT id FROM findings WHERE id = ?", (finding_id,))
        if not existing:
            raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
        async with transaction(settings.sqlite_path) as connection:
            await connection.execute(
                "INSERT INTO implementation_records (id, finding_id, commit_sha, changed_files, verification, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record_id, finding_id, commit_sha, json.dumps(cleaned_files, ensure_ascii=True), verification, notes, now),
            )
            await connection.execute("UPDATE findings SET status = 'implemented', updated_at = ? WHERE id = ?", (now, finding_id))
            await connection.execute(
                "INSERT INTO finding_decisions (id, finding_id, status, decision_note, decided_by, decided_at, created_at) VALUES (?, ?, 'implemented', ?, ?, ?, ?)",
                (f"decision_{uuid4().hex[:12]}", finding_id, notes or verification, actor.actor_id, now, now),
            )
        result = {
            "id": record_id,
            "finding_id": finding_id,
            "commit_sha": commit_sha,
            "changed_files": json.dumps(cleaned_files, ensure_ascii=True),
            "verification": verification,
            "notes": notes,
            "created_at": now,
        }
    now = utc_now()
    task = await fetch_one(settings.sqlite_path, "SELECT id FROM tasks WHERE finding_id = ?", (finding_id,))
    if task:
        await execute(settings.sqlite_path, "UPDATE tasks SET status = 'done', updated_at = ? WHERE finding_id = ?", (now, finding_id))
    graph_rebuild = collaboration_v2.skipped_v2_graph_rebuild()
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
    finding = await fetch_one(settings.sqlite_path, "SELECT id, status, title FROM findings WHERE id = ?", (finding_id,))
    if not finding:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    changed_files = payload.changed_files or (_git_changed_files() if payload.include_git_status else [])
    cleaned_files = _clean_changed_files(changed_files)
    if payload.commit_sha and not re.match(r"^[A-Fa-f0-9]{7,40}$", payload.commit_sha):
        raise HTTPException(status_code=422, detail={"code": "implementation_record_invalid_commit", "message": "Invalid commit hash", "details": {}})
    task = await fetch_one(settings.sqlite_path, "SELECT * FROM tasks WHERE finding_id = ?", (finding_id,))
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
        "SELECT f.*, fe.evidence, fe.proposed_change, COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality, "
        "r.vault_id, r.title AS review_title, r.source_agent, r.source_model, "
        "t.id AS task_id, t.status AS task_status, t.priority AS task_priority, t.owner AS task_owner, "
        "t.task_prompt, t.expected_verification, t.updated_at AS task_updated_at, "
        "(SELECT COUNT(*) FROM implementation_records i WHERE i.finding_id = f.id) AS implementation_count "
        "FROM findings f "
        "JOIN reviews r ON r.id = f.review_id "
        "LEFT JOIN finding_evidence fe ON fe.finding_id = f.id "
        "LEFT JOIN tasks t ON t.finding_id = f.id "
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
    groups = await _finding_duplicate_groups_for_settings(request.app.state.settings, vault_id=vault_id, statuses=statuses, limit=max(20, min(limit, 1000)))
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
    settings = request.app.state.settings
    row = await collaboration_v2.finding(settings.sqlite_path, finding_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    return {"ok": True, "data": {"finding": row, "actor_role": actor.role}}


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: str = "open",
    limit: int = 50,
    actor: Actor = Depends(require_review_access),
):
    if status not in {"open", "in_progress", "done", "blocked", "all"}:
        raise HTTPException(status_code=409, detail={"code": "task_invalid_status", "message": "Invalid task status", "details": {"status": status}})
    limit = max(1, min(limit, 100))
    rows = await collaboration_v2.list_tasks(request.app.state.settings.sqlite_path, status=status, limit=limit)
    return {"ok": True, "data": {"tasks": rows, "actor_role": actor.role}}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    row = await collaboration_v2.task(settings.sqlite_path, task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "task_not_found", "message": "Task not found", "details": {"task_id": task_id}})
    return {"ok": True, "data": {"task": row, "actor_role": actor.role}}


@router.get("/patch-suggestion")
async def patch_suggestion(
    finding_id: str,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    finding = await fetch_one(settings.sqlite_path, "SELECT id, title, status FROM findings WHERE id = ?", (finding_id,))
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
        "SELECT t.*, f.review_id, f.severity, f.area, f.title, "
        "COALESCE(fe.evidence, '') AS evidence, COALESCE(fe.proposed_change, '') AS proposed_change, "
        "COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality, f.status AS finding_status, "
        "r.title AS review_title, r.source_agent, r.source_model "
        "FROM tasks t "
        "JOIN findings f ON f.id = t.finding_id "
        "JOIN reviews r ON r.id = f.review_id "
        "LEFT JOIN finding_evidence fe ON fe.finding_id = f.id "
        "WHERE r.vault_id = ? AND t.status IN ('open','in_progress') "
        "ORDER BY CASE t.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, "
        "CASE f.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, t.updated_at DESC LIMIT 1",
        (vault_id,),
    )
    if task:
        return {
            "ok": True,
            "data": {
                "action_type": "implement_task",
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
        "(SELECT COUNT(*) FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status IN ('pending','needs_more_context')) AS pending_findings, "
        "(SELECT COUNT(*) FROM reviews WHERE vault_id = ? AND status = 'pending_review') AS pending_reviews, "
        "(SELECT COUNT(*) FROM findings f JOIN reviews r ON r.id = f.review_id WHERE r.vault_id = ? AND f.status = 'accepted') AS accepted_findings",
        (vault_id, vault_id, vault_id),
    )
    pending_findings = int(counts["pending_findings"] or 0) if counts else 0
    pending_reviews = int(counts["pending_reviews"] or 0) if counts else 0
    accepted_findings = int(counts["accepted_findings"] or 0) if counts else 0

    finding = await fetch_one(
        settings.sqlite_path,
        "SELECT f.*, COALESCE(fe.evidence, '') AS evidence, COALESCE(fe.proposed_change, '') AS proposed_change, "
        "COALESCE(fe.evidence_quality, 'unspecified') AS evidence_quality, "
        "r.vault_id, r.title AS review_title, r.source_agent, r.source_model, "
        "(SELECT COUNT(*) FROM implementation_records i WHERE i.finding_id = f.id) AS implementation_count "
        "FROM findings f JOIN reviews r ON r.id = f.review_id "
        "LEFT JOIN finding_evidence fe ON fe.finding_id = f.id "
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

    duplicate_groups = await _finding_duplicate_groups_for_settings(settings, vault_id=vault_id, statuses={"pending", "needs_more_context", "accepted", "deferred"}, limit=500)
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
async def create_task_from_finding(
    finding_id: str,
    payload: FindingTaskRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    finding = await collaboration_v2.finding(settings.sqlite_path, finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail={"code": "collaboration_finding_not_found", "message": "Finding not found", "details": {"finding_id": finding_id}})
    if finding["status"] != "accepted":
        raise HTTPException(
            status_code=409,
            detail={"code": "task_requires_accepted_finding", "message": "Only accepted findings can become implementation tasks", "details": {"status": finding["status"]}},
        )
    priority = payload.priority.strip().lower() if payload.priority else "normal"
    if priority not in {"urgent", "high", "normal", "low"}:
        raise HTTPException(status_code=409, detail={"code": "task_invalid_priority", "message": "Invalid task priority", "details": {"priority": payload.priority}})
    task_prompt = payload.task_prompt.strip() if payload.task_prompt else _task_prompt_from_finding(finding)
    expected_verification = payload.expected_verification.strip() if payload.expected_verification else _verification_from_finding(finding)
    task = await _upsert_task_for_settings(
        settings,
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


@router.post("/project-snapshot-packets")
async def create_project_snapshot_packet(payload: ProjectSnapshotPacketRequest, request: Request, actor: Actor = Depends(require_review_access)):
    settings = request.app.state.settings
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
    quality = await collaboration_v2.ai_state_quality(settings.sqlite_path, payload.vault_id)
    matrix = await collaboration_v2.provider_matrix_summary(settings.sqlite_path)
    preflight = await collaboration_v2.packet_preflight(settings.sqlite_path, payload.vault_id)
    since, since_packet, delta_warnings = await collaboration_v2.resolve_snapshot_since(
        settings.sqlite_path,
        packet_id=payload.since_packet_id,
        vault_id=payload.vault_id,
        profile=profile,
        allow_fallback=payload.allow_since_packet_fallback,
    )
    since = payload.since or since
    delta = await collaboration_v2.project_snapshot_delta(settings.sqlite_path, payload.vault_id, since)
    high_open_count = await collaboration_v2.high_open_count(settings.sqlite_path, payload.vault_id)
    source_rows = await collaboration_v2.packet_source_rows(settings.sqlite_path, vault_id=payload.vault_id, task_limit=task_limit, run_limit=run_limit)
    task_rows = source_rows["tasks"]
    accepted_rows = source_rows["accepted"]
    run_rows = source_rows["runs"]
    node_rows = await collaboration_v2.node_rows(settings.sqlite_path, vault_id=payload.vault_id, delta=delta)
    snapshot_node_cards = [node_card(row, short_summary=f"Recent {row.get('system_kind') or 'page'} node for {profile} packet.") for row in node_rows]
    duplicate_groups = await _finding_duplicate_groups_for_settings(settings, vault_id=payload.vault_id, statuses={"pending", "needs_more_context", "accepted", "deferred"}, limit=500)
    warnings = _packet_warning_list(health, quality, preflight, high_open_count) + delta_warnings
    important = await collaboration_v2.important_changes(
        settings.sqlite_path,
        vault_id=payload.vault_id,
        since=since,
        limit=min(int(target_policy["max_important_changes"]), int(hard_limits["max_important_changes"])),
        action_route=action_route,
    )
    diff_summary = snapshot_diff_summary(important, delta)
    no_reopen = await collaboration_v2.do_not_reopen(settings.sqlite_path, vault_id=payload.vault_id)
    do_not_suggest = do_not_suggest_rules(profile)
    summary_payload = packet_summary(accepted_rows=accepted_rows, task_rows=task_rows, run_rows=run_rows, important=important)
    ai_context_payload = ai_context(profile=profile, target_agent=payload.target_agent, focus=focus, output_mode=output_mode)
    packet_id = f"snapshot_{uuid4().hex[:12]}"
    generated_at = utc_now()
    packet_source_manifest = source_manifest(snapshot_node_cards, generated_at=generated_at)
    trace_payload = packet_trace(
        trace_id=packet_id,
        name="knownet.project_snapshot_packet",
        attributes={
            "knownet.packet.kind": "project_snapshot",
            "knownet.packet.profile": profile,
            "knownet.packet.target_agent": payload.target_agent,
        },
    )
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
    effective_limits = compact_limits(profile=profile, target_policy=target_policy, hard_limits=hard_limits)
    contract_ref = PACKET_SCHEMA_REF
    contract_hash = "sha256:" + hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    compact_health_payload = compact_health(health)
    standard_delta = _standard_delta(delta)
    empty_state_payload = empty_state_signal(preflight=preflight, quality=quality, health=health)
    compact_role_payload = compact_role_boundaries(contract["role_and_access_boundaries"])

    def compact_payload(
        *,
        signals: list[dict[str, Any]] | None = None,
        integrity: dict[str, Any] | None = None,
        fitness: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        include_provider_detail = profile == "provider_review"
        include_detail_state = profile in {"stability", "performance", "security", "implementation", "provider_review"}
        active_signals = signals or []
        context_questions = build_context_questions(active_signals, max_questions=int(OUTPUT_MODES[output_mode].get("max_questions") or 3))
        payload_dict = {
            "id": packet_id,
            "type": "project_snapshot_packet",
            "contract_version": PACKET_CONTRACT_VERSION,
            "protocol_version": PACKET_PROTOCOL_VERSION,
            "schema_ref": PACKET_SCHEMA_REF,
            "contract_ref": contract_ref,
            "contract_hash": contract_hash,
            "generated_at": generated_at,
            "packet_url": f"/api/collaboration/project-snapshot-packets/{packet_id}",
            "trace": trace_payload,
            "vault_id": payload.vault_id,
            "profile": profile,
            "output_mode": output_mode,
            "effective_focus": focus,
            "ai_context": ai_context_payload,
            "limits": effective_limits,
            "role_boundaries": compact_role_payload,
            "health": compact_health_payload,
            "signals": active_signals,
            "context_questions": context_questions if output_mode == "context_questions" else None,
            "empty_state": empty_state_payload,
            "packet_summary": summary_payload,
            "snapshot_diff_summary": diff_summary,
            "do_not_suggest": do_not_suggest,
            "packet_integrity": integrity,
            "packet_fitness": fitness,
            "preflight": preflight if include_detail_state else None,
            "ai_state_quality": {"overall_status": quality.get("overall_status"), "summary": quality.get("summary", {})} if include_detail_state else None,
            "search_index_status": (health or {}).get("search"),
            "delta": standard_delta,
            "node_cards": snapshot_node_cards,
            "source_manifest": packet_source_manifest if snapshot_node_cards else None,
            "provider_matrix": matrix.get("summary", {}) if include_provider_detail else None,
            "important_changes": important if include_detail_state else {"summary": important.get("summary", {})},
            "do_not_reopen": no_reopen if include_detail_state else None,
        }
        return omit_empty(payload_dict)

    content = json.dumps(compact_payload(), ensure_ascii=False, indent=2)
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
        high_open_findings=high_open_count,
        provider_matrix=matrix.get("summary", {}),
    )
    signals = packet_signals(issues, max_signals=int(effective_limits["max_signals"]))
    packet_integrity = packet_integrity_summary(status="pass", checks_passed=4, checked_at=generated_at)
    char_budget = profile_char_budget(profile)
    optimization_target = 8000 if profile == "overview" else min(8000, char_budget)
    content = ""
    packet_fitness: dict[str, Any] | None = None
    for _ in range(3):
        content_payload = compact_payload(signals=signals, integrity=packet_integrity, fitness=packet_fitness)
        content = json.dumps(content_payload, ensure_ascii=False, indent=2)
        packet_integrity.update(
            {
                "content_chars": len(content),
                "char_budget": char_budget,
                "optimization_target_chars": optimization_target,
                "under_char_budget": len(content) <= char_budget,
                "under_optimization_target": len(content) <= optimization_target,
            }
        )
        packet_fitness = packet_fitness_score(
            content_chars=len(content),
            char_budget=char_budget,
            optimization_target=optimization_target,
            signals=signals,
            empty_state=empty_state_payload,
            packet_summary_payload=summary_payload,
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
        contract_hash = "sha256:" + hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        content_payload = compact_payload(signals=signals, integrity=packet_integrity, fitness=packet_fitness)
        content = json.dumps(content_payload, ensure_ascii=False, indent=2)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    packet_dir = settings.data_dir / "project-snapshot-packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_path = packet_dir / f"{packet_id}.md"
    packet_path.write_text(content, encoding="utf-8")
    from ..db.sqlite import execute

    await collaboration_v2.store_project_packet(
        settings.sqlite_path,
        snapshot_id=f"snapshot_state_{uuid4().hex[:12]}",
        packet_id=packet_id,
        vault_id=payload.vault_id,
        target_agent=payload.target_agent,
        profile=profile,
        output_mode=output_mode,
        focus=focus,
        content_hash=content_hash,
        content_path=str(packet_path).replace("\\", "/"),
        contract_version=PACKET_CONTRACT_VERSION,
        created_by=actor.actor_id,
        created_at=generated_at,
        summary={"warnings": warnings, "snapshot_quality": snapshot_quality, "packet_fitness": packet_fitness},
        node_cards=snapshot_node_cards,
    )
    await write_audit_event(
        settings.sqlite_path,
        action="project_snapshot_packet.create",
        actor=actor,
        target_type="project_snapshot_packet",
        target_id=packet_id,
        metadata={"content_hash": content_hash, "warnings": warnings, "focus": focus, "since": since, "since_packet_id": payload.since_packet_id, "profile": profile, "contract_version": PACKET_CONTRACT_VERSION},
    )
    self_href = f"/api/collaboration/project-snapshot-packets/{packet_id}"
    storage_href = f"project-snapshot-packets/{packet_id}.md"
    response_data = {
            "id": packet_id,
            "type": "project_snapshot_packet",
            "generated_at": generated_at,
            "links": _resource_links(self_href=self_href, content_href=self_href, storage_href=storage_href),
            "content": content,
            "content_hash": content_hash,
            "preflight": preflight,
            "delta": standard_delta,
            "warnings": warnings,
            "snapshot_quality": snapshot_quality,
            "packet_integrity": packet_integrity,
            "packet_fitness": packet_fitness,
            "contract_ref": contract_ref,
            "contract_hash": contract_hash,
            "limits": effective_limits,
            "role_boundaries": contract["role_and_access_boundaries"],
            "protocol_version": PACKET_PROTOCOL_VERSION,
            "schema_ref": PACKET_SCHEMA_REF,
            "trace": trace_payload,
            "ai_context": ai_context_payload,
            "issues": issues,
            "signals": signals,
            "context_questions": build_context_questions(signals, max_questions=int(OUTPUT_MODES[output_mode].get("max_questions") or 3)),
            "empty_state": empty_state_payload,
            "packet_summary": summary_payload,
            "node_cards": snapshot_node_cards,
            "source_manifest": packet_source_manifest,
            "profile": profile,
            "output_mode": output_mode,
            "effective_focus": focus,
            "important_changes": important,
            "snapshot_diff_summary": diff_summary,
            "do_not_suggest": do_not_suggest,
            "contract_version": PACKET_CONTRACT_VERSION,
            "copy_ready": True,
    }
    response_data = omit_empty(response_data)
    schema_errors = validate_packet_schema_core(response_data)
    if schema_errors:
        raise HTTPException(status_code=500, detail={"code": "project_snapshot_packet_schema_invalid", "message": "Generated project snapshot packet failed packet schema validation", "details": {"errors": schema_errors}})
    return {"ok": True, "data": response_data}


@router.get("/project-snapshot-packets/{packet_id}")
async def get_project_snapshot_packet(packet_id: str, request: Request, actor: Actor = Depends(require_review_access)):
    if not re.match(r"^snapshot_[a-f0-9]{12}$", packet_id):
        raise HTTPException(status_code=404, detail={"code": "project_snapshot_packet_not_found", "message": "Project snapshot packet not found", "details": {"packet_id": packet_id}})
    path = request.app.state.settings.data_dir / "project-snapshot-packets" / f"{packet_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "project_snapshot_packet_not_found", "message": "Project snapshot packet not found", "details": {"packet_id": packet_id}})
    content = path.read_text(encoding="utf-8")
    self_href = f"/api/collaboration/project-snapshot-packets/{packet_id}"
    return {
        "ok": True,
        "data": {
            "id": packet_id,
            "type": "project_snapshot_packet",
            "content": content,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "links": _resource_links(self_href=self_href, content_href=self_href, storage_href=f"project-snapshot-packets/{packet_id}.md"),
            "copy_ready": True,
        },
    }


def _stored_packet_json(settings, packet_id: str) -> dict[str, Any]:
    if not re.match(r"^snapshot_[a-f0-9]{12}$", packet_id):
        raise HTTPException(status_code=404, detail={"code": "project_snapshot_packet_not_found", "message": "Project snapshot packet not found", "details": {"packet_id": packet_id}})
    path = settings.data_dir / "project-snapshot-packets" / f"{packet_id}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "project_snapshot_packet_not_found", "message": "Project snapshot packet not found", "details": {"packet_id": packet_id}})
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=409, detail={"code": "project_snapshot_packet_not_json", "message": "Stored packet is not JSON", "details": {"packet_id": packet_id, "error": str(exc)}}) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=409, detail={"code": "project_snapshot_packet_invalid_json", "message": "Stored packet JSON must be an object", "details": {"packet_id": packet_id}})
    return parsed


@router.post("/project-snapshot-packets/compare")
async def compare_project_snapshot_packets(payload: PacketCompareRequest, request: Request, actor: Actor = Depends(require_review_access)):
    settings = request.app.state.settings
    left = payload.left_packet or (_stored_packet_json(settings, payload.left_packet_id) if payload.left_packet_id else None)
    right = payload.right_packet or (_stored_packet_json(settings, payload.right_packet_id) if payload.right_packet_id else None)
    if not isinstance(left, dict) or not isinstance(right, dict):
        raise HTTPException(status_code=422, detail={"code": "packet_compare_requires_two_packets", "message": "Provide left/right packet objects or packet ids.", "details": {}})
    return {"ok": True, "data": packet_diff_view(left, right)}


@router.post("/ai-review-comparisons")
async def compare_external_ai_reviews(payload: AIReviewComparisonRequest, actor: Actor = Depends(require_review_access)):
    reviews = [{"source_agent": item.source_agent, "text": item.text} for item in payload.reviews]
    return {"ok": True, "data": compare_ai_reviews(reviews)}


@router.post("/experiment-packets")
async def create_experiment_packet(payload: ExperimentPacketRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    raise HTTPException(
        status_code=410,
        detail={
            "code": "experiment_packets_retired",
            "message": "Experiment packets were retired in DB v2. Use project snapshot packets with node_cards and context_questions.",
            "details": {"replacement_endpoint": "/api/collaboration/project-snapshot-packets"},
        },
    )


@router.get("/experiment-packets/{packet_id}")
async def get_experiment_packet(packet_id: str, request: Request, actor: Actor = Depends(require_review_access)):
    raise HTTPException(status_code=410, detail={"code": "experiment_packets_retired", "message": "Experiment packets were retired in DB v2.", "details": {"replacement_endpoint": "/api/collaboration/project-snapshot-packets"}})


@router.post("/experiment-packets/{packet_id}/responses/dry-run")
async def dry_run_experiment_packet_response(packet_id: str, payload: ExperimentPacketResponseRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    raise HTTPException(status_code=410, detail={"code": "experiment_packets_retired", "message": "Experiment packet responses were retired in DB v2.", "details": {"replacement_endpoint": "/api/collaboration/reviews/import"}})


@router.post("/experiment-packets/{packet_id}/responses/{response_id}/import")
async def import_experiment_packet_response(packet_id: str, response_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    raise HTTPException(status_code=410, detail={"code": "experiment_packets_retired", "message": "Experiment packet imports were retired in DB v2.", "details": {"replacement_endpoint": "/api/collaboration/reviews/import"}})


@router.post("/context-bundles")
async def create_context_bundle(payload: ContextBundleRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    raise HTTPException(
        status_code=410,
        detail={
            "code": "context_bundles_retired",
            "message": "Context bundles were retired in DB v2. Use compact project snapshot packets instead.",
            "details": {"replacement_endpoint": "/api/collaboration/project-snapshot-packets"},
        },
    )
