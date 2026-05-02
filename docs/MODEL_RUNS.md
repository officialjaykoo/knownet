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
