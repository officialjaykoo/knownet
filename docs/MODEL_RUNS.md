# Model Runs

This file records KnowNet-initiated model review runs.

External AIs that connect through MCP are covered by
[MCP_CLIENTS.md](MCP_CLIENTS.md). This document is for server-side provider
runners where KnowNet builds sanitized context, calls a model API, stores the
result in `model_review_runs`, and waits for explicit operator import.

## Gemini Direction

Gemini is an API-key runner integration. KnowNet uses this flow:

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

The same runner path is used whether the API key has free quota or paid quota.
Do not describe Gemini as a manual web path.

## Current State

As of 2026-05-04:

```txt
provider: gemini
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_local_model_after_test: gemini-2.5-flash
operator_console: implemented in Phase 17
provider_matrix: implemented in Phase 17
release_readiness: implemented in Phase 17
```

## Phase 17 Operator Status

Phase 17 adds operator-facing status around model runs:

```txt
GET /api/operator/provider-matrix
GET /api/operator/ai-state-quality
GET /api/operator/release-readiness
```

Verification levels are conservative:

```txt
mocked:
  A mock run or mocked test path succeeded.

configured:
  Credentials/config are present, but no successful non-mock provider run has
  been recorded.

live_verified:
  A non-mock provider run reached dry_run_ready or imported through
  model_review_runs.

failed:
  Recent provider attempts failed and no stronger evidence is available.

unavailable:
  No implemented/configured route exists.
```

Mocked runs never upgrade a provider to `live_verified`.

Provider matrix also reports `latest_failure`, total failed runs, consecutive
failed runs, and a `stability_alert` flag when a provider reaches three
consecutive failed runs. This keeps transient GLM/DeepSeek/MiniMax/Kimi/Qwen
failures visible without treating access-limited findings as release blockers.
Model run responses include `duration_ms` for both successful dry-run results
and failed provider attempts so timeout/latency triage can distinguish a quick
auth/config failure from a slow provider response.

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
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_MODEL=gemini-2.5-flash
GEMINI_RESPONSE_MIME_TYPE=application/json
GEMINI_THINKING_BUDGET=0
GEMINI_TIMEOUT_SECONDS=90
```

`gemini-2.5-pro` may require billing or a plan with available quota.

KnowNet uses Google's native Gemini `generateContent` REST shape:

```txt
POST {GEMINI_BASE_URL}/models/{GEMINI_MODEL}:generateContent
x-goog-api-key: <GEMINI_API_KEY>
generationConfig.responseMimeType: application/json
generationConfig.responseJsonSchema: KnowNet review schema
generationConfig.thinkingConfig.thinkingBudget: GEMINI_THINKING_BUDGET
```

For fast daily review with `gemini-2.5-flash`, keep
`GEMINI_THINKING_BUDGET=0`. Increase or unset it only when the run needs more
reasoning depth and slower latency is acceptable.

Free and paid API keys use the same KnowNet code path. Free-tier limitations
such as rate limits or unavailable quota should be recorded as configured or
failed until a successful non-mock run reaches `dry_run_ready`.

## Safety Policy

```txt
Model output is never imported automatically.
Every provider result must become dry_run_ready first.
An operator/admin must explicitly import the run before it becomes a durable
collaboration review and findings.
```

## Non-Runner Client Paths

Some providers are better treated as MCP clients or pasted review-pack
reviewers instead of first-class API runners:

```txt
Manus:
  Use protected HTTPS Custom MCP or Custom API with a scoped agent token.
  Quick tunnels are testing-only and require an access gate before repeated use.

Qwen:
  Use Qwen-Agent with the KnowNet MCP server where possible. A future API
  runner may use DashScope-compatible OpenAI-style settings, but the current
  stable path is MCP plus scoped tokens.

Kimi:
  The Kimi/Moonshot API runner is implemented. Kimi Code or web/playground
  paths should be treated as MCP/client or pasted-review workflows, not as
  evidence of API live verification.
```

Keep provider-specific setup in the web Operator Console, `.env.example`, and
MCP config templates. Do not create new provider-specific docs unless the setup
has unique operational steps that cannot fit here.

For pasted-review fallback, use the generic helper instead of provider-specific
wrapper scripts:

```powershell
python scripts\knownet_review_pack.py --provider qwen --copy
python scripts\knownet_review_pack.py --provider kimi --copy
python scripts\knownet_review_pack.py --provider minimax --copy
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

DeepSeek official docs describe two compatible API bases:

```txt
OpenAI-compatible base_url: https://api.deepseek.com
Anthropic-compatible base_url: https://api.deepseek.com/anthropic
```

KnowNet uses the OpenAI-compatible surface for model review runs:
`POST https://api.deepseek.com/chat/completions` with
`Authorization: Bearer ...`, `response_format: {"type": "json_object"}`,
`reasoning_effort`, and `thinking`.

Current local state as of 2026-05-03:

