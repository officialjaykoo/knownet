# KnowNet AI-Centered Design

KnowNet is an AI-centered collaboration knowledge base.

Human readability matters, but it is secondary. The primary design question is:

```txt
Can the next AI agent understand the current project state, review it, make a
structured decision, and hand useful implementation work back to Codex?
```

## Core Rules

```txt
Primary user:
  AI agents that need durable project context, review targets, decisions, and
  implementation records.

Human role:
  The operator chooses direction, checks outcomes, and keeps the system useful.

Core loop:
  Context -> AI review -> findings -> decision -> implementation ->
  verification -> updated context.
```

## Format Split

```txt
Markdown:
  Long-form context, rationale, review text, implementation notes, runbooks,
  architecture explanations, and project memory.

SQLite / JSON:
  Findings, severity, status, decisions, graph links, audit events, context
  bundle manifests, implementation records, and machine-checkable state.
```

Markdown is the durable writing surface. SQLite and JSON are the structure that
keeps AI agents from guessing.

## Page Quality

Useful pages contain current state, boundaries, known issues, review targets,
and verification notes.

Weak pages are generic explanations, marketing copy, large unstructured dumps,
or advice that cannot be accepted, rejected, deferred, or implemented.

## Security Boundary

External AI agents receive curated context bundles only. They do not receive
secrets, databases, backups, sessions, direct shell access, or unrestricted
repository exports.

## Implementation Source

This document is a judgment guide, not a task list.

Use the phase task files for implementation:

```txt
PHASE_7_TASKS.md  collaboration MVP
PHASE_8_TASKS.md  AI-centered hardening
```
