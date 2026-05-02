import re
from pathlib import Path
from typing import Any

from ..paths import page_storage_dir

WORD_RE = re.compile(r"[A-Za-z0-9가-힣_+-]{2,}")


class SourceSelector:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def select_for_message(self, *, message_id: str, content: str) -> dict[str, Any]:
        return {
            "candidate_sources": [{"source_key": message_id, "source_type": "message", "text": content[:2000]}],
            "candidate_pages": self._keyword_pages(content),
            "selection_reason": "message source + keyword page match",
        }

    def _keyword_pages(self, content: str) -> list[dict[str, Any]]:
        terms = self._terms(content)
        if not terms:
            return []

        scored: list[tuple[int, str, dict[str, Any]]] = []
        pages_dir = page_storage_dir(self.data_dir)
        for path in sorted(pages_dir.glob("*.md")):
            if path.name == ".gitkeep":
                continue
            try:
                markdown = path.read_text(encoding="utf-8")
            except OSError:
                continue
            haystack = f"{path.stem}\n{markdown}".lower()
            score = sum(haystack.count(term) for term in terms)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    path.stem,
                    {
                        "source_key": f"page:{path.stem}",
                        "slug": path.stem,
                        "path": str(path).replace("\\", "/"),
                        "text": self._truncate(markdown),
                        "score": score,
                    },
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:2]]

    def _terms(self, content: str) -> list[str]:
        seen: set[str] = set()
        terms: list[str] = []
        for match in WORD_RE.finditer(content.lower()):
            term = match.group(0)
            if term not in seen:
                seen.add(term)
                terms.append(term)
        return terms[:20]

    def _truncate(self, markdown: str) -> str:
        body = markdown.strip()
        if len(body) <= 2000:
            return body
        return body[:2000].rstrip() + "\n...[truncated]"
