# External AI Access Log

This file records practical external AI access tests for KnowNet.

It intentionally focuses on access method and observed result, not every finding
each AI produced.

## Current Test Endpoint

Temporary Cloudflare Quick Tunnel:

```txt
https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
```

Local target:

```txt
http://127.0.0.1:8010/mcp
```

Important:

```txt
This is testing-only infrastructure.
It is not a production endpoint.
```

## Access Modes

### Full MCP JSON-RPC

Clients that can POST JSON-RPC to `/mcp` can use the real KnowNet tools:

```txt
initialize
tools/list
tools/call
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_review_dry_run
```

This is the strongest external AI access path.

### GET Discovery / Preview

Clients that cannot POST can still read safe preview context:

```txt
GET /mcp
GET /mcp?resource=agent:onboarding
GET /mcp?resource=agent:state-summary
```

Limits:

```txt
No tool calls
No dry-run submission
No review submit
Read-only context only
```

## ChatGPT / Codex

Environment:

```txt
Codex shell
Cloudflare Quick Tunnel
KnowNet MCP HTTP bridge
```

Confirmed calls:

```txt
initialize
tools/list
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_review_dry_run
```

Result:

```txt
Full MCP JSON-RPC POST works.
Review dry-run works.
No real review was submitted during this test.
```

## ChatGPT PC Web

Environment:

```txt
ChatGPT PC Web
Custom MCP connector
Cloudflare Quick Tunnel
```

Configuration:

```txt
URL: https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
Authentication: none
```

Confirmed calls:

```txt
knownet_start_here
```

Result:

```txt
ChatGPT PC Web can use KnowNet when the custom MCP connector is registered.
Ordinary chats without the connector cannot see knownet_* tools.
```

## Claude

Working route:

```txt
Claude Desktop or claude.ai settings
-> Connectors / Integrations
-> Add custom MCP server
-> enter the KnowNet MCP URL directly
```

Configuration:

```txt
URL: https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
Authentication: none
```

Confirmed calls:

```txt
knownet_start_here
knownet_me
knownet_state_summary
```

Observed state:

```txt
token_id: agent_55b5a5bf6896
role: agent_reviewer
scopes: citations/read, findings/read, graph/read, pages/read, reviews/read, reviews/create
phase: 14
pages: 64
reviews: 13
findings: 59
graph_nodes: 630
release_ready: false
```

Important:

```txt
Uploading claude_desktop_config.json into a Claude chat is not the working path.
The working path is registering the MCP URL in Claude's connector/integration UI.
```

## DeepSeek Web / Desktop App

User observation:

```txt
DeepSeek web and desktop app are effectively the same for this purpose.
Differences are minor UI details such as shortcuts.
```

Free realistic route:

```txt
Use GET discovery and GET preview.
```

Useful URLs:

```txt
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary
```

Result:

```txt
DeepSeek free web/app can inspect KnowNet through GET preview.
It cannot perform JSON-RPC tool calls or review dry-run directly from the free web/app UI.
```

Recommended prompt for DeepSeek free web/app:

```txt
Use these KnowNet GET preview URLs:

1. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
2. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
3. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary

Review KnowNet as a first-time external AI contributor.
Do not submit a review.
Return findings in this format:

### Finding
Title:
Severity:
Area:
Evidence:
Proposed change:
```

Separate DeepSeek API runner status is recorded in
[MODEL_RUNS.md](MODEL_RUNS.md).

## Free Vs Paid/API Rule

Keep these paths separate. Do not mix them during testing.

```txt
Free web plan:
  Treat the AI as a manual document reviewer.
  Use GET preview when the web tool can browse.
  Prefer a generated review pack when the web tool is confused or cannot POST.
  The operator runs local helpers; the AI only reads pasted/uploaded results.

Paid/API or dedicated agent tool:
  Treat the AI as a provider behind KnowNet's controlled runner or as an MCP
  client if that product explicitly supports MCP.
  KnowNet still owns tool execution, safe context, dry-run parsing, and operator
  import.
  Never give raw database files, raw tokens, `.env`, backups, sessions, or whole
  filesystem access.
```

