# Phase 23 Tasks: Standard MCP Baseline

Status: completed in the codebase
Created: 2026-05-05
Implemented: 2026-05-05

Phase 23 turns the Phase 22 packet MCP contract into the minimum real MCP server
surface. It does not add operator powers. It only standardizes safe reads and
proposal-only tools.

Reference:

- `docs/MCP_SCOPE.md`

## Fixed Rules

Do not:

- Add raw database, shell, filesystem, backup, user, session, token, or
  release-check tools.
- Add provider live-call tools.
- Add a second MCP-specific schema that diverges from packet JSON Schema.
- Expose long full graph dumps by default.
- Let tools directly mark findings implemented or mutate maintenance state.

Do:

- Use MCP method names and JSON-RPC behavior already implemented by the stdio
  server.
- Prefer `knownet://...` resource URIs.
- Prefer `knownet.*` tool and prompt names.
- Expose only the standard MCP resource, tool, and prompt names.

## P23-001 Standard Resources

Add these resources to `resources/list` and `resources/read`:

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

Done when:

- `resources/list` exposes the standard URIs.
- `resources/read` returns compact JSON for the standard URIs.
- `knownet://agent/...` aliases are not exposed.

Implementation status: completed. The MCP server exposes only snapshot
resources, `knownet://node/{slug_or_page_id}`, and `knownet://finding/recent`;
tests cover list/read behavior for the standard names and reject agent aliases.

## P23-002 Proposal Tools

Add these tools:

```txt
knownet.propose_finding
knownet.propose_task
knownet.submit_implementation_evidence
```

Done when:

- `knownet.propose_finding` dry-runs parser-ready finding Markdown.
- `knownet.propose_task` returns a structured proposal without creating a task.
- `knownet.submit_implementation_evidence` returns an operator-gated proposal
  without marking a finding implemented.

Implementation status: completed. All three tools are present in `tools/list`;
write-like behavior is proposal-only or parser dry-run only.

## P23-003 Standard Prompts

Add these prompts:

```txt
knownet.compact_review
knownet.implementation_candidate
knownet.provider_risk_check
```

Done when:

- `prompts/list` exposes them.
- `prompts/get` returns bounded instructions that use standard resource and
  tool names.

Implementation status: completed. The prompts reference the standard snapshot,
finding, and proposal tool names and explicitly avoid raw/admin surfaces.

## Acceptance

```txt
1. initialize, resources/list/read, tools/list/call, and prompts/list/get work.
2. Standard URI/tool/prompt names match the packet contract.
3. Proposal tools are draft/dry-run only.
4. Forbidden raw/admin surfaces remain absent.
5. MCP tests cover the standard names.
```
