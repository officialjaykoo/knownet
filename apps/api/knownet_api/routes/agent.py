import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from ..db.sqlite import fetch_all, fetch_one
from ..security import AgentAuth, record_agent_access, require_agent
from ..services.system_pages import ONBOARDING_START_PAGES, system_fields


router = APIRouter(prefix="/api/agent", tags=["agent"])


ONBOARDING_FORBIDDEN_ACTIONS = [
    {
        "action": "request_database_file",
        "reason": "security_boundary",
        "description": "Do not request database files, backup archives, sessions, users, or secrets.",
    },
    {
        "action": "assume_filesystem_access",
        "reason": "agent_api_boundary",
        "description": "Do not assume direct local filesystem access outside the scoped API.",
    },
    {
        "action": "submit_without_dry_run",
        "reason": "review_quality",
        "description": "Do not submit reviews without dry-run when an MCP or SDK helper is available.",
    },
    {
        "action": "echo_raw_token",
        "reason": "secret_safety",
        "description": "Do not ask for raw tokens or include token values in reviews, logs, or pages.",
    },
    {
        "action": "recommend_broad_expansion_first",
        "reason": "scope_control",
        "description": "Do not recommend broad feature expansion before checking current priorities.",
    },
]

ONBOARDING_REVIEW_WORKFLOW = [
    {"step": "inspect_token", "endpoint": "GET /api/agent/me", "purpose": "Inspect role, scopes, limits, expiry warnings, and start-here status."},
    {"step": "read_onboarding", "endpoint": "GET /api/agent/onboarding", "purpose": "Read the external-agent workflow contract and recommended start pages."},
    {"step": "read_state_summary", "endpoint": "GET /api/agent/state-summary", "purpose": "Check project counts, graph shape, and collaboration readiness."},
    {"step": "read_structured_state", "endpoint": "GET /api/agent/ai-state", "purpose": "Read compact page state without local paths or secrets."},
    {"step": "read_needed_pages", "endpoint": "GET /api/agent/pages/{page_id}", "purpose": "Read only the pages needed for the review focus."},
    {"step": "draft_findings", "endpoint": "local", "purpose": "Draft findings in the fixed Finding format."},
    {"step": "dry_run", "endpoint": "POST /api/collaboration/reviews?dry_run=true", "purpose": "Inspect parser output before durable import."},
    {"step": "submit_review", "endpoint": "POST /api/collaboration/reviews", "purpose": "Submit the real review only after dry-run is acceptable."},
]

ONBOARDING_PRIORITIES = [
    "Improve quality, tests, and reliability of existing behavior before adding features.",
    "Find API contract inconsistencies and unclear scope errors.",
    "Find UI behavior that confuses operators or hides safety state.",
    "Find slow loading paths with measured evidence.",
    "Find documentation gaps that block another AI from safe contribution.",
]

ONBOARDING_HANDOFF_FORMAT = {
    "heading": "### Finding",
    "required_fields": ["Title", "Severity", "Area", "Evidence", "Proposed change"],
    "severity_values": ["critical", "high", "medium", "low", "info"],
    "area_values": ["API", "UI", "Rust", "Security", "Data", "Ops", "Docs"],
    "example_valid_finding": "### Finding\n\nTitle: State summary lacks current focus\nSeverity: medium\nArea: API\n\nEvidence:\nGET /api/agent/state-summary did not include current_focus.\n\nProposed change:\nAdd current_focus to first_agent_brief.",
    "example_invalid_finding": "Looks good but maybe improve docs.",
}

CONFLICT_RESOLUTION_POLICY = {
    "canonical_state": "SQLite structured records and generated ai_state are the canonical AI collaboration state.",
    "narrative_sources": "Markdown pages are durable narrative source attachments and should be read through the scoped API.",
    "on_conflict": "If page content, ai_state, and graph/citation indexes disagree, treat it as index drift. Do not guess; request or run verify-index/rebuild through an operator-controlled path.",
    "external_agent_rule": "External agents should report drift as findings. They must not request database files or direct filesystem access.",
}

