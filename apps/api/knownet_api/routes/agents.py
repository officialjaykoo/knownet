import json
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import execute, fetch_all, fetch_one
from ..security import Actor, agent_token_hash, require_admin_access, utc_now


router = APIRouter(prefix="/api/agents", tags=["agents"])

TOKEN_PREFIX = "kn_agent_"
ROLE_VALUES = {"agent_reader", "agent_reviewer", "agent_contributor"}
SCOPE_PRESETS = {
    "preset:reader": ["pages:read", "graph:read", "citations:read"],
    "preset:reviewer": ["reviews:read", "findings:read", "reviews:create"],
    "preset:contributor": ["reviews:read", "findings:read", "reviews:create", "messages:create"],
}


class CreateAgentTokenRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    agent_name: str = Field(min_length=1, max_length=120)
    agent_model: str | None = Field(default=None, max_length=120)
    purpose: str = Field(min_length=1, max_length=240)
    role: str = "agent_reader"
    vault_id: str = "local-default"
    scopes: list[str] = Field(default_factory=list, max_length=50)
    max_pages_per_request: int = Field(default=20, ge=1, le=200)
    max_chars_per_request: int = Field(default=60000, ge=1000, le=500000)
    expires_at: str | None = None


def _validate_expires_at(value: str | None) -> str | None:
    if not value:
        return None
    try:
        expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "agent_expiry_invalid", "message": "expires_at must be an ISO datetime", "details": {}}) from exc
    if expires.tzinfo is None:
        raise HTTPException(status_code=422, detail={"code": "agent_expiry_invalid", "message": "expires_at must include timezone", "details": {}})
    return expires.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expand_scopes(scopes: list[str]) -> list[str]:
    expanded: list[str] = []
    for scope in scopes:
        if scope in SCOPE_PRESETS:
            expanded.extend(SCOPE_PRESETS[scope])
        else:
            if "*" in scope:
                raise HTTPException(status_code=422, detail={"code": "agent_scope_invalid", "message": "Wildcard scopes are not allowed", "details": {"scope": scope}})
            expanded.append(scope)
    return sorted(set(expanded))


def _public_token_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "agent_name": row["agent_name"],
        "agent_model": row["agent_model"],
        "purpose": row["purpose"],
        "role": row["role"],
        "vault_id": row["vault_id"],
        "scopes": json.loads(row["scopes"] or "[]"),
        "max_pages_per_request": row["max_pages_per_request"],
        "max_chars_per_request": row["max_chars_per_request"],
        "expires_at": row["expires_at"],
        "revoked_at": row["revoked_at"],
        "last_used_at": row["last_used_at"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _create_token_row(request: Request, payload: CreateAgentTokenRequest, actor: Actor) -> dict:
    if payload.role not in ROLE_VALUES:
        raise HTTPException(status_code=422, detail={"code": "agent_role_invalid", "message": "Invalid agent role", "details": {"role": payload.role}})
    scopes = _expand_scopes(payload.scopes)
    expires_at = _validate_expires_at(payload.expires_at)
    token_id = f"agent_{uuid4().hex[:12]}"
    raw_token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    now = utc_now()
    await execute(
        request.app.state.settings.sqlite_path,
        "INSERT INTO agent_tokens (id, token_hash, label, agent_name, agent_model, purpose, role, vault_id, scopes, "
        "max_pages_per_request, max_chars_per_request, expires_at, created_by, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            token_id,
            agent_token_hash(raw_token),
            payload.label,
            payload.agent_name,
            payload.agent_model,
            payload.purpose,
            payload.role,
            payload.vault_id,
            json.dumps(scopes, ensure_ascii=True),
            payload.max_pages_per_request,
            payload.max_chars_per_request,
            expires_at,
            actor.actor_id,
            now,
            now,
        ),
    )
    row = await fetch_one(request.app.state.settings.sqlite_path, "SELECT * FROM agent_tokens WHERE id = ?", (token_id,))
    await write_audit_event(
        request.app.state.settings.sqlite_path,
        action="agent_token.create",
        actor=actor,
        target_type="agent_token",
        target_id=token_id,
        metadata={"role": payload.role, "scopes": scopes},
    )
    return {**_public_token_row(row), "raw_token": raw_token}


