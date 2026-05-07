# Phase 27 Tasks: SARIF Findings Export

Status: implemented in the codebase on 2026-05-07
Created: 2026-05-07
Updated: 2026-05-07

Phase 27 introduces SARIF as the standard exchange format for code-oriented
KnowNet findings. Do not hand-roll the SARIF object model. Use the existing
SARIF ecosystem and keep KnowNet code as a thin adapter from collaboration
findings to SARIF results.

This phase does not replace compact AI packets. Packets remain the best format
for broad project state, missing context, and AI-to-AI review handoff. SARIF is
for a narrower job:

```txt
KnowNet finding -> code/tooling finding -> GitHub Code Scanning / IDE / CI
```

The reason to add SARIF is simple: when a finding can point to a source file,
line, rule, or implementation evidence, GitHub and developer tools already know
how to display and compare that result. That is better than inventing another
custom format for code-related findings.

Implemented surface:

```txt
- apps/api/pyproject.toml declares sarif-om as the SARIF runtime object model
  dependency.
- apps/api/knownet_api/services/sarif_export.py exports KnowNet findings through
  sarif-om objects and serializes them with SARIF JSON property names.
- /api/collaboration/findings.sarif exports conservative SARIF by default:
  accepted/implemented findings with direct_access/operator_verified evidence.
- context_limited findings require explicit evidence_quality selection.
- implementation_records.changed_files become SARIF locations only when paths
  pass KnowNet ignore/secret path policy.
- Unsafe locations are omitted and recorded under properties.knownet.
- scripts/export_sarif.ps1 provides a local operator export helper and does not
  upload to GitHub automatically.
- SARIF fixtures cover accepted, implemented-with-location, and explicit
  context_limited exports.
- Follow-up scope is explicitly limited to schema validation, UI export, and
  opt-in GitHub upload. Finding source-location schema work is deferred to a
  later phase.
- Generated SARIF is validated locally against a checked-in SARIF 2.1.0 schema
  cache before the endpoint returns it.
- AI Reviews exposes a small Export SARIF action that downloads the trusted
  default export.
- scripts/upload_sarif_to_github.ps1 provides explicit operator-triggered
  GitHub Code Scanning upload through the `gh` CLI.
```

## Fixed Rules

Do not:

- Treat SARIF as a replacement for Project Snapshot Packets.
- Force every KnowNet finding into SARIF.
- Invent a custom GitHub findings schema when SARIF already exists.
- Hand-build the whole SARIF object model from scratch if a maintained library
  covers it.
- Add GitHub upload as the first step.
- Require code locations for non-code findings.
- Add explicit finding source-location fields in this phase.
- Turn context_limited findings into GitHub alerts without operator review.
- Put raw evidence dumps, secrets, raw DB content, backups, local-only machine
  paths, or packet bodies into SARIF.
- Add SARIF details to compact packets.

Do:

- Start with export-first SARIF generation.
- Prefer `sarif-om` for Python SARIF object construction.
- Validate against the official SARIF 2.1.0 JSON Schema.
- Use `sarif-tools` only as a helper/validation/reporting tool, not as the
  core Knownet data model.
- Include only accepted or operator-selected findings by default.
- Preserve KnowNet metadata in SARIF `properties`.
- Keep evidence_quality visible.
- Map severity to SARIF levels conservatively.
- Support GitHub upload later, after local export is stable.
- Keep implementation small and local-first.

## Why SARIF, And Where It Fits

SARIF is useful when the finding is about code or implementation work:

```txt
- a source file needs a change
- a test gap points to a test file
- a security finding points to a route/module
- implementation evidence names changed files
- a future static check produces line-level results
```

SARIF is less useful for:

```txt
- general product strategy
- external AI packet quality
- missing operator context
- provider API-key setup notes
- graph-level knowledge design
- "ask Claude/Gemini/DeepSeek this question" workflows
```

For those, compact packets and KnowNet collaboration findings remain better.

## Existing Tools To Absorb

Use existing open-source/standard components instead of inventing SARIF support:

| Tool / Source | Role In KnowNet |
|---|---|
| `microsoft/sarif-python-om` / PyPI `sarif-om` | Python classes for the SARIF object model. Preferred builder layer. |
| OASIS SARIF 2.1.0 schema | Authoritative validation target. |
| `microsoft/sarif-tools` / PyPI `sarif-tools` | Optional CLI/helper for viewing, filtering, validating, or converting SARIF during development. |
| GitHub SARIF code scanning docs | Compatibility target for future upload. |

Decision:

```txt
Do not write a full custom SARIF model.
Do write a small KnowNet adapter:
  collaboration_findings rows
  -> sarif_om objects
  -> SARIF 2.1.0 JSON
  -> schema/sarif-tools validation
```

Package direction:

```txt
Runtime/export dependency:
- sarif-om

Developer/test helper, optional:
- sarif-tools

Validation source:
- official OASIS SARIF 2.1.0 schema
```

