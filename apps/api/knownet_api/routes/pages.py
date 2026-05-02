from datetime import datetime, timezone
from pathlib import Path
import re
from shutil import move
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..audit import write_audit_event
from ..db.sqlite import fetch_all, fetch_one
from ..paths import page_storage_dir
from ..security import Actor, enforce_write_rate_limit, ensure_length, require_admin_access, require_write_access
from ..services.rust_core import RustCoreError
from ..status import operation_failure_status

router = APIRouter(prefix="/api/pages", tags=["pages"])


class CreatePageRequest(BaseModel):
    slug: str
    title: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _page_id_from_slug(slug: str) -> str:
    return f"page_{slug.replace('-', '_')}"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail={"code": "invalid_slug", "message": "Invalid slug", "details": {}})
    return slug


def _safe_page_path(data_dir: Path, slug: str) -> Path:
    if not slug or "/" in slug or "\\" in slug or slug in {".", ".."}:
        raise HTTPException(status_code=400, detail={"code": "invalid_slug", "message": "Invalid slug", "details": {}})
    pages_dir = page_storage_dir(data_dir).resolve()
    path = (pages_dir / f"{slug}.md").resolve()
    if pages_dir not in path.parents:
        raise HTTPException(status_code=400, detail={"code": "invalid_slug", "message": "Invalid slug", "details": {}})
    return path


async def _page_row_by_slug(settings, slug: str) -> dict | None:
    return await fetch_one(
        settings.sqlite_path,
        "SELECT id, slug, title, path, status, current_revision_id FROM pages WHERE slug = ?",
        (slug,),
    )


def _move_orphan_page_file_to_tombstone(data_dir: Path, slug: str, path: Path, tombstoned_at: str) -> str:
    page_id = _page_id_from_slug(slug)
    tombstone_dir = data_dir / "revisions" / page_id
    tombstone_dir.mkdir(parents=True, exist_ok=True)
    safe_stamp = re.sub(r"[^A-Za-z0-9]+", "-", tombstoned_at).strip("-")
    tombstone_path = tombstone_dir / f"tombstone-{safe_stamp}.md"
    move(str(path), str(tombstone_path))
    return str(tombstone_path).replace("\\", "/")


def _strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    return markdown[end + 5 :] if end != -1 else markdown


