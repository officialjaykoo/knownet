from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ..db.sqlite import fetch_all
from ..security import Actor, require_admin_access

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditQuery(BaseModel):
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


@router.get("")
async def list_audit_events(
    request: Request,
    action: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 50,
    actor: Actor = Depends(require_admin_access),
):
    query = AuditQuery(action=action, target_type=target_type, target_id=target_id, limit=limit)
    where = []
    params: list[str | int] = []
    if query.action:
        where.append("action = ?")
        params.append(query.action)
    if query.target_type:
        where.append("target_type = ?")
        params.append(query.target_type)
    if query.target_id:
        where.append("target_id = ?")
        params.append(query.target_id)

    settings = request.app.state.settings
    sql = (
        "SELECT id, created_at, action, actor_type, actor_id, request_id, "
        "target_type, target_id, meta "
        "FROM audit_events"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(query.limit)

    rows = await fetch_all(settings.sqlite_path, sql, tuple(params))
    return {"ok": True, "data": {"events": rows}}
