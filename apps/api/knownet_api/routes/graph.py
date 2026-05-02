import hashlib
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..security import Actor, require_review_access, require_write_access, requested_vault_id, utc_now
from ..services.rust_core import RustCoreError
from ..services.system_pages import system_rows_for_page_ids

router = APIRouter(prefix="/api/graph", tags=["graph"])


class RebuildGraphRequest(BaseModel):
    scope: str = Field(pattern="^(vault|page)$")
    page_id: str | None = None


class UpsertLayoutNodeRequest(BaseModel):
    layout_key: str
    node_id: str
    x: float
    y: float
    pinned: bool = True


class SetGraphNodePinRequest(BaseModel):
    node_id: str
    pinned: bool = True


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _json_meta(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _layout_key(vault_id: str, node_type: str | None, edge_type: str | None, status: str | None) -> str:
    parts = []
    for name, value in sorted({"edge_type": edge_type, "node_type": node_type, "status": status}.items()):
        if value:
            parts.append(f"{name}={','.join(sorted(_csv(value)))}")
    if not parts:
        return f"vault:{vault_id}:default"
    digest = hashlib.sha256("&".join(parts).encode("utf-8")).hexdigest()[:8]
    return f"vault:{vault_id}:filter:{digest}"


def _graph_stale(request: Request, vault_id: str) -> bool:
    active = getattr(request.app.state, "graph_rebuilds", set())
    return vault_id in active


async def _run_rebuild(request: Request, vault_id: str, scope: str, page_id: str | None, actor: Actor) -> dict:
    settings = request.app.state.settings
    if scope == "page" and not page_id:
        raise HTTPException(status_code=422, detail={"code": "page_id_required", "message": "page_id is required", "details": {}})
    if not hasattr(request.app.state, "graph_rebuilds"):
        request.app.state.graph_rebuilds = set()
    request.app.state.graph_rebuilds.add(vault_id)
    cmd = "rebuild_graph_for_vault" if scope == "vault" else "rebuild_graph_for_page"
    params = {
        "sqlite_path": str(settings.sqlite_path),
        "vault_id": vault_id,
        "rebuilt_at": utc_now(),
    }
    if scope == "page":
        params["page_id"] = page_id
    try:
        result = await request.app.state.rust_core.request(cmd, params)
        await write_audit_event(
            settings.sqlite_path,
            action=f"graph.rebuild_{scope}",
            actor=actor,
            target_type=scope,
            target_id=page_id or vault_id,
            metadata=result,
        )
        return result
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    finally:
        request.app.state.graph_rebuilds.discard(vault_id)


@router.get("")
async def get_graph(
    request: Request,
    vault_id: str | None = None,
    node_type: str | None = None,
    edge_type: str | None = None,
    status: str | None = None,
    limit: int = 500,
):
    settings = request.app.state.settings
    effective_vault_id = vault_id or requested_vault_id(request)
    limit = max(1, min(limit, 2000))
    node_types = _csv(node_type) or ["page"]
    statuses = _csv(status)

    node_clauses = [
        "gn.vault_id = ?",
        "(gn.node_type != 'page' OR EXISTS (SELECT 1 FROM pages p WHERE p.id = gn.target_id AND p.vault_id = gn.vault_id AND p.status = 'active'))",
        "(json_extract(gn.meta, '$.page_id') IS NULL OR EXISTS (SELECT 1 FROM pages p WHERE p.id = json_extract(gn.meta, '$.page_id') AND p.vault_id = gn.vault_id AND p.status = 'active'))",
    ]
    node_params: list[object] = [effective_vault_id]
    if node_types:
        node_clauses.append("gn.node_type IN ({})".format(",".join("?" for _ in node_types)))
        node_params.extend(node_types)
    if statuses:
        node_clauses.append("gn.status IN ({})".format(",".join("?" for _ in statuses)))
        node_params.extend(statuses)
    where_nodes = " AND ".join(node_clauses)
    count_row = await fetch_one(settings.sqlite_path, f"SELECT COUNT(*) AS count FROM graph_nodes gn WHERE {where_nodes}", tuple(node_params))
    total_node_count = int(count_row["count"]) if count_row else 0
    node_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT gn.id, gn.vault_id, gn.node_type, gn.label, gn.target_type, gn.target_id, gn.status, gn.weight, gn.meta, gn.updated_at "
        f"FROM graph_nodes gn WHERE {where_nodes} ORDER BY gn.weight DESC, gn.label LIMIT ?",
        tuple([*node_params, limit]),
    )
    node_ids = [row["id"] for row in node_rows]
    edges = []
    if node_ids:
        edge_types = _csv(edge_type)
        edge_clauses = [
            "vault_id = ?",
            "from_node_id IN ({})".format(",".join("?" for _ in node_ids)),
            "to_node_id IN ({})".format(",".join("?" for _ in node_ids)),
        ]
        edge_params: list[object] = [effective_vault_id, *node_ids, *node_ids]
        if edge_types:
            edge_clauses.append("edge_type IN ({})".format(",".join("?" for _ in edge_types)))
            edge_params.extend(edge_types)
        if statuses:
            edge_clauses.append("status IN ({})".format(",".join("?" for _ in statuses)))
            edge_params.extend(statuses)
        edges = await fetch_all(
            settings.sqlite_path,
            "SELECT id, vault_id, edge_type, from_node_id, to_node_id, weight, status, meta, updated_at "
            "FROM graph_edges WHERE "
            + " AND ".join(edge_clauses)
            + " ORDER BY weight DESC LIMIT ?",
            tuple([*edge_params, limit * 3]),
        )
    system_by_page_id = await system_rows_for_page_ids(
        settings.sqlite_path,
        [row["target_id"] for row in node_rows if row.get("node_type") == "page" and row.get("target_id")],
    )
    nodes = []
    for row in node_rows:
        meta = _json_meta(row.get("meta"))
        system = system_by_page_id.get(row["target_id"]) if row.get("node_type") == "page" else None
        if system:
            meta.update(system)
        nodes.append({**row, "meta": meta, **(system or {"system_kind": None, "system_tier": None, "system_locked": False})})
    edge_data = [{**row, "meta": _json_meta(row.get("meta"))} for row in edges]
    summary = _summary(nodes, edge_data, total_node_count)
    return {
        "ok": True,
        "data": {
            "nodes": nodes,
            "edges": edge_data,
            "truncated": total_node_count > len(nodes),
            "total_node_count": total_node_count,
            "graph_stale": _graph_stale(request, effective_vault_id),
            "layout_key": _layout_key(effective_vault_id, node_type, edge_type, status),
            "summary": summary,
        },
    }