```txt
provider: deepseek
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_model: deepseek-v4-flash
local_api_key: not configured
request_shape: OpenAI-compatible DeepSeek v4
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

Model catalog check:

```txt
GET https://api.deepseek.com/models
configured_model: deepseek-v4-flash
available_models:
- deepseek-v4-flash
- deepseek-v4-pro
configured_model_listed: true
```

Final DeepSeek test status:

```txt
status: integrated_but_unfunded
live_api_auth: verified
model_catalog: verified
mock_dry_run: verified
real_generation: blocked_by_balance
next_action: add DeepSeek balance/credits before retrying live generation
```

Local settings needed for a real run:

```txt
DEEPSEEK_API_KEY=<local secret>
DEEPSEEK_RUNNER_ENABLED=true
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_REASONING_EFFORT=high
DEEPSEEK_THINKING_ENABLED=true
```

Use `DEEPSEEK_MODEL=deepseek-v4-pro` when the run needs the stronger
DeepSeek v4 profile. `deepseek-chat` and `deepseek-reasoner` remain legacy
compatibility names and are documented by DeepSeek as deprecated after
2026-07-24.

Until a local key is present, non-mock DeepSeek calls are intentionally blocked
with `deepseek_disabled` or `deepseek_api_key_missing`.

## Qwen Direction

Qwen uses Alibaba Cloud DashScope OpenAI-compatible mode:

```txt
KnowNet
-> build safe context
-> call DashScope compatible-mode Chat Completions API
-> allow only read-only knownet_* tool calls inside the runner
-> request final structured JSON
-> normalize to review Markdown
-> dry-run parse
-> operator chooses whether to import
```

Official DashScope compatible mode uses:

```txt
POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
Authorization: Bearer <DASHSCOPE_API_KEY or QWEN_API_KEY>
model: qwen-plus
```

KnowNet uses `QWEN_API_KEY` for provider naming consistency. If an operator
already has `DASHSCOPE_API_KEY`, copy that value into `QWEN_API_KEY` locally.

Local settings:

```txt
QWEN_API_KEY=<local secret>
QWEN_RUNNER_ENABLED=true
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
QWEN_MAX_TOKENS=4000
QWEN_ENABLE_SEARCH=false
QWEN_TIMEOUT_SECONDS=90
```

Keep `QWEN_ENABLE_SEARCH=false` for KnowNet review runs. The model should use
only sanitized KnowNet context and read-only `knownet_*` tool calls.

## MiniMax Direction

MiniMax uses the same server-side model-runner pattern as Gemini and DeepSeek,
but its strongest API shape is OpenAI-compatible REST with tool calls:

```txt
KnowNet
-> build safe context
-> call MiniMax Chat Completions API
-> allow only read-only knownet_* tool calls inside the runner
-> request final structured JSON
-> normalize to review Markdown
-> dry-run parse
-> operator chooses whether to import
```

MiniMax official docs describe an OpenAI-compatible endpoint at
`https://api.minimaxi.com/v1/chat/completions`, Bearer auth, and tool calls through
the `tools` parameter. They also expose `reasoning_split` so reasoning content
can be separated from the final answer. The implementation follows that model
while keeping KnowNet as the tool executor.

Current local state as of 2026-05-03:

```txt
provider: minimax
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_model: MiniMax-M2.7
local_api_key: configured
request_shape: OpenAI-compatible MiniMax chat completions with tools
```

Local settings:

```txt
MINIMAX_API_KEY=<local secret>
MINIMAX_RUNNER_ENABLED=true
MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MINIMAX_MODEL=MiniMax-M2.7
MINIMAX_MAX_TOKENS=4000
MINIMAX_REASONING_SPLIT=true
MINIMAX_TIMEOUT_SECONDS=90
```

Mock smoke path:

```txt
POST /api/model-runs/minimax/reviews
mock: true
status: dry_run_ready
```

Non-mock safety:

```txt
MINIMAX_RUNNER_ENABLED=false blocks real calls by default.
MINIMAX_API_KEY is required before a live MiniMax run.
MiniMax output remains dry-run-ready until an operator imports it.
```

Real API attempt after `MINIMAX_API_KEY` was configured locally:

```txt
model: MiniMax-M2.7
run_id: modelrun_49c7425ceb87
status: failed
code: minimax_rate_limited
reason: insufficient balance (1008)
```

Interpretation:

```txt
The local key was accepted far enough to reach the MiniMax API.
The run did not produce a review because the MiniMax account had no usable
balance.
No collaboration review or finding was imported.
```

Allowed MiniMax runner tools:

```txt
knownet_state_summary
knownet_ai_state
knownet_list_findings
```

Forbidden:

```txt
maintenance, raw database, backups, shell/code execution, filesystem reads,
direct page writes, raw tokens, token hashes, sessions, users
```

## Kimi / Moonshot Direction

Kimi uses the same server-side model-runner pattern as MiniMax and GLM.
The web chat remains a pasted-pack fallback; the useful API shape is
Moonshot/Kimi's OpenAI-compatible chat completions endpoint:

