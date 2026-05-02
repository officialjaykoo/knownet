from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db.sqlite import fetch_one
from .routes.agent import router as agent_router
from .routes.agents import router as agents_router
from .routes.auth import router as auth_router
from .routes.audit import router as audit_router
from .routes.citations import router as citations_router
from .routes.collaboration import router as collaboration_router
from .routes.events import router as events_router
from .routes.graph import router as graph_router
from .routes.jobs import router as jobs_router
from .routes.maintenance import active_maintenance_lock, ensure_phase6_schema, router as maintenance_router
from .routes.messages import router as messages_router
from .routes.search import router as search_router
from .routes.submissions import router as submissions_router
from .routes.suggestions import router as suggestions_router
from .routes.vaults import router as vaults_router
from .routes.pages import router as pages_router
from .services.draft_service import DraftService
from .services.citation_verifier import CitationVerifier
from .services.embedding_service import EmbeddingService
from .services.job_processor import JobProcessor
from .services.rust_core import RustCoreClient
from .services.source_selector import SourceSelector


HEALTH_ISSUE_DEFINITIONS = {
    "rust_daemon.unavailable": {
        "severity": "action_required",
        "description": "Rust daemon is unavailable, so parsing and write commands cannot run.",
        "action": "Restart the API after rebuilding or freeing knownet-core.exe.",
    },
    "sqlite.unavailable": {
        "severity": "action_required",
        "description": "SQLite initialization did not complete successfully.",
        "action": "Check API startup logs and run the migration endpoint after fixing the database path.",
    },
    "sqlite.missing": {
        "severity": "action_required",
        "description": "The configured SQLite database file is missing.",
        "action": "Restore from a snapshot, run migration, or rebuild from Markdown if no snapshot exists.",
    },
    "security.public_without_admin_token": {
        "severity": "action_required",
        "description": "Public mode is enabled without an admin token.",
        "action": "Set ADMIN_TOKEN or disable PUBLIC_MODE before accepting writes.",
    },
    "security.weak_admin_token": {
        "severity": "action_required",
        "description": "Public mode is enabled with an admin token below the configured minimum length.",
        "action": "Set a long random ADMIN_TOKEN or disable PUBLIC_MODE before accepting writes.",
    },
    "security.public_without_cloudflare_access": {
        "severity": "warning",
        "description": "Public mode is enabled without the Cloudflare Access origin gate.",
        "action": "Enable CLOUDFLARE_ACCESS_REQUIRED when exposing KnowNet through a tunnel.",
    },
    "security.cloudflare_access_open_policy": {
        "severity": "warning",
        "description": "Cloudflare Access enforcement is enabled without an allowed email list.",
        "action": "Set CLOUDFLARE_ACCESS_ALLOWED_EMAILS to the accounts allowed to reach KnowNet.",
    },
    "backup.age_exceeded": {
        "severity": "warning",
        "description": "The latest snapshot is older than the configured health threshold.",
        "action": "Create a new snapshot from the Operations panel or POST /api/maintenance/snapshots.",
    },
    "backup.missing": {
        "severity": "setup_needed",
        "description": "No local snapshot has been created yet.",
        "action": "Create the first snapshot after confirming the app is working.",
    },
    "embedding.unavailable": {
        "severity": "expected_degraded",
        "description": "Local embeddings are not loaded; keyword search and deterministic fallbacks still work.",
        "action": "Load embeddings only if semantic search is needed.",
    },
    "graph.stale": {
        "severity": "warning",
        "description": "A graph rebuild is running or pending, so graph results may be stale.",
        "action": "Wait for the rebuild to finish or run verify-index afterward.",
    },
}


def _health_issue_detail(code: str) -> dict:
    definition = HEALTH_ISSUE_DEFINITIONS.get(
        code,
        {
            "severity": "warning",
            "description": "Health reported an uncategorized issue.",
            "action": "Check the full /health response and application logs.",
        },
    )
    return {"code": code, **definition}


