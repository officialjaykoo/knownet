# Phase 21 Tasks: External Standards Alignment

Status: implemented in the codebase on 2026-05-05
Created: 2026-05-05

Phase 21 aligns KnowNet packet, model-run, and evaluation language with existing public standards. Phase 20 made packets machine-enforceable. Phase 21 makes the naming and validation model less custom.

Implemented surface:

```txt
1. Project snapshot, experiment, and provider fast-lane packet surfaces emit
   protocol_version, schema_ref, and trace.
2. Packet contracts include protocol_version, schema_ref, and MCP resource,
   tool, and prompt names.
3. Trace metadata uses 32-hex trace_id, 16-hex span_id, uppercase span_kind,
   W3C traceparent, and attributes.
4. docs/schemas/packet.p20.v1.schema.json defines the concrete packet schema.
5. Phase 21 absorbed standard MCP, OpenAPI/JSON Schema, and trace concepts into the runtime packet contract
   Schema, OpenTelemetry/OpenInference, Promptfoo, and Langfuse/Agenta.
6. Parser fixtures cover every current output_mode: top_findings,
   decision_only, implementation_candidates, and provider_risk_check.
7. model_review_runs stores trace_id and packet_trace_id for provider runs.
8. Runtime packet generation calls the shared packet schema core validator.
9. Provider comparison parser fixtures live under
   apps/api/tests/fixtures/provider_comparison/.
```

## Goals

1. Use protocol/schema/trace fields consistently across every outbound packet and provider context.
2. Document packet contracts as reusable schema components.
3. Treat provider comparison as fixture + assertion work, not ad hoc review prose.
4. Map model runs and provider calls to trace-like evidence records.
5. Keep KnowNet's finding/task/evidence loop, but use standard terminology around it.

## P21-001 Protocol And Schema Header

Required fields:

```json
{
  "contract_version": "p20.v1",
  "packet_schema_version": "p20.v1",
  "protocol_version": "2026-05-05",
  "schema_ref": "knownet://schemas/packet/p20.v1"
}
```

Done when:

- Project snapshot packets include all four fields.
- Experiment packets include all four fields.
- Provider fast-lane contexts include all four fields.
- Tests assert these fields.

## P21-002 Trace Metadata

Required field:

```json
{
  "trace": {
    "trace_id": "snapshot_...",
    "span_id": "...",
    "traceparent": "00-<trace_id>-<span_id>-01",
    "name": "knownet.project_snapshot_packet",
    "span_kind": "INTERNAL"
  }
}
```

Done when:

- Project snapshots, experiment packets, and provider fast-lane contexts emit trace metadata.
- Later model-run evidence can correlate back to packet trace IDs.

## P21-003 Schema Component Documentation

Create a schema document for:

- packet header
- trace
- role/access boundaries
- stale context suppression
- issue
- packet summary item
- node card
- import contract

Done when:

- Schema documentation is stored under `docs/schemas/`.
- `schema_ref` points to the named KnowNet packet schema.

## P21-004 Provider Assertion Fixtures

Use Promptfoo-style thinking:

- same packet
- multiple providers
- expected parser result
- expected rejection result
- explicit assertions

Done when:

- `top_findings`, `decision_only`, `implementation_candidates`, and `provider_risk_check` each have a dry-run fixture.
- Unsupported sections fail with actionable feedback.

## P21-005 Run And Evidence Trace Mapping

Use OpenTelemetry/OpenInference-style terms for model calls:

- provider call
- prompt profile
- input/output tokens
- status
- error code/message
- trace ID
- evidence quality

Done when:

- Model run records expose trace-compatible metadata.
- Implementation evidence can reference the originating packet/model run.

Implemented:

- `model_review_runs.trace_id` records the run trace.
- `model_review_runs.packet_trace_id` records the packet/context trace that
  produced the run.
- Provider request/response JSON includes the same trace values for audit
  readability.

## P21-006 Runtime Schema Validation

Use the JSON Schema document as the stable contract and connect a lightweight
runtime validator to packet creation.

Done when:

- Project snapshot packets fail closed if required schema fields are missing.
- Experiment packets fail closed if required schema fields are missing.
- Provider fast-lane contexts fail closed before leaving the safe context
  builder.
- Tests load docs/schemas/packet.p20.v1.schema.json and assert the runtime
  validator agrees with its required fields.

Implemented:

- `validate_packet_schema_core` checks the schema header, trace, contract, and
  required packet fields.
- Project snapshot, experiment packet, and provider fast-lane generation call
  the validator at runtime.

## Acceptance

Phase 21 is complete when:

```txt
1. All outbound packet surfaces carry protocol_version, schema_ref, and trace.
2. Packet schema components are documented.
3. Output-mode dry-run fixtures cover every supported output mode.
4. Provider comparison tests use file-based fixture/assertion language.
5. Model-run evidence has trace-compatible identifiers.
6. Runtime packet surfaces are checked against the schema core.
```
