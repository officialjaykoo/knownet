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
    await execute(
        sqlite_path,
        "INSERT INTO audit_log ("
        "created_at, action, actor_type, actor_id, session_id, ip_hash, user_agent_hash, "
        "target_type, target_id, before_revision_id, after_revision_id, "
        "model_provider, model_name, model_version, prompt_version, metadata_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            utc_now(),
            action,
            actor.actor_type,
            actor.actor_id,
            actor.session_id,
            actor.ip_hash,
            actor.user_agent_hash,
            target_type,
            target_id,
            before_revision_id,
            after_revision_id,
            model_provider,
            model_name,
            model_version,
            prompt_version,
            json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True),
        ),
    )