@router.post("/tokens")
async def create_agent_token(payload: CreateAgentTokenRequest, request: Request, actor: Actor = Depends(require_admin_access)):
    token = await _create_token_row(request, payload, actor)
    return {"ok": True, "data": {"token": token}}


@router.get("/tokens")
async def list_agent_tokens(request: Request, actor: Actor = Depends(require_admin_access)):
    rows = await fetch_all(request.app.state.settings.sqlite_path, "SELECT * FROM agent_tokens ORDER BY created_at DESC", ())
    return {"ok": True, "data": {"tokens": [_public_token_row(row) for row in rows], "actor_role": actor.role}}


@router.post("/tokens/{token_id}/revoke")
async def revoke_agent_token(token_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    row = await fetch_one(request.app.state.settings.sqlite_path, "SELECT id, revoked_at FROM agent_tokens WHERE id = ?", (token_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "agent_token_not_found", "message": "Agent token not found", "details": {"token_id": token_id}})
    if row["revoked_at"]:
        return {"ok": True, "data": {"token_id": token_id, "revoked_at": row["revoked_at"], "already_revoked": True}}
    now = utc_now()
    await execute(request.app.state.settings.sqlite_path, "UPDATE agent_tokens SET revoked_at = ?, updated_at = ? WHERE id = ?", (now, now, token_id))
    await write_audit_event(request.app.state.settings.sqlite_path, action="agent_token.revoke", actor=actor, target_type="agent_token", target_id=token_id, metadata={})
    return {"ok": True, "data": {"token_id": token_id, "revoked_at": now}}


@router.post("/tokens/{token_id}/rotate")
async def rotate_agent_token(token_id: str, request: Request, actor: Actor = Depends(require_admin_access)):
    row = await fetch_one(request.app.state.settings.sqlite_path, "SELECT * FROM agent_tokens WHERE id = ?", (token_id,))
    if not row:
        raise HTTPException(status_code=404, detail={"code": "agent_token_not_found", "message": "Agent token not found", "details": {"token_id": token_id}})
    await revoke_agent_token(token_id, request, actor)
    payload = CreateAgentTokenRequest(
        label=row["label"],
        agent_name=row["agent_name"],
        agent_model=row["agent_model"],
        purpose=row["purpose"],
        role=row["role"],
        vault_id=row["vault_id"],
        scopes=json.loads(row["scopes"] or "[]"),
        max_pages_per_request=row["max_pages_per_request"],
        max_chars_per_request=row["max_chars_per_request"],
        expires_at=row["expires_at"],
    )
    token = await _create_token_row(request, payload, actor)
    await write_audit_event(request.app.state.settings.sqlite_path, action="agent_token.rotate", actor=actor, target_type="agent_token", target_id=token_id, metadata={"new_token_id": token["id"]})
    return {"ok": True, "data": {"old_token_id": token_id, "token": token}}


@router.get("/tokens/{token_id}/events")
async def list_agent_token_events(token_id: str, request: Request, limit: int = 50, actor: Actor = Depends(require_admin_access)):
    limit = min(max(limit, 1), 200)
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT id, token_id, vault_id, agent_name, action, target_type, target_id, request_id, status, meta, created_at "
        "FROM agent_access_events WHERE token_id = ? ORDER BY created_at DESC LIMIT ?",
        (token_id, limit),
    )
    events = []
    for row in rows:
        item = dict(row)
        try:
            item["meta"] = json.loads(item["meta"] or "{}")
        except json.JSONDecodeError:
            item["meta"] = {}
        events.append(item)
    return {"ok": True, "data": {"events": events, "actor_role": actor.role}}