SECURITY_BOUNDARY_POLICY = {
    "raw_tokens": "Raw agent tokens are shown once by the operator dashboard and are never returned by agent read APIs, MCP tools, resource previews, or event APIs.",
    "forbidden_data": ["database files", "backup archives", "session rows", "user rows", "token hashes", "raw tokens", "local filesystem paths"],
    "write_boundary": "External agents submit reviews and findings through scoped APIs. They do not receive raw filesystem write tools or admin maintenance tools.",
    "get_preview_boundary": "GET previews expose safe onboarding and state-summary context only. Review dry-run and submit remain JSON-RPC POST operations.",
}

INFRASTRUCTURE_NOTICE = {
    "tunnel_type": "temporary_quick_tunnel",
    "production_ready": False,
    "recommended_use": "testing_only",
    "operator_note": "Quick tunnels are for external AI review experiments. Use a named tunnel with access controls before operational use.",
}

ACTION_HINTS = [
    {
        "action": "read_pages",
        "required_scope": "pages:read",
        "endpoint": "GET /api/agent/pages",
        "description": "List and read scoped pages.",
    },
    {
        "action": "read_structured_state",
        "required_scope": "pages:read",
        "endpoint": "GET /api/agent/ai-state",
        "description": "Read compact structured AI state.",
    },
    {
        "action": "read_reviews",
        "required_scope": "reviews:read",
        "endpoint": "GET /api/agent/reviews",
        "description": "Read collaboration reviews.",
    },
    {
        "action": "submit_review",
        "required_scope": "reviews:create",
        "endpoint": "POST /api/collaboration/reviews",
        "description": "Submit a collaboration review after dry-run.",
    },
    {
        "action": "create_message",
        "required_scope": "messages:create",
        "endpoint": "POST /api/messages",
        "description": "Create an input message for normal processing.",
    },
]


def _action_hints(agent: AgentAuth) -> tuple[list[dict], list[dict]]:
    scopes = set(agent.scopes)
    allowed = []
    unavailable = []
    for item in ACTION_HINTS:
        if item["required_scope"] in scopes:
            allowed.append(item)
        else:
            unavailable.append({**item, "reason": "missing_scope"})
    return allowed, unavailable


def _token_warning(agent: AgentAuth) -> str | None:
    if agent.expires_at is None:
        return "no_expiry"
    if agent.expires_in_seconds is not None and agent.expires_in_seconds <= 7 * 24 * 60 * 60:
        return "expires_soon"
    return None


def _token_management(agent: AgentAuth) -> dict | None:
    warning = _token_warning(agent)
    if not warning:
        return None
    operator_action = "Ask the operator to rotate or create a new agent token from the Agent Dashboard."
    if warning == "no_expiry":
        operator_action = "Ask the operator to rotate this token with an explicit expiry from the Agent Dashboard."
    return {
        "warning": warning,
        "expires_at": agent.expires_at,
        "expires_in_seconds": agent.expires_in_seconds,
        "operator_alert_available": False,
        "escalation_endpoint": None,
        "operator_action": operator_action,
        "dashboard_hint": "Open User Panel -> Agent Dashboard.",
        "agent_rule": "Do not ask for raw token values. Ask the operator to rotate or create a new token.",
    }


def _sanitize_ai_state(state: dict) -> tuple[dict, str]:
    sanitized = json.loads(json.dumps(state))
    source = sanitized.get("source")
    if isinstance(source, dict):
        source.pop("path", None)
    headings = {
        str(section.get("heading", "")).strip().lower()
        for section in sanitized.get("sections", [])
        if isinstance(section, dict)
    }
    draft_markers = {"question", "claims", "evidence", "next actions", "related pages"}
    state_status = "draft" if len(headings.intersection(draft_markers)) >= 3 else "published"
    sanitized["state_status"] = state_status
    sanitized["source_ref"] = f"pages/{sanitized.get('slug', 'unknown')}.md"
    return sanitized, state_status


