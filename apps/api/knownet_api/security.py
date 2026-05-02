import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json

from fastapi import Depends, HTTPException, Request

from .config import Settings, get_settings
from .db.sqlite import execute, fetch_all, fetch_one


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


@dataclass(frozen=True)
class AgentAuth:
    token_id: str
    label: str
    agent_name: str
    agent_model: str | None
    purpose: str
    role: str
    vault_id: str
    scopes: list[str]
    max_pages_per_request: int
    max_chars_per_request: int
    expires_at: str | None
    expires_in_seconds: int | None
    actor: Actor


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


def _extract_agent_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token.startswith("kn_agent_"):
            return token
    return None


def agent_token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


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


async def record_agent_access(
    sqlite_path,
    *,
    agent: AgentAuth | None,
    action: str,
    status: str,
    target_type: str | None = None,
    target_id: str | None = None,
    request_id: str | None = None,
    meta: dict | None = None,
) -> None:
    metadata = dict(meta or {})
    for forbidden in ("raw_token", "token_hash", "content", "body", "password", "secret"):
        metadata.pop(forbidden, None)
    await execute(
        sqlite_path,
        "INSERT INTO agent_access_events (token_id, vault_id, agent_name, action, target_type, target_id, request_id, status, meta, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            agent.token_id if agent else None,
            agent.vault_id if agent else DEFAULT_VAULT_ID,
            agent.agent_name if agent else None,
            action,
            target_type,
            target_id,
            request_id,
            status,
            json.dumps(metadata, ensure_ascii=True, sort_keys=True),
            utc_now(),
        ),
    )


def _expires_in_seconds(expires_at: str | None) -> int | None:
    if not expires_at:
        return None
    try:
        expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((expires - datetime.now(timezone.utc)).total_seconds()))


async def authenticate_agent_token(request: Request, settings: Settings | None = None) -> AgentAuth:
    settings = settings or get_settings()
    raw_token = _extract_agent_token(request)
    if not raw_token:
        raise HTTPException(status_code=401, detail={"code": "agent_token_required", "message": "Agent token required", "details": {}})
    now = utc_now()
    row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, label, agent_name, agent_model, purpose, role, vault_id, scopes, max_pages_per_request, "
        "max_chars_per_request, expires_at, revoked_at FROM agent_tokens WHERE token_hash = ?",
        (agent_token_hash(raw_token),),
    )
    if not row or row["revoked_at"] or (row["expires_at"] and row["expires_at"] <= now):
        await record_agent_access(settings.sqlite_path, agent=None, action="agent.auth", status="denied", meta={"reason": "invalid_or_expired"})
        raise HTTPException(status_code=401, detail={"code": "agent_token_invalid", "message": "Invalid, expired, or revoked agent token", "details": {}})
    try:
        scopes = json.loads(row["scopes"] or "[]")
    except json.JSONDecodeError:
        scopes = []
    if not isinstance(scopes, list):
        scopes = []
    host = _client_host(request)
    actor = Actor(
        actor_type="ai",
        actor_id=row["id"],
        session_id=None,
        ip_hash=_hash_value(host),
        user_agent_hash=_hash_value(request.headers.get("user-agent")),
        role=row["role"],
        vault_id=row["vault_id"],
    )
    await execute(settings.sqlite_path, "UPDATE agent_tokens SET last_used_at = ?, updated_at = ? WHERE id = ?", (now, now, row["id"]))
    agent = AgentAuth(
        token_id=row["id"],
        label=row["label"],
        agent_name=row["agent_name"],
        agent_model=row["agent_model"],
        purpose=row["purpose"],
        role=row["role"],
        vault_id=row["vault_id"],
        scopes=[str(scope) for scope in scopes],
        max_pages_per_request=int(row["max_pages_per_request"] or 20),
        max_chars_per_request=int(row["max_chars_per_request"] or 60000),
        expires_at=row["expires_at"],
        expires_in_seconds=_expires_in_seconds(row["expires_at"]),
        actor=actor,
    )
    since = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    count_row = await fetch_one(
        settings.sqlite_path,
        "SELECT COUNT(*) AS count FROM agent_access_events WHERE token_id = ? AND created_at >= ?",
        (agent.token_id, since),
    )
    if count_row and count_row["count"] >= 60:
        await record_agent_access(settings.sqlite_path, agent=agent, action="agent.rate_limit", status="rate_limited", meta={"limit_per_minute": 60})
        raise HTTPException(
            status_code=429,
            detail={"code": "agent_rate_limited", "message": "Too many agent requests", "details": {"retry_after_seconds": 60}},
        )
    if agent.expires_in_seconds is not None:
        request.state.agent_expires_in_seconds = agent.expires_in_seconds
    request.state.agent_token_warning = "no_expiry" if agent.expires_at is None else None
    return agent


async def require_agent(request: Request, settings: Settings = Depends(get_settings)) -> AgentAuth:
    return await authenticate_agent_token(request, settings)


def agent_has_scope(agent: AgentAuth, scope: str) -> bool:
    if scope in agent.scopes:
        return True
    if scope.startswith("pages:read:slug:") and scope in agent.scopes:
        return True
    return False


async def require_agent_scope(request: Request, scope: str, settings: Settings | None = None) -> AgentAuth:
    settings = settings or get_settings()
    agent = await authenticate_agent_token(request, settings)
    if scope not in agent.scopes:
        await record_agent_access(settings.sqlite_path, agent=agent, action=f"scope.{scope}", status="denied", meta={"scope": scope})
        raise HTTPException(status_code=403, detail={"code": "agent_scope_forbidden", "message": "Agent scope does not allow this operation", "details": {"scope": scope}})
    return agent
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
    if _extract_agent_token(request):
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": "Agent tokens cannot use this endpoint", "details": {}},
        )
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
    if _extract_agent_token(request):
        agent = await require_agent_scope(request, "messages:create", settings)
        if agent.role != "agent_contributor":
            raise HTTPException(status_code=403, detail={"code": "agent_role_forbidden", "message": "agent_contributor role required", "details": {"role": agent.role}})
        return agent.actor
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
