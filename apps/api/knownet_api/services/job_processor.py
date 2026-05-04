import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ..audit import AI_ACTOR, write_audit_event
from ..db.sqlite import fetch_one
from .draft_service import DraftService
from .rust_core import RustCoreClient, RustCoreError
from .source_selector import SourceSelector


logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown.strip()
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown.strip()
    return markdown[end + 5 :].strip()


class JobProcessor:
    def __init__(
        self,
        rust: RustCoreClient,
        settings: Any,
        draft_service: DraftService | None = None,
        source_selector: SourceSelector | None = None,
    ) -> None:
        self.rust = rust
        self.settings = settings
        self.draft_service = draft_service or DraftService(
            api_key=getattr(settings, "openai_api_key", None),
            base_url=getattr(settings, "openai_base_url", "https://api.openai.com/v1"),
            model=getattr(settings, "openai_model", "gpt-5-mini"),
            reasoning_effort=getattr(settings, "openai_reasoning_effort", "low"),
            max_output_tokens=getattr(settings, "openai_max_output_tokens", 2000),
            timeout_seconds=getattr(settings, "openai_timeout_seconds", 60.0),
        )
        self.source_selector = source_selector or SourceSelector(settings.data_dir)
        self.task: asyncio.Task[None] | None = None
        self.running = False

    def start(self) -> None:
        self.running = True
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    async def _loop(self) -> None:
        while self.running:
            try:
                did_work = await self.process_once()
            except Exception:
                logger.exception("Job processor loop failed")
                did_work = False
            await asyncio.sleep(0.2 if did_work else 1.0)

    async def process_once(self) -> bool:
        if not self.rust.available:
            return False
        lock = await fetch_one(
            self.settings.sqlite_path,
            "SELECT id FROM maintenance_locks WHERE status IN ('active', 'running') LIMIT 1",
            (),
        )
        if lock:
            return False
        now = datetime.now(timezone.utc)
        stale_before = now - timedelta(seconds=self.settings.job_stale_after_seconds)
        await self.rust.request(
            "recover_stale_jobs",
            {
                "sqlite_path": str(self.settings.sqlite_path),
                "stale_before": stale_before.isoformat().replace("+00:00", "Z"),
                "now": now.isoformat().replace("+00:00", "Z"),
            },
        )
        claim = await self.rust.request(
            "claim_next_job",
            {"sqlite_path": str(self.settings.sqlite_path), "now": utc_now()},
        )
        if not claim.get("claimed"):
            return False
        job = claim["job"]
        try:
            if job["job_type"] == "draft_page" and job["target_type"] == "message":
                await self._process_draft_job(job)
            else:
                await self._fail_job(job["id"], "unsupported_job_type", f"Unsupported job type: {job['job_type']}")
        except RustCoreError:
            raise
        except Exception as error:
            await self._fail_job(job["id"], "processor_error", str(error))
        return True

    async def _process_draft_job(self, job: dict[str, Any]) -> None:
        message_id = job["target_id"]
        message_path = self.settings.data_dir / "inbox" / f"{message_id.replace('_', '-')}.md"
        source = message_path.read_text(encoding="utf-8")
        content = strip_frontmatter(source)
        title = self._title_from_content(content)
        suggestion_id = f"sug_{uuid4().hex[:12]}"
        selected = self.source_selector.select_for_message(message_id=message_id, content=content)
        draft_result = await self.draft_service.create_draft(
            message_id=message_id,
            content=content,
            title=title,
            candidate_pages=selected["candidate_pages"],
            candidate_sources=selected["candidate_sources"],
        )
        draft = self._wrap_suggestion_markdown(
            suggestion_id=suggestion_id,
            title=draft_result.structured.title,
            source_message=message_id,
            markdown=draft_result.markdown,
        )

        tmp_dir = self.settings.data_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"{suggestion_id}.md"
        tmp_path.write_text(draft, encoding="utf-8")

        await self.rust.request(
            "complete_draft_job",
            {
                "data_dir": str(self.settings.data_dir),
                "sqlite_path": str(self.settings.sqlite_path),
                "job_id": job["id"],
                "suggestion_id": suggestion_id,
                "markdown_path": str(tmp_path),
                "title": draft_result.structured.title,
                "created_at": utc_now(),
            },
        )
        await write_audit_event(
            self.settings.sqlite_path,
            action="draft.generated",
            actor=AI_ACTOR,
            target_type="suggestion",
            target_id=suggestion_id,
            model_provider=draft_result.provider,
            model_name=draft_result.model,
            prompt_version=draft_result.prompt_version,
            metadata={
                "message_id": message_id,
                "job_id": job["id"],
                "title": draft_result.structured.title,
                "selection_reason": selected["selection_reason"],
                "candidate_pages": [page["slug"] for page in selected["candidate_pages"]],
                "candidate_sources": [source["source_key"] for source in selected["candidate_sources"]],
            },
        )

    async def _fail_job(self, job_id: str, code: str, message: str) -> None:
        await self.rust.request(
            "fail_job",
            {
                "sqlite_path": str(self.settings.sqlite_path),
                "job_id": job_id,
                "error_code": code,
                "error_message": message,
                "now": utc_now(),
            },
        )

    def _title_from_content(self, content: str) -> str:
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "Untitled note")
        return first_line[:48]

    def _wrap_suggestion_markdown(
        self,
        *,
        suggestion_id: str,
        title: str,
        source_message: str,
        markdown: str,
    ) -> str:
        now = utc_now()
        return (
            "---\n"
            "schema_version: 1\n"
            f"id: {suggestion_id}\n"
            f"title: {title}\n"
            "status: pending\n"
            f"source_message: {source_message}\n"
            f"created_at: {now}\n"
            f"updated_at: {now}\n"
            "---\n\n"
            f"{markdown}"
        )
