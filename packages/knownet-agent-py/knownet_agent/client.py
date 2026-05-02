from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

from .errors import (
    KnowNetAuthError,
    KnowNetConnectionError,
    KnowNetError,
    KnowNetPayloadTooLargeError,
    KnowNetRateLimitError,
    KnowNetScopeError,
    KnowNetServerError,
    KnowNetVersionError,
)
from .models import (
    SUPPORTED_SCHEMA_VERSION,
    KnowNetCitation,
    KnowNetFinding,
    KnowNetMeta,
    KnowNetPage,
    KnowNetReview,
)


@dataclass
class KnowNetResponse:
    data: dict[str, Any]
    meta: dict[str, Any]
    expires_in_seconds: int | None

    @property
    def meta_obj(self) -> KnowNetMeta:
        return KnowNetMeta.from_dict(self.meta)

    @property
    def truncated(self) -> bool:
        return self.meta_obj.truncated

    @property
    def total_count(self) -> int | None:
        return self.meta_obj.total_count

    @property
    def returned_count(self) -> int | None:
        return self.meta_obj.returned_count

    @property
    def next_offset(self) -> int | None:
        return self.meta_obj.next_offset

    def pages(self) -> list[KnowNetPage]:
        return [KnowNetPage.from_dict(item) for item in self.data.get("pages", [])]

    def page(self) -> KnowNetPage | None:
        page = self.data.get("page")
        return KnowNetPage.from_dict(page) if isinstance(page, dict) else None

    def reviews(self) -> list[KnowNetReview]:
        return [KnowNetReview.from_dict(item) for item in self.data.get("reviews", [])]

    def findings(self) -> list[KnowNetFinding]:
        return [KnowNetFinding.from_dict(item) for item in self.data.get("findings", [])]

    def citations(self) -> list[KnowNetCitation]:
        return [KnowNetCitation.from_dict(item) for item in self.data.get("citations", [])]


