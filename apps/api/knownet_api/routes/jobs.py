from fastapi import APIRouter, HTTPException, Request

from ..db.sqlite import fetch_one

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}")
async def get_job(job_id: str, request: Request):
    settings = request.app.state.settings
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, job_type, target_type, target_id, status, attempts, max_attempts, error_code, error_message, created_at, updated_at FROM jobs WHERE id = ?",
        (job_id,),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Job not found", "details": {}})
    suggestion = await fetch_one(
        settings.sqlite_path,
        "SELECT id, title, status FROM suggestions WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
        (job_id,),
    )
    return {"ok": True, "data": {"job_id": row.pop("id"), **row, "suggestion": suggestion}}