async def _recommended_start_pages(request: Request, vault_id: str) -> list[dict]:
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT p.id, p.slug, p.title, p.updated_at, sp.kind AS system_kind, sp.tier AS system_tier, sp.locked AS system_locked "
        "FROM pages p LEFT JOIN system_pages sp ON sp.page_id = p.id "
        "WHERE p.vault_id = ? AND p.status = 'active' AND p.slug IN ({})".format(
            ",".join("?" for _ in ONBOARDING_START_PAGES)
        ),
        (vault_id, *(item["slug"] for item in ONBOARDING_START_PAGES)),
    )
    by_slug = {row["slug"]: row for row in rows}
    result = []
    for item in ONBOARDING_START_PAGES:
        row = by_slug.get(item["slug"])
        result.append(
            {
                **item,
                "available": bool(row),
                "page_id": row["id"] if row else None,
                "updated_at": row["updated_at"] if row else None,
                **system_fields(row),
            }
        )
    return result


async def _start_here_status(request: Request, agent: AgentAuth) -> dict:
    row = await fetch_one(
        request.app.state.settings.sqlite_path,
        "SELECT COUNT(*) AS count, MAX(created_at) AS last_seen_at FROM agent_access_events WHERE token_id = ? AND action = 'agent.onboarding'",
        (agent.token_id,),
    )
    seen_count = int(row["count"] or 0) if row else 0
    return {
        "hint": "recommended" if seen_count == 0 else "available",
        "seen_count": seen_count,
        "last_seen_at": row["last_seen_at"] if row else None,
        "scope": "token_local",
        "hint_reason": "no_recent_start_seen" if seen_count == 0 else "recent_start_seen",
    }


async def _onboarding_payload(request: Request, agent: AgentAuth) -> dict:
    status = await _start_here_status(request, agent)
    allowed_actions, unavailable_actions = _action_hints(agent)
    return {
        "purpose": "/api/agent/onboarding is the external-agent workflow contract. /api/agent/me is only the current token status snapshot.",
        "start_here_hint": status["hint"],
        "start_here_hint_legend": {
            "recommended": "The token has not recently called onboarding. Read the start pages first.",
            "available": "The token recently called onboarding. Start pages remain available as reference.",
        },
        "start_here_status": status,
        "recommended_start_pages": await _recommended_start_pages(request, agent.vault_id),
        "allowed_actions": allowed_actions,
        "unavailable_actions": unavailable_actions,
        "forbidden_actions": ONBOARDING_FORBIDDEN_ACTIONS,
        "review_workflow": ONBOARDING_REVIEW_WORKFLOW,
        "current_priorities": ONBOARDING_PRIORITIES,
        "token_management": _token_management(agent),
        "handoff_format": ONBOARDING_HANDOFF_FORMAT,
        "conflict_resolution_policy": CONFLICT_RESOLUTION_POLICY,
        "security_boundary_policy": SECURITY_BOUNDARY_POLICY,
        "infrastructure_notice": INFRASTRUCTURE_NOTICE,
        "entrypoints": {
            "api": "/api/agent/onboarding",
            "mcp_tool": "knownet_start_here",
            "mcp_resource": "knownet://agent/onboarding",
            "sdk_method": "client.start_here()",
        },
        "setup_docs": {
            "mcp": "docs/MCP_CLIENTS.md",
            "sdk": "docs/SDK_CLIENTS.md",
        },
    }


def _meta(agent: AgentAuth, *, total: int, returned: int, truncated: bool, offset: int = 0) -> dict:
    has_more = bool(truncated or total > offset + returned)
    meta = {
        "schema_version": 1,
        "vault_id": agent.vault_id,
        "agent_scope": agent.scopes,
        "truncated": truncated,
        "has_more": has_more,
        "total_count": total,
        "returned_count": returned,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if has_more:
        meta["next_offset"] = offset + returned
    return meta


def _require_scope(agent: AgentAuth, scope: str, *, slug: str | None = None) -> None:
    if slug and f"{scope}:slug:{slug}" in agent.scopes:
        return
    if scope not in agent.scopes:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "agent_scope_forbidden",
                "message": "Agent scope does not allow this operation",
                "details": {"required_scope": scope, "current_scopes": agent.scopes},
            },
        )


