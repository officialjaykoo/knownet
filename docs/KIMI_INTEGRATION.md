# Kimi Integration

KnowNet supports Kimi through two separate paths.

## API Runner

```txt
POST /api/model-runs/kimi/reviews
```

The runner calls Moonshot/Kimi's OpenAI-compatible chat completions endpoint
with sanitized KnowNet context. Kimi may request only these read-only tools
inside the runner:

```txt
knownet_state_summary
knownet_ai_state
knownet_list_findings
```

The run stays in `dry_run_ready` until an operator imports it. Kimi cannot write
pages, apply suggestions, access maintenance, read raw database files, or see
secrets.

Environment:

```txt
KIMI_API_KEY
KIMI_RUNNER_ENABLED=false
KIMI_BASE_URL=https://api.moonshot.ai/v1
KIMI_MODEL=kimi-k2-0905-preview
```

## Kimi Code / Playground MCP

Use:

```txt
apps/mcp/configs/kimi_mcp.example.json
```

This path is unverified until the operator tests Kimi Code or Kimi Playground.

## Free Web Fallback

Kimi web should be treated as a pasted-document reviewer:

```powershell
python scripts\kimi_review_pack.py --copy
```

Do not ask Kimi web to decide whether it is connected to MCP.
