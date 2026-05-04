# Phase 22 Tasks: Lightweight Standard Absorption

Status: implemented in the codebase on 2026-05-05
Created: 2026-05-05

Phase 22 identifies parts of KnowNet that should stop being invented from
scratch where mature open standards or open-source patterns already exist. The
goal is not to turn KnowNet into a heavy observability, eval, graph database,
or provider gateway product. The goal is to absorb the smallest useful pieces
that make KnowNet faster to maintain and easier for external AI collaborators
to understand.

## Fixed Rules

Do not:

- Add a heavy always-on service just because an upstream project has one.
- Replace KnowNet's node, finding, task, and evidence loop.
- Add provider-specific packet schemas.
- Make daily workflows depend on full release checks.
- Store raw prompts, raw secrets, raw database files, backups, sessions, or
  user dumps in packets or traces.
- Build a second dashboard when a schema, fixture, or narrow endpoint is enough.

Do:

- Prefer existing standards and open-source data shapes.
- Keep adoption shallow until repeated usage proves value.
- Put compatibility at the boundary, not deep in core logic.
- Add tests before expanding automation.
- Keep packet/snapshot size budgets intact.

Implemented surface:

```txt
1. Provider capability registry classifies Gemini as custom_api and
   DeepSeek/MiniMax/Kimi/Qwen/GLM as openai_compatible_with_overrides.
2. Operator provider matrix exposes provider capabilities and a dedicated
   /api/operator/provider-capabilities endpoint.
3. model-run observations expose trace_id, packet_trace_id, provider/model,
   status, duration_ms, token counts, error details, evidence_quality, and
   provenance through /api/model-runs/observations.
4. Packet contracts use MCP standard method names, resource URIs, tool names,
   and prompt names while making clear that packet transport is not an MCP
   server.
5. Node cards, finding summaries, task summaries, and model-run summaries carry
   compact provenance where available.
6. Provider comparison and provider capability tests use file-based fixtures
   through one shared fixture loader.
7. docs/schemas/packet.p20.v1.schema.json documents the `mcp` contract surface and
   compact provenance fields.
8. Snapshot, experiment, and provider fast-lane packets expose API-resource
   fields: `id`, `type`, `generated_at`, and `links`.
9. Snapshot deltas expose `delta` with `summary`, `added`, `changed`, and
   `removed` sections. Legacy response aliases such as `packet_id`, `read_url`,
   `storage_path`, and `delta_summary` are not emitted.
```

## P22-001 Provider Gateway Alignment

Reference patterns:

- LiteLLM
- OpenAI-compatible chat completions
- Provider capability matrices

Problem:

KnowNet currently carries provider-specific adapter code for Gemini, DeepSeek,
MiniMax, Kimi, Qwen, and GLM. Some provider differences are real, but much of
the call path can follow a shared OpenAI-compatible shape.

Pre-work gate:

- Classify each provider before refactoring code:
  - `openai_compatible`: request/response can use the shared OpenAI-compatible
    adapter with only base URL/model/options changes.
  - `openai_compatible_with_overrides`: shared adapter is usable, but
    provider-specific request fields, thinking/reasoning options, or response
    normalization are required.
  - `custom_api`: official API shape is materially different and must stay on a
    custom adapter.
- Record the classification in tests or a provider registry fixture.
- Do not refactor provider code until this classification exists.

Implementation shape:

- Add a provider capability registry that records:
  - provider id
  - base URL
  - model
  - OpenAI-compatible support
  - Anthropic-compatible support when applicable
  - compatibility class
  - timeout
  - reasoning/thinking option support
- Route OpenAI-compatible providers through one shared adapter where practical.
- Keep truly custom Gemini behavior separate only where the official API shape
  requires it.
- Add one fixture per provider that asserts the generated request payload shape.

Avoid:

- Adding LiteLLM as a mandatory runtime dependency before the local adapter
  shape proves insufficient.
- Hiding provider-specific safety settings behind opaque generic options.

Done when:

- New providers can be added mostly by registry config.
- Existing provider tests still verify official request payload shapes.
- Provider-specific code shrinks or stops growing.
- Provider classification explains why Gemini or any other provider remains
  custom.

## P22-002 LLM Ops Trace And Run Metrics

Reference patterns:

- Langfuse
- OpenLIT
- Arize Phoenix
- OpenTelemetry / OpenInference

Problem:

Phase 21 added trace-compatible packet and model-run IDs. KnowNet still lacks a
compact run timeline: latency, retry, error class, token/cost estimate, and
packet lineage are not yet consistently queryable as a single evidence record.

Scope boundary:

