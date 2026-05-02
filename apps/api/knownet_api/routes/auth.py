import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db.sqlite import fetch_one
from ..security import Actor, require_actor, utc_now
from ..services.rust_core import RustCoreError

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_failures(request: Request) -> dict:
    if not hasattr(request.app.state, "auth_failures"):
        request.app.state.auth_failures = {}
    return request.app.state.auth_failures


def _auth_failure_key(request: Request, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    host_hash = hashlib.sha256(host.encode("utf-8")).hexdigest()[:24]
    username_hash = hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()[:24]
    return f"{host_hash}:{username_hash}"


def _check_auth_lockout(request: Request, username: str) -> None:
    settings = request.app.state.settings
    entry = _auth_failures(request).get(_auth_failure_key(request, username))
    now = datetime.now(timezone.utc).timestamp()
    if entry and entry.get("locked_until", 0) > now:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "auth_rate_limited",
                "message": "Too many failed login attempts",
                "details": {"retry_after_seconds": int(entry["locked_until"] - now)},
            },
        )


def _record_auth_failure(request: Request, username: str) -> None:
    settings = request.app.state.settings
    key = _auth_failure_key(request, username)
    failures = _auth_failures(request)
    now = datetime.now(timezone.utc).timestamp()
    entry = failures.get(key, {"count": 0, "locked_until": 0})
    count = int(entry.get("count", 0)) + 1
    locked_until = now + settings.auth_lockout_seconds if count >= settings.auth_max_failed_attempts else 0
    failures[key] = {"count": count, "locked_until": locked_until}


def _clear_auth_failures(request: Request, username: str) -> None:
    _auth_failures(request).pop(_auth_failure_key(request, username), None)


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return "pbkdf2_sha256$120000${}${}".format(
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _session_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=14)).isoformat().replace("+00:00", "Z")


async def _create_session(request: Request, user_id: str) -> dict:
    rust = request.app.state.rust_core
    if not rust.available:
        raise HTTPException(status_code=503, detail={"code": "daemon_unavailable", "message": "Rust daemon is unavailable", "details": {}})
    settings = request.app.state.settings
    session_id = f"sess_{secrets.token_urlsafe(32).replace('-', '_').replace('~', '_')}"
    created_at = utc_now()
    expires_at = _session_expiry()
    session_meta = json.dumps(
        {
            "ip_hash": hashlib.sha256((request.client.host if request.client else "unknown").encode("utf-8")).hexdigest()[:24],
            "user_agent_hash": hashlib.sha256((request.headers.get("user-agent") or "").encode("utf-8")).hexdigest()[:24],
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    await rust.request(
        "create_session",
        {
            "sqlite_path": str(settings.sqlite_path),
            "session_id": session_id,
            "user_id": user_id,
            "actor_type": "user",
            "session_meta": session_meta,
            "expires_at": expires_at,
            "created_at": created_at,
        },
    )
    return {"session_id": session_id, "expires_at": expires_at}


@router.post("/bootstrap")
async def bootstrap(payload: BootstrapRequest, request: Request):
    settings = request.app.state.settings
    existing = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM users", ())
    if existing and existing["count"] > 0:
        raise HTTPException(status_code=409, detail={"code": "bootstrap_closed", "message": "A user already exists", "details": {}})
    rust = request.app.state.rust_core
    if not rust.available:
        raise HTTPException(status_code=503, detail={"code": "daemon_unavailable", "message": "Rust daemon is unavailable", "details": {}})
    user_id = f"user_{uuid4().hex[:12]}"
    now = utc_now()
    try:
        await rust.request(
            "create_user",
            {
                "sqlite_path": str(settings.sqlite_path),
                "user_id": user_id,
                "username": payload.username.strip(),
                "password_hash": _hash_password(payload.password),
                "role": "owner",
                "created_at": now,
            },
        )
        session = await _create_session(request, user_id)
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": {"user_id": user_id, "username": payload.username.strip(), "role": "owner", **session}}


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    settings = request.app.state.settings
    _check_auth_lockout(request, payload.username)
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, username, password_hash, role FROM users WHERE username = ?",
        (payload.username.strip(),),
    )
    if not row or not _verify_password(payload.password, row["password_hash"]):
        _record_auth_failure(request, payload.username)
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "Invalid username or password", "details": {}})
    _clear_auth_failures(request, payload.username)
    try:
        session = await _create_session(request, row["id"])
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": {"user_id": row["id"], "username": row["username"], "role": row["role"], **session}}


@router.post("/logout")
async def logout(request: Request, actor: Actor = Depends(require_actor)):
    if not actor.session_id:
        return {"ok": True, "data": {"status": "noop"}}
    try:
        await request.app.state.rust_core.request(
            "revoke_session",
            {"sqlite_path": str(request.app.state.settings.sqlite_path), "session_id": actor.session_id},
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": {"status": "revoked"}}


@router.get("/me")
async def me(actor: Actor = Depends(require_actor)):
    return {
        "ok": True,
        "data": {
            "actor_type": actor.actor_type,
            "actor_id": actor.actor_id,
            "session_id": actor.session_id,
            "role": actor.role,
            "vault_id": actor.vault_id,
        },
    }