@router.get("/ping")
async def agent_ping():
    return {"ok": True, "version": "9.0"}


@router.get("/me")
async def agent_me(request: Request, agent: AgentAuth = Depends(require_agent)):
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.me", status="ok")
    recommended_start_pages = await _recommended_start_pages(request, agent.vault_id)
    start_here_status = await _start_here_status(request, agent)
    return {
        "ok": True,
        "data": {
            "token_id": agent.token_id,
            "label": agent.label,
            "agent_name": agent.agent_name,
            "agent_model": agent.agent_model,
            "model_label_note": "agent_model is the token creation label and may not reflect the actual calling model. Review submissions should set source_model for the actual model.",
            "purpose": agent.purpose,
            "role": agent.role,
            "vault_id": agent.vault_id,
            "scopes": agent.scopes,
            "scope_presets": [],
            "max_pages_per_request": agent.max_pages_per_request,
            "max_chars_per_request": agent.max_chars_per_request,
            "rate_limit": {"read_requests_per_minute": 60, "write_requests_per_minute": 10},
            "expires_at": agent.expires_at,
            "expires_in_seconds": agent.expires_in_seconds,
            "token_warning": _token_warning(agent),
            "token_management": _token_management(agent),
            "start_here_hint": start_here_status["hint"],
            "start_here_status": start_here_status,
            "recommended_start_pages": recommended_start_pages,
            "onboarding_endpoint": "/api/agent/onboarding",
        },
    }


@router.get("/onboarding")
async def agent_onboarding(request: Request, agent: AgentAuth = Depends(require_agent)):
    payload = await _onboarding_payload(request, agent)
    await record_agent_access(
        request.app.state.settings.sqlite_path,
        agent=agent,
        action="agent.onboarding",
        status="ok",
        meta={"recommended_pages": len(payload["recommended_start_pages"])},
    )
    return {"ok": True, "data": payload, "meta": _meta(agent, total=1, returned=1, truncated=False)}


@router.get("/pages")
async def agent_pages(request: Request, limit: int = 20, offset: int = 0, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "pages:read")
    limit = min(max(limit, 1), agent.max_pages_per_request)
    offset = max(offset, 0)
    total = await fetch_one(request.app.state.settings.sqlite_path, "SELECT COUNT(*) AS count FROM pages WHERE vault_id = ? AND status = 'active'", (agent.vault_id,))
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT p.id, p.slug, p.title, p.updated_at, sp.kind AS system_kind, sp.tier AS system_tier, sp.locked AS system_locked "
        "FROM pages p LEFT JOIN system_pages sp ON sp.page_id = p.id "
        "WHERE p.vault_id = ? AND p.status = 'active' ORDER BY p.updated_at DESC LIMIT ? OFFSET ?",
        (agent.vault_id, limit, offset),
    )
    truncated = bool(total and total["count"] > offset + len(rows))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.pages", status="ok", meta={"returned_count": len(rows), "truncated": truncated})
    pages = [{**row, **system_fields(row)} for row in rows]
    return {"ok": True, "data": {"pages": pages}, "meta": _meta(agent, total=total["count"] if total else 0, returned=len(rows), truncated=truncated, offset=offset)}