class KnowNetClient:
    def __init__(self, *, base_url: str = "http://127.0.0.1:8000", token: str, timeout: float = 30.0):
        if not token:
            raise ValueError("token is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._last_me: KnowNetResponse | None = None
        self._closed = False

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

    def __enter__(self) -> "KnowNetClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._closed = True

    def ping(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/ping", auth=False)

    def me(self) -> KnowNetResponse:
        response = self._request("GET", "/api/agent/me")
        self._last_me = response
        return response

    def state_summary(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/state-summary")

    def list_pages(self, limit: int = 20, offset: int | None = None) -> KnowNetResponse:
        return self._request("GET", "/api/agent/pages", query={"limit": limit, "offset": offset})

    def read_page(self, page_id: str) -> KnowNetResponse:
        return self._request("GET", f"/api/agent/pages/{urllib.parse.quote(page_id)}")

    def list_reviews(self, limit: int = 50, offset: int | None = None) -> KnowNetResponse:
        return self._request("GET", "/api/agent/reviews", query={"limit": limit, "offset": offset})

    def list_findings(self, limit: int = 100, offset: int | None = None, status: str | None = None) -> KnowNetResponse:
        return self._request("GET", "/api/agent/findings", query={"limit": limit, "offset": offset, "status": status})

    def graph_summary(self, limit: int = 200) -> KnowNetResponse:
        return self._request("GET", "/api/agent/graph", query={"limit": limit})

    def list_citations(self, limit: int = 100, offset: int | None = None, status: str | None = None) -> KnowNetResponse:
        return self._request("GET", "/api/agent/citations", query={"limit": limit, "offset": offset, "status": status})

    def get_context(self) -> KnowNetResponse:
        return self._request("GET", "/api/agent/context")

    def iter_pages(self, limit: int = 20, max_items: int | None = None) -> Iterator[KnowNetPage]:
        yield from self._iterate(lambda offset: self.list_pages(limit=limit, offset=offset), lambda response: response.pages(), max_items=max_items)

    def iter_reviews(self, limit: int = 50, max_items: int | None = None) -> Iterator[KnowNetReview]:
        yield from self._iterate(lambda offset: self.list_reviews(limit=limit, offset=offset), lambda response: response.reviews(), max_items=max_items)

    def iter_findings(self, limit: int = 100, status: str | None = None, max_items: int | None = None) -> Iterator[KnowNetFinding]:
        yield from self._iterate(lambda offset: self.list_findings(limit=limit, offset=offset, status=status), lambda response: response.findings(), max_items=max_items)

    def iter_citations(self, limit: int = 100, status: str | None = None, max_items: int | None = None) -> Iterator[KnowNetCitation]:
        yield from self._iterate(lambda offset: self.list_citations(limit=limit, offset=offset, status=status), lambda response: response.citations(), max_items=max_items)

    def require_scopes(self, required: list[str]) -> None:
        response = self.me()
        current = set(response.data.get("scopes") or [])
        missing = [scope for scope in required if scope not in current]
        if missing:
            payload = {"detail": {"message": "Required agent scopes are missing", "details": {"scope": missing[0], "current_scopes": sorted(current)}}}
            raise KnowNetScopeError("Required agent scopes are missing", status=403, payload=payload)

    def token_expires_soon(self, within_seconds: int = 604800) -> bool:
        response = self._last_me or self.me()
        seconds = response.expires_in_seconds or response.meta_obj.token_expires_in_seconds
        return seconds is not None and seconds <= within_seconds

    def read_context_for_review(self, max_pages: int = 5) -> list[KnowNetPage]:
        pages: list[KnowNetPage] = []
        for page in self.iter_pages(limit=min(max_pages, 20), max_items=max_pages):
            detailed = self.read_page(page.id).page()
            pages.append(detailed or page)
        return pages

    def dry_run_review(self, markdown: str, source_agent: str | None = None, source_model: str | None = None) -> KnowNetResponse:
        return self._review(markdown, source_agent, source_model, dry_run=True)

    def submit_review(self, markdown: str, source_agent: str | None = None, source_model: str | None = None) -> KnowNetResponse:
        return self._review(markdown, source_agent, source_model, dry_run=False)

    def dry_run_then_submit_review(self, markdown: str, source_agent: str | None = None, source_model: str | None = None) -> KnowNetResponse:
        dry_run = self.dry_run_review(markdown, source_agent=source_agent, source_model=source_model)
        if dry_run.data.get("parser_error") or dry_run.data.get("errors"):
            dry_run.meta["warning"] = "dry_run_failed_not_submitted"
            return dry_run
        if int(dry_run.data.get("finding_count") or 0) <= 0:
            dry_run.meta["warning"] = "dry_run_zero_findings_not_submitted"
            return dry_run
        return self.submit_review(markdown, source_agent=source_agent, source_model=source_model)

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

    def _iterate(self, fetch, extract, *, max_items: int | None):
        offset = 0
        yielded = 0
        while True:
            response = fetch(offset)
            items = extract(response)
            for item in items:
                if max_items is not None and yielded >= max_items:
                    return
                yielded += 1
                yield item
            if response.next_offset is None:
                return
            offset = response.next_offset

    def _request(self, method: str, path: str, *, query: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, auth: bool = True, retry_read: bool = True) -> KnowNetResponse:
        if self._closed:
            raise KnowNetError("KnowNetClient is closed")
        try:
            return self._request_once(method, path, query=query, payload=payload, auth=auth)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as error:
            if method == "GET" and retry_read:
                try:
                    return self._request_once(method, path, query=query, payload=payload, auth=auth)
                except urllib.error.URLError as retry_error:
                    raise KnowNetConnectionError(str(retry_error), payload={"detail": {"message": str(retry_error)}}) from retry_error
            raise KnowNetConnectionError(str(error), payload={"detail": {"message": str(error)}}) from error

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
                try:
                    payload_data = json.loads(response.read().decode("utf-8"))
                except json.JSONDecodeError as error:
                    raise KnowNetServerError("KnowNet returned malformed JSON") from error
                expires = response.headers.get("X-Token-Expires-In")
                result = KnowNetResponse(data=payload_data.get("data", payload_data), meta=payload_data.get("meta", {}), expires_in_seconds=int(expires) if expires else None)
                self._check_schema(result)
                return result
        except urllib.error.HTTPError as error:
            try:
                payload_data = json.loads(error.read().decode("utf-8"))
            except Exception:
                payload_data = {"detail": {"message": str(error)}}
            raise self._error_from_status(error.code, payload_data) from error

    def _check_schema(self, response: KnowNetResponse) -> None:
        version = response.meta_obj.schema_version
        if version is not None and version != SUPPORTED_SCHEMA_VERSION:
            raise KnowNetVersionError(f"Unsupported KnowNet schema_version: {version}", payload={"meta": response.meta})

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
