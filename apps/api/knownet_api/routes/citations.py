from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..security import Actor, require_review_access, requested_vault_id, utc_now
from ..services.rust_core import RustCoreError

router = APIRouter(prefix="/api/citations", tags=["citations"])


class ReviewCitationRequest(BaseModel):
    reason: str = Field(default="Reviewed by human", max_length=300)


class VerifyCitationRequest(BaseModel):
    use_openai_mock: bool = False


@router.get("/audits")
async def list_citation_audits(
    request: Request,
    vault_id: str | None = None,
    status: str | None = None,
    page_id: str | None = None,
    verifier_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    effective_vault_id = vault_id or requested_vault_id(request)
    if effective_vault_id != actor.vault_id and actor.actor_type not in {"local", "admin_token"}:
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Vault access denied", "details": {}})
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    clauses = ["vault_id = ?"]
    params: list[object] = [effective_vault_id]
    if status:
        statuses = [item.strip() for item in status.split(",") if item.strip()]
        if statuses:
            clauses.append("status IN ({})".format(",".join("?" for _ in statuses)))
            params.extend(statuses)
    if page_id:
        clauses.append("page_id = ?")
        params.append(page_id)
    if verifier_type:
        clauses.append("verifier_type = ?")
        params.append(verifier_type)
    params.extend([limit, offset])
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT id, vault_id, page_id, revision_id, citation_key, claim_hash, claim_text, status, "
        "confidence, verifier_type, verifier_id, reason, source_hash, evidence_snapshot_id, created_at, updated_at "
        "FROM citation_audits WHERE "
        + " AND ".join(clauses)
        + " ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        tuple(params),
    )
    return {"ok": True, "data": {"audits": rows, "limit": limit, "offset": offset}}


async def _set_status(request: Request, audit_id: str, actor: Actor, status: str, reason: str):
    settings = request.app.state.settings
    try:
        result = await request.app.state.rust_core.request(
            "update_citation_audit_status",
            {
                "sqlite_path": str(settings.sqlite_path),
                "audit_id": audit_id,
                "actor_type": actor.actor_type,
                "actor_id": actor.actor_id,
                "status": status,
                "reason": reason,
                "updated_at": utc_now(),
            },
        )
    except RustCoreError as error:
        status_code = 404 if error.code == "citation_audit_not_found" else 409 if error.code == "citation_already_resolved" else 500
        raise HTTPException(status_code=status_code, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action=f"citation.{status}",
        actor=actor,
        target_type="citation_audit",
        target_id=audit_id,
        metadata={"reason": reason},
    )
    return {"ok": True, "data": result}


@router.post("/audits/{audit_id}/resolve")
async def resolve_citation_audit(
    audit_id: str,
    payload: ReviewCitationRequest,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    return await _set_status(request, audit_id, actor, "supported", payload.reason)


@router.post("/audits/{audit_id}/needs-review")
async def mark_citation_needs_review(
    audit_id: str,
    payload: ReviewCitationRequest,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    return await _set_status(request, audit_id, actor, "needs_review", payload.reason)


@router.post("/audits/{audit_id}/verify")
async def verify_citation_audit(
    audit_id: str,
    payload: VerifyCitationRequest,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, claim_text, evidence_snapshot_id FROM citation_audits WHERE id = ?",
        (audit_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "citation_audit_not_found", "message": "Citation audit not found", "details": {}})
    if not payload.use_openai_mock:
        return await _set_status(request, audit_id, actor, "needs_review", "Manual verifier requested; OpenAI not enabled")
    return await _set_status(request, audit_id, actor, "needs_review", "OpenAI mock verifier marked this for review")


@router.post("/rebuild/page/{page_id}")
async def rebuild_page_citation_audits(
    page_id: str,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    settings = request.app.state.settings
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT path, current_revision_id FROM pages WHERE id = ?",
        (page_id,),
    )
    if not row or not Path(row["path"]).exists():
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Page not found", "details": {"page_id": page_id}})
    try:
        result = await request.app.state.rust_core.request(
            "rebuild_citation_audits_for_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "page_id": page_id,
                "revision_id": row["current_revision_id"],
                "path": row["path"],
                "rebuilt_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action="citation.rebuild_page",
        actor=actor,
        target_type="page",
        target_id=page_id,
        metadata=result,
    )
    return {"ok": True, "data": result}