- This is not a Langfuse clone.
- Phase 22 only needs a compact observation summary that KnowNet can use in
  packets, operator views, and provider reliability checks.
- Full prompt/version tracking, prompt playgrounds, dashboards, span trees,
  scoring pipelines, and hosted telemetry export are out of scope.

Implementation shape:

- Add a lightweight model-run observation serializer:
  - run id
  - trace id
  - packet trace id
  - provider/model
  - status
  - duration_ms
  - input/output token estimate
  - error code/message
  - evidence_quality
- Expose it through a narrow API endpoint or packet summary field.
- Add aggregation for last N runs by provider:
  - success count
  - failure count
  - p50/p95 duration if available
  - consecutive failures

Avoid:

- Running a telemetry collector.
- Storing full raw prompts or raw model outputs in metrics tables.
- Building a full Langfuse clone.

Done when:

- Operator and AI packet flows can answer "which provider is flaky or slow?"
  without reading full run bodies.
- Failed provider runs preserve enough structured detail for retry decisions.
- The implementation is a summary endpoint/serializer, not a new observability
  subsystem.

## P22-003 Provider Evaluation Fixtures

Reference patterns:

- Promptfoo
- eval fixture assertions
- golden output tests

Problem:

Provider comparison is useful only when it is repeatable. Human-readable review
prose does not tell us whether differences came from the model, packet shape,
or parser behavior.

Implementation shape:

- Keep provider comparison fixtures file-based.
- Add fixture metadata:
  - packet profile
  - output mode
  - expected parser result
  - accepted/rejected sections
  - max findings
- Add a small command or test helper that can run the same fixture through
  multiple provider adapters in mock mode.
- Store comparison output as structured evidence, not long narrative.
- Reuse the same fixture loader/assertion helper used by P22-001 provider
  capability tests and P22-005 schema tests where practical.

Avoid:

- Making live provider calls mandatory for CI.
- Treating context_limited provider opinions as release blockers.
- Adding subjective scoring before parser correctness is stable.

Done when:

- One fixture can be reused against at least two provider paths.
- Parser failure feedback is actionable and file-based.

## P22-004 MCP Resource Boundary

Reference patterns:

- Model Context Protocol resources/tools/prompts
- read-only resource discovery

Problem:

KnowNet's strongest use case is AI reading project memory quickly. Packets help,
but MCP resource, tool, and prompt names are still only partially represented as
packet metadata.

Naming rule:

- Use MCP standard method names and object field names inside packets:
  `resources/list`, `resources/read`, `tools/list`, `tools/call`,
  `prompts/list`, and `prompts/get`.
- Use MCP resource URIs such as `knownet://snapshot/{profile}` and
  tool/prompt names such as `knownet.propose_finding`.
- Do not call the packet itself a full MCP server unless KnowNet exposes the
  actual MCP transport and JSON-RPC message contract.

Implementation shape:

- Define a small MCP resource catalog in code:
  - `knownet://snapshot/{profile}`
  - `knownet://node/{slug}`
  - `knownet://finding/{finding_id}`
  - `knownet://task/{task_id}`
  - `knownet://model-run/{run_id}/observation`
- Define allowed tools with namespaced MCP tool names:
  - `knownet.propose_finding`
  - `knownet.propose_task`
  - `knownet.submit_implementation_evidence`
- Define reusable prompts with namespaced MCP prompt names:
  - `knownet.compact_review`
  - `knownet.implementation_candidate`
- Keep raw DB, shell, filesystem, secrets, backups, sessions, and users refused.
- Reuse packet `capabilities` and `role_and_access_boundaries`.

Avoid:

- Exposing unrestricted file paths or database queries.
- Adding a network MCP server before local API/resource contracts are stable.
- Duplicating packet logic in a second incompatible resource format.

Done when:

- An external AI can discover what it may read and propose without reading a
  long policy document.
- The resource list and packet capabilities agree.
- Documentation clearly says the packet embeds MCP names/object shapes, while
  JSON-RPC transport belongs to the MCP server.

## P22-005 API Schema And Contract Tests

Reference patterns:

- OpenAPI
- JSON Schema
- schema-based response checks

Problem:

Phase 21 documented packet schema and added runtime core validation. Other API
surfaces still rely mostly on route tests and implicit response shapes.

Implementation shape:

- Create one shared fixture/schema assertion helper rather than separate test
  harnesses per task.
- Add schema checks for:
  - project snapshot packet response
  - experiment packet response
  - model-run observation summary
  - provider capability registry
- Use FastAPI/OpenAPI generation where possible.
- Add narrow tests that fail when required fields silently disappear.