If `sarif-om` is too awkward for a small subset, KnowNet may still produce a
minimal dict, but only against the official schema and only for the small result
subset. That fallback must be documented as a fallback, not the primary plan.

## SARIF Mapping

KnowNet fields should map to SARIF in a predictable way:

| KnowNet | SARIF |
|---|---|
| finding id | `result.guid` or `partialFingerprints.knownetFindingId` |
| title | `result.message.text` |
| area | `result.ruleId` prefix or `rule.properties.knownet.area` |
| severity | `result.level` |
| evidence | `result.properties.knownet.evidence` |
| proposed_change | `result.properties.knownet.proposed_change` |
| evidence_quality | `result.properties.knownet.evidence_quality` |
| status | `result.properties.knownet.status` |
| source_agent/source_model | `result.properties.knownet.source` |
| implementation record commit | `result.properties.knownet.implementation.commit` |
| changed_files | `result.locations[]` when paths are safe |

Severity mapping:

```txt
critical -> error
high     -> error
medium   -> warning
low      -> note
info     -> note
```

Keep the original severity in `properties.knownet.severity` so no information is
lost.

## P27-001 Local SARIF Export Service

Problem:

KnowNet findings currently live in SQLite and API responses. GitHub and IDEs
cannot consume them directly.

Implementation shape:

Create a small service that exports selected findings to SARIF 2.1.0 JSON using
`sarif-om` as the primary object model.

Candidate module:

```txt
apps/api/knownet_api/services/sarif_export.py
```

Candidate function:

```python
def build_sarif_log(findings: list[dict], *, run_id: str, generated_at: str) -> dict:
    ...
```

Implementation rule:

```txt
Use sarif-om objects for:
- SarifLog
- Run
- Tool
- ToolComponent
- ReportingDescriptor
- Result
- Message
- Location / PhysicalLocation / ArtifactLocation when a safe path exists
```

Convert the final object to JSON through the library-supported serialization
path. Do not create a parallel custom object hierarchy.

Rules:

- Produce valid SARIF 2.1.0.
- Use one SARIF `run` with tool name `KnowNet`.
- Put KnowNet-specific fields under `properties.knownet`.
- Never include secrets, raw DB paths, backup paths, or packet bodies.
- Missing file locations are allowed; SARIF result may have no `locations`.

Done when:

- A unit test can build a SARIF log from synthetic findings.
- The SARIF output includes `$schema`, `version`, `runs`, `tool`, `rules`, and
  `results`.
- Non-code findings export without fake locations.
- The service uses `sarif-om` or explicitly documents why the minimal-schema
  fallback was required.

## P27-002 Findings Export Endpoint

Problem:

Operators need a simple way to generate SARIF without hand-writing scripts.

Implementation shape:

Add a read/review-access endpoint:

```txt
GET /api/collaboration/findings.sarif
```

Supported query parameters:

```txt
vault_id=local-default
status=accepted|implemented|pending|all
severity=critical,high,medium,low,info
evidence_quality=direct_access,operator_verified,context_limited,inferred,unspecified
limit=100
```

Default export should be conservative:

```txt
status=accepted,implemented
evidence_quality=direct_access,operator_verified
```

Rules:

- Do not export context_limited by default.
- If context_limited is explicitly requested, mark it clearly in properties.
- Return `application/sarif+json` when possible.
- Keep the JSON downloadable/copyable.

Done when:

- Endpoint returns SARIF JSON for accepted/implemented findings.
- Default filter avoids low-confidence findings.
- Tests cover default filtering and explicit context_limited export.

## P27-003 Safe Location Extraction

Problem:

SARIF is strongest when it can point to files, but KnowNet findings may not have
source locations.

Implementation shape:

Extract locations only from trusted structured fields:

```txt
implementation_records.changed_files
finding_tasks.expected_verification, only if safely parseable later
future explicit finding location fields
```

For Phase 27, prefer `implementation_records.changed_files`.

Safe path rules:

- Relative repo paths only.
- No absolute paths.
- No `..`.
- No `.env`, secrets, backups, `.git`, `.next`, `node_modules`, DB files, or
  generated caches.
- Drop unsafe locations rather than failing the whole export.

Candidate SARIF location:

```json
{
  "physicalLocation": {
    "artifactLocation": {
      "uri": "apps/api/knownet_api/routes/collaboration.py"
    }
  }
}
```

Done when:

- Safe changed files become SARIF locations.
- Unsafe paths are omitted and counted in export metadata.
- Non-code findings still export without locations.

## P27-004 GitHub Upload Script, Not Automatic Upload

Problem:

GitHub can consume SARIF, but automatic upload should not be the first step.

Implementation shape:

Add a small script later in the phase:

```txt
scripts/export_sarif.ps1
```

or:

```txt
scripts/upload_sarif_to_github.ps1
```

The first version should generate local SARIF and print the path. Upload can be
operator-triggered later.

Rules:

- Do not require GitHub upload for normal KnowNet operation.
- Do not add GitHub token requirements to packet generation.
- Do not run upload automatically from API endpoints.
- Keep upload opt-in and documented.

