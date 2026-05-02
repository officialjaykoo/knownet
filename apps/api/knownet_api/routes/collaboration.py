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
from ..security import Actor, ensure_text_size, require_admin_access, require_write_access, utc_now
from ..services.rust_core import RustCoreError

try:
    import frontmatter
except Exception:  # pragma: no cover - fallback is for minimally installed dev envs.
    frontmatter = None


router = APIRouter(prefix="/api/collaboration", tags=["collaboration"])

SEVERITIES = {"critical", "high", "medium", "low", "info"}
DECISION_STATUSES = {"accepted", "rejected", "deferred", "needs_more_context"}
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
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
]


class ImportReviewRequest(BaseModel):
    vault_id: str = "local-default"
    markdown: str = Field(min_length=1)
    source_agent: str | None = Field(default=None, max_length=80)
    source_model: str | None = Field(default=None, max_length=120)
    page_id: str | None = Field(default=None, max_length=120)


class FindingDecisionRequest(BaseModel):
    status: str
    decision_note: str | None = Field(default=None, max_length=1000)


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
    match = re.search(rf"(?im)^\s*{re.escape(name)}:\s*(.+?)\s*$", block)
    return match.group(1).strip() if match else None


def _section(block: str, start: str, end: str | None = None) -> str | None:
    if end:
        pattern = rf"(?is)^\s*{re.escape(start)}:\s*\n(.*?)(?=^\s*{re.escape(end)}:\s*$|\Z)"
    else:
        pattern = rf"(?is)^\s*{re.escape(start)}:\s*\n(.*)\Z"
    match = re.search(pattern, block, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def parse_review_markdown(markdown: str) -> tuple[dict, list[dict], list[str]]:
    metadata, body = _parse_frontmatter(markdown)
    errors: list[str] = []
    metadata.setdefault("type", "agent_review")
    metadata.setdefault("status", "pending_review")
    metadata.setdefault("source_agent", "unknown")

    heading_matches = list(re.finditer(r"(?m)^###\s+Finding\b.*$", body))
    if not heading_matches:
        errors.append("no_finding_headings")
        return metadata, [
            {
                "severity": "info",
                "area": "general",
                "title": _title_from_markdown(markdown, "Unparsed review"),
                "evidence": None,
                "proposed_change": None,
                "raw_text": body.strip() or markdown,
                "status": "needs_more_context",
            }
        ], errors

    findings: list[dict] = []
    for index, match in enumerate(heading_matches):
        next_start = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(body)
        block = body[match.start() : next_start].strip()
        title = match.group(0).replace("###", "", 1).strip() or f"Finding {index + 1}"
        severity = (_field(block, "Severity") or "info").lower()
        if severity not in SEVERITIES:
            errors.append(f"unknown_severity:{severity}")
            severity = "info"
        area = _field(block, "Area") or "general"
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
                "area": area[:120],
                "title": title[:220],
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


@router.post("/reviews")
async def import_review(payload: ImportReviewRequest, request: Request, actor: Actor = Depends(require_write_access)):
    settings = request.app.state.settings
    ensure_text_size(payload.markdown, settings.max_message_bytes, "markdown")
    metadata, findings, parser_errors = parse_review_markdown(payload.markdown)
    if not findings:
        raise HTTPException(status_code=422, detail={"code": "collaboration_no_findings", "message": "No findings found", "details": {}})

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
    return {"ok": True, "data": {"review": review, "findings": created_findings, "graph_rebuild": graph_rebuild}}


@router.get("/reviews")
async def list_reviews(
    request: Request,
    vault_id: str = "local-default",
    status: str | None = "pending_review",
    source_agent: str | None = None,
    area: str | None = None,
    limit: int = 50,
    actor: Actor = Depends(require_write_access),
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
async def get_review(review_id: str, request: Request, actor: Actor = Depends(require_write_access)):
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


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


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

    sections = [
        "# KnowNet Context Bundle",
        f"generated_at: {utc_now()}",
        f"pages_included: {len(rows)}",
        "generated_for: external AI review",
        "warning: Do not include secrets in this bundle.",
        "",
    ]
    for row in rows:
        path = Path(row["path"]).resolve()
        data_dir = settings.data_dir.resolve()
        if data_dir not in path.parents:
            raise HTTPException(status_code=400, detail={"code": "context_bundle_forbidden_path", "message": "Page path is outside data directory", "details": {"page_id": row["id"]}})
        content = _strip_frontmatter(path.read_text(encoding="utf-8"))
        if _contains_secret(content):
            raise HTTPException(status_code=422, detail={"code": "context_bundle_secret_detected", "message": "Secret-like value detected", "details": {"page_id": row["id"]}})
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
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    filename = f"knownet-context-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:8]}.md"
    manifest_id = f"bundle_{uuid4().hex[:12]}"
    try:
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
                "included_sections": json.dumps(["pages", "citation_summary", "graph_summary" if payload.include_graph_summary else "no_graph"], ensure_ascii=True),
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
