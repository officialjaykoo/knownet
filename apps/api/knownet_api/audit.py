import json
from typing import Any

from .db.sqlite import execute
from .security import Actor, utc_now


SYSTEM_ACTOR = Actor(
    actor_type="system",
    actor_id="system",
    session_id=None,
    ip_hash=None,
    user_agent_hash=None,
)


AI_ACTOR = Actor(
    actor_type="ai",
    actor_id="mock-draft-service",
    session_id=None,
    ip_hash=None,
    user_agent_hash=None,
)


async def write_audit_event(
    sqlite_path,
    *,
    action: str,
    actor: Actor,
    target_type: str | None = None,
    target_id: str | None = None,
    before_revision_id: str | None = None,
    after_revision_id: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = utc_now()
    meta = dict(metadata or {})
    if before_revision_id:
        meta["before_revision_id"] = before_revision_id
    if after_revision_id:
        meta["after_revision_id"] = after_revision_id
    if model_provider:
        meta["model_provider"] = model_provider
    if model_name:
        meta["model_name"] = model_name
    if model_version:
        meta["model_version"] = model_version
    if prompt_version:
        meta["prompt_version"] = prompt_version
    if actor.session_id:
        meta["session_id"] = actor.session_id
    if actor.ip_hash:
        meta["ip_hash"] = actor.ip_hash
    if actor.user_agent_hash:
        meta["user_agent_hash"] = actor.user_agent_hash

    await execute(
        sqlite_path,
        "INSERT INTO audit_events (vault_id, actor_type, actor_id, action, target_type, target_id, request_id, meta, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            getattr(actor, "vault_id", None) or "local-default",
            actor.actor_type,
            actor.actor_id or "unknown",
            action,
            target_type,
            target_id,
            None,
            json.dumps(meta, ensure_ascii=True, sort_keys=True),
            now,
        ),
    )
