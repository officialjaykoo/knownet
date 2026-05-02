from __future__ import annotations

import hashlib
import json
import re
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
from ..services.rust_core import RustCoreError

try:
    import frontmatter
except Exception:  # pragma: no cover - fallback is for minimally installed dev envs.
    frontmatter = None


router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

SEVERITIES = {"critical", "high", "medium", "low", "info"}
AREAS = {"API": "API", "UI": "UI", "Rust": "Rust", "Security": "Security", "Data": "Data", "Ops": "Ops", "Docs": "Docs"}
AREA_NORMALIZE = {key.lower(): value for key, value in AREAS.items()}
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


class ContextBundleRequest(BaseModel):
    vault_id: str = "local-default"
    page_ids: list[str] = Field(default_factory=list, max_length=50)
    include_graph_summary: bool = True


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


def parse_review_markdown(markdown: str) -> tuple[dict, list[dict], list[str]]:
    metadata, body = _parse_frontmatter(markdown)
    errors: list[str] = []
    metadata.setdefault("type", "agent_review")
    metadata.setdefault("status", "pending_review")
    metadata.setdefault("source_agent", "unknown")

    heading_matches = list(re.finditer(r"(?im)^###\s+finding\b.*$", body))
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
        title = match.group(0).replace("###", "", 1).strip() or f"Finding {index + 1}"
        severity = (_field(block, "Severity") or "info").lower()
        if severity not in SEVERITIES:
            errors.append(f"unknown_severity:{severity}")
            severity = "info"
        area = _normalize_area(_field(block, "Area"))
        explicit_title = _field(block, "Title")
        evidence = _section(block, "Evidence", "Proposed change")
        proposed_change = _section(block, "Proposed change")
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
                "status": status,
            }
        )
    return metadata, findings, errors


def _http_from_rust(error: RustCoreError) -> HTTPException:
    status = 404 if error.code.endswith("_not_found") else 409 if "invalid_status" in error.code else 500
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details})


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
    if dry_run:
        if agent:
            await record_agent_access(
                settings.sqlite_path,
                agent=agent,
                action="review.dry_run",
                status="ok",
                meta={"finding_count": len(findings), "parser_errors": parser_errors, "truncated_findings": bool(metadata.get("truncated_findings"))},
            )
        return {
            "ok": True,
            "data": {
                "dry_run": True,
                "metadata": metadata,
                "finding_count": len(findings),
                "findings": findings,
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
        metadata={"source_agent": source_agent, "findings": len(created_findings), "parser_errors": parser_errors, "graph_rebuild": graph_rebuild},
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
    graph_rebuild = await _rebuild_collaboration_graph(request, actor.vault_id)
    await write_audit_event(
        settings.sqlite_path,
        action=f"finding.{payload.status}",
        actor=actor,
        target_type="collaboration_finding",
        target_id=finding_id,
        metadata={"decision_note": payload.decision_note, "graph_rebuild": graph_rebuild},
    )
    return {"ok": True, "data": {**result, "graph_rebuild": graph_rebuild}}


@router.post("/findings/{finding_id}/implementation")
async def record_implementation(
    finding_id: str,
    payload: ImplementationRecordRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    if payload.commit_sha and not re.match(r"^[A-Fa-f0-9]{7,40}$", payload.commit_sha):
        raise HTTPException(status_code=422, detail={"code": "implementation_record_invalid_commit", "message": "Invalid commit hash", "details": {}})
    settings = request.app.state.settings
    record_id = f"impl_{uuid4().hex[:12]}"
    try:
        result = await request.app.state.rust_core.request(
            "create_implementation_record",
            {
                "sqlite_path": str(settings.sqlite_path),
                "record_id": record_id,
                "finding_id": finding_id,
                "commit_sha": payload.commit_sha,
                "changed_files": json.dumps(payload.changed_files, ensure_ascii=True),
                "verification": payload.verification,
                "notes": payload.notes,
                "created_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise _http_from_rust(error) from error
    graph_rebuild = await _rebuild_collaboration_graph(request, actor.vault_id)
    await write_audit_event(
        settings.sqlite_path,
        action="implementation.record",
        actor=actor,
        target_type="collaboration_finding",
        target_id=finding_id,
        metadata={"record_id": record_id, "commit_sha": payload.commit_sha, "changed_files": payload.changed_files, "graph_rebuild": graph_rebuild},
    )
    return {"ok": True, "data": {**result, "graph_rebuild": graph_rebuild}}


def _strip_frontmatter(markdown: str) -> str:
    if markdown.startswith("---\n"):
        end = markdown.find("\n---\n", 4)
        if end != -1:
            return markdown[end + 5 :].lstrip()
    return markdown


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
