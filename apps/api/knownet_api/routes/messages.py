from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..security import (
    Actor,
    enforce_job_limit,
    enforce_write_rate_limit,
    ensure_text_size,
    require_message_actor,
)
from ..services.rust_core import RustCoreError

router = APIRouter(prefix="/api/messages", tags=["messages"])


class CreateMessageRequest(BaseModel):
    content: str = Field(min_length=1)


@router.post("")
async def create_message(
    payload: CreateMessageRequest,
    request: Request,
    actor: Actor = Depends(require_message_actor),
):
    rust = request.app.state.rust_core
    if not rust.available:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "daemon_unavailable",
                "message": "Rust daemon is unavailable",
                "details": {},
            },
        )

    now = datetime.now(timezone.utc)
    message_id = f"msg_{now.strftime('%Y%m%d_%H%M%S_%f')}"
    settings = request.app.state.settings
    ensure_text_size(payload.content, settings.max_message_bytes, "content")
    await enforce_write_rate_limit(request, actor, settings)
    should_queue_job = actor.role in {"owner", "admin", "editor"} and actor.actor_type != "anonymous"
    if should_queue_job:
        await enforce_job_limit(actor, settings)
    try:
        created_at = now.isoformat().replace("+00:00", "Z")
        command = "write_message" if should_queue_job else "write_pending_message"
        result = await rust.request(
            command,
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "message_id": message_id,
                "content": payload.content,
                "created_at": created_at,
            },
        )
        if not should_queue_job:
            submission_id = f"sub_{now.strftime('%Y%m%d_%H%M%S_%f')}"
            submission = await rust.request(
                "create_submission",
                {
                    "sqlite_path": str(settings.sqlite_path),
                    "submission_id": submission_id,
                    "message_id": message_id,
                    "actor_type": actor.actor_type,
                    "session_id": actor.session_id,
                    "created_at": created_at,
                },
            )
            result["submission_id"] = submission["submission_id"]
        result["embedding"] = await request.app.state.embedding_service.upsert_text(
            rust=rust,
            sqlite_path=settings.sqlite_path,
            tmp_dir=settings.data_dir / "tmp",
            owner_type="message",
            owner_id=message_id,
            text=payload.content,
            updated_at=created_at,
        )
        await write_audit_event(
            settings.sqlite_path,
            action="message.created",
            actor=actor,
            target_type="message",
            target_id=result["message_id"],
            metadata={"job_id": result.get("job_id"), "path": result["path"], "submission_id": result.get("submission_id")},
        )
    except RustCoreError as error:
        status_code = 503 if error.code == "daemon_unavailable" else 500
        raise HTTPException(
            status_code=status_code,
            detail={"code": error.code, "message": error.message, "details": error.details},
        ) from error

    return {"ok": True, "data": result}