Provider rule of thumb:

```txt
Qwen free web:
  GET preview or `scripts\qwen_review_pack.py --copy`

Qwen paid/API/Qwen-Agent/Qwen Code:
  Implemented config/profile path:
  apps/mcp/configs/qwen_agent_mcp.example.json
  Use Qwen-Agent MCP as the preferred higher-capability route.

Kimi free web:
  `scripts\kimi_review_pack.py --copy` only. Do not ask it to decide MCP setup.

Kimi paid/API/Kimi Code/Playground:
  Implemented REST/model tool-calling runner:
  POST /api/model-runs/kimi/reviews
  Kimi Code/Playground MCP config remains available:
  apps/mcp/configs/kimi_mcp.example.json

MiniMax free web:
  `scripts\minimax_review_pack.py --copy`

MiniMax paid/API:
  Implemented REST/model tool-calling runner:
  POST /api/model-runs/minimax/reviews
  Live generation still requires account balance.

GLM free web:
  GET preview or pasted review pack if needed.

GLM paid/API:
  Implemented REST/model tool-calling runner:
  POST /api/model-runs/glm/reviews
  Live retry with replaced key reached provider quota check:
  glm_rate_limited / insufficient balance or missing resource package.

GLM Coding Plan / MCP-capable coding tools:
  Use KnowNet MCP endpoint directly with an agent token.

Manus paid/agent:
  Implemented config/profile path:
  apps/mcp/configs/manus_custom_mcp.example.json
  Use protected HTTPS Custom MCP or Custom API; do not use localhost.
```

## Qwen Web

User observation:

```txt
Qwen web can use built-in web_search / web_extractor style tools.
It does not need a separate Qwen API runner for the current free web test.
```

Free realistic route:

```txt
Use GET discovery and GET preview through Qwen's extractor/search tools.
If that is too manual, generate one pack with:
  python scripts\qwen_review_pack.py --copy
```

Useful URLs:

```txt
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
GET https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary
```

Result:

```txt
Qwen free web can inspect KnowNet through GET preview.
It cannot directly perform KnowNet JSON-RPC tool calls from the web UI.
It can still help generate or inspect a local MCP client script that the operator runs on this PC.
No Qwen API provider runner is needed at this stage.
```

Assisted local MCP mode:

```txt
Qwen Web
-> operator runs one local helper on the KnowNet PC
-> helper sends JSON-RPC POST calls to KnowNet /mcp
-> helper writes one paste-ready Markdown review pack
-> operator pastes or uploads that single file to Qwen
```

Easy mode:

```powershell
python scripts\qwen_review_pack.py --copy
```

This writes:

```txt
data/tmp/qwen-review-pack.md
```

and, with `--copy`, also places the full review pack on the Windows clipboard.
Paste it into Qwen free web and ask it to review the pack.

Manual mode is still available when debugging a single MCP call:

```powershell
python scripts\knownet_mcp_post_client.py --preset start-here
python scripts\knownet_mcp_post_client.py --preset state-summary
python scripts\knownet_mcp_post_client.py --preset tools
python scripts\knownet_mcp_post_client.py --preset ai-state
```

Use a tunnel URL when testing from outside the PC:

```powershell
python scripts\knownet_mcp_post_client.py --url https://dealers-spirituality-marker-compute.trycloudflare.com/mcp --preset start-here
```

Recommended prompt for Qwen free web:

```txt
Use web_extractor or equivalent browsing tools to read these KnowNet URLs:

1. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp
2. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:onboarding
3. https://dealers-spirituality-marker-compute.trycloudflare.com/mcp?resource=agent:state-summary

Review KnowNet as a first-time external AI contributor.
Do not submit a review.
Return findings in this format:

### Finding
Title:
Severity:
Area:
Evidence:
Proposed change:
```

## Kimi Web And Kimi Code

User observation:

```txt
Kimi web chat does not expose MCP directly.
It uses Moonshot/Kimi's own tool system, such as web search and browser visit.
Kimi Code CLI and Kimi Playground can register MCP servers.
Kimi has a desktop app, but the web chat itself should not be treated as a
direct KnowNet MCP client.
```