@router.get("/neighborhood/{node_id}")
async def get_neighborhood(
    node_id: str,
    request: Request,
    depth: int = 1,
    limit: int = 200,
    vault_id: str | None = None,
):
    settings = request.app.state.settings
    effective_vault_id = vault_id or requested_vault_id(request)
    if depth > 2:
        raise HTTPException(status_code=422, detail={"code": "graph_depth_exceeded", "message": "Graph depth max is 2", "details": {"max": 2}})
    depth = max(1, depth)
    limit = max(1, min(limit, 500))
    root = await fetch_one(settings.sqlite_path, "SELECT id FROM graph_nodes WHERE vault_id = ? AND id = ?", (effective_vault_id, node_id))
    if not root:
        raise HTTPException(status_code=404, detail={"code": "graph_node_not_found", "message": "Graph node not found", "details": {"node_id": node_id}})
    seen = {node_id}
    frontier = {node_id}
    edges: list[dict] = []
    for _ in range(depth):
        placeholders = ",".join("?" for _ in frontier)
        rows = await fetch_all(
            settings.sqlite_path,
            "SELECT id, vault_id, edge_type, from_node_id, to_node_id, weight, status, meta, updated_at "
            f"FROM graph_edges WHERE vault_id = ? AND (from_node_id IN ({placeholders}) OR to_node_id IN ({placeholders})) LIMIT ?",
            tuple([effective_vault_id, *frontier, *frontier, limit]),
        )
        next_frontier = set()
        for row in rows:
            edges.append(row)
            for key in ("from_node_id", "to_node_id"):
                if row[key] not in seen:
                    seen.add(row[key])
                    next_frontier.add(row[key])
        frontier = next_frontier
        if not frontier or len(seen) >= limit:
            break
    node_ids = list(seen)[:limit]
    placeholders = ",".join("?" for _ in node_ids)
    node_rows = await fetch_all(
        settings.sqlite_path,
        "SELECT id, vault_id, node_type, label, target_type, target_id, status, weight, meta, updated_at "
        f"FROM graph_nodes WHERE vault_id = ? AND id IN ({placeholders}) ORDER BY weight DESC, label",
        tuple([effective_vault_id, *node_ids]),
    )
    system_by_page_id = await system_rows_for_page_ids(
        settings.sqlite_path,
        [row["target_id"] for row in node_rows if row.get("node_type") == "page" and row.get("target_id")],
    )
    nodes = []
    for row in node_rows:
        meta = _json_meta(row.get("meta"))
        system = system_by_page_id.get(row["target_id"]) if row.get("node_type") == "page" else None
        if system:
            meta.update(system)
        nodes.append({**row, "meta": meta, **(system or {"system_kind": None, "system_tier": None, "system_locked": False})})
    return {
        "ok": True,
        "data": {
            "nodes": nodes,
            "edges": [{**row, "meta": _json_meta(row.get("meta"))} for row in edges],
            "truncated": len(seen) > len(node_ids),
            "graph_stale": _graph_stale(request, effective_vault_id),
        },
    }


