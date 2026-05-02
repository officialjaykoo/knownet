# KnowNet Phase 5 Tasks

Phase 5 goal: turn KnowNet from a verified AI knowledge base into an explorable knowledge
map that helps users see relationships between pages, claims, sources, and weak
citations.

Phase 4 made citation trust auditable. Phase 5 uses the existing Markdown,
links, backlinks, sections, citations, and citation audit metadata to build a
graph view and knowledge map without introducing a graph database.

Implementation status: completed in the codebase.

Implemented surface:

```txt
Rust graph schema/rebuild/layout commands
FastAPI /api/graph routes, neighborhood endpoint, rebuild endpoint, layout cache endpoint
Automatic graph rebuild after suggestion apply, revision restore, page create, import, and migrate
verify-index graph checks
Cytoscape.js knowledge map UI with list fallback
Phase 5 graph tests
```

## Phase 5 Fixed Decisions

These choices are fixed before implementation so the agent does not invent a
new graph architecture while coding.

```txt
Graph source of truth: Markdown remains canonical.
Graph storage: SQLite stores derived graph nodes, edges, layout cache, and filters.
Graph database: not introduced in Phase 5.
Graph scope: vault-scoped by vault_id.
Graph rebuild: deterministic and recoverable from Markdown + SQLite metadata.
Graph layout: computed client-side first; server may cache coordinates later.
Graph library: Cytoscape.js with react-cytoscapejs wrapper.
Graph library reason: declarative node style/filter/event control and stable React integration.
Graph alternatives rejected: D3-force risks React re-render conflicts; Sigma.js is oversized for Phase 5.
Write rule: graph rebuild/cache writes go through Rust daemon commands.
```

## Phase 5 Config Defaults

```txt
GRAPH_SEMANTIC_EDGE_THRESHOLD=0.7
GRAPH_SEMANTIC_MAX_EDGES_PER_NODE=10
GRAPH_UI_NODE_LIMIT=1000
```

## Phase 5 Error Codes

```txt
graph_rebuild_failed: rebuild failed and transaction rolled back
graph_node_not_found: neighborhood endpoint requested a missing node_id
graph_depth_exceeded: requested depth is above the allowed max
graph_layout_not_found: requested layout_key has no cached rows
```

## Phase 5 Principles

```txt
Do not make graph state canonical.
Do not require embeddings or OpenAI for the graph to work.
Keep the first graph useful on small vaults before optimizing for huge ones.
Show trust and uncertainty visually, not only as text.
Let users move from graph node to page, citation audit, or source.
Keep graph rebuild safe: no Markdown writes, no revision creation, no frontmatter edits.
```

## Phase 5 Graph Model

Node types:

```txt
page: canonical page
section: heading-level section inside a page
source: message/source backing a citation
citation_audit: citation trust record from Phase 4
tag: optional frontmatter tag when present
unresolved: pagelink target without a page
```

Edge types:

```txt
page_link: page -> page or page -> unresolved
backlink: derived inverse of page_link, not stored separately unless cached
contains_section: page -> section
cites: page/section -> source
has_audit: page/section -> citation_audit
audit_source: citation_audit -> source
tagged: page -> tag
semantic_related: optional, derived from embeddings when available
```

Semantic related edge rules:

```txt
Create semantic_related only when embeddings exist for the page.
Use cosine similarity > GRAPH_SEMANTIC_EDGE_THRESHOLD.
Never create a semantic_related edge from a node to itself.
Limit generated semantic edges to GRAPH_SEMANTIC_MAX_EDGES_PER_NODE per node.
If embeddings are missing, skip semantic edges and record embedding_missing in the rebuild report.
After embeddings are added later, rebuild_graph_for_page must run again to create semantic edges.
```

Stable IDs:

```txt
page node: page:{page_id}
section node: section:{page_id}:{revision_id}:{section_key}
source node: source:{source_type}:{source_id}
citation audit node: citation_audit:{audit_id}
tag node: tag:{normalized_tag}
unresolved node: unresolved:{normalized_target}
edge id: edge:{edge_type}:{from_node_id}:{to_node_id}
```

## Phase 5 SQLite Schema Baseline

```sql
CREATE TABLE graph_nodes (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  node_type TEXT NOT NULL,
  label TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  status TEXT,
  weight REAL NOT NULL DEFAULT 1.0,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE graph_edges (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  edge_type TEXT NOT NULL,
  from_node_id TEXT NOT NULL,
  to_node_id TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  status TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, edge_type, from_node_id, to_node_id)
);

CREATE TABLE graph_layout_cache (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  layout_key TEXT NOT NULL,
  node_id TEXT NOT NULL,
  x REAL NOT NULL,
  y REAL NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, layout_key, node_id)
);
```

