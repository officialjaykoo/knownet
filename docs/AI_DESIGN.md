# KnowNet AI Design

KnowNet is an AI-centered collaboration knowledge base for review, decision, and implementation records.

The product question is simple:

```txt
Can the next AI agent understand the current project state, review it, make a structured decision, and hand useful implementation work back to Codex?
```

## Product Shape

```txt
KnowNet stores:
  structured collaboration records
  project context pages
  AI review documents
  structured findings
  accept/reject/defer decisions
  implementation records
  context bundle manifests
  audit and verification notes

External AI agents:
  read curated context bundles, packets, or MCP resources
  return structured findings and optional review prose
  do not write source code through KnowNet

Codex:
  reads reviews and packets
  checks findings against the local repository
  implements accepted changes
  records verification evidence
```

## Canonical State

```txt
SQLite / JSON:
  Findings, severity, status, decisions, graph links, audit events, context
  bundle manifests, implementation records, and machine-checkable state.
  This is the canonical AI collaboration state.

Markdown:
  Long-form rationale, source review prose, implementation notes, runbooks,
  architecture explanations, and operator-facing context.
  This is a narrative attachment, not the canonical collaboration state.
```

AI-to-AI handoff should prefer structured records first. Markdown is preserved when long reasoning or original prose matters.

## Operating Principles

```txt
Durable artifacts over chat:
  Reviews, findings, decisions, and implementation records must survive after a conversation ends.

Small context by default:
  Export the minimum useful project context, not the whole workspace.

Auditable implementation:
  Code changes should link back to an accepted finding, commit hash, and verification note when possible.

No remote code authority:
  External agents do not receive repository, shell, database, backup, session, or secret access through KnowNet.
```

## Workflow

```txt
1. Generate a curated context packet or MCP resource read.
2. External AI returns structured findings with optional narrative review text.
3. KnowNet imports the review and stores canonical structured records.
4. Codex or the operator triages findings.
5. Accepted findings become implementation work.
6. Codex edits code, runs checks, and records evidence.
7. KnowNet updates project context for the next AI agent.
```

## Page Quality

Useful pages contain current state, boundaries, known issues, review targets, and verification notes.

Weak pages are generic explanations, marketing copy, large unstructured dumps, or advice that cannot be accepted, rejected, deferred, or implemented.

## Security Boundary

External AI agents receive curated context only. They do not receive secrets, databases, backups, sessions, direct shell access, or unrestricted repository exports.