def _allowed_cloudflare_emails(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.draft_service = DraftService(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        timeout_seconds=settings.openai_timeout_seconds,
    )
    app.state.source_selector = SourceSelector(settings.data_dir)
    app.state.embedding_service = EmbeddingService(settings.local_embedding_model)
    if settings.local_embedding_auto_load:
        await app.state.embedding_service.load(allow_download=not settings.local_embedding_local_files_only)
    app.state.rust_core = RustCoreClient(settings.rust_core_path)
    await app.state.rust_core.start()
    app.state.citation_verifier = CitationVerifier(sqlite_path=settings.sqlite_path, rust=app.state.rust_core)
    app.state.sqlite_status = "unknown"
    if app.state.rust_core.available:
        await app.state.rust_core.request("init_db", {"sqlite_path": str(settings.sqlite_path)})
        await app.state.rust_core.request(
            "run_phase3_migration",
            {
                "sqlite_path": str(settings.sqlite_path),
                "backup_dir": str(settings.data_dir / "backups"),
                "migrated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            },
        )
        await app.state.rust_core.request("ensure_phase4_schema", {"sqlite_path": str(settings.sqlite_path)})
        await app.state.rust_core.request("ensure_graph_schema", {"sqlite_path": str(settings.sqlite_path)})
        await ensure_phase6_schema(settings.sqlite_path)
        app.state.sqlite_status = "ok"
    app.state.graph_rebuilds = set()
    app.state.auth_failures = {}
    app.state.job_processor = JobProcessor(
        app.state.rust_core,
        settings,
        app.state.draft_service,
        app.state.source_selector,
    )
    app.state.job_processor.start()
    yield
    await app.state.job_processor.stop()
    await app.state.rust_core.stop()


app = FastAPI(title="KnowNet API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def require_cloudflare_access(request, call_next):
    settings = getattr(request.app.state, "settings", get_settings())
    if not getattr(settings, "cloudflare_access_required", False):
        return await call_next(request)

    path = request.url.path
    if path.startswith("/docs") or path.startswith("/openapi"):
        return await call_next(request)

    email = request.headers.get("cf-access-authenticated-user-email")
    assertion = request.headers.get("cf-access-jwt-assertion")
    allowed_emails = _allowed_cloudflare_emails(getattr(settings, "cloudflare_access_allowed_emails", ""))

    if getattr(settings, "cloudflare_access_require_jwt", True) and not assertion:
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "cf_access_required", "message": "Cloudflare Access assertion is required"}},
        )
    if allowed_emails and (not email or email.strip().lower() not in allowed_emails):
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "cf_access_forbidden", "message": "Cloudflare Access email is not allowed"}},
        )

    return await call_next(request)


