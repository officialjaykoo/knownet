# MCP Compatibility References

This document is intentionally narrow. It records only MCP connection lessons
that KnowNet should reuse. It does not import another product's collaboration,
issue tracking, graph, memory, or database model.

## Scope

Use external projects and docs for:

- MCP transport patterns: stdio, Streamable HTTP, GET discovery, JSON-RPC POST.
- MCP surface shape: tools, resources, prompts, strict schemas, diagnostics.
- Client setup examples for desktop, coding, and remote connector clients.
- Gateway/wrapper patterns that convert local stdio servers to HTTP when needed.

Do not use them for:

- KnowNet data model.
- Review/finding workflow.
- Page storage.
- Dashboard features.
- Multi-agent orchestration.
- Broad filesystem access.

## References To Learn From

### Official MCP SDK And Examples

Reference:

```txt
modelcontextprotocol/typescript-sdk
modelcontextprotocol official examples
```

What to reuse:

- Keep tools/resources/prompts as separate MCP surfaces.
- Keep input schemas strict and machine-readable.
- Support stdio for local clients and HTTP for remote/gateway clients.
- Keep examples executable and minimal.

KnowNet status:

```txt
Implemented:
  - tools/list, tools/call
  - resources/list, resources/read
  - prompts/list, prompts/get
  - strict additionalProperties=false schemas
  - stdio server
  - HTTP bridge with JSON-RPC POST /mcp

Still useful:
  - broader Streamable HTTP compatibility testing with MCP Inspector/client
  - packaged examples for more clients
```

### Claude Desktop Local MCP Pattern

Reference:

```txt
Claude Desktop local MCP server configuration
Claude Code MCP stdio examples
```

What to reuse:

- Prefer local stdio for desktop clients.
- Store tokens in environment variables, not prompts.
- Let the client launch the MCP process with command/args/env.
- Treat remote HTTP as a different path from desktop local MCP.

KnowNet rule:

```txt
Claude Desktop / Cursor / local coding clients:
  Use apps/mcp/knownet_mcp/server.py over stdio.
  Do not require Cloudflare.
  Do not expose raw DB files.
```

### Gateway Pattern

Reference:

```txt
Supergateway-style stdio-to-HTTP bridge pattern
official Streamable HTTP examples
```

What to reuse:

- A small bridge can expose an MCP server over HTTP for clients that need a URL.
- HTTP GET can safely expose discovery and preview resources.
- Real tools still use JSON-RPC POST.

KnowNet rule:

```txt
HTTP bridge:
  /mcp GET = discovery
  /mcp?resource=agent:onboarding = safe preview
  /mcp?resource=agent:state-summary = safe preview
  /mcp POST = JSON-RPC MCP

Review dry-run and submit stay POST-only.
```

### Web-Only AI Fallback

Reference:

```txt
External AI tests captured in docs/EXTERNAL_AI_ACCESS_LOG.md
```

What to reuse:

- Some web AIs can only GET pages.
- Some can read `/mcp` discovery but cannot POST JSON-RPC.
- Some hallucinate unrelated public repositories when live tools are unavailable.

KnowNet rule:

```txt
If knownet_* tools are unavailable:
  1. Read GET /mcp.
  2. Read GET /mcp?resource=agent:onboarding.
  3. Read GET /mcp?resource=agent:state-summary.
  4. Mark review_source=get_preview_only.
  5. Do not treat GitHub repo preview as live KnowNet state.
```

## Client Profiles

| Client class | Best path | Realistic free/test path | KnowNet surface |
|---|---|---|---|
| ChatGPT PC app | Custom MCP connector over protected HTTP bridge | Quick tunnel test | `/mcp` HTTP bridge |
| Claude Desktop | Local stdio MCP | Local stdio MCP if desktop MCP is available | `apps/mcp/knownet_mcp/server.py` |
| Cursor / local coding clients | Local stdio MCP | Local stdio MCP | `apps/mcp/knownet_mcp/server.py` |
| Manus | HTTPS Custom MCP or Custom API | GET preview unless Custom MCP/API is configured | protected HTTP gateway |
| DeepSeek/Qwen/Kimi/MiniMax/GLM API runners | Provider tool-calling runner that calls KnowNet | mocked runner / GET preview | Phase 16 runner + KnowNet API/MCP |
| Web-only AI chat | None for live POST | GET preview and copied JSON | `/mcp?resource=...` |

## Compatibility Checklist

Before claiming a client is supported:

```txt
1. tools/list works or GET discovery works.
2. knownet_start_here works or onboarding preview works.
3. knownet_me works if authenticated tool calls are supported.
4. knownet_state_summary or state-summary preview works.
5. knownet_review_dry_run works before knownet_submit_review.
6. token is scoped and never appears in output/logs.
7. request_id appears in errors or logs.
8. client failure mode is documented:
     live_mcp_post
     get_preview_only
     static_spec_fallback
```

## Implementation Guidance

Keep one MCP tool family:

```txt
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_list_pages
knownet_read_page
knownet_list_reviews
knownet_list_findings
knownet_graph_summary
knownet_list_citations
knownet_review_dry_run
knownet_submit_review
```

Do not create provider-specific MCP tools such as:

```txt
deepseek_read_state
qwen_submit_review
kimi_find_pages
```

Provider-specific work belongs in Phase 16 model adapters, not in the MCP
surface.

