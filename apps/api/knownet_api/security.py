import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request

from .config import Settings, get_settings
from .db.sqlite import fetch_all, fetch_one


DEFAULT_VAULT_ID = "local-default"


@dataclass(frozen=True)
class Actor:
    actor_type: str
    actor_id: str
    session_id: str | None
    ip_hash: str | None
    user_agent_hash: str | None
    role: str = "viewer"
    vault_id: str = DEFAULT_VAULT_ID


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_value(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _client_host(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else None


def _is_loopback(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


def _extract_token(request: Request) -> str | None:
    header_token = request.headers.get("x-knownet-admin-token")
    if header_token:
        return header_token
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def requested_vault_id(request: Request) -> str:
    value = request.headers.get("x-knownet-vault") or DEFAULT_VAULT_ID
    valid = value and all(ch.isascii() and (ch.isalnum() or ch in {"-", "_"}) for ch in value)
    if not valid:
        raise HTTPException(status_code=400, detail={"code": "invalid_vault", "message": "Invalid vault id", "details": {}})
    return value


def _actor_from_request(request: Request, actor_type: str, role: str = "viewer", actor_id: str | None = None) -> Actor:
    host = _client_host(request)
    user_agent = request.headers.get("user-agent")
    session_id = request.headers.get("x-knownet-session")
    ip_hash = _hash_value(host)
    resolved_actor_id = actor_id or ("local" if _is_loopback(host) else ip_hash or "unknown")
    return Actor(
        actor_type=actor_type,
        actor_id=resolved_actor_id,
        session_id=session_id,
        ip_hash=ip_hash,
        user_agent_hash=_hash_value(user_agent),
        role=role,
        vault_id=requested_vault_id(request),
    )


def anonymous_actor(request: Request) -> Actor:
    host = _client_host(request)
    user_agent = request.headers.get("user-agent")
    ip_hash = _hash_value(host)
    return Actor(
        actor_type="anonymous",
        actor_id=ip_hash or "anonymous",
        session_id=request.headers.get("x-knownet-session"),
        ip_hash=ip_hash,
        user_agent_hash=_hash_value(user_agent),
        role="anonymous",
        vault_id=requested_vault_id(request),
    )


async def _actor_from_session(request: Request, settings: Settings, token: str) -> Actor | None:
    now = utc_now()
    vault_id = requested_vault_id(request)
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT s.id AS session_id, s.user_id, s.actor_type, s.expires_at, "
        "u.username, u.role AS user_role, "
        "vm.role AS vault_role "
        "FROM sessions s "
        "LEFT JOIN users u ON u.id = s.user_id "
        "LEFT JOIN vault_members vm ON vm.user_id = s.user_id AND vm.vault_id = ? "
        "WHERE s.id = ? AND s.expires_at > ?",
        (vault_id, token, now),
    )
    if not row:
        return None
    role = row["vault_role"] or (row["user_role"] if vault_id == DEFAULT_VAULT_ID else None)
    if not role:
        return None
    host = _client_host(request)
    user_agent = request.headers.get("user-agent")
    return Actor(
        actor_type=row["actor_type"],
        actor_id=row["user_id"] or row["session_id"],
        session_id=row["session_id"],
        ip_hash=_hash_value(host),
        user_agent_hash=_hash_value(user_agent),
        role=role,
        vault_id=vault_id,
    )


async def require_actor(request: Request, settings: Settings = Depends(get_settings)) -> Actor:
    host = _client_host(request)
    token = _extract_token(request)
    if settings.public_mode and settings.admin_token and len(settings.admin_token) < settings.admin_token_min_chars:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "security_misconfigured",
                "message": "ADMIN_TOKEN is too short for PUBLIC_MODE",
                "details": {"min_chars": settings.admin_token_min_chars},
            },
        )
    if settings.admin_token:
        if token and hmac.compare_digest(token, settings.admin_token):
            return _actor_from_request(request, "admin_token", role="owner", actor_id="admin-token")
        if token:
            actor = await _actor_from_session(request, settings, token)
            if actor:
                return actor
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Admin token required", "details": {}},
        )

    if token:
        actor = await _actor_from_session(request, settings, token)
        if actor:
            return actor

    if _is_loopback(host):
        return _actor_from_request(request, "local", role="owner")

    if settings.public_mode:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "security_misconfigured",
                "message": "PUBLIC_MODE requires ADMIN_TOKEN before writes are enabled",
                "details": {},
            },
        )

    raise HTTPException(
        status_code=403,
        detail={"code": "forbidden", "message": "Write access is local-only", "details": {}},
    )


async def require_write_access(actor: Actor = Depends(require_actor)) -> Actor:
    if actor.role not in {"owner", "admin", "editor"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Editor role required", "details": {"role": actor.role}},
        )
    return actor


async def require_message_actor(request: Request, settings: Settings = Depends(get_settings)) -> Actor:
    token = _extract_token(request)
    if token or not settings.public_mode:
        return await require_actor(request, settings)
    return anonymous_actor(request)


async def require_review_access(actor: Actor = Depends(require_actor)) -> Actor:
    if actor.role not in {"owner", "admin", "editor", "reviewer", "viewer"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Viewer role required", "details": {"role": actor.role}},
        )
    return actor


async def require_admin_access(actor: Actor = Depends(require_actor)) -> Actor:
    if actor.role not in {"owner", "admin"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Admin role required", "details": {"role": actor.role}},
        )
    return actor


def ensure_text_size(text: str, max_bytes: int, field_name: str) -> None:
    if len(text.encode("utf-8")) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "input_too_large",
                "message": f"{field_name} exceeds the configured size limit",
                "details": {"max_bytes": max_bytes},
            },
        )


def ensure_length(value: str, max_chars: int, field_name: str) -> None:
    if len(value) > max_chars:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "input_too_long",
                "message": f"{field_name} exceeds the configured length limit",
                "details": {"max_chars": max_chars},
            },
        )


async def enforce_write_rate_limit(request: Request, actor: Actor, settings: Settings) -> None:
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT COUNT(*) AS count FROM audit_log "
        "WHERE created_at >= ? AND (actor_id = ? OR ip_hash = ?) "
        "AND action IN ('message.created', 'suggestion.applied', 'revision.restored')",
        (since, actor.actor_id, actor.ip_hash),
    )
    count = rows[0]["count"] if rows else 0
    if count >= settings.write_requests_per_minute:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "rate_limited",
                "message": "Too many write requests",
                "details": {"limit_per_minute": settings.write_requests_per_minute},
            },
        )


async def enforce_job_limit(actor: Actor, settings: Settings) -> None:
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued', 'running', 'retry_scheduled')",
        (),
    )
    count = rows[0]["count"] if rows else 0
    if count >= settings.queued_jobs_per_actor:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "too_many_jobs",
                "message": "Too many queued or running jobs",
                "details": {"limit": settings.queued_jobs_per_actor},
            },
        )
