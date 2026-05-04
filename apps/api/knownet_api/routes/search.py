import math
import struct
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..db.sqlite import fetch_all
from ..paths import page_storage_dir

router = APIRouter(prefix="/api/search", tags=["search"])


class SemanticSearchRequest(BaseModel):
    q: str = ""


def _decode_vector(blob: bytes, dims: int) -> list[float]:
    expected = dims * 4
    if dims <= 0 or len(blob) != expected:
        return []
    return list(struct.unpack(f"<{dims}f", blob))


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


async def _keyword_results(q: str, request: Request) -> list[dict]:
    settings = request.app.state.settings
    query = q.strip()
    if not query:
        return []

    indexed = await fetch_all(
        settings.sqlite_path,
        "SELECT DISTINCT p.slug, p.title, p.path, 'index' AS match_type "
        "FROM pages p "
        "LEFT JOIN links l ON l.page_id = p.id "
        "LEFT JOIN sections s ON s.page_id = p.id "
        "WHERE lower(p.title) LIKE ? OR lower(p.slug) LIKE ? OR lower(l.target) LIKE ? OR lower(s.heading) LIKE ? "
        "LIMIT 50",
        tuple([f"%{query.lower()}%"] * 4),
    )
    pages = [dict(row) for row in indexed]
    seen = {page["slug"] for page in pages}
    if len(pages) < 50:
        for path in sorted(page_storage_dir(settings.data_dir).glob("*.md")):
            if path.stem in seen:
                continue
            markdown = path.read_text(encoding="utf-8")
            if query.lower() in markdown.lower() or query.lower() in path.stem.lower():
                pages.append(
                    {
                        "slug": path.stem,
                        "title": path.stem,
                        "path": str(path).replace("\\", "/"),
                        "match_type": "markdown",
                    }
                )
                seen.add(path.stem)
            if len(pages) >= 50:
                break
    return pages[:50]


async def _semantic_results(q: str, request: Request) -> list[dict]:
    settings = request.app.state.settings
    embedding = request.app.state.embedding_service
    query_vector = await embedding.encode(q)
    rows = await fetch_all(
        settings.sqlite_path,
        "SELECT e.owner_type, e.owner_id, e.vector, e.dims, e.model, "
        "p.slug, p.title, p.path "
        "FROM embeddings e "
        "LEFT JOIN pages p ON e.owner_type = 'page' AND e.owner_id = p.id "
        "WHERE e.model = ?",
        (embedding.model_name,),
    )
    results = []
    for row in rows:
        vector = _decode_vector(row["vector"], row["dims"])
        score = _cosine_similarity(query_vector, vector)
        if score <= 0:
            continue
        result = {
            "score": score,
            "match_type": "semantic",
            "owner_type": row["owner_type"],
            "owner_id": row["owner_id"],
            "model": row["model"],
        }
        if row["owner_type"] == "page":
            result.update(
                {
                    "slug": row["slug"],
                    "title": row["title"] or row["owner_id"],
                    "path": row["path"],
                }
            )
        else:
            result.update({"slug": None, "title": row["owner_id"], "path": None})
        results.append(result)
    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:20]


@router.get("")
async def keyword_search(q: str, request: Request):
    started = time.perf_counter()
    results = await _keyword_results(q, request)
    return {"ok": True, "data": {"results": results, "duration_ms": int((time.perf_counter() - started) * 1000)}}


@router.post("/semantic")
async def semantic_search(payload: SemanticSearchRequest, request: Request):
    started = time.perf_counter()
    embedding = request.app.state.embedding_service
    health = embedding.health()
    if health["status"] != "ready":
        return {
            "ok": True,
            "data": {
                "results": await _keyword_results(payload.q, request),
                "status": "degraded",
                "fallback": "keyword",
                "reason": health["reason"],
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        }
    try:
        results = await _semantic_results(payload.q, request)
    except Exception as error:
        return {
            "ok": True,
            "data": {
                "results": await _keyword_results(payload.q, request),
                "status": "degraded",
                "fallback": "keyword",
                "reason": f"semantic_search_failed: {error}",
                "duration_ms": int((time.perf_counter() - started) * 1000),
            },
        }
    return {
        "ok": True,
        "data": {
            "results": results,
            "status": "ready",
            "fallback": None,
            "reason": None,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        },
    }
