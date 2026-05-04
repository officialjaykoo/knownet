# KnowNet MCP Scope

KnowNet's MCP target is a real, minimal MCP server for external AI
collaboration. The server should let MCP clients read compact KnowNet state and
submit bounded proposals. It must not let AI operate KnowNet.

## Completion Line

KnowNet MCP is sufficient when an MCP client can:

1. Call `initialize` and receive `serverInfo`, `protocolVersion`, and
   capabilities for resources, tools, and prompts.
2. Call `resources/list` and discover safe KnowNet resources.
3. Call `resources/read` and read compact JSON resources without raw database,
   filesystem, backup, session, user, or token exposure.
4. Call `tools/list` and discover proposal-only tools.
5. Call `tools/call` to propose findings, propose tasks, or submit
   implementation evidence as operator-gated drafts.
6. Call `prompts/list` and `prompts/get` for reusable review prompts.

That is the line. Anything beyond it needs a separate phase and evidence that
the lightweight path failed.

## Required Resources

Expose these resource names through `resources/list` where the backing data is
available:

```txt
knownet://snapshot/overview
knownet://snapshot/stability
knownet://snapshot/performance
knownet://snapshot/security
knownet://snapshot/implementation
knownet://snapshot/provider_review
knownet://node/{slug_or_page_id}
knownet://finding/recent
```

Existing `knownet://agent/...` resources may remain as aliases for older MCP
client setups, but new packet and prompt contracts should prefer the resource
names above.

## Required Tools

Expose these tool names through `tools/list`:

```txt
knownet.propose_finding
knownet.propose_task
knownet.submit_implementation_evidence
```

Tool behavior:

- `knownet.propose_finding` performs a parser dry-run only. It does not create
  records.
- `knownet.propose_task` returns a structured task proposal. It does not create
  or assign tasks.
- `knownet.submit_implementation_evidence` returns an operator-gated evidence
  proposal. It does not mark a finding implemented.

The legacy `knownet_review_dry_run` and `knownet_submit_review` tools can remain
for established clients, but the standard-facing names above are preferred.

## Required Prompts

Expose these prompt names through `prompts/list`:

```txt
knownet.compact_review
knownet.implementation_candidate
knownet.provider_risk_check
```

## Forbidden MCP Scope

Do not expose:

- raw SQLite query tools
- shell tools
- filesystem read/write tools
- backup restore/delete tools
- user/session/token resources
- release_check execution tools
- provider live-call tools
- full graph dump tools
- long Markdown export as the default read path
- MCP-specific schemas that diverge from packet JSON Schema

## Design Rule

MCP names should match packet contract names. If a packet advertises
`knownet://snapshot/overview` or `knownet.propose_finding`, the MCP server
should either implement that resource/tool or not advertise it.
