import re
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..security import Actor, require_admin_access, require_actor, utc_now
from ..services.rust_core import RustCoreError

router = APIRouter(prefix="/api/vaults", tags=["vaults"])


class CreateVaultRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    vault_id: str | None = Field(default=None, max_length=80)


class AssignMemberRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=80)
    role: str = Field(pattern="^(owner|admin|editor|reviewer|viewer)$")


def _safe_vault_id(value: str) -> str:
    vault_id = re.sub(r"[^A-Za-z0-9_-]+", "-", value.lower()).strip("-")
    if not vault_id:
        vault_id = f"vault-{uuid4().hex[:8]}"
    return vault_id


@router.get("")
async def list_vaults(request: Request, actor: Actor = Depends(require_actor)):
    settings = request.app.state.settings
    if actor.role in {"owner", "admin"} and actor.actor_type in {"local", "admin_token"}:
        rows = await fetch_all(
            settings.sqlite_path,
            "SELECT v.id, v.name, COALESCE(vm.role, 'owner') AS role, v.created_at "
            "FROM vaults v LEFT JOIN vault_members vm ON vm.vault_id = v.id AND vm.user_id = ? "
            "ORDER BY v.created_at ASC",
            (actor.actor_id,),
        )
    else:
        rows = await fetch_all(
            settings.sqlite_path,
            "SELECT v.id, v.name, vm.role, v.created_at "
            "FROM vault_members vm JOIN vaults v ON v.id = vm.vault_id "
            "WHERE vm.user_id = ? ORDER BY v.created_at ASC",
            (actor.actor_id,),
        )
    return {"ok": True, "data": {"vaults": rows, "current_vault_id": actor.vault_id}}


@router.post("")
async def create_vault(payload: CreateVaultRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    if actor.actor_type == "anonymous":
        raise HTTPException(status_code=403, detail={"code": "forbidden", "message": "Anonymous actors cannot create vaults", "details": {}})
    settings = request.app.state.settings
    vault_id = _safe_vault_id(payload.vault_id or payload.name)
    existing = await fetch_one(settings.sqlite_path, "SELECT id FROM vaults WHERE id = ?", (vault_id,))
    if existing:
        raise HTTPException(status_code=409, detail={"code": "vault_exists", "message": "Vault already exists", "details": {"vault_id": vault_id}})
    try:
        result = await request.app.state.rust_core.request(
            "create_vault",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": vault_id,
                "name": payload.name.strip(),
                "owner_user_id": actor.actor_id,
                "created_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action="vault.create",
        actor=actor,
        target_type="vault",
        target_id=vault_id,
        metadata={"name": payload.name.strip()},
    )
    return {"ok": True, "data": result}


@router.post("/{vault_id}/members")
async def assign_member(
    vault_id: str,
    payload: AssignMemberRequest,
    request: Request,
    actor: Actor = Depends(require_admin_access),
):
    settings = request.app.state.settings
    existing = await fetch_one(settings.sqlite_path, "SELECT id FROM vaults WHERE id = ?", (vault_id,))
    if not existing:
        raise HTTPException(status_code=404, detail={"code": "vault_not_found", "message": "Vault not found", "details": {"vault_id": vault_id}})
    try:
        result = await request.app.state.rust_core.request(
            "assign_vault_member",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": vault_id,
                "user_id": payload.user_id,
                "role": payload.role,
                "created_at": utc_now(),
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action="vault.member.assign",
        actor=actor,
        target_type="vault",
        target_id=vault_id,
        metadata={"user_id": payload.user_id, "role": payload.role},
    )
    return {"ok": True, "data": result}