@app.middleware("http")
async def block_mutations_during_maintenance(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        path = request.url.path
        allowed = {
            "/api/maintenance/restore",
            "/api/maintenance/snapshots",
        }
        is_lock_release = path.startswith("/api/maintenance/locks/")
        if path not in allowed and not is_lock_release:
            settings = getattr(request.app.state, "settings", get_settings())
            if settings.sqlite_path.exists():
                lock = await active_maintenance_lock(settings.sqlite_path)
                if lock:
                    return JSONResponse(
                        status_code=423,
                        content={"detail": {"code": "maintenance_locked", "message": "Maintenance operation is active", "details": lock}},
                    )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    expires_in = getattr(request.state, "agent_expires_in_seconds", None)
    if expires_in is not None:
        response.headers["X-Token-Expires-In"] = str(expires_in)
    return response
app.include_router(messages_router)
app.include_router(agent_router)
app.include_router(agents_router)
app.include_router(auth_router)
app.include_router(citations_router)
app.include_router(collaboration_router)
app.include_router(jobs_router)
app.include_router(events_router)
app.include_router(graph_router)
app.include_router(vaults_router)
app.include_router(pages_router)
app.include_router(suggestions_router)
app.include_router(submissions_router)
app.include_router(search_router)
app.include_router(maintenance_router)
app.include_router(audit_router)


async def _health_payload() -> dict:
    rust_status = "unavailable"
    rust = getattr(app.state, "rust_core", None)
    if rust and rust.available:
        rust_status = "ok"
    sqlite_status = getattr(app.state, "sqlite_status", "unknown")
    embedding = getattr(app.state, "embedding_service", None)
    settings = app.state.settings
    issues: list[str] = []
    if rust_status != "ok":
        issues.append("rust_daemon.unavailable")
    if sqlite_status != "ok":
        issues.append("sqlite.unavailable")
    vault = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM vaults WHERE id = 'local-default'", ()) if settings.sqlite_path.exists() else None
    pages = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM pages WHERE status = 'active'", ()) if settings.sqlite_path.exists() else None
    citations = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM citation_audits", ()) if settings.sqlite_path.exists() else None
    weak = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM citation_audits WHERE status IN ('unsupported','stale','needs_review','contradicted')", ()) if settings.sqlite_path.exists() else None
    graph_nodes = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM graph_nodes", ()) if settings.sqlite_path.exists() else None
    graph_edges = await fetch_one(settings.sqlite_path, "SELECT COUNT(*) AS count FROM graph_edges", ()) if settings.sqlite_path.exists() else None
    lock = await active_maintenance_lock(settings.sqlite_path) if settings.sqlite_path.exists() else None
    if not settings.sqlite_path.exists():
        issues.append("sqlite.missing")
    if getattr(settings, "public_mode", False) and not getattr(settings, "admin_token", None):
        issues.append("security.public_without_admin_token")
    if (
        getattr(settings, "public_mode", False)
        and getattr(settings, "admin_token", None)
        and len(settings.admin_token) < settings.admin_token_min_chars
    ):
        issues.append("security.weak_admin_token")
    if getattr(settings, "public_mode", False) and not getattr(settings, "cloudflare_access_required", False):
        issues.append("security.public_without_cloudflare_access")
    if getattr(settings, "cloudflare_access_required", False) and not getattr(settings, "cloudflare_access_allowed_emails", ""):
        issues.append("security.cloudflare_access_open_policy")
    backup_dir = settings.data_dir / "backups"
    snapshots = sorted(backup_dir.glob("knownet-snapshot-*.tar.gz"), key=lambda path: path.stat().st_mtime, reverse=True) if backup_dir.exists() else []
    latest_snapshot = snapshots[0] if snapshots else None
    latest_age = None
    if latest_snapshot:
        latest_age = (datetime.now(timezone.utc).timestamp() - latest_snapshot.stat().st_mtime) / 3600
        if latest_age > settings.health_backup_max_age_hours:
            issues.append("backup.age_exceeded")
    else:
        issues.append("backup.missing")
    embedding_health = embedding.health() if embedding else {"status": "unknown"}
    if embedding_health.get("status") != "ready":
        issues.append("embedding.unavailable")
    graph_stale = bool(getattr(app.state, "graph_rebuilds", set()))
    if graph_stale:
        issues.append("graph.stale")
    issue_details = [_health_issue_detail(issue) for issue in issues]
    blocking = [issue for issue in issue_details if issue["severity"] == "action_required"]
    overall = "attention_required" if blocking else "degraded" if issues else "healthy"
    return {
        "api": "ok",
        "rust_daemon": rust_status,
        "sqlite": sqlite_status,
        "api_detail": {"status": "ok"},
        "rust_daemon_detail": {"status": rust_status},
        "sqlite_detail": {"status": sqlite_status},
        "security": {
            "public_mode": getattr(settings, "public_mode", False),
            "write_auth": "admin_token" if getattr(settings, "admin_token", None) else "local_only",
            "cloudflare_access_required": getattr(settings, "cloudflare_access_required", False),
            "cloudflare_access_allowed_emails_configured": bool(getattr(settings, "cloudflare_access_allowed_emails", "")),
            "default_vault_id": "local-default",
        },
        "vault": {"default_vault_exists": bool(vault and vault["count"])},
        "pages": {"page_count": pages["count"] if pages else 0},
        "citations": {"audit_count": citations["count"] if citations else 0, "weak_count": weak["count"] if weak else 0},
        "graph": {"node_count": graph_nodes["count"] if graph_nodes else 0, "edge_count": graph_edges["count"] if graph_edges else 0, "stale": graph_stale},
        "backup": {
            "latest_snapshot": latest_snapshot.name if latest_snapshot else None,
            "latest_snapshot_age_hours": latest_age,
        },
        "embedding": embedding_health,
        "maintenance": {"active_lock": lock},
        "overall_status": overall,
        "issues": issues,
        "issue_details": issue_details,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.get("/health")
async def health():
    return {"ok": True, "data": await _health_payload()}


@app.get("/health/summary")
async def health_summary():
    data = await _health_payload()
    return {"ok": True, "data": {"overall_status": data["overall_status"], "issues": data["issues"], "issue_details": data["issue_details"], "checked_at": data["checked_at"]}}