@router.post("/rebuild")
async def rebuild_graph(
    payload: RebuildGraphRequest,
    request: Request,
    actor: Actor = Depends(require_review_access),
):
    result = await _run_rebuild(request, actor.vault_id, payload.scope, payload.page_id, actor)
    return {"ok": True, "data": result}


@router.post("/layout/nodes")
async def upsert_layout_node(
    payload: UpsertLayoutNodeRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    try:
        result = await request.app.state.rust_core.request(
            "upsert_graph_layout_node",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "layout_key": payload.layout_key,
                "node_id": payload.node_id,
                "x": payload.x,
                "y": payload.y,
                "pinned": payload.pinned,
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": result}


@router.post("/pins/nodes")
async def set_graph_node_pin(
    payload: SetGraphNodePinRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    node = await fetch_one(
        settings.sqlite_path,
        "SELECT id, node_type, target_id FROM graph_nodes WHERE vault_id = ? AND id = ?",
        (actor.vault_id, payload.node_id),
    )
    if not node:
        raise HTTPException(
            status_code=404,
            detail={"code": "graph_node_not_found", "message": "Graph node not found", "details": {"node_id": payload.node_id}},
        )
    try:
        result = await request.app.state.rust_core.request(
            "set_graph_node_pin",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "node_id": payload.node_id,
                "pinned": payload.pinned,
                "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        await write_audit_event(
            settings.sqlite_path,
            action="graph.node_pin",
            actor=actor,
            target_type="graph_node",
            target_id=payload.node_id,
            metadata={"pinned": payload.pinned},
        )
        if node["node_type"] == "page" and node["target_id"]:
            await _run_rebuild(request, actor.vault_id, "page", node["target_id"], actor)
    except RustCoreError as error:
        status_code = 404 if error.code == "graph_node_not_found" else 500
        raise HTTPException(status_code=status_code, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": result}


@router.delete("/layout")
async def clear_layout(
    request: Request,
    layout_key: str | None = None,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    try:
        result = await request.app.state.rust_core.request(
            "clear_graph_layout_cache",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "layout_key": layout_key,
            },
        )
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": result}


def _summary(nodes: list[dict], edges: list[dict], total_node_count: int) -> dict:
    page_nodes = [node for node in nodes if node["node_type"] == "page"]
    weak_pages = 0
    orphan_pages = 0
    hub_pages = 0
    core_pages = 0
    for node in page_nodes:
        meta = node.get("meta") or {}
        weak_pages += 1 if meta.get("weak_citation_cluster") else 0
        orphan_pages += 1 if meta.get("orphan") else 0
        hub_pages += 1 if meta.get("hub") else 0
        core_pages += 1 if meta.get("core") else 0
    return {
        "visible_node_count": len(nodes),
        "total_node_count": total_node_count,
        "visible_edge_count": len(edges),
        "page_count": len(page_nodes),
        "weak_page_count": weak_pages,
        "orphan_page_count": orphan_pages,
        "hub_page_count": hub_pages,
        "core_page_count": core_pages,
    }