def _frontmatter(markdown: str) -> dict:
    if not markdown.startswith("---\n"):
        return {}
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}
    result = {}
    for line in markdown[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("\"'")
    return result


def _citation_definitions(markdown: str) -> dict[str, str]:
    definitions: dict[str, str] = {}
    for line in _strip_frontmatter(markdown).splitlines():
        match = re.match(r"^\[\^([^\]]+)\]:\s*(.*)$", line.strip())
        if match:
            definitions[match.group(1).strip()] = match.group(2).strip()
    return definitions


def _source_excerpt(path: str | None, max_chars: int = 420) -> str | None:
    if not path:
        return None
    source_path = Path(path)
    if not source_path.exists():
        return None
    text = _strip_frontmatter(source_path.read_text(encoding="utf-8")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


async def _citation_sources(settings, page_id: str, revision_id: str | None, markdown: str) -> list[dict]:
    definitions = _citation_definitions(markdown)
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT c.citation_key, c.validation_status, m.path AS message_path, "
        "ca.status AS audit_status, ca.reason, ca.evidence_snapshot_id, ev.excerpt AS evidence_excerpt "
        "FROM citations c "
        "LEFT JOIN messages m ON m.id = c.citation_key "
        "LEFT JOIN citation_audits ca ON ca.page_id = c.page_id "
        "  AND (ca.revision_id IS c.revision_id OR ca.revision_id = c.revision_id) "
        "  AND ca.citation_key = c.citation_key "
        "LEFT JOIN citation_evidence_snapshots ev ON ev.id = ca.evidence_snapshot_id "
        "WHERE c.page_id = ? AND (c.revision_id IS ? OR c.revision_id = ?) "
        "ORDER BY c.citation_key, ca.updated_at DESC",
        (page_id, revision_id, revision_id),
    )
    seen: set[str] = set()
    sources: list[dict] = []
    for row in rows:
        key = row["citation_key"]
        if key in seen:
            continue
        seen.add(key)
        excerpt = row["evidence_excerpt"] or _source_excerpt(row["message_path"])
        sources.append(
            {
                "key": key,
                "definition": definitions.get(key),
                "excerpt": excerpt,
                "status": row["audit_status"] or row["validation_status"],
                "reason": row["reason"],
            }
        )
    for key, definition in definitions.items():
        if key not in seen:
            sources.append({"key": key, "definition": definition, "excerpt": None, "status": "unchecked", "reason": None})
    return sources


async def _run_post_create_tasks(
    request: Request,
    *,
    sqlite_path: Path,
    page_path: str,
    page_id: str,
    revision_id: str,
    vault_id: str,
    now: str,
) -> tuple[dict, dict]:
    index_status: dict = {"status": "pending"}
    graph_rebuild: dict = {"status": "skipped", "reason": "index_not_completed"}
    try:
        await request.app.state.rust_core.request(
            "index_page",
            {
                "sqlite_path": str(sqlite_path),
                "path": page_path,
                "page_id": page_id,
                "revision_id": revision_id,
                "indexed_at": now,
            },
        )
        index_status = {"status": "indexed"}
    except Exception as error:
        return operation_failure_status(error), graph_rebuild

    try:
        result = await request.app.state.rust_core.request(
            "rebuild_graph_for_page",
            {
                "sqlite_path": str(sqlite_path),
                "vault_id": vault_id,
                "page_id": page_id,
                "rebuilt_at": now,
            },
        )
        graph_rebuild = {"status": "rebuilt", "result": result or {}}
    except Exception as error:
        graph_rebuild = operation_failure_status(error)
    return index_status, graph_rebuild


async def _parse_page(request: Request, path: Path) -> dict:
    rust = request.app.state.rust_core
    if not rust.available:
        raise HTTPException(status_code=503, detail={"code": "daemon_unavailable", "message": "Rust daemon is unavailable", "details": {}})
    try:
        parsed = await rust.request("parse", {"path": str(path)})
    except RustCoreError as error:
        raise HTTPException(status_code=500, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    markdown = path.read_text(encoding="utf-8")
    frontmatter = parsed.get("frontmatter") or {}
    return {
        "slug": frontmatter.get("slug") or path.stem,
        "title": frontmatter.get("title") or path.stem,
        "path": str(path).replace("\\", "/"),
        "markdown": markdown,
        "frontmatter": frontmatter,
        "links": parsed.get("links") or [],
        "citations": parsed.get("citations") or [],
        "sections": parsed.get("sections") or [],
    }


async def _indexed_page(settings, page_row: dict, path: Path) -> dict:
    markdown = path.read_text(encoding="utf-8")
    frontmatter = _frontmatter(markdown)
    revision_id = page_row["current_revision_id"] if page_row else None
    page_id = page_row["id"] if page_row else _page_id_from_slug(path.stem)
    links = await fetch_all(
        settings.sqlite_path,
        "SELECT raw, target, display, status FROM links WHERE page_id = ? AND (revision_id IS ? OR revision_id = ?) ORDER BY target",
        (page_id, revision_id, revision_id),
    )
    citations = await fetch_all(
        settings.sqlite_path,
        "SELECT citation_key AS key FROM citations WHERE page_id = ? AND (revision_id IS ? OR revision_id = ?) ORDER BY citation_key",
        (page_id, revision_id, revision_id),
    )
    sections = await fetch_all(
        settings.sqlite_path,
        "SELECT heading, level, section_key FROM sections WHERE page_id = ? AND (revision_id IS ? OR revision_id = ?) ORDER BY position",
        (page_id, revision_id, revision_id),
    )
    return {
        "slug": frontmatter.get("slug") or page_row.get("slug") or path.stem,
        "title": frontmatter.get("title") or page_row.get("title") or path.stem,
        "path": str(path).replace("\\", "/"),
        "markdown": markdown,
        "frontmatter": frontmatter,
        "links": links,
        "citations": citations,
        "sections": sections,
    }


@router.get("")
async def list_pages(request: Request):
    settings = request.app.state.settings
    pages_dir = page_storage_dir(settings.data_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT p.slug, p.title, p.path, "
        "(SELECT COUNT(*) FROM links l WHERE l.page_id = p.id AND (l.revision_id IS p.current_revision_id OR l.revision_id = p.current_revision_id)) AS links_count, "
        "(SELECT COUNT(*) FROM citations c WHERE c.page_id = p.id AND (c.revision_id IS p.current_revision_id OR c.revision_id = p.current_revision_id)) AS citations_count "
        "FROM pages p WHERE p.status = 'active' AND p.path LIKE '%.md' ORDER BY p.title, p.slug",
        (),
    )
    if rows:
        pages = [
            {
                "slug": row["slug"],
                "title": row["title"],
                "path": row["path"],
                "links_count": row["links_count"],
                "citations_count": row["citations_count"],
            }
            for row in rows
            if Path(row["path"]).exists()
        ]
    else:
        pages = []
        for path in sorted(pages_dir.glob("*.md")):
            pages.append({"slug": path.stem, "title": path.stem, "path": str(path).replace("\\", "/"), "links_count": 0, "citations_count": 0})
    return {"ok": True, "data": {"pages": pages}}


@router.post("")
async def create_page(
    payload: CreatePageRequest,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    slug = _safe_slug(payload.slug)
    ensure_length(slug, settings.max_slug_chars, "slug")
    title = (payload.title or slug.replace("-", " ").title()).strip()
    ensure_length(title, settings.max_title_chars, "title")
    await enforce_write_rate_limit(request, actor, settings)
    path = _safe_page_path(settings.data_dir, slug)
    if path.exists():
        raise HTTPException(status_code=409, detail={"code": "page_exists", "message": "Page already exists", "details": {"slug": slug}})

    page_id = _page_id_from_slug(slug)
    revision_id = f"rev_{uuid4().hex[:12]}"
    now = _utc_now()
    try:
        created = await request.app.state.rust_core.request(
            "create_page",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "page_id": page_id,
                "revision_id": revision_id,
                "slug": slug,
                "title": title,
                "created_at": now,
            },
        )
    except RustCoreError as error:
        status = 409 if error.code == "page_exists" else 500
        raise HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    page_path = created["path"]
    index_status, graph_rebuild = await _run_post_create_tasks(
        request,
        sqlite_path=settings.sqlite_path,
        page_path=page_path,
        page_id=page_id,
        revision_id=revision_id,
        vault_id=actor.vault_id,
        now=now,
    )
    await write_audit_event(
        settings.sqlite_path,
        action="page.created",
        actor=actor,
        target_type="page",
        target_id=page_id,
        after_revision_id=revision_id,
        metadata={"slug": slug, "path": page_path, "index_status": index_status, "graph_rebuild": graph_rebuild},
    )
    return {
        "ok": True,
        "data": {
            "slug": slug,
            "title": title,
            "path": page_path,
            "revision_id": created["revision_id"],
            "index_status": index_status,
            "graph_rebuild": graph_rebuild,
        },
    }


@router.get("/{slug}")
async def get_page(slug: str, request: Request):
    settings = request.app.state.settings
    page_row = await _page_row_by_slug(settings, slug)
    if page_row and page_row["status"] != "active":
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Page not found", "details": {"slug": slug}})
    path = _safe_page_path(settings.data_dir, slug)
    if not path.exists():
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Page not found", "details": {"slug": slug}})
    try:
        page = await _indexed_page(settings, page_row or {}, path)
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=422, detail={"code": "invalid_markdown_encoding", "message": "Page is not valid UTF-8", "details": {"slug": slug, "error": str(error)}}) from error
    page_id = page_row["id"] if page_row else _page_id_from_slug(slug)
    revision_id = page_row["current_revision_id"] if page_row else None
    page["citation_sources"] = await _citation_sources(settings, page_id, revision_id, page["markdown"])
    return {"ok": True, "data": page}


@router.get("/{slug}/links")
async def get_page_links(slug: str, request: Request):
    settings = request.app.state.settings
    page_id = _page_id_from_slug(slug)
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT raw, target, display, status, revision_id FROM links WHERE page_id = ? ORDER BY target",
        (page_id,),
    )
    unresolved = [row for row in rows if row["status"] == "unresolved"]
    return {"ok": True, "data": {"slug": slug, "links": rows, "unresolved": unresolved}}


