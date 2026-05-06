from pathlib import Path
import difflib
import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..paths import page_storage_dir
from ..security import (
    Actor,
    enforce_write_rate_limit,
    ensure_length,
    require_write_access,
)
from ..services.rust_core import RustCoreError
from ..services.citation_titles import backfill_citation_display_titles
from ..services.search_index import sync_page_fts
from ..services.system_pages import raise_if_system_page_locked

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])


class ApplySuggestionRequest(BaseModel):
    slug: str | None = None


class RejectSuggestionRequest(BaseModel):
    reason: str | None = None


def _read_markdown(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail={"code": "file_not_found", "message": "Suggestion file not found", "details": {"path": path}})
    return file_path.read_text(encoding="utf-8")


def _safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.lower()).strip("-")
    return slug or fallback


def _page_id_from_slug(slug: str) -> str:
    return f"page_{slug.replace('-', '_')}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown.strip()
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown.strip()
    return markdown[end + 5 :].strip()


def _line_changes(existing: str, proposed: str) -> list[dict]:
    changes = []
    for line in difflib.ndiff(existing.splitlines(), proposed.splitlines()):
        if line.startswith("- "):
            changes.append({"type": "removed", "text": line[2:]})
        elif line.startswith("+ "):
            changes.append({"type": "added", "text": line[2:]})
    return changes


async def _suggestion_row(settings, suggestion_id: str) -> dict:
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, job_id, message_id, path, title, status, created_at, updated_at FROM suggestions WHERE id = ?",
        (suggestion_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "suggestion_not_found", "message": "Suggestion not found", "details": {}})
    return row


@router.get("")
async def list_suggestions(request: Request, job_id: str | None = None):
    settings = request.app.state.settings
    if job_id:
        rows = await fetch_all(
            settings.sqlite_path,
            "SELECT id, job_id, message_id, path, title, status, created_at, updated_at FROM suggestions WHERE job_id = ? ORDER BY created_at DESC",
            (job_id,),
        )
    else:
        rows = await fetch_all(
            settings.sqlite_path,
            "SELECT id, job_id, message_id, path, title, status, created_at, updated_at FROM suggestions ORDER BY created_at DESC LIMIT 50",
            (),
        )
    return {"ok": True, "data": {"suggestions": rows}}


@router.get("/{suggestion_id}")
async def get_suggestion(suggestion_id: str, request: Request):
    settings = request.app.state.settings
    row = await _suggestion_row(settings, suggestion_id)
    return {"ok": True, "data": {**row, "markdown": _read_markdown(row["path"])}}


@router.get("/{suggestion_id}/diff")
async def get_suggestion_diff(suggestion_id: str, request: Request):
    settings = request.app.state.settings
    row = await _suggestion_row(settings, suggestion_id)
    suggestion_markdown = _read_markdown(row["path"])
    proposed = _strip_frontmatter(suggestion_markdown)
    slug = _safe_slug(row["title"], suggestion_id.replace("_", "-"))
    page_path = page_storage_dir(settings.data_dir) / f"{slug}.md"
    existing = _strip_frontmatter(page_path.read_text(encoding="utf-8")) if page_path.exists() else ""
    unified = "\n".join(
        difflib.unified_diff(
            existing.splitlines(),
            proposed.splitlines(),
            fromfile=f"pages/{slug}.md" if existing else "/dev/null",
            tofile=f"suggestion/{suggestion_id}.md",
            lineterm="",
        )
    )
    return {
        "ok": True,
        "data": {
            "suggestion_id": suggestion_id,
            "slug": slug,
            "status": row["status"],
            "mode": "update" if existing else "create",
            "existing_markdown": existing,
            "proposed_markdown": proposed,
            "unified_diff": unified,
            "changes": _line_changes(existing, proposed),
        },
    }