```txt
KnowNet
-> build safe context
-> call Kimi / Moonshot Chat Completions API
-> allow only read-only knownet_* tool calls inside the runner
-> request final structured JSON
-> normalize to review Markdown
-> dry-run parse
-> operator chooses whether to import
```

Kimi official docs describe `https://api.moonshot.ai/v1/chat/completions`,
Bearer auth, OpenAI SDK compatibility, and API-key based access. K2.5 docs use
`max_tokens` and allow explicit `thinking` control. KnowNet keeps tool
execution local and sends only sanitized context.

Kimi API keys require paid/API access. The free Kimi web plan is a manual
review-pack fallback and cannot live-test this runner.

Current local state as of 2026-05-03:

```txt
provider: kimi
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_model: kimi-k2.5
local_api_key: not verified
live_verification: blocked until paid/API key is available
request_shape: OpenAI-compatible Kimi chat completions with tools
```

Local settings:

```txt
KIMI_API_KEY=<local secret>
KIMI_RUNNER_ENABLED=true
KIMI_BASE_URL=https://api.moonshot.ai/v1
KIMI_MODEL=kimi-k2.5
KIMI_MAX_TOKENS=4000
KIMI_THINKING_ENABLED=false
KIMI_TIMEOUT_SECONDS=90
```

Mock smoke path:

```txt
POST /api/model-runs/kimi/reviews
mock: true
status: dry_run_ready
```

Non-mock safety:

```txt
KIMI_RUNNER_ENABLED=false blocks real calls by default.
KIMI_API_KEY is required before a live Kimi run.
Kimi output remains dry-run-ready until an operator imports it.
```

Allowed Kimi runner tools:

```txt
knownet_state_summary
knownet_ai_state
knownet_list_findings
```

Forbidden:

```txt
maintenance, raw database, backups, shell/code execution, filesystem reads,
direct page writes, raw tokens, token hashes, sessions, users
```

## GLM / Z.AI Direction

GLM uses the same server-side model-runner pattern as MiniMax:

```txt
KnowNet
-> build safe context
-> call Z.AI Chat Completions API
-> allow only read-only knownet_* tool calls inside the runner
-> request final structured JSON
-> normalize to review Markdown
-> dry-run parse
-> operator chooses whether to import
```

Z.AI official docs describe an OpenAI-compatible endpoint at
`https://api.z.ai/api/paas/v4/chat/completions`, Bearer auth, tool calls through
the `tools` parameter, and structured output via
`response_format: {"type":"json_object"}`. KnowNet sets `max_tokens` explicitly
and keeps thinking disabled by default for fast review runs.

Current local state as of 2026-05-03:

```txt
provider: glm
real_adapter: implemented
mock_adapter: working
operator_import_required: true
default_model: glm-5.1
local_api_key: configured
request_shape: OpenAI-compatible Z.AI chat completions with tools
```

Local settings:

```txt
GLM_API_KEY=<local secret>
GLM_RUNNER_ENABLED=true
GLM_BASE_URL=https://api.z.ai/api/paas/v4
GLM_MODEL=glm-5.1
GLM_MAX_TOKENS=4000
GLM_THINKING_ENABLED=false
GLM_TIMEOUT_SECONDS=90
```

Mock smoke path:

```txt
POST /api/model-runs/glm/reviews
mock: true
status: dry_run_ready
```

Non-mock safety:

```txt
GLM_RUNNER_ENABLED=false blocks real calls by default.
GLM_API_KEY is required before a live GLM run.
GLM output remains dry-run-ready until an operator imports it.
```

First real API attempt after `GLM_API_KEY` was configured locally:

```txt
model: glm-5.1
status: failed
code: glm_auth_failed
reason: Authentication Failed
```

Endpoint checks with the same key:

```txt
GET https://api.z.ai/api/paas/v4/models
status: 401
reason: Authentication Failed

GET https://api.z.ai/api/coding/paas/v4/models
status: 401
reason: Authentication Failed
```

Interpretation:

```txt
The local value in GLM_API_KEY was not accepted as a Z.AI Bearer API key on
either the general API endpoint or the coding endpoint.
The runner wiring is implemented, but live GLM generation is blocked until the
operator provides a valid Z.AI API key for the selected endpoint.
No collaboration review or finding was imported.
```

Second real API attempt after replacing the local key:

```txt
model: glm-5.1
status: failed
code: glm_rate_limited
reason: Insufficient balance or no resource package. Please recharge.
```

Interpretation:

```txt
The replacement key passed the basic authentication boundary and reached the
provider account/quota check. Live GLM generation is still blocked by account
balance or missing resource package, not by KnowNet runner wiring.
No collaboration review or finding was imported.
```

Allowed GLM runner tools:

```txt
knownet_state_summary
knownet_ai_state
knownet_list_findings
```

Forbidden:

```txt
maintenance, raw database, backups, shell/code execution, filesystem reads,
direct page writes, raw tokens, token hashes, sessions, users
```
