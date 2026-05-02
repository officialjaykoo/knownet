from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1


@dataclass
class KnowNetMeta:
    schema_version: int | None = None
    vault_id: str | None = None
    agent_scope: list[str] | None = None
    truncated: bool = False
    total_count: int | None = None
    returned_count: int | None = None
    next_offset: int | None = None
    generated_at: str | None = None
    request_id: str | None = None
    chars_returned: int | None = None
    warning: str | None = None
    token_expires_in_seconds: int | None = None
    token_warning: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "KnowNetMeta":
        data = value or {}
        return cls(
            schema_version=data.get("schema_version"),
            vault_id=data.get("vault_id"),
            agent_scope=list(data.get("agent_scope") or []),
            truncated=bool(data.get("truncated")),
            total_count=data.get("total_count"),
            returned_count=data.get("returned_count"),
            next_offset=data.get("next_offset"),
            generated_at=data.get("generated_at"),
            request_id=data.get("request_id"),
            chars_returned=data.get("chars_returned"),
            warning=data.get("warning"),
            token_expires_in_seconds=data.get("token_expires_in_seconds"),
            token_warning=data.get("token_warning"),
        )


@dataclass
class KnowNetPage:
    id: str
    slug: str | None = None
    title: str | None = None
    updated_at: str | None = None
    content: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowNetPage":
        return cls(id=value["id"], slug=value.get("slug"), title=value.get("title"), updated_at=value.get("updated_at"), content=value.get("content"))


@dataclass
class KnowNetReview:
    id: str
    title: str | None = None
    source_agent: str | None = None
    source_model: str | None = None
    status: str | None = None
    page_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowNetReview":
        return cls(
            id=value["id"],
            title=value.get("title"),
            source_agent=value.get("source_agent"),
            source_model=value.get("source_model"),
            status=value.get("status"),
            page_id=value.get("page_id"),
            created_at=value.get("created_at"),
            updated_at=value.get("updated_at"),
        )


@dataclass
class KnowNetFinding:
    id: str
    review_id: str | None = None
    severity: str | None = None
    area: str | None = None
    title: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowNetFinding":
        return cls(
            id=value["id"],
            review_id=value.get("review_id"),
            severity=value.get("severity"),
            area=value.get("area"),
            title=value.get("title"),
            status=value.get("status"),
            created_at=value.get("created_at"),
            updated_at=value.get("updated_at"),
        )


@dataclass
class KnowNetCitation:
    id: str
    page_id: str | None = None
    citation_key: str | None = None
    status: str | None = None
    verifier_type: str | None = None
    confidence: float | None = None
    reason: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowNetCitation":
        return cls(
            id=value["id"],
            page_id=value.get("page_id"),
            citation_key=value.get("citation_key"),
            status=value.get("status"),
            verifier_type=value.get("verifier_type"),
            confidence=value.get("confidence"),
            reason=value.get("reason"),
            updated_at=value.get("updated_at"),
        )
