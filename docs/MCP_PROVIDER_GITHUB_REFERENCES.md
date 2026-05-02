# MCP Provider GitHub References

This document records GitHub repositories and docs that are useful only for
connecting external AI clients/providers to KnowNet through MCP, HTTP tools, or
provider-side tool calling. It is not a feature roadmap for KnowNet's
collaboration model.

## Classification

```txt
official:
  Maintained by the provider or by the MCP project itself.

semi_official:
  Maintained by a closely related ecosystem project or commonly referenced
  integration repo.

community:
  Useful implementation example, but do not copy code without license review.

not_found:
  No strong official GitHub integration repo found during this search.
```

## 1. ChatGPT / OpenAI

Best GitHub references:

- https://github.com/openai/openai-apps-sdk-examples
- https://github.com/modelcontextprotocol/typescript-sdk
- https://github.com/modelcontextprotocol/example-remote-server

Useful lessons:

- ChatGPT connector path expects a public MCP URL.
- Local development normally uses a tunnel such as ngrok/cloudflared.
- MCP tool results can include structured content and UI metadata, but KnowNet
  should keep review/finding flows text/JSON-first for now.
- DNS rebinding / allowed host settings matter when using SDK servers behind a
  tunnel.

KnowNet action:

```txt
Keep:
  /mcp HTTP bridge
  GET discovery
  search/fetch fallback
  short-lived tunnel token test flow

Do not add yet:
  ChatGPT Apps SDK widgets
  in-chat dashboard UI
```

## 2. Claude / Anthropic

Best GitHub references:

- https://github.com/modelcontextprotocol/servers
- https://github.com/modelcontextprotocol/typescript-sdk
- https://github.com/modelcontextprotocol/example-remote-server

Useful lessons:

- Local stdio remains the strongest Claude Desktop-style route.
- Config examples should use `command`, `args`, and `env`.
- MCP Roots / filesystem-like access should remain constrained; KnowNet should
  not expose broad PC filesystem tools.

KnowNet action:

```txt
Keep:
  apps/mcp/knownet_mcp/server.py as stdio server
  Claude Desktop config template
  token in env only

Next possible:
  .mcpb package after plain stdio setup is stable
```

## 3. Gemini

Best GitHub references:

- https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md
- https://github.com/google-gemini/gemini-cli
- https://github.com/GoogleCloudPlatform/gemini-cloud-assist-mcp
- https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-gemini-cli.md

Useful lessons:

- Gemini CLI has `mcpServers` config.
- It supports stdio, SSE, and Streamable HTTP-style transports.
- The `/mcp` status/list command pattern is useful for diagnostics.
- Trust/confirmation settings must be explicit.

KnowNet action:

```txt
Add:
  Gemini CLI settings.json template for KnowNet MCP
  notes about trust=false by default

Do not confuse:
  Gemini CLI MCP client support
  with Gemini web chat, which cannot call local MCP
```

## 4. Manus

Best GitHub references:

- https://github.com/nanameru/Manus-MCP
- https://github.com/gianlucamazza/mcp-manus-server
- https://github.com/kyopark2014/mcp-manus

Useful lessons:

- Manus-style integrations are usually API/HTTPS gateway based.
- Repos emphasize canonical server names, env-based API keys, Cursor/Claude
  config examples, and troubleshooting.
- Some Manus API paths are still private-beta/mock in community repos, so treat
  live behavior as unverified until tested.

KnowNet action:

```txt
Add:
  Manus Custom MCP/API profile doc
  read-only first policy
  scoped token examples

Do not add:
  Manus task orchestration into KnowNet core
```

## 5. DeepSeek

Best GitHub references found:

- https://github.com/aiamblichus/mcp-chat-adapter
- https://github.com/lgcyaxi/oh-my-claude
- https://github.com/grll/mcpadapt

Status:

```txt
official DeepSeek-specific MCP client/server repo:
  not_found in this pass

usable route:
  OpenAI-compatible chat/tool runner
  function-calling style wrapper
  generic MCP adapter libraries
```

Useful lessons:

- Treat DeepSeek as an API/provider behind a KnowNet-controlled runner.
- Use OpenAI-compatible adapters rather than provider-specific MCP tools.
- Validate tool arguments before calling KnowNet.

KnowNet action:

```txt
Implement later:
  shared provider runner adapter
  tools.deepseek.json generated from common schema

Do not add:
  deepseek_* MCP tool family
```

## 6. Qwen

Best GitHub references:

- https://github.com/QwenLM/Qwen-Agent
- https://github.com/QwenLM/qwen-code

Useful lessons:

- Qwen-Agent supports function calling, tools, RAG, code interpreter, and MCP.
- Qwen-Agent can use an MCP config containing `mcpServers`.
- This is one of the strongest open provider-side integration paths.

KnowNet action:

```txt
Add later:
  qwen-agent config template
  qwen tool schema generated from common KnowNet tools

Keep:
  common knownet_* MCP family
```

## 7. Kimi / Moonshot

Best GitHub references:

- https://github.com/MoonshotAI/kimi-cli

Useful lessons:

- Kimi Code CLI supports MCP.
- It supports `kimi mcp add --transport http ...` and stdio server configs.
- It can load an MCP config file.

KnowNet action:

```txt
Add:
  kimi MCP config template
  HTTP and stdio examples

Do not assume:
  Kimi web chat has the same MCP capability
```

## 8. MiniMax

Best GitHub references:

- https://github.com/MiniMax-AI/Mini-Agent
- https://github.com/PsychArch/minimax-mcp-tools

Useful lessons:

- Mini-Agent is the useful direction for KnowNet, not the media-oriented
  MiniMax MCP servers.
- Mini-Agent repo emphasizes MCP loading tests and agent execution pipelines.
- Third-party MiniMax MCP tools are useful for async/rate-limit design, but not
  for KnowNet's data access model.

KnowNet action:

```txt
Add later:
  minimax-agent config template
  read-only HTTP tool profile

Do not add:
  media generation tools
```

## 9. GLM / Z.AI

Best GitHub references:

- https://github.com/geoh/z.ai-powered-claude-code
- https://github.com/lgcyaxi/oh-my-claude
- https://github.com/grll/mcpadapt

Status:

```txt
official GLM KnowNet-style MCP client repo:
  not_found in this pass

strong route:
  GLM Coding Plan or compatible coding clients
  connected to KnowNet MCP
```

Useful lessons:

- GLM is best treated as a model behind existing MCP-capable coding tools.
- Provider routing wrappers can support GLM, DeepSeek, MiniMax, Kimi, and Qwen
  without changing the KnowNet MCP tool family.

KnowNet action:

```txt
Add later:
  glm provider-runner config template
  MCP-capable coding-tool setup note

Do not add:
  GLM-specific live-state endpoints
```

## Shared Repositories Worth Tracking

- https://github.com/modelcontextprotocol/typescript-sdk
- https://github.com/modelcontextprotocol/servers
- https://github.com/modelcontextprotocol/example-remote-server
- https://github.com/grll/mcpadapt
- https://github.com/mcp-use
- https://github.com/github/github-mcp-server
- https://github.com/steipete/mcporter

Shared lessons:

```txt
1. Generate client templates from one canonical tool schema.
2. Keep stdio and HTTP bridge profiles separate.
3. Prefer env-held tokens over prompt-held tokens.
4. Keep GET preview read-only.
5. Use smoke tests before claiming support.
6. Do not multiply provider-specific MCP tools.
```