Done when:

- Operator can generate a SARIF file locally.
- The script does not create venvs or local dependency folders.
- Upload remains an explicit future/manual action.

## P27-005 SARIF Validation Fixture

Problem:

SARIF is useful only if the output is stable and valid enough for tools.

Implementation shape:

Add fixtures:

```txt
apps/api/tests/fixtures/sarif/
  accepted-finding.sarif.json
  implemented-finding-with-location.sarif.json
  context-limited-explicit.sarif.json
```

Rules:

- Fixtures must be small.
- Use synthetic findings only.
- Include one location case and one no-location case.
- Include `properties.knownet.evidence_quality`.
- Validate fixtures against the official SARIF 2.1.0 schema or `sarif-tools`
  where available.

Done when:

- Tests compare exported SARIF against expected shape.
- Tests verify severity mapping.
- Tests verify KnowNet properties are preserved.
- Tests fail if the export stops being SARIF 2.1.0-compatible.

## P27-006 Future GitHub Code Scanning Integration

Problem:

GitHub integration is valuable, but only after export quality is stable.

Implementation shape:

Document the later integration path:

```txt
KnowNet finding export -> SARIF file -> GitHub code scanning upload
```

Potential future command:

```txt
gh api repos/{owner}/{repo}/code-scanning/sarifs
```

Rules:

- This is not required for Phase 27 completion unless explicitly requested.
- Do not block local SARIF export on GitHub availability.
- Do not upload context_limited findings unless operator-selected.

Done when:

- The phase document names the future path.
- The implementation does not overfit to GitHub before local export works.

## P27-007 SARIF Schema Validation

Problem:

The endpoint currently emits a SARIF-shaped log. Phase 27 should also validate
that log against the official SARIF schema or a local cached copy of it.

Implementation shape:

Use a lightweight JSON Schema validator and the official SARIF 2.1.0 schema.
Prefer a checked-in schema cache if network validation would make tests flaky.

Rules:

- Do not fetch the schema during every request.
- Do not make external network availability part of normal export.
- Validation should be local and deterministic.
- If validation fails, return a clear API error rather than invalid SARIF.

Done when:

- Unit tests validate generated SARIF against the schema.
- `/api/collaboration/findings.sarif` validates output before returning it.
- Invalid SARIF generation fails loudly in tests.

## P27-008 UI Export Button

Problem:

Operators should not need to know the endpoint URL to export SARIF.

Implementation shape:

Add an export action to the AI Reviews workspace:

```txt
Export SARIF
```

The button should call the conservative default endpoint and download or copy
the `.sarif` JSON.

Rules:

- Keep this small. No SARIF dashboard.
- Use the existing auth/session fetch path.
- Show success/failure status.
- Do not expose GitHub token handling in the UI.

Done when:

- AI Reviews has a visible SARIF export action.
- The action uses the default trusted filter.
- Failure is visible to the operator.

## P27-009 Optional GitHub Upload Script

Problem:

GitHub Code Scanning can consume SARIF, but upload must remain explicit.

Implementation shape:

Add a separate opt-in script:

```txt
scripts/upload_sarif_to_github.ps1
```

It should accept a SARIF file path and repo coordinates, then call GitHub using
the installed `gh` CLI or GitHub API. This is not called by the API or UI.

Rules:

- No automatic upload.
- No GitHub token storage in KnowNet.
- Fail with a clear message if `gh` is unavailable or unauthenticated.
- Do not upload context_limited findings unless the operator exported them
  explicitly.

Done when:

- Operator can run the script manually after generating SARIF.
- Script does not create local dependency folders or venvs.
- Phase docs clearly state upload is optional.

## Acceptance

```txt
1. KnowNet can export selected collaboration findings as SARIF 2.1.0 JSON.
2. Default export is conservative: accepted/implemented and trusted evidence
   quality only.
3. context_limited findings require explicit export selection.
4. Safe changed files can become SARIF locations.
5. Non-code findings export without fake locations.
6. SARIF preserves KnowNet metadata under properties.knownet.
7. Compact packets remain unchanged and do not inline SARIF.
8. GitHub upload is documented as an opt-in later step, not automatic behavior.
9. SARIF export is schema-validated locally.
10. AI Reviews exposes a small Export SARIF action.
```

## Suggested Implementation Order

```txt
P27-001 Local SARIF Export Service
P27-003 Safe Location Extraction
P27-005 SARIF Validation Fixture
P27-002 Findings Export Endpoint
P27-004 Local Export Script
P27-006 Future GitHub Code Scanning Integration
P27-007 SARIF Schema Validation
P27-008 UI Export Button
P27-009 Optional GitHub Upload Script
```

## Out Of Scope

```txt
- Replacing compact project snapshot packets
- Replacing KnowNet collaboration findings
- Automatic GitHub upload
- GitHub token management
- SARIF import from GitHub
- Line-level code scanning engine
- Finding source-location schema migration
- Static analysis implementation
- JSON-LD, CloudEvents, or in-toto
- Full release_check
```