@router.post("/{suggestion_id}/apply")
async def apply_suggestion(
    suggestion_id: str,
    payload: ApplySuggestionRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, title FROM suggestions WHERE id = ?",
        (suggestion_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "suggestion_not_found", "message": "Suggestion not found", "details": {}})

    slug = _safe_slug(payload.slug or row["title"], suggestion_id.replace("_", "-"))
    await raise_if_system_page_locked(settings.sqlite_path, slug=slug)
    ensure_length(slug, settings.max_slug_chars, "slug")
    ensure_length(row["title"], settings.max_title_chars, "title")
    await enforce_write_rate_limit(request, actor, settings)
    existing_page = await fetch_one(
        settings.sqlite_path,
        "SELECT current_revision_id FROM pages WHERE slug = ?",
        (slug,),
    )
    revision_id = f"rev_{uuid4().hex[:12]}"
    rust = request.app.state.rust_core
    try:
        result = await rust.request(
            "apply_suggestion",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "suggestion_id": suggestion_id,
                "slug": slug,
                "revision_id": revision_id,
                "applied_at": _utc_now(),
            },
        )
        await rust.request(
            "index_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "path": result["path"],
                "page_id": _page_id_from_slug(result["slug"]),
                "revision_id": result["revision_id"],
                "indexed_at": _utc_now(),
            },
        )
        await backfill_citation_display_titles(settings.sqlite_path)
        page_id = _page_id_from_slug(result["slug"])
        markdown = Path(result["path"]).read_text(encoding="utf-8")
        page_row = await fetch_one(settings.sqlite_path, "SELECT id, vault_id, title, slug, status FROM pages WHERE id = ?", (page_id,))
        result["fts_status"] = await sync_page_fts(
            settings.sqlite_path,
            page_id=page_id,
            vault_id=(page_row or {}).get("vault_id") or actor.vault_id,
            title=(page_row or {}).get("title") or row["title"],
            slug=result["slug"],
            body=markdown,
            active=(page_row or {}).get("status", "active") == "active",
        )
        result["citation_verification"] = await request.app.state.citation_verifier.verify_page(
            page_id=page_id,
            revision_id=result["revision_id"],
            page_markdown=markdown,
        )
        citation_audit = await rust.request(
            "rebuild_citation_audits_for_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "page_id": page_id,
                "revision_id": result["revision_id"],
                "path": result["path"],
                "rebuilt_at": _utc_now(),
            },
        )
        result["citation_audit"] = citation_audit
        result["citation_warnings"] = citation_audit.get("citation_warnings") or []
        result["embedding"] = await request.app.state.embedding_service.upsert_text(
            rust=rust,
            sqlite_path=settings.sqlite_path,
            tmp_dir=settings.data_dir / "tmp",
            owner_type="page",
            owner_id=page_id,
            text=markdown,
            updated_at=_utc_now(),
        )
        result["graph_rebuild"] = await rust.request(
            "rebuild_graph_for_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "page_id": page_id,
                "rebuilt_at": _utc_now(),
            },
        )
        await write_audit_event(
            settings.sqlite_path,
            action="suggestion.applied",
            actor=actor,
            target_type="page",
            target_id=page_id,
            before_revision_id=existing_page["current_revision_id"] if existing_page else None,
            after_revision_id=result["revision_id"],
            metadata={
                "suggestion_id": suggestion_id,
                "slug": result["slug"],
                "path": result["path"],
                "fts_status": result.get("fts_status"),
                "embedding": result.get("embedding"),
                "citation_verification": result.get("citation_verification"),
                "citation_audit": result.get("citation_audit"),
                "graph_rebuild": result.get("graph_rebuild"),
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": result}


@router.post("/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    payload: RejectSuggestionRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    row = await _suggestion_row(settings, suggestion_id)
    if row["status"] == "applied":
        raise HTTPException(status_code=409, detail={"code": "suggestion_already_applied", "message": "Applied suggestions cannot be rejected", "details": {}})
    await enforce_write_rate_limit(request, actor, settings)
    now = _utc_now()
    try:
        result = await request.app.state.rust_core.request(
            "reject_suggestion",
            {
                "sqlite_path": str(settings.sqlite_path),
                "suggestion_id": suggestion_id,
                "rejected_at": now,
            },
        )
    except RustCoreError as error:
        status = 404 if error.code == "suggestion_not_found" else 500
        raise HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action="suggestion.rejected",
        actor=actor,
        target_type="suggestion",
        target_id=suggestion_id,
        metadata={"reason": payload.reason, "previous_status": row["status"]},
    )
    return {"ok": True, "data": result}