@router.get("/{slug}/backlinks")
async def get_page_backlinks(slug: str, request: Request):
    settings = request.app.state.settings
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT l.raw, l.display, l.source_path, l.revision_id, p.slug AS source_slug, p.title AS source_title "
        "FROM links l "
        "LEFT JOIN pages p ON p.id = l.page_id "
        "WHERE lower(l.target) = lower(?) OR lower(l.target) = lower(?) "
        "ORDER BY p.title, l.raw",
        (slug, slug.replace("-", " ")),
    )
    return {"ok": True, "data": {"slug": slug, "backlinks": rows}}


@router.delete("/{slug}")
async def tombstone_page(
    slug: str,
    request: Request,
    actor: Actor = Depends(require_admin_access),
):
    settings = request.app.state.settings
    await enforce_write_rate_limit(request, actor, settings)
    page_row = await _page_row_by_slug(settings, slug)
    if not page_row:
        path = _safe_page_path(settings.data_dir, slug)
        if not path.exists():
            raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Page not found", "details": {"slug": slug}})
        tombstone_path = _move_orphan_page_file_to_tombstone(settings.data_dir, slug, path, _utc_now())
        await write_audit_event(
            settings.sqlite_path,
            action="page.tombstone_orphan",
            actor=actor,
            target_type="page",
            target_id=_page_id_from_slug(slug),
            metadata={"slug": slug, "path": tombstone_path, "orphan_file": True},
        )
        return {"ok": True, "data": {"slug": slug, "status": "tombstone", "path": tombstone_path, "orphan_file": True}}
    try:
        result = await request.app.state.rust_core.request(
            "tombstone_page",
            {
                "data_dir": str(settings.data_dir),
                "sqlite_path": str(settings.sqlite_path),
                "slug": slug,
                "tombstoned_at": _utc_now(),
            },
        )
    except RustCoreError as error:
        status = 404 if error.code in {"page_not_found", "file_not_found"} else 409 if error.code == "page_already_tombstoned" else 500
        raise HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action="page.tombstone",
        actor=actor,
        target_type="page",
        target_id=page_row["id"],
        metadata={"slug": slug, "path": result["path"]},
    )
    await request.app.state.rust_core.request(
        "rebuild_graph_for_page",
        {
            "sqlite_path": str(settings.sqlite_path),
            "vault_id": actor.vault_id,
            "page_id": page_row["id"],
            "rebuilt_at": _utc_now(),
        },
    )
    return {"ok": True, "data": result}


