import re
from pathlib import Path
from typing import Any

from ..db.sqlite import fetch_all, fetch_one
from .rust_core import RustCoreClient


WORD_RE = re.compile(r"[A-Za-z0-9가-힣_+-]{3,}")


def strip_frontmatter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown
    return markdown[end + 5 :]


class CitationVerifier:
    def __init__(self, *, sqlite_path: Path, rust: RustCoreClient) -> None:
        self.sqlite_path = sqlite_path
        self.rust = rust

    async def verify_page(self, *, page_id: str, revision_id: str | None, page_markdown: str) -> dict[str, Any]:
        citations = await fetch_all(
            self.sqlite_path,
            "SELECT id, citation_key FROM citations WHERE page_id = ? AND (revision_id IS ? OR revision_id = ?)",
            (page_id, revision_id, revision_id),
        )
        statuses = []
        for citation in citations:
            status = await self._verify_citation(citation["citation_key"], page_markdown)
            await self.rust.request(
                "update_citation_validation_status",
                {
                    "sqlite_path": str(self.sqlite_path),
                    "citation_id": citation["id"],
                    "status": status,
                },
            )
            statuses.append({"citation_key": citation["citation_key"], "validation_status": status})
        return {"checked": len(statuses), "statuses": statuses}

    async def verify_all(self, *, data_dir: Path) -> dict[str, Any]:
        pages = await fetch_all(self.sqlite_path, "SELECT id, path, current_revision_id FROM pages", ())
        results = []
        for page in pages:
            path = Path(page["path"])
            if not path.exists():
                continue
            results.append(
                {
                    "page_id": page["id"],
                    **await self.verify_page(
                        page_id=page["id"],
                        revision_id=page["current_revision_id"],
                        page_markdown=path.read_text(encoding="utf-8"),
                    ),
                }
            )
        return {
            "pages_checked": len(results),
            "citations_checked": sum(item["checked"] for item in results),
            "results": results,
        }

    async def _verify_citation(self, citation_key: str, page_markdown: str) -> str:
        message = await fetch_one(self.sqlite_path, "SELECT path FROM messages WHERE id = ?", (citation_key,))
        if not message:
            return "unsupported"
        path = Path(message["path"])
        if not path.exists():
            return "unsupported"
        source_text = strip_frontmatter(path.read_text(encoding="utf-8"))
        overlap = self._overlap_ratio(page_markdown, source_text)
        if overlap >= 0.35:
            return "supported"
        if overlap >= 0.15:
            return "partially_supported"
        return "unsupported"

    def _overlap_ratio(self, page_markdown: str, source_text: str) -> float:
        page_terms = self._terms(page_markdown)
        source_terms = self._terms(source_text)
        if not source_terms:
            return 0.0
        return len(page_terms & source_terms) / len(source_terms)

    def _terms(self, text: str) -> set[str]:
        return {match.group(0).lower() for match in WORD_RE.finditer(text)}
