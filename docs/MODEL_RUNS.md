# Model Runs

This file records KnowNet-initiated model review runs.

External AIs that connect to KnowNet through MCP are recorded in
[EXTERNAL_AI_ACCESS_LOG.md](EXTERNAL_AI_ACCESS_LOG.md). Gemini is different:
KnowNet calls the Gemini API as an operator-controlled reviewer.

## Gemini Direction

Gemini web chat cannot reliably connect to local KnowNet MCP tools. KnowNet uses
the inverse flow:

```txt
KnowNet
-> build safe context
-> call Gemini API
-> receive structured JSON
-> convert to review Markdown
-> dry-run parse
-> operator chooses whether to import
```

Gemini never receives raw database files, local filesystem paths, sessions,
users, backups, raw tokens, token hashes, or `.env` values.

## Current State

As of 2026-05-03:

```txt
provider: gemini
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_local_model_after_test: gemini-2.5-flash
```

## Mock Run

Request shape:

```txt
POST /api/model-runs/gemini/reviews
mock: true
max_pages: 8
prompt_profile: gemini_external_reviewer_v1
```

Result:

```txt
run_id: modelrun_8627bc8d86ed
status: dry_run_ready
provider: gemini
model: gemini-2.5-pro
input_tokens: 6489
output_tokens: 266
finding_count: 2
parser_errors: none
```

Verified:

```txt
safe context builder works
secret/path guard passed
Gemini mock adapter works
model JSON -> review Markdown conversion works
review dry-run parser works
collaboration records were not created automatically
```

## Real API Test

After `GEMINI_API_KEY` was configured locally, KnowNet attempted a real Gemini
run with `mock=false`.

First attempt:

```txt
model: gemini-2.5-pro
status: failed
code: gemini_rate_limited
reason: free-tier quota for gemini-2.5-pro was 0 for this key
```

Second attempt:

```txt
model: gemini-2.5-flash
run_id: modelrun_df3692b778eb
status: dry_run_ready
mock: false
input_tokens: 1151
output_tokens: 375
finding_count: 1
parser_errors: none
```

The real Gemini result stayed in dry-run state. It was not imported into
`collaboration_reviews` or `collaboration_findings`.

Gemini finding title:

```txt
Path sandboxing requirements are not obvious from fallback specs
```

## Local Settings Needed

Use local `.env` only. Do not commit it.

```txt
GEMINI_API_KEY=<local secret>
GEMINI_RUNNER_ENABLED=true
GEMINI_MODEL=gemini-2.5-flash
```

`gemini-2.5-pro` may require billing or a plan with available quota.

## Safety Policy

```txt
Model output is never imported automatically.
Every provider result must become dry_run_ready first.
An operator/admin must explicitly import the run before it becomes a durable
collaboration review and findings.
```

## DeepSeek Direction

DeepSeek uses the same server-side model-runner pattern as Gemini:

```txt
KnowNet
-> build safe context
-> call DeepSeek Chat Completions API
-> request JSON output
-> normalize to review Markdown
-> dry-run parse
-> operator chooses whether to import
```

DeepSeek official docs describe an OpenAI-compatible API at
`https://api.deepseek.com/chat/completions` with `Authorization: Bearer ...`,
and JSON output through `response_format: {"type": "json_object"}`.

Current local state as of 2026-05-03:

```txt
provider: deepseek
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_model: deepseek-v4-flash
local_api_key: not configured
```

Mock smoke test:

```txt
run_id: modelrun_33835668fb06
status: dry_run_ready
finding_count: 1
parser_errors: none
```

Non-mock safety check without a local key:

```txt
status: blocked
code: deepseek_disabled
```

Real API attempt after `DEEPSEEK_API_KEY` was configured locally:

```txt
model: deepseek-v4-flash
run_id: modelrun_bdf7b8d76a6c
status: failed
code: deepseek_request_failed
reason: Insufficient Balance
```

Interpretation:

```txt
The local key was accepted far enough to reach the DeepSeek API.
The run did not produce a review because the DeepSeek account had no usable balance.
No collaboration review or finding was imported.
```

Local settings needed for a real run:

```txt
DEEPSEEK_API_KEY=<local secret>
DEEPSEEK_RUNNER_ENABLED=true
DEEPSEEK_MODEL=deepseek-v4-flash
```

Until a local key is present, non-mock DeepSeek calls are intentionally blocked
with `deepseek_disabled` or `deepseek_api_key_missing`.
