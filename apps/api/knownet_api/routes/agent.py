import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from ..db.sqlite import fetch_all, fetch_one
from ..security import AgentAuth, record_agent_access, require_agent


router = APIRouter(prefix="/api/agent", tags=["agent"])


def _meta(agent: AgentAuth, *, total: int, returned: int, truncated: bool) -> dict:
    return {
        "schema_version": 1,
        "vault_id": agent.vault_id,
        "agent_scope": agent.scopes,
        "truncated": truncated,
        "total_count": total,
        "returned_count": returned,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _require_scope(agent: AgentAuth, scope: str, *, slug: str | None = None) -> None:
    if slug and f"{scope}:slug:{slug}" in agent.scopes:
        return
    if scope not in agent.scopes:
        raise HTTPException(status_code=403, detail={"code": "agent_scope_forbidden", "message": "Agent scope does not allow this operation", "details": {"scope": scope}})


@router.get("/ping")
async def agent_ping():
    return {"ok": True, "version": "9.0"}


@router.get("/me")
async def agent_me(request: Request, agent: AgentAuth = Depends(require_agent)):
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.me", status="ok")
    return {
        "ok": True,
        "data": {
            "token_id": agent.token_id,
            "label": agent.label,
            "agent_name": agent.agent_name,
            "agent_model": agent.agent_model,
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
        },
    }


@router.get("/pages")
async def agent_pages(request: Request, limit: int = 20, offset: int = 0, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "pages:read")
    limit = min(max(limit, 1), agent.max_pages_per_request)
    offset = max(offset, 0)
    total = await fetch_one(request.app.state.settings.sqlite_path, "SELECT COUNT(*) AS count FROM pages WHERE vault_id = ? AND status = 'active'", (agent.vault_id,))
    rows = await fetch_all(
        request.app.state.settings.sqlite_path,
        "SELECT id, slug, title, updated_at FROM pages WHERE vault_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (agent.vault_id, limit, offset),
    )
    truncated = bool(total and total["count"] > offset + len(rows))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.pages", status="ok", meta={"returned_count": len(rows), "truncated": truncated})
    return {"ok": True, "data": {"pages": rows}, "meta": _meta(agent, total=total["count"] if total else 0, returned=len(rows), truncated=truncated)}


@router.get("/pages/{page_id}")
async def agent_page(page_id: str, request: Request, agent: AgentAuth = Depends(require_agent)):
    row = await fetch_one(
        request.app.state.settings.sqlite_path,
        "SELECT id, slug, title, path, updated_at FROM pages WHERE id = ? AND vault_id = ? AND status = 'active'",
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
    return {"ok": True, "data": {"page": {"id": row["id"], "slug": row["slug"], "title": row["title"], "updated_at": row["updated_at"], "content": content}}, "meta": _meta(agent, total=1, returned=1, truncated=truncated)}


@router.get("/reviews")
async def agent_reviews(request: Request, limit: int = 50, offset: int = 0, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "reviews:read")
    limit = min(max(limit, 1), 200)
    offset = max(offset, 0)
    total = await fetch_one(request.app.state.settings.sqlite_path, "SELECT COUNT(*) AS count FROM collaboration_reviews WHERE vault_id = ?", (agent.vault_id,))
    rows = await fetch_all(request.app.state.settings.sqlite_path, "SELECT id, title, source_agent, source_model, status, page_id, created_at, updated_at FROM collaboration_reviews WHERE vault_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?", (agent.vault_id, limit, offset))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.reviews", status="ok", meta={"returned_count": len(rows)})
    count = total["count"] if total else 0
    return {"ok": True, "data": {"reviews": rows}, "meta": _meta(agent, total=count, returned=len(rows), truncated=count > offset + len(rows))}


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
    return {"ok": True, "data": {"findings": rows}, "meta": _meta(agent, total=count, returned=len(rows), truncated=count > offset + len(rows))}


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
    rows = await fetch_all(request.app.state.settings.sqlite_path, "SELECT id, page_id, citation_key, status, verifier_type, confidence, reason, updated_at FROM citation_audits " + filters + " ORDER BY updated_at DESC LIMIT ? OFFSET ?", (*params, limit, offset))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.citations", status="ok", meta={"returned_count": len(rows)})
    count = total["count"] if total else 0
    return {"ok": True, "data": {"citations": rows}, "meta": _meta(agent, total=count, returned=len(rows), truncated=count > offset + len(rows))}


@router.get("/context")
async def agent_context(request: Request, agent: AgentAuth = Depends(require_agent)):
    _require_scope(agent, "pages:read")
    pages = await fetch_all(request.app.state.settings.sqlite_path, "SELECT id, slug, title, updated_at FROM pages WHERE vault_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT ?", (agent.vault_id, agent.max_pages_per_request))
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.context", status="ok", meta={"returned_count": len(pages)})
    return {"ok": True, "data": {"pages": pages}, "meta": _meta(agent, total=len(pages), returned=len(pages), truncated=False)}


@router.get("/state-summary")
async def agent_state_summary(request: Request, agent: AgentAuth = Depends(require_agent)):
    summary = {}
    for name, query in {
        "pages": "SELECT COUNT(*) AS count FROM pages WHERE vault_id = ? AND status = 'active'",
        "reviews": "SELECT COUNT(*) AS count FROM collaboration_reviews WHERE vault_id = ?",
        "findings": "SELECT COUNT(*) AS count FROM collaboration_findings f JOIN collaboration_reviews r ON r.id = f.review_id WHERE r.vault_id = ?",
        "graph_nodes": "SELECT COUNT(*) AS count FROM graph_nodes WHERE vault_id = ?",
    }.items():
        row = await fetch_one(request.app.state.settings.sqlite_path, query, (agent.vault_id,))
        summary[name] = row["count"] if row else 0
    await record_agent_access(request.app.state.settings.sqlite_path, agent=agent, action="agent.state_summary", status="ok")
    return {"ok": True, "data": {"summary": summary}, "meta": _meta(agent, total=len(summary), returned=len(summary), truncated=False)}