Required indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_graph_nodes_vault_type
  ON graph_nodes(vault_id, node_type);

CREATE INDEX IF NOT EXISTS idx_graph_edges_from
  ON graph_edges(vault_id, from_node_id);

CREATE INDEX IF NOT EXISTS idx_graph_edges_to
  ON graph_edges(vault_id, to_node_id);
```

## Rust Daemon Commands

Phase 5 mutation commands:

```txt
ensure_graph_schema
rebuild_graph_for_page
rebuild_graph_for_vault
upsert_graph_layout_node
clear_graph_layout_cache
```

FastAPI may read graph tables directly, but graph rebuild/cache mutations go
through Rust daemon commands.

## Graph Rebuild Idempotency

`rebuild_graph_for_page` must use a delete-then-insert strategy inside one
SQLite transaction:

```txt
1. Resolve every graph node owned by the page, including page:{page_id} and section nodes.
2. Delete graph_edges where from_node_id or to_node_id belongs to that page-owned set.
3. Delete page:{page_id}.
4. Delete section nodes for the page.
5. Recreate nodes and edges from Markdown plus SQLite metadata.
6. Commit only after the full page graph has been rebuilt.
```

`rebuild_graph_for_vault` must also run transactionally:

```txt
1. Delete graph_edges and graph_nodes for the vault_id.
2. Do not delete graph_layout_cache, so user pins survive rebuild.
3. Regenerate every vault page in stable sorted order.
4. Skip pages that fail to parse and record failed count/report entries.
5. Roll back to the previous graph state if the transaction fails.
```

## Automatic Rebuild Triggers

```txt
Run rebuild_graph_for_page after write_revision completes.
Run rebuild_graph_for_page after restore_revision completes.
Run rebuild_graph_for_page after suggestion apply completes.
Run rebuild_graph_for_vault after Obsidian import completes.
Run rebuild_graph_for_vault after vault migration completes.
Allow manual vault/page rebuild through POST /api/graph/rebuild.
Run rebuilds as asynchronous jobs and expose status over the existing SSE flow.
While rebuild is in progress, GET /api/graph may return stale data but must include graph_stale: true.
```

## Completion Criteria

```txt
Current pages can produce graph_nodes and graph_edges.
Graph rebuild is vault-scoped and does not write Markdown.
GET /api/graph returns nodes/edges with filters, truncated state, and stale state.
GET /api/graph/neighborhood/{node_id} returns a bounded subgraph.
Web UI shows an interactive graph view.
Clicking a page node opens/selects the page.
Citation audit nodes visually indicate supported/unsupported/stale/needs_review.
Unresolved link nodes are visible and can be converted to pages through existing create flow.
Graph can degrade to a table/list view if canvas rendering fails.
Tests cover rebuild, filtering, neighborhood, and UI data shape.
```

## P5-001 Graph Schema and Rebuild

Goal:

```txt
Build graph metadata from existing Markdown-derived tables.
```

Tasks:

```txt
Add graph_nodes, graph_edges, and graph_layout_cache tables.
Add Rust ensure_graph_schema command.
Add Rust rebuild_graph_for_page command.
Add Rust rebuild_graph_for_vault command.
Use links, sections, citations, citation_audits, pages, and messages as inputs.
Delete/rebuild derived graph rows for the selected page/vault safely.
Use delete-then-insert rebuild inside a single SQLite transaction.
Preserve graph_layout_cache during vault rebuild.
Return created/skipped/removed/failed counts plus parse/embedding skip details.
```

Done when:

```txt
A vault can rebuild graph metadata without changing Markdown files.
```

## P5-002 Graph API

Goal:

```txt
Serve graph data in bounded, filterable shapes.
```

Endpoints:

```txt
GET /api/graph
  ?vault_id=local-default required
  &node_type=page,source optional comma-separated list, default page
  &edge_type=page_link,cites optional comma-separated list
  &status=unsupported,stale optional comma-separated list
  &limit=500 default 500, max 2000

Response shape:
{
  "nodes": [],
  "edges": [],
  "truncated": false,
  "total_node_count": 0,
  "graph_stale": false,
  "summary": {}
}

GET /api/graph/neighborhood/{node_id}
  ?depth=1 default 1, max 2
  &limit=200 default 200, max 500

POST /api/graph/rebuild
  body: { "scope": "vault" | "page", "page_id": "optional" }