@router.get("/pages/{page_id}")
async def agent_page(page_id: str, request: Request, agent: AgentAuth = Depends(require_agent)):
    row = await fetch_one(
        request.app.state.settings.sqlite_path,
        "SELECT p.id, p.slug, p.title, p.path, p.updated_at, sp.kind AS system_kind, sp.tier AS system_tier, sp.locked AS system_locked "
        "FROM pages p LEFT JOIN system_pages sp ON sp.page_id = p.id "
        "WHERE p.id = ? AND p.vault_id = ? AND p.status = 'active'",
        (page_id, agent.vault_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Page not found", "details": {"page_id": page_id}})
    _require_scope(agent, "pages:read", slug=row["slug"])
    path_text = str(row["path"]).replace("\\", "/")
    if any(part in path_text.lower() for part in (".env", ".db", "backups/", "inbox/")):
        raise HTTPException(status_code=403, detail={"code": "agent_forbidden_data", "message": "Forbidden page path", "details": {"page_id": page_id}})
    content = request.app.state.settings.data_dir.joinpath("pages", f"{row['slug']}.md").read_text(encoding="utf-8")
    truncated = False
    if len(content) > agent.max_chars_per_request:
        content = content[: agent.max_chars_per_request]
        truncated = True
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.page", status="ok", target_type="page", target_id=page_id, meta={"truncated": truncated})
    page = {"id": row["id"], "slug": row["slug"], "title": row["title"], "updated_at": row["updated_at"], "content": content, **system_fields(row)}
    meta = _meta(agent, total=1, returned=1, truncated=False)
    meta["content_truncated"] = truncated
    return {"ok": True, "data": {"page": page}, "meta": meta}


@router.get("/reviews")
async def agent_reviews(request: Request, limit: int = 50, offset: int = 0, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "reviews:read")
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    total = await fetch_one(request.app.state.settings.sqlite_path, "SELECT COUNT(*) AS count FROM collaboration_reviews WHERE vault_id = ?", (agent.vault_id,))
    rows = await fetch_all(request.app.state.settings.sqlite_path, "SELECT id, title, source_agent, source_model, status, page_id, created_at, updated_at FROM collaboration_reviews WHERE vault_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?", (agent.vault_id, limit, offset))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.reviews", status="ok", meta={"returned_count": len(rows)})
    count = total["count"] if total else 0
    return {"ok": True, "data": {"reviews": rows}, "meta": _meta(agent, total=count, returned=len(rows), truncated=count > offset + len(rows), offset=offset)}


@router.get("/findings")
async def agent_findings(request: Request, limit: int = 100, offset: int = 0, status: str | None = None, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "findings:read")
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    filters = "WHERE r.vault_id = ?"
    params: list[object] = [agent.vault_id]
    if status:
        filters += " AND f.status = ?"
        params.append(status)
    total = await fetch_one(
        request.app.state.settings.sqlite_path,
        "SELECT COUNT(*) AS count FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id " + filters,
        tuple(params),
    )
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT f.id, f.review_id, f.severity, f.area, f.title, f.status, f.created_at, f.updated_at "
        "FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id "
        + filters
        + " ORDER BY f.updated_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.findings", status="ok", meta={"returned_count": len(rows)})
    count = total["count"] if total else 0
    return {"ok": True, "data": {"findings": rows}, "meta": _meta(agent, total=count, returned=len(rows), truncated=count > offset + len(rows), offset=offset)}


@router.get("/graph")
async def agent_graph(request: Request, limit: int = 200, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "graph:read")
    limit = min(max(limit, 1), 500)
    nodes = await fetch_all(request.app.state.settings.sqlite_path, "SELECT id, node_type, label, target_type, target_id, status, weight, meta FROM graph_nodes WHERE vault_id = ? ORDER BY weight DESC LIMIT ?", (agent.vault_id, limit))
    node_ids = [row["id"] for row in nodes]
    edges = []
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        edges = await fetch_all(request.app.state.settings.sqlite_path, f"SELECT id, edge_type, from_node_id, to_node_id, weight, status, meta FROM graph_edges WHERE vault_id = ? AND from_node_id IN ({placeholders})", (agent.vault_id, *node_ids))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.graph", status="ok", meta={"nodes": len(nodes), "edges": len(edges)})
    return {"ok": True, "data": {"nodes": nodes, "edges": edges}, "meta": _meta(agent, total=len(nodes), returned=len(nodes), truncated=False)}


@router.get("/citations")
async def agent_citations(request: Request, limit: int = 100, offset: int = 0, status: str | None = None, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "citations:read")
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    filters = "WHERE vault_id = ?"
    params: list[object] = [agent.vault_id]
    if status:
        filters += " AND status = ?"
        params.append(status)
    total = await fetch_one(request.app.state.settings.sqlite_path, "SELECT COUNT(*) AS count FROM citation_audits " + filters, tuple(params))
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT ca.id, ca.page_id, ca.citation_key, COALESCE(cd.display_title, ca.citation_key) AS display_title, "
        "ca.status, ca.verifier_type, ca.confidence, ca.reason, ca.updated_at "
        "FROM citation_audits ca "
        "LEFT JOIN (SELECT citation_key, MAX(display_title) AS display_title FROM citations GROUP BY citation_key) cd ON cd.citation_key = ca.citation_key "
        + filters.replace("vault_id", "ca.vault_id")
        + " ORDER BY ca.updated_at DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    )
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.citations", status="ok", meta={"returned_count": len(rows)})
    count = total["count"] if total else 0
    return {"ok": True, "data": {"citations": rows}, "meta": _meta(agent, total=count, returned=len(rows), truncated=count > offset + len(rows), offset=offset)}


@router.get("/context")
async def agent_context(request: Request, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "pages:read")
    pages = await fetch_all(request.app.state.settings.sqlite_path, "SELECT id, slug, title, updated_at FROM pages WHERE vault_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT ?", (agent.vault_id, agent.max_pages_per_request))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.context", status="ok", meta={"returned_count": len(pages)})
    return {"ok": True, "data": {"pages": pages}, "meta": _meta(agent, total=len(pages), returned=len(pages), truncated=False)}


@router.get("/ai-state")
async def agent_ai_state(request: Request, limit: int = 50, offset: int = 0, include_drafts: bool = False, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "pages:read")
    limit = min(max(limit, 1), agent.max_pages_per_request)
    offset = max(offset, 0)
    total = await fetch_one(request.app.state.settings.sqlite_path, "SELECT COUNT(*) AS count FROM ai_state_pages WHERE vault_id = ?", (agent.vault_id,))
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT page_id, slug, title, source_path, content_hash, state_json, updated_at "
        "FROM ai_state_pages WHERE vault_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (agent.vault_id, limit, offset),
    )
    states = []
    skipped_drafts = 0
    for row in rows:
        try:
            state = json.loads(row["state_json"] or "{}")
        except json.JSONDecodeError:
            state = {}
        state, state_status = _sanitize_ai_state(state)
        if state_status == "draft" and not include_drafts:
            skipped_drafts += 1
            continue
        states.append(
            {
                "page_id": row["page_id"],
                "slug": row["slug"],
                "title": row["title"],
                "source_ref": f"pages/{row['slug']}.md",
                "content_hash": row["content_hash"],
                "state_status": state_status,
                "state": state,
                "updated_at": row["updated_at"],
            }
        )
    count = total["count"] if total else 0
    truncated = count > offset + len(rows)
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.ai_state", status="ok", meta={"returned_count": len(states), "skipped_drafts": skipped_drafts, "truncated": truncated})
    meta = _meta(agent, total=count, returned=len(states), truncated=truncated, offset=offset)
    if truncated:
        meta["next_offset"] = offset + len(rows)
    meta["skipped_drafts"] = skipped_drafts
    meta["include_drafts"] = include_drafts
    if rows and not states and skipped_drafts:
        meta["no_published_in_range"] = True
        meta["warning"] = "page_range_contains_only_drafts_use_next_offset"
    return {"ok": True, "data": {"ai_state_pages": states}, "meta": meta}


