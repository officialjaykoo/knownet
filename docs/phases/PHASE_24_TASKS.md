# Phase 24 Tasks: Lightweight SQLite FTS5 Search

Status: planned
Created: 2026-05-06

Phase 24 adds a small SQLite FTS5 index for page-level keyword search. This is
not a new search product and not a vector-search phase. It exists to remove the
current Markdown full-file scan bottleneck while keeping KnowNet local-first,
single-file, and easy to operate.

References:

- SQLite FTS5 official documentation:
  https://www.sqlite.org/fts5.html
- Datasette full-text search documentation:
  https://docs.datasette.io/en/latest/full_text_search.html

Reference patterns absorbed:

- Use SQLite FTS5 instead of adding a separate search service.
- Use `unicode61` tokenization first.
- Use `MATCH` and `bm25()` for ranked page search.
- Keep a rebuild path so the index can be recreated from canonical pages.
- Keep deterministic fallback behavior when FTS is unavailable.

## Fixed Rules

Do not:

- Add PostgreSQL, Elasticsearch, OpenSearch, Qdrant, LanceDB, or another search
  server.
- Add chunk-level FTS in this phase.
- Add hybrid FTS + embedding ranking in this phase.
- Add Korean morphology plugins or custom tokenizers in this phase.
- Make search depend on embeddings.
- Remove the existing LIKE fallback until FTS behavior is proven.
- Index raw secrets, raw database files, backups, sessions, users, tokens, or
  environment files.

Do:

- Keep Markdown files and `pages` rows as the canonical source.
- Add only one page-level FTS table.
- Prefer a full rebuild command/API over complex incremental queues.
- Update FTS on normal page create/update flows where the code already writes
  page content.
- Return the search source in API results: `fts`, `index`, `markdown_fallback`,
  or `semantic`.
- Keep tests small and focused.

## P24-001 FTS5 Capability And Schema

Problem:

KnowNet currently searches indexed fields with `LIKE`, then scans Markdown files
directly when indexed metadata is not enough. That works for small vaults, but
AI collaboration will keep adding pages, reviews, evidence, and snapshots. Full
Markdown scans should not be the primary retrieval path.

Implementation shape:

Add a single FTS5 table:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
  page_id UNINDEXED,
  vault_id UNINDEXED,
  title,
  slug,
  body,
  tokenize = 'unicode61'
);
```

Notes:

- `pages_fts` is an index table, not the source of truth.
- `page_id` and `vault_id` are stored for joins/filtering but not tokenized.
- Keep the schema simple. Do not use external content triggers in the first
  implementation unless the existing write path makes them clearly simpler.
- If the runtime SQLite build does not support FTS5, search must fall back to
  the current behavior and report `fts_unavailable`.

Done when:

- New databases create `pages_fts`.
- Startup or health can detect whether FTS5 is available.
- Tests cover the unavailable path without throwing 500s.

## P24-002 Rebuild FTS Index

Problem:

FTS is derived state. Since KnowNet is local-first and Markdown remains
canonical, the index must be disposable and rebuildable.

Implementation shape:

- Add a narrow maintenance endpoint:

```txt
POST /api/maintenance/search/rebuild-fts
```

- The endpoint should:
  - clear `pages_fts`
  - read active pages from SQLite
  - read each page Markdown body from `data/pages/*.md`
  - insert page id, vault id, title, slug, and body into `pages_fts`
  - return counts: indexed, skipped, failed, duration_ms

Avoid:

- Running this as part of full release checks.
- Adding a background queue.
- Rebuilding embeddings.

Done when:

- Rebuild succeeds from the current Markdown pages.
- Missing Markdown files are skipped with a warning count, not a crash.
- The endpoint is admin-only.

## P24-003 Page Write Path Sync

Problem:

If the index only rebuilds manually, search can become stale after normal page
edits.

Implementation shape:

- On page create/update flows that already know the page id/title/slug/body,
  upsert the corresponding `pages_fts` row.
- On archive/delete/inactive transitions, remove that page from `pages_fts`.
- Keep this best-effort: if FTS write fails, log/report the issue but do not
  corrupt the canonical page write.

Avoid:

- Adding triggers that read Markdown files.
- Re-parsing all pages on every write.
- Letting FTS failures block page saves unless the underlying SQLite write is
  broken.

Done when:

- Updating a page updates FTS results without a manual rebuild.
- Deactivating/removing a page removes it from FTS results.
- Tests cover create/update/remove sync.

## P24-004 FTS-First Keyword Search

Problem:

`/api/search` should use the fastest reliable local keyword path first.

Implementation shape:

Search order:

```txt
1. pages_fts MATCH query
2. existing indexed LIKE query
3. existing Markdown file scan fallback
```

FTS result shape:

```json
{
  "slug": "page-slug",
  "title": "Page Title",
  "path": "pages/page-slug.md",
  "match_type": "fts",
  "rank": 0.42
}
```

Query handling:

- Escape or normalize user input so FTS query syntax errors do not produce
  500s.
- If FTS raises a syntax/runtime error, fall back to the existing path and
  include `fallback: "keyword"`.
- Limit results before reading large bodies.

Done when:

- `/api/search?q=...` returns FTS results when the index exists.
- Bad FTS syntax falls back gracefully.
- Existing integration tests continue to pass.

## P24-005 Health, Snapshot, And Packet Signals

Problem:

External AI needs to know whether keyword search used FTS or slow fallbacks.

Implementation shape:

- Add a compact search index status to health/operator state:

```json
{
  "search": {
    "fts": "ready",
    "indexed_pages": 42,
    "fallback": "like_markdown_scan"
  }
}
```

- Add a small packet/snapshot hint for performance reviews:
  - `search_index_status`
  - `fts_ready`
  - `indexed_pages`
  - `last_rebuild_at` if available

Avoid:

- Adding long per-page index dumps to packets.
- Turning FTS warnings into release blockers by default.

Done when:

- Performance profile packets can tell an external AI whether FTS is ready.
- Health explains degraded search without requiring a full release check.

## P24-006 Tests And Acceptance

Targeted tests:

```txt
1. Fresh schema can create pages_fts when SQLite supports FTS5.
2. Rebuild endpoint indexes active Markdown pages.
3. FTS search returns a matching page before Markdown fallback.
4. Invalid FTS query falls back without 500.
5. Page update changes FTS result content.
6. Inactive/deleted page is absent from FTS results.
7. Semantic search still degrades to keyword when embeddings are unavailable.
8. Packet/search health exposes compact FTS status only.
```

Acceptance:

```txt
1. No new service or daemon is introduced.
2. pages_fts is the only FTS table.
3. Existing LIKE + Markdown scan fallback remains available.
4. /api/search prefers FTS when ready.
5. Rebuild is admin-only and bounded.
6. Search status is visible to health/snapshots without bloating packets.
```

## Later, Not Phase 24

Keep these out of scope until actual usage proves they are needed:

- `page_chunks`
- `chunk_fts`
- snippet/highlight extraction
- hybrid FTS + embedding reranking
- sqlite-vec or pgvector
- external search engines
- custom Korean tokenizer or morphology pipeline
