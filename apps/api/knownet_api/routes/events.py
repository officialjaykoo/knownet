import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..db.sqlite import fetch_all, fetch_one

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/jobs/{job_id}")
async def stream_job_events(job_id: str, request: Request):
    settings = request.app.state.settings
    job = await fetch_one(settings.sqlite_path, "SELECT id FROM jobs WHERE id = ?", (job_id,))
    if not job:
        raise HTTPException(status_code=404, detail={"code": "job_not_found", "message": "Job not found", "details": {}})

    last_event_id_header = request.headers.get("last-event-id")
    try:
        last_event_id = int(last_event_id_header) if last_event_id_header else 0
    except ValueError:
        last_event_id = 0

    async def event_generator():
        nonlocal last_event_id
        while True:
            if await request.is_disconnected():
                break
            rows = await fetch_all(
                settings.sqlite_path,
                "SELECT id, event_type, payload FROM job_events WHERE job_id = ? AND id > ? ORDER BY id ASC",
                (job_id, last_event_id),
            )
            for row in rows:
                last_event_id = row["id"]
                payload = row["payload"]
                try:
                    json.loads(payload)
                except json.JSONDecodeError:
                    payload = json.dumps({"raw": payload})
                yield f"id: {row['id']}\nevent: {row['event_type']}\ndata: {payload}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

