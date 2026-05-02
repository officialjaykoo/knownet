# Manus Integration

KnowNet supports Manus through protected HTTPS Custom MCP or Custom API
configuration.

## Best Path

```txt
Manus
-> Custom MCP Server or Custom API
-> protected HTTPS KnowNet gateway
-> scoped KnowNet agent token
-> existing knownet_* tools or read-only agent API
```

Manus is not a localhost desktop client. Do not configure it with local paths or
raw database access.

## Config

Use:

```txt
apps/mcp/configs/manus_custom_mcp.example.json
```

The endpoint must be a protected HTTPS domain. Quick tunnels are testing-only.

## Observed Test

The operator connected Manus through:

```txt
Settings -> Connectors -> URL connection
```

Using the KnowNet MCP URL was enough for initial setup. The MCP bridge logs
confirmed successful calls:

```txt
knownet_start_here
knownet_me
knownet_state_summary
knownet_ai_state
knownet_list_pages
knownet_read_page
```

Status:

```txt
connector registration: works
read-only MCP calls: work
infrastructure: quick tunnel, testing-only
production blocker: named tunnel + access control still required
```

## Safety Rules

```txt
Start read-only.
Use scoped bearer tokens.
Do not provide ADMIN_TOKEN.
Do not provide raw database files.
Do not expose backups, sessions, users, token hashes, raw tokens, or local paths.
Do not enable write access until read-only behavior is verified.
```

## Free / No-Connector Fallback

Without Manus Custom MCP/API setup, use only GET preview or a pasted review
pack. Manus should not be expected to reach localhost.
