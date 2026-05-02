from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..security import Actor, require_review_access, utc_now
from ..services.rust_core import RustCoreError

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


class ReviewSubmissionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.get("")
async def list_submissions(request: Request, status: str = "pending_review", actor: Actor = Depends(require_review_access)):
    settings = request.app.state.settings
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT s.id, s.message_id, s.actor_type, s.session_id, s.status, s.reviewed_by, "
        "s.review_note, s.created_at, s.updated_at, m.path AS message_path "
        "FROM submissions s JOIN messages m ON m.id = s.message_id "
        "WHERE s.status = ? ORDER BY s.created_at ASC LIMIT 100",
        (status,),
    )
    return {"ok": True, "data": {"submissions": rows, "actor_role": actor.role}}


async def _review_submission(request: Request, submission_id: str, status: str, actor: Actor, note: str | None):
    settings = request.app.state.settings
    existing = await fetch_one(
        settings.sqlite_path,
        "SELECT id, message_id, status FROM submissions WHERE id = ?",
        (submission_id,),
    )
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "submission_not_found", "message": "Submission not found", "details": {}})
    if existing["status"] != "pending_review":
        raise HTTPException(status_code=409, detail={"code": "submission_already_reviewed", "message": "Submission is already reviewed", "details": {"status": existing["status"]}})
    try:
        result = await request.app.state.rust_core.request(
            "update_submission_status",
            {
                "sqlite_path": str(settings.sqlite_path),
                "submission_id": submission_id,
                "status": status,
                "reviewed_by": actor.actor_id,
                "review_note": note,
                "updated_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error

    await write_audit_event(
        settings.sqlite_path,
        action="submission.approve" if status == "queued" else "submission.reject",
        actor=actor,
        target_type="submission",
        target_id=submission_id,
        metadata={"message_id": existing["message_id"], "job_id": result.get("job_id") or None, "note": note},
    )
    return {"ok": True, "data": result}


@router.post("/{submission_id}/approve")
async def approve_submission(
    submission_id: str,
    payload: ReviewSubmissionRequest,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    return await _review_submission(request, submission_id, "queued", actor, payload.note)


@router.post("/{submission_id}/reject")
async def reject_submission(
    submission_id: str,
    payload: ReviewSubmissionRequest,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    return await _review_submission(request, submission_id, "rejected", actor, payload.note)