```

Done when:

```txt
The UI initially loads page nodes, warns when truncated=true, and lazy loads bounded neighborhoods for details.
```

## P5-003 Graph UI

Goal:

```txt
Make the knowledge map usable, not decorative.
```

Tasks:

```txt
Add graph tab/view to the existing app.
Use Cytoscape.js through react-cytoscapejs.
Render page, source, citation_audit, unresolved, and tag nodes distinctly.
Color citation audit nodes by trust status.
Show node details panel on click.
Allow selecting/opening a page node.
Allow filtering by node_type, edge_type, and citation status.
Provide list fallback for small screens or graph render failures.
Fallback to list view when Cytoscape initialization fails within 5 seconds.
Fallback to list view when node count exceeds GRAPH_UI_NODE_LIMIT.
Allow users to manually switch to list view.
In list fallback, show page name, connected page count, and citation status summary.
Sort fallback list by weak citation count descending.
```

Done when:

```txt
Users can navigate from map to page and quickly spot weak citation clusters.
```

## P5-004 Knowledge Map Signals

Goal:

```txt
Use graph metadata to reveal useful structure.
```

Signals:

```txt
orphan pages: page nodes with no incoming or outgoing page_link edges
hub pages: pages with high degree
weak citation clusters: pages connected to unsupported/stale/needs_review audits
unresolved clusters: pages with many unresolved links
source-heavy pages: pages with many citation source edges
```

Signal calculation:

```txt
Calculate signals after rebuild_graph_for_vault completes.
Store results in graph_nodes.weight and graph_nodes.meta JSON.
Example meta: {"degree":12,"weak_citation_count":3,"orphan":false,"hub":true}
Do not recalculate signals on every GET request.
Trigger recalculation through page/vault rebuilds after suggestion apply, restore revision, and import completion.
Orphan page: page node with zero incoming and outgoing page_link edges.
Hub page: degree in the top 10% of pages in the vault.
Weak citation cluster: unsupported/stale/needs_review audit ratio above 50%.
```

Tasks:

```txt
Add summary metrics to GET /api/graph.
Add node weight calculation based on degree and citation risk.
Expose warnings for orphan pages and weak citation clusters.
Show graph summary strip in the UI.
```

Done when:

```txt
The graph tells users where the knowledge base needs attention.
```

## P5-005 Layout Cache

Goal:

```txt
Let users keep useful graph arrangements without making layout canonical.
```

Tasks:

```txt
Store pinned node positions in graph_layout_cache.
Use layout_key to separate filters/views.
Do not store every physics tick; save only explicit pin/move events.
Allow clearing layout cache for a vault.
```

Layout key rules:

```txt
Default graph layout_key: vault:{vault_id}:default
Filtered graph layout_key: vault:{vault_id}:filter:{hash}
Hash input: sorted filter parameters for node_type, edge_type, and status.
Hash format: first 8 characters of sha256(hash input).
Save pinned nodes only.
Pin event: user drags a node and releases it.
Unpin event: user double-clicks a node or chooses unpin from context menu.
```

Done when:

```txt
User-pinned graph positions survive reloads but graph topology remains rebuildable.
```

## P5-006 verify-index and Rebuild Checks

Goal:

```txt
Make graph state recoverable and auditable.
```

Tasks:

```txt
verify-index reports graph nodes whose target page/source/audit no longer exists.
verify-index reports links/citations missing graph edges.
rebuild_graph_for_vault returns created/skipped/removed/failed counts.
Graph rebuild never writes Markdown, frontmatter, or revisions.
GET /api/graph exposes graph_stale=true while an async rebuild is running.
```

Done when:

```txt
Graph metadata can be checked and rebuilt like other derived indexes.
```

## P5-007 Tests

Required tests:

```txt
page link creates page->page edge
unresolved link creates unresolved node
section creates page->section edge
citation audit creates page/source/audit edges
unsupported citation audit appears with risk status
graph API filters node_type and edge_type
neighborhood endpoint respects depth and limit
graph rebuild is idempotent
graph rebuild rolls back on transaction failure
graph API returns truncated and total_node_count
graph API returns graph_stale during rebuild
semantic_related skips missing embeddings
verify-index reports missing graph edges
layout cache stores pinned node only
layout_key hash is stable for equivalent sorted filters
web graph data shape renders without crashing
```

## Out of Scope

```txt
Graph database migration
Real-time collaborative graph editing
Automatic AI clustering/naming of communities
3D graph view
Large-scale distributed graph processing
```

## Suggested Development Order

```txt
1. P5-001 Graph Schema and Rebuild
2. P5-002 Graph API
3. P5-006 verify-index and Rebuild Checks
4. P5-003 Graph UI
5. P5-004 Knowledge Map Signals
6. P5-005 Layout Cache
7. P5-007 Tests
```
