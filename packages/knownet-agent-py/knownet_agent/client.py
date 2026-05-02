from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class KnowNetError(Exception):
    def __init__(self, message: str, *, status: int | None = None, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class KnowNetAuthError(KnowNetError):
    pass


class KnowNetScopeError(KnowNetError):
    pass


class KnowNetRateLimitError(KnowNetError):
    @property
    def retry_after_seconds(self) -> int | None:
        detail = self.payload.get("detail") or {}
        details = detail.get("details") or {}
        return details.get("retry_after_seconds")


class KnowNetPayloadTooLargeError(KnowNetError):
    pass


class KnowNetServerError(KnowNetError):
    pass


@dataclass
class KnowNetResponse:
    data: dict[str, Any]
    meta: dict[str, Any]
    expires_in_seconds: int | None

    @property
    def truncated(self) -> bool:
        return bool(self.meta.get("truncated"))

    @property
    def total_count(self) -> int | None:
        return self.meta.get("total_count")

    @property
    def returned_count(self) -> int | None:
        return self.meta.get("returned_count")


class KnowNetClient:
    def __init__(self, *, base_url: str = "http://127.0.0.1:8000", token: str, timeout: float = 30.0):
        if not token:
            raise ValueError("token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "KnowNetClient":
        token = os.environ.get("KNOWNET_AGENT_TOKEN")
        if not token:
            raise ValueError("KNOWNET_AGENT_TOKEN is required")
        return cls(
            base_url=os.environ.get("KNOWNET_BASE_URL", "http://127.0.0.1:8000"),
            token=token,
            timeout=float(os.environ.get("KNOWNET_AGENT_TIMEOUT_SECONDS", "30")),
        )

    def ping(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/ping", auth=False)

    def me(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/me")

    def state_summary(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/state-summary")

    def list_pages(self, limit: int = 20) -> KnowNetResponse:
        return self._request("GET", "/api/agent/pages", query={"limit": limit})

    def read_page(self, page_id: str) -> KnowNetResponse:
        return self._request("GET", f"/api/agent/pages/{urllib.parse.quote(page_id)}")

    def list_reviews(self, limit: int = 50) -> KnowNetResponse:
        return self._request("GET", "/api/agent/reviews", query={"limit": limit})

    def list_findings(self, limit: int = 100) -> KnowNetResponse:
        return self._request("GET", "/api/agent/findings", query={"limit": limit})

    def graph_summary(self, limit: int = 200) -> KnowNetResponse:
        return self._request("GET", "/api/agent/graph", query={"limit": limit})

    def list_citations(self, limit: int = 100) -> KnowNetResponse:
        return self._request("GET", "/api/agent/citations", query={"limit": limit})

    def get_context(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/context")

    def dry_run_review(self, markdown: str, source_agent: str | None = None, source_model: str | None = None) -> KnowNetResponse:
        return self._review(markdown, source_agent, source_model, dry_run=True)

    def submit_review(self, markdown: str, source_agent: str | None = None, source_model: str | None = None) -> KnowNetResponse:
        return self._review(markdown, source_agent, source_model, dry_run=False)

    def submit_message(self, content: str) -> KnowNetResponse:
        return self._request("POST", "/api/messages", payload={"content": content})

    def _review(self, markdown: str, source_agent: str | None, source_model: str | None, *, dry_run: bool) -> KnowNetResponse:
        payload: dict[str, Any] = {"markdown": markdown}
        if source_agent:
            payload["source_agent"] = source_agent
        if source_model:
            payload["source_model"] = source_model
        path = "/api/collaboration/reviews?dry_run=true" if dry_run else "/api/collaboration/reviews"
        return self._request("POST", path, payload=payload)

    def _request(self, method: str, path: str, *, query: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, auth: bool = True, retry_read: bool = True) -> KnowNetResponse:
        try:
            return self._request_once(method, path, query=query, payload=payload, auth=auth)
        except urllib.error.URLError:
            if method == "GET" and retry_read:
                return self._request_once(method, path, query=query, payload=payload, auth=auth)
            raise

    def _request_once(self, method: str, path: str, *, query: dict[str, Any] | None, payload: dict[str, Any] | None, auth: bool) -> KnowNetResponse:
        clean_query = {key: value for key, value in (query or {}).items() if value is not None}
        url = self.base_url + path
        if clean_query:
            url += "?" + urllib.parse.urlencode(clean_query)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload_data = json.loads(response.read().decode("utf-8"))
                expires = response.headers.get("X-Token-Expires-In")
                return KnowNetResponse(data=payload_data.get("data", payload_data), meta=payload_data.get("meta", {}), expires_in_seconds=int(expires) if expires else None)
        except urllib.error.HTTPError as error:
            try:
                payload_data = json.loads(error.read().decode("utf-8"))
            except Exception:
                payload_data = {"detail": {"message": str(error)}}
            raise self._error_from_status(error.code, payload_data) from error

    def _error_from_status(self, status: int, payload: dict[str, Any]) -> KnowNetError:
        detail = payload.get("detail") or payload.get("error") or {}
        message = detail.get("message") or "KnowNet request failed"
        if status == 401:
            return KnowNetAuthError(message, status=status, payload=payload)
        if status == 403:
            return KnowNetScopeError(message, status=status, payload=payload)
        if status == 429:
            return KnowNetRateLimitError(message, status=status, payload=payload)
        if status == 413:
            return KnowNetPayloadTooLargeError(message, status=status, payload=payload)
        return KnowNetServerError(message, status=status, payload=payload)
