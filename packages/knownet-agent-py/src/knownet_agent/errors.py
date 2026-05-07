from __future__ import annotations

from typing import Any


class KnowNetError(Exception):
    def __init__(self, message: str, *, status: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}
        detail = self.payload.get("detail") or self.payload.get("error") or {}
        meta = self.payload.get("meta") or {}
        self.code = detail.get("code")
        self.request_id = meta.get("request_id") or detail.get("request_id")


class KnowNetAuthError(KnowNetError):
    pass


class KnowNetScopeError(KnowNetError):
    @property
    def required_scope(self) -> str | None:
        detail = self.payload.get("detail") or self.payload.get("error") or {}
        details = detail.get("details") or {}
        return detail.get("required_scope") or details.get("scope") or details.get("required_scope")

    @property
    def current_scopes(self) -> list[str]:
        detail = self.payload.get("detail") or self.payload.get("error") or {}
        details = detail.get("details") or {}
        return list(detail.get("current_scopes") or details.get("current_scopes") or [])


class KnowNetRateLimitError(KnowNetError):
    @property
    def retry_after_seconds(self) -> int | None:
        detail = self.payload.get("detail") or self.payload.get("error") or {}
        details = detail.get("details") or {}
        return detail.get("retry_after_seconds") or details.get("retry_after_seconds")


class KnowNetPayloadTooLargeError(KnowNetError):
    @property
    def limit_hint(self) -> str | None:
        detail = self.payload.get("detail") or self.payload.get("error") or {}
        details = detail.get("details") or {}
        return detail.get("limit_hint") or details.get("limit_hint")


class KnowNetServerError(KnowNetError):
    pass


class KnowNetConnectionError(KnowNetError):
    pass


class KnowNetVersionError(KnowNetError):
    pass
