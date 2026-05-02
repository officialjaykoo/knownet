# Qwen Integration

KnowNet supports Qwen through Qwen-Agent/MCP configuration first.

Qwen API access requires Alibaba Cloud DashScope / Model Studio signup. The
operator noted that free usage may be available after signup, but it is still an
account/API-key based path rather than anonymous web access.

## Best Path

```txt
Qwen-Agent
-> KnowNet MCP server
-> scoped KnowNet agent token
-> existing knownet_* tools
```

This matches the Qwen-Agent open-source pattern: Qwen-Agent can discover tools
from external MCP servers and expose them to the agent. KnowNet does not create
Qwen-specific tools or tables.

## Config

Use:

```txt
apps/mcp/configs/qwen_agent_mcp.example.json
```

Replace only placeholders:

```txt
KNOWNET_BASE_URL
KNOWNET_AGENT_TOKEN
```

Do not place `ADMIN_TOKEN`, database paths, backup paths, or raw secrets in the
Qwen config.

## Future API Runner Slot

KnowNet reserves these environment names for a later Qwen API runner:

```txt
QWEN_API_KEY
QWEN_RUNNER_ENABLED=false
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus
```

The API runner is not implemented yet. Current support is Qwen-Agent/MCP config
plus web fallback.

## Free Web Fallback

Qwen web can use GET preview or a generated review pack:

```powershell
python scripts\qwen_review_pack.py --copy
```

The web fallback is read-only and cannot perform JSON-RPC dry-run calls by
itself.
