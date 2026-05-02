# KnowNet AI Collaboration Concept

KnowNet is an AI-centered collaboration knowledge base for review, decision,
and implementation records.

The goal is not to give every agent direct access to the source tree. The goal
is to give agents enough safe project context to write useful reviews, then let
the local implementation agent decide what to apply in code.

## Product Shape

```txt
KnowNet stores:
  project context pages
  AI review documents
  structured findings
  accept/reject/defer decisions
  implementation records
  context bundle manifests
  audit and verification notes

External AI agents:
  read curated context bundles
  write review documents
  do not write source code through KnowNet

Codex:
  reads reviews
  checks findings against the local repository
  implements accepted changes
  records verification evidence
```

## Operating Principles

```txt
Durable artifacts over chat:
  Reviews, findings, decisions, and implementation records must survive after a
  conversation ends.

Small context by default:
  Export the minimum useful project context, not the whole workspace.

Auditable implementation:
  Code changes should link back to an accepted finding, commit hash, and
  verification note when possible.

No remote code authority:
  External agents do not receive repository, shell, database, backup, session,
  or secret access through KnowNet.
```

## Workflow

```txt
1. Generate a curated context bundle.
2. External AI writes an agent review.
3. KnowNet imports the review and parses findings.
4. Codex or the operator triages findings.
5. Accepted findings become implementation work.
6. Codex edits code, runs checks, and records evidence.
7. KnowNet updates project context for the next AI agent.
```

## Implementation Source

This document defines product direction only.

Use the phase task files for implementation:

```txt
PHASE_7_TASKS.md  collaboration MVP
PHASE_8_TASKS.md  AI-centered hardening
```