@router.get("/state-summary")
async def agent_state_summary(request: Request, agent: AgentAuth = Depends(require_agent)):
    summary = {}
    for name, query in {
        "pages": "SELECT COUNT(*) AS count FROM pages WHERE vault_id = ? AND status = 'active'",
        "ai_state_pages": "SELECT COUNT(*) AS count FROM ai_state_pages WHERE vault_id = ?",
        "reviews": "SELECT COUNT(*) AS count FROM collaboration_reviews WHERE vault_id = ?",
        "findings": "SELECT COUNT(*) AS count FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ?",
        "graph_nodes": "SELECT COUNT(*) AS count FROM graph_nodes WHERE vault_id = ?",
    }.items():
        row = await fetch_one(request.app.state.settings.sqlite_path, query, (agent.vault_id,))
        summary[name] = row["count"] if row else 0
    graph_breakdown_rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT node_type, COUNT(*) AS count FROM graph_nodes WHERE vault_id = ? GROUP BY node_type",
        (agent.vault_id,),
    )
    graph_node_breakdown = {row["node_type"]: row["count"] for row in graph_breakdown_rows}
    graph_node_breakdown["other_nodes"] = max(0, summary["graph_nodes"] - sum(graph_node_breakdown.values()))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.state_summary", status="ok")
    first_agent_brief = {
        "current_phase": 14,
        "phase_label_note": "Token labels may reference a target or test phase. current_phase reflects the last verified project state summary.",
        "current_focus": "External AI onboarding, protected system/managed pages, and MCP connector reliability.",
        "current_priorities": ONBOARDING_PRIORITIES,
        "implementation_status": "active_hardening",
        "verification_status": "targeted tests and live local API checks are required after each connector change.",
        "next_phase_candidate": "Remote connector production hardening after quick-tunnel testing is stable.",
        "top_risks": [
            "External AI clients may connect through different MCP modes and only expose search/fetch unless developer mode is enabled.",
            "Completion labels can be over-trusted unless implementation, tests, live verification, and release readiness are separated.",
            "Quick tunnels are temporary and should not be treated as production access.",
        ],
        "risk_mitigation_status": [
            {
                "risk": "external_connector_mode_variance",
                "status": "mitigating",
                "mitigation": "GET discovery and GET resource previews are available for clients that cannot call JSON-RPC tools.",
            },
            {
                "risk": "quick_tunnel_not_production",
                "status": "accepted_for_testing",
                "mitigation": "Temporary agent tokens and explicit infrastructure_notice are used during quick-tunnel reviews.",
            },
            {
                "risk": "stale_static_review_inputs",
                "status": "mitigating",
                "mitigation": "Reviews should label review_source and operators triage fallback reviews against live JSON.",
            },
        ],
        "next_best_actions": [
            "Use onboarding before reviewing project state.",
            "Read state_summary and ai_state before broad page reads.",
            "Run review dry-run before durable review submission.",
        ],
    }
    phase_status = {
        "phase": 14,
        "implemented": True,
        "tests_passed": True,
        "live_api_verified": True,
        "docs_updated": True,
        "release_ready": False,
        "release_ready_blockers": [
            "Quick tunnel access is for testing only; a named tunnel with access controls is required for operational external access.",
            "External AI review findings are still being triaged and hardened before a release-ready claim.",
        ],
        "verification_evidence": [
            "targeted pytest for agent access",
            "Next.js production build",
            "live MCP bridge initialize/tools/start_here checks",
        ],
    }
    ai_state_pages_match = summary["pages"] == summary["ai_state_pages"]
    return {
        "ok": True,
        "data": {
            "summary": summary,
            "first_agent_brief": first_agent_brief,
            "phase_status": phase_status,
            "token_management": _token_management(agent),
            "conflict_resolution_policy": CONFLICT_RESOLUTION_POLICY,
            "security_boundary_policy": SECURITY_BOUNDARY_POLICY,
            "infrastructure_notice": INFRASTRUCTURE_NOTICE,
            "ai_state_coverage_note": "ai_state_pages counts structured state rows generated from active pages. It can differ from pages during sync or rebuild drift.",
            "ai_state_pages_match": ai_state_pages_match,
            "drift_suspected": not ai_state_pages_match,
            "graph_node_breakdown": graph_node_breakdown,
            "collaboration_status": {
                "ready_for_review": True,
                "note": "reviews/findings may be zero on a fresh or fully cleared review queue; collaboration import is still available when reviews:create is scoped.",
            },
        },
        "meta": _meta(agent, total=len(summary), returned=len(summary), truncated=False),
    }