@router.post("/{slug}/recover")
async def recover_page(
    slug: str,
    request: Request,
    actor: Actor = Depends(require_admin_access),
):
    settings = request.app.state.settings
    await enforce_write_rate_limit(request, actor, settings)
    page_row = await fetch_one(settings.sqlite_path, "SELECT id, status FROM pages WHERE slug = ?", (slug,))
    if not page_row:
        raise HTTPException(status_code=404, detail={"code": "page_not_found", "message": "Page not found", "details": {"slug": slug}})
    try:
        result = await request.app.state.rust_core.request(
            "recover_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "slug": slug,
                "recovered_at": _utc_now(),
            },
        )
    except RustCoreError as error:
        status = 404 if error.code in {"page_not_found", "tombstone_not_found"} else 409 if error.code == "page_not_tombstoned" else 500
        raise HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    await write_audit_event(
        settings.sqlite_path,
        action="page.recover",
        actor=actor,
        target_type="page",
        target_id=page_row["id"],
        metadata={"slug": slug, "path": result["path"]},
    )
    return {"ok": True, "data": result}


@router.post("/{slug}/revisions/{revision_id}/restore")
async def restore_revision(
    slug: str,
    revision_id: str,
    request: Request,
    actor: Actor = Depends(require_write_access),
):
    settings = request.app.state.settings
    rust = request.app.state.rust_core
    if not rust.available:
        raise HTTPException(status_code=503, detail={"code": "daemon_unavailable", "message": "Rust daemon is unavailable", "details": {}})
    await enforce_write_rate_limit(request, actor, settings)
    page_row = await fetch_one(
        settings.sqlite_path,
        "SELECT id, current_revision_id FROM pages WHERE slug = ?",
        (slug,),
    )
    try:
        result = await rust.request(
            "restore_revision",
            {
                "sqlite_path": str(settings.sqlite_path),
                "slug": slug,
                "revision_id": revision_id,
                "restored_at": _utc_now(),
            },
        )
        await rust.request(
            "index_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "path": result["path"],
                "page_id": _page_id_from_slug(slug),
                "revision_id": revision_id,
                "indexed_at": _utc_now(),
            },
        )
        await rust.request(
            "rebuild_graph_for_page",
            {
                "sqlite_path": str(settings.sqlite_path),
                "vault_id": actor.vault_id,
                "page_id": _page_id_from_slug(slug),
                "rebuilt_at": _utc_now(),
            },
        )
        await write_audit_event(
            settings.sqlite_path,
            action="revision.restored",
            actor=actor,
            target_type="page",
            target_id=page_row["id"] if page_row else _page_id_from_slug(slug),
            before_revision_id=page_row["current_revision_id"] if page_row else None,
            after_revision_id=revision_id,
            metadata={"slug": slug, "path": result["path"]},
        )
    except RustCoreError as error:
        status = 404 if error.code in {"page_not_found", "revision_not_found", "file_not_found"} else 500
        raise HTTPException(status_code=status, detail={"code": error.code, "message": error.message, "details": error.details}) from error
    return {"ok": True, "data": result}
