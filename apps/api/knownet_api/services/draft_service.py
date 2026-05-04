import json
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError


DRAFT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "summary", "question", "claims", "evidence", "actions", "links", "citations"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "question": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "confidence", "source_keys"],
                "properties": {
                    "text": {"type": "string"},
                    "confidence": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "source_keys": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "source_keys"],
                "properties": {
                    "text": {"type": "string"},
                    "source_keys": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "actions": {"type": "array", "items": {"type": "string"}},
        "links": {"type": "array", "items": {"type": "string"}},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
}


class DraftClaim(BaseModel):
    text: str = Field(min_length=1)
    confidence: float | None = None
    source_keys: list[str] = Field(default_factory=list)


class DraftEvidence(BaseModel):
    text: str = Field(min_length=1)
    source_keys: list[str] = Field(default_factory=list)


class StructuredDraft(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1)
    question: str = Field(min_length=1)
    claims: list[DraftClaim] = Field(default_factory=list)
    evidence: list[DraftEvidence] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class DraftResult:
    markdown: str
    structured: StructuredDraft
    provider: str
    model: str
    prompt_version: str


class DraftService:
    prompt_version = "source-to-page-v1"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str = "https://api.openai.com/v1",
        model: str,
        reasoning_effort: str | None = "low",
        max_output_tokens: int = 2000,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds

    async def create_draft(
        self,
        *,
        message_id: str,
        content: str,
        title: str,
        candidate_pages: list[dict[str, Any]] | None = None,
        candidate_sources: list[dict[str, Any]] | None = None,
    ) -> DraftResult:
        if not self.api_key:
            structured = self._mock_draft(message_id=message_id, content=content, title=title)
            return DraftResult(
                markdown=self.to_markdown(structured, message_id),
                structured=structured,
                provider="mock",
                model="mock-draft-service",
                prompt_version=self.prompt_version,
            )

        structured = await self._openai_draft(
            message_id=message_id,
            content=content,
            candidate_pages=candidate_pages or [],
            candidate_sources=candidate_sources or [],
        )
        return DraftResult(
            markdown=self.to_markdown(structured, message_id),
            structured=structured,
            provider="openai",
            model=self.model,
            prompt_version=self.prompt_version,
        )

    async def _openai_draft(
        self,
        *,
        message_id: str,
        content: str,
        candidate_pages: list[dict[str, Any]],
        candidate_sources: list[dict[str, Any]],
    ) -> StructuredDraft:
        payload = {
            "model": self.model,
            "instructions": (
                "You are a knowledge page assistant. Produce JSON only through the provided schema. "
                "Use only the supplied message and candidate sources. Do not invent citations. "
                "Set confidence to null unless it is externally verified."
            ),
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "message": {"id": message_id, "content": content},
                                    "candidate_pages": candidate_pages[:2],
                                    "candidate_sources": candidate_sources[:5],
                                    "required_source_rule": "Claims and evidence must cite real source_keys.",
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "knownet_structured_draft",
                    "strict": True,
                    "schema": DRAFT_JSON_SCHEMA,
                }
            },
            "max_output_tokens": self.max_output_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(f"{self.base_url}/responses", headers=headers, json=payload)
        if response.status_code == 429:
            raise RuntimeError("draft_rate_limited")
        if response.status_code >= 400:
            raise RuntimeError(f"draft_openai_error: {response.status_code} {response.text[:500]}")

        data = response.json()
        text = data.get("output_text") or self._extract_output_text(data)
        if not text:
            raise RuntimeError("draft_schema_invalid: missing output_text")
        try:
            return StructuredDraft.model_validate_json(text)
        except ValidationError as error:
            raise RuntimeError(f"draft_schema_invalid: {error}") from error

    def _extract_output_text(self, data: dict[str, Any]) -> str:
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        return "".join(chunks)

    def _mock_draft(self, *, message_id: str, content: str, title: str) -> StructuredDraft:
        clean = content.strip()
        question = clean if clean.endswith("?") else f"What should be captured from {title}?"
        return StructuredDraft(
            title=title,
            summary=clean[:500] or title,
            question=question,
            claims=[DraftClaim(text=clean[:500] or title, confidence=None, source_keys=[message_id])],
            evidence=[DraftEvidence(text=clean[:500] or title, source_keys=[message_id])],
            actions=["Review the draft and connect it to related pages."],
            links=[],
            citations=[message_id],
        )

    def to_markdown(self, draft: StructuredDraft, message_id: str) -> str:
        lines = [
            f"# {draft.title}",
            "",
            "## Summary",
            "",
            draft.summary,
            "",
            "## Question",
            "",
            draft.question,
            "",
            "## Claims",
            "",
            *self._claim_lines(draft.claims),
            "",
            "## Evidence",
            "",
            *self._evidence_lines(draft.evidence),
            "",
            "## Next Actions",
            "",
            *([f"- {action}" for action in draft.actions] or ["- Review and refine this note."]),
            "",
            "## Related Pages",
            "",
            *([f"- [[{link}]]" for link in draft.links] or ["- None yet"]),
            "",
            "## Citations",
            "",
        ]
        citations = draft.citations or [message_id]
        lines.extend([f"- [^{key}]" for key in citations])
        lines.append("")
        lines.extend([f"[^{key}]: Source `{key}`." for key in citations])
        return "\n".join(lines).strip() + "\n"

    def _claim_lines(self, claims: list[DraftClaim]) -> list[str]:
        if not claims:
            return ["- No claims yet."]
        return [f"- {claim.text} {self._source_suffix(claim.source_keys)}".rstrip() for claim in claims]

    def _evidence_lines(self, evidence: list[DraftEvidence]) -> list[str]:
        if not evidence:
            return ["- No evidence yet."]
        return [f"- {item.text} {self._source_suffix(item.source_keys)}".rstrip() for item in evidence]

    def _source_suffix(self, source_keys: list[str]) -> str:
        return " ".join(f"[^{key}]" for key in source_keys)