Avoid:

- Hand-writing huge schemas for every endpoint.
- Blocking all development on perfect OpenAPI completeness.

Done when:

- The high-value AI collaboration endpoints have required-field tests.
- Breaking response shape changes fail targeted tests.

## P22-006 Graph Provenance And Export Shape

Reference patterns:

- JSON-LD style provenance ideas
- graph export/import manifests
- TerminusDB/RDF-inspired provenance, without adopting the stack

Problem:

KnowNet nodes and edges are useful, but external AI collaboration needs clearer
provenance: which human, AI, packet, model run, finding, or implementation
record caused a node or edge to exist.

Timing rule:

- Do not leave provenance modeling until the very end.
- Define the compact provenance shape before or alongside P22-001 through
  P22-003 so provider runs, eval fixtures, and graph exports can reference the
  same fields.
- Full backfill can wait, but the shape should not.

Implementation shape:

- Add a lightweight provenance shape for exported node cards:
  - created_by_type
  - created_by_id
  - source_packet_id
  - source_model_run_id
  - source_finding_id
  - evidence_quality
  - updated_at
- Include provenance in snapshot/export summaries only when compact.
- Add tests that provenance never includes secrets or raw local paths.

Avoid:

- Replacing SQLite graph tables with RDF or a graph database.
- Adding full JSON-LD framing unless a concrete integration needs it.
- Inflating every packet with full provenance history.

Done when:

- AI reviewers can tell whether a node is operator-authored, AI-suggested,
  implementation-derived, or system-generated.
- Graph export remains compact and safe.
- New provider/eval evidence can attach provenance without later schema churn.

## Suggested Order

```txt
P22-000 Shared Test And Provenance Shape Pre-work
  -> P22-001 Provider Gateway Alignment
  -> P22-002 LLM Ops Trace And Run Metrics
  -> P22-003 Provider Evaluation Fixtures
  -> P22-004 MCP Resource Boundary
  -> P22-005 API Schema And Contract Tests
  -> P22-006 Graph Provenance Backfill And Export Shape
```

Reasoning:

Define the shared fixture/schema helper and compact provenance shape first so
later tasks do not invent separate test harnesses or incompatible lineage
fields. Provider call shape and run metrics are then the biggest maintenance
savings. Eval fixtures become more useful after provider paths are less custom.
MCP resource names and API schemas then make the external AI
collaboration loop easier to use without adding heavy infrastructure.
Provenance backfill/export is last, but the provenance shape is not.

## P22-000 Shared Test And Provenance Shape Pre-work

Purpose:

Prevent Phase 22 from creating three separate fixture systems and prevent late
provenance backfill from forcing schema churn.

Implementation shape:

- Define one small fixture loader/assertion helper for provider payload,
  provider comparison, and schema response fixtures.
- Define the compact provenance object once:
  - source_type
  - source_id
  - source_packet_id
  - source_packet_trace_id
  - source_model_run_id
  - source_model_run_trace_id
  - source_finding_id
  - evidence_quality
  - updated_at
- Add validation that provenance objects never include secrets, raw local paths,
  raw DB paths, backups, sessions, or users.

Done when:

- P22-001, P22-003, and P22-005 can reuse the same fixture helper.
- New records can carry compact provenance fields even if old records are not
  backfilled yet.

Implemented:

- `apps/api/tests/fixture_utils.py` provides a shared JSON fixture loader.
- `apps/api/knownet_api/services/provenance.py` defines the compact provenance
  object and safety validator.

## Acceptance

Phase 22 is complete when:

```txt
1. Provider configuration is registry-like and common OpenAI-compatible
   providers are classified for shared adapter consolidation.
2. Model-run summaries expose trace, packet lineage, duration, status, token,
   and error metrics without raw prompt leakage.
3. Provider comparison fixtures are reusable across provider paths.
4. MCP resources/tools/prompts are represented as lightweight, safe
   contracts.
5. High-value AI collaboration APIs have required-field schema tests.
6. Node cards or graph exports include compact provenance where available.
```

Acceptance status:

- Complete for lightweight registry/classification, observations, fixtures,
  MCP packet contract fields, schema fields, and compact provenance.
- Shared adapter consolidation is intentionally limited to classification and
  registry contracts in this phase. Existing provider adapters remain in place
  until repeated provider additions prove that a deeper shared adapter is worth
  the maintenance risk.

## Non-Goal

Phase 22 must not become a platform rewrite. It is a cleanup and absorption
phase. If a task requires a new daemon, hosted service, collector, graph
database, or large dependency, defer it unless there is repeated evidence that
the lightweight version failed.
