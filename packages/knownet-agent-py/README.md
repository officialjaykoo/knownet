# KnowNet Agent Python SDK

Python SDK for scoped KnowNet agent APIs.

```python
from knownet_agent import KnowNetClient

with KnowNetClient.from_env() as client:
    print(client.me().data)
    for page in client.iter_pages(max_items=5):
        print(page.title)
```

Required environment:

```txt
KNOWNET_AGENT_TOKEN=<token shown once by the operator dashboard>
KNOWNET_BASE_URL=http://127.0.0.1:8000
```

Optional:

```txt
KNOWNET_AGENT_TIMEOUT_SECONDS=30
```

## Install

```powershell
python -m pip install -e packages/knownet-agent-py
```

## Typed Responses

`KnowNetResponse.data` remains available as raw JSON-compatible data. For common
state, use typed helpers:

```python
response = client.list_pages()
pages = response.pages()
meta = response.meta_obj
```

Typed helpers include:

```txt
response.page()
response.pages()
response.reviews()
response.findings()
response.citations()
```

## Pagination

Use bounded iterators instead of unbounded reads:

```python
for finding in client.iter_findings(status="needs_more_context", max_items=50):
    print(finding.id, finding.title)
```

## Review Workflow

Use dry-run before submit:

```python
client.require_scopes(["reviews:create", "pages:read"])
pages = client.read_context_for_review(max_pages=5)
result = client.dry_run_then_submit_review(markdown, source_agent="my-agent")
```

`dry_run_then_submit_review` does not submit if parsing fails or if the dry-run
finds zero findings.

## Errors

Errors expose useful fields where the API provides them:

```python
try:
    client.require_scopes(["reviews:create"])
except KnowNetScopeError as error:
    print(error.required_scope, error.current_scopes)
```

Other useful properties:

```txt
KnowNetError.code
KnowNetError.request_id
KnowNetRateLimitError.retry_after_seconds
KnowNetPayloadTooLargeError.limit_hint
```

## Async

`AsyncKnowNetClient` is reserved for a later phase. Phase 12 completes the
synchronous SDK and keeps the code structured for a future native async client.

## Safety

The SDK does not read KnowNet's SQLite database and does not implement a second
auth model. Writes go through the existing KnowNet API. Do not hard-code agent
tokens in source files.
