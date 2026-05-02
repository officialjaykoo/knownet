# SDK Client Setup

The Python SDK is for custom scripts and non-MCP agents that need scoped
KnowNet access.

Install locally:

```powershell
python -m pip install -e packages/knownet-agent-py
```

Environment:

```txt
KNOWNET_BASE_URL=http://127.0.0.1:8000
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_AGENT_TIMEOUT_SECONDS=30
```

## Basic Read

```python
from knownet_agent import KnowNetClient

with KnowNetClient.from_env() as client:
    client.require_scopes(["pages:read"])
    for row in client.iter_ai_state(max_items=10):
        print(row["slug"], row["state"]["summary"])
    for page in client.iter_pages(max_items=10):
        print(page.id, page.title)
```

## Safe Review Flow

```python
from knownet_agent import KnowNetClient

with KnowNetClient.from_env() as client:
    client.require_scopes(["reviews:create", "pages:read"])
    if client.token_expires_soon():
        print("Rotate this token before a long review.")
    pages = client.read_context_for_review(max_pages=5)
    markdown = build_review_markdown(pages)
    result = client.dry_run_then_submit_review(markdown, source_agent="my-agent")
    print(result.data, result.meta)
```

`dry_run_then_submit_review` submits only when dry-run parsing succeeds and the
review contains at least one finding.

## Pagination

Use `iter_ai_state`, `iter_pages`, `iter_reviews`, `iter_findings`, and
`iter_citations` with `max_items`. The SDK follows `meta.next_offset` and stops
when there is no next page.

## Error Handling

Useful error properties:

```txt
KnowNetScopeError.required_scope
KnowNetScopeError.current_scopes
KnowNetRateLimitError.retry_after_seconds
KnowNetError.request_id
```

## Async

Phase 12 does not implement async HTTP. `AsyncKnowNetClient` is reserved for a
later native async client and currently raises `NotImplementedError`.

## Safety

The SDK uses scoped HTTP APIs only. It does not access local database files,
operator-only routes, or shell commands. Keep tokens in environment variables.