Actual test result:

```txt
Status: not useful enough for the current KnowNet review workflow.

What happened:
  Kimi web explained that it was not using MCP and instead used Moonshot/Kimi's
  own XML/function-calling style web tools.
  It then gave mixed guidance about desktop app, Kimi Code CLI, Playground MCP,
  and API support.

Operator judgment:
  Kimi web was not reliable enough to decide its own access method.
  Do not ask Kimi web to reason about MCP setup or live KnowNet connectivity.

Safe use:
  Treat Kimi web only as a pasted-document reviewer.
  It may read `data/tmp/kimi-review-pack.md` and produce finding drafts.
  It must not claim that it directly called KnowNet MCP/API unless an operator
  ran the local helper and pasted the resulting pack.
```

Practical split:

```txt
Kimi free web:
  Paste a generated review pack.
  GET discovery/preview may work, but do not rely on Kimi to choose the right
  access path by itself.

Kimi paid/API:
  Future Agent Runner path using OpenAI-compatible tool calls.

Kimi Code / Kimi Playground:
  Register KnowNet MCP and test direct tool calls there.
```

Easy mode for Kimi web:

```powershell
python scripts\kimi_review_pack.py --copy
```

This writes:

```txt
data/tmp/kimi-review-pack.md
```

and, with `--copy`, places the full review pack on the Windows clipboard.
Paste it into Kimi web and ask it to review the pack.

Recommended prompt for Kimi web:

```txt
You are not connected to KnowNet directly.
Do not claim that you called MCP, API, JSON-RPC, or local files.
Read only the pasted KnowNet review pack below.
Act as a first-time external AI reviewer and write finding drafts only.
```

Equivalent generic command:

```powershell
python scripts\knownet_review_pack.py --provider kimi --copy
```

Kimi Code MCP command shape to test later:

```bash
kimi mcp add --transport http knownet https://YOUR_KNOWNET_DOMAIN_OR_TUNNEL/mcp
kimi mcp list
```

## MiniMax

MiniMax observation:

```txt
MiniMax understood the protocol split clearly:
  KnowNet is an MCP JSON-RPC server.
  MiniMax API is a REST/model tool-calling surface.

Direct MiniMax API -> KnowNet MCP is not the right shape.
MiniMax needs one of:
  1. REST wrapper in front of KnowNet MCP
  2. MiniMax function-calling Agent Runner that executes KnowNet tools
  3. A higher-level bridge that translates MiniMax tool calls to KnowNet MCP
```

Current practical route:

```txt
MiniMax free web:
  Use pasted review pack or safe GET preview.

MiniMax paid/API:
  Implemented server-side model-runner path using OpenAI-compatible REST.
  The runner, not MiniMax itself, executes allowed KnowNet read tools.

Mini-Agent / MCP:
  Future higher-capability route after the shared Agent Runner contract is
  stable.
```

Easy mode for MiniMax web:

```powershell
python scripts\minimax_review_pack.py --copy
```

This writes:

```txt
data/tmp/minimax-review-pack.md
```

Equivalent generic command:

```powershell
python scripts\knownet_review_pack.py --provider minimax --copy
```

Recommended prompt for MiniMax web:

```txt
You are not connected to KnowNet directly.
Read only the pasted KnowNet review pack below.
Act as a first-time external AI reviewer and write finding drafts only.
Do not claim that you called MCP/API unless the data is present in the pack.
```

## Current Judgment

Confirmed:

```txt
ChatGPT/Codex: full MCP JSON-RPC works
ChatGPT PC Web: custom MCP connector works
Claude: connector/integration registration works
DeepSeek Web/Desktop free: GET discovery/preview works
Qwen Web free: GET discovery/preview works through extractor/search tools
Kimi Web: no direct MCP in web chat; too unreliable for access decisions; use generated review pack only
Kimi Code/Playground: MCP-capable path to test later
MiniMax: direct API-to-MCP mismatch understood; use review pack for web, REST/Agent Runner implemented for API path
```

Next infrastructure step:

```txt
Move from quick tunnel to named tunnel plus access control before production use.
```
