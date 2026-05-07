PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pages (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  title TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  path TEXT NOT NULL,
  current_revision_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS revisions (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  page_id TEXT NOT NULL,
  path TEXT NOT NULL,
  author_type TEXT NOT NULL,
  change_note TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_pages (
  page_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  tier INTEGER NOT NULL DEFAULT 1,
  locked INTEGER NOT NULL DEFAULT 1,
  owner TEXT NOT NULL DEFAULT 'system',
  description TEXT,
  registered_at_phase TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_system_pages_kind
  ON system_pages(kind, tier, locked);

CREATE TABLE IF NOT EXISTS sections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id TEXT NOT NULL,
  revision_id TEXT,
  section_key TEXT NOT NULL,
  heading TEXT NOT NULL,
  level INTEGER NOT NULL,
  position INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id TEXT NOT NULL,
  revision_id TEXT,
  source_path TEXT NOT NULL,
  raw TEXT NOT NULL,
  target TEXT NOT NULL,
  display TEXT,
  status TEXT NOT NULL DEFAULT 'unresolved',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  page_id TEXT NOT NULL,
  revision_id TEXT,
  citation_key TEXT NOT NULL,
  display_title TEXT,
  source_type TEXT,
  source_id TEXT,
  validation_status TEXT NOT NULL DEFAULT 'unchecked',
  created_at TEXT NOT NULL,
  UNIQUE(page_id, revision_id, citation_key)
);

CREATE TABLE IF NOT EXISTS citation_audits (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  page_id TEXT NOT NULL,
  revision_id TEXT,
  citation_key TEXT NOT NULL,
  claim_hash TEXT NOT NULL,
  claim_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unchecked',
  confidence REAL,
  verifier_type TEXT NOT NULL,
  verifier_id TEXT,
  reason TEXT,
  source_hash TEXT,
  evidence_snapshot_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, page_id, revision_id, citation_key, claim_hash)
);

CREATE TABLE IF NOT EXISTS citation_evidence (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  citation_key TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT,
  source_path TEXT,
  excerpt TEXT NOT NULL,
  excerpt_hash TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citation_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  citation_audit_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason TEXT,
  meta TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  title TEXT NOT NULL,
  source_agent TEXT NOT NULL,
  source_model TEXT,
  review_type TEXT NOT NULL DEFAULT 'agent_review',
  status TEXT NOT NULL DEFAULT 'pending_review',
  page_id TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS findings (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  area TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS finding_evidence (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL,
  evidence TEXT,
  proposed_change TEXT,
  raw_text TEXT,
  evidence_quality TEXT NOT NULL DEFAULT 'unspecified',
  source_agent TEXT,
  source_model TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS finding_locations (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL,
  source_path TEXT NOT NULL,
  source_start_line INTEGER,
  source_end_line INTEGER,
  source_snippet TEXT,
  source_location_status TEXT NOT NULL DEFAULT 'omitted',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS finding_decisions (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL,
  status TEXT NOT NULL,
  decision_note TEXT,
  decided_by TEXT,
  decided_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  finding_id TEXT UNIQUE,
  status TEXT NOT NULL DEFAULT 'open',
  priority TEXT NOT NULL DEFAULT 'normal',
  owner TEXT,
  task_prompt TEXT NOT NULL,
  expected_verification TEXT,
  notes TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS implementation_records (
  id TEXT PRIMARY KEY,
  finding_id TEXT,
  commit_sha TEXT,
  changed_files TEXT,
  verification TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  state_hash TEXT,
  summary_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS packets (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  target_agent TEXT NOT NULL,
  profile TEXT NOT NULL DEFAULT 'overview',
  output_mode TEXT NOT NULL DEFAULT 'top_findings',
  focus TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  content_path TEXT,
  contract_version TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS packet_sources (
  id TEXT PRIMARY KEY,
  packet_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT,
  content_hash TEXT,
  source_path TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS node_cards (
  id TEXT PRIMARY KEY,
  packet_id TEXT NOT NULL,
  node_id TEXT,
  title TEXT NOT NULL,
  node_type TEXT,
  short_summary TEXT,
  detail_url TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_runs (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_profile TEXT NOT NULL,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  status TEXT NOT NULL,
  context_summary_json TEXT NOT NULL DEFAULT '{}',
  review_id TEXT,
  trace_id TEXT,
  packet_trace_id TEXT,
  error_code TEXT,
  error_message TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_run_metrics (
  run_id TEXT PRIMARY KEY,
  input_tokens INTEGER,
  output_tokens INTEGER,
  estimated_cost_usd REAL,
  duration_ms INTEGER,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_run_artifacts (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  artifact_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS graph_nodes (
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

CREATE TABLE IF NOT EXISTS graph_edges (
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

CREATE TABLE IF NOT EXISTS graph_pins (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  node_id TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, node_id)
);

CREATE TABLE IF NOT EXISTS embeddings (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  owner_type TEXT NOT NULL,
  owner_id TEXT NOT NULL,
  vector BLOB NOT NULL,
  dims INTEGER NOT NULL,
  model TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(owner_type, owner_id, model)
);

CREATE TABLE IF NOT EXISTS search_index_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
  page_id UNINDEXED,
  vault_id UNINDEXED,
  title,
  slug,
  body,
  tokenize = 'unicode61'
);

CREATE TABLE IF NOT EXISTS search_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  query TEXT NOT NULL,
  mode TEXT NOT NULL,
  result_count INTEGER NOT NULL,
  clicked_page_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  job_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  error_code TEXT,
  error_message TEXT,
  run_after TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance_locks (
  id TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS maintenance_runs (
  id TEXT PRIMARY KEY,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  report TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS backup_checks (
  id TEXT PRIMARY KEY,
  snapshot_path TEXT NOT NULL,
  status TEXT NOT NULL,
  report_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'viewer',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  actor_type TEXT NOT NULL,
  session_meta TEXT,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vaults (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vault_members (
  vault_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (vault_id, user_id)
);

CREATE TABLE IF NOT EXISTS agent_tokens (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  agent_model TEXT,
  purpose TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'agent_reader',
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  scopes TEXT NOT NULL DEFAULT '[]',
  max_pages_per_request INTEGER NOT NULL DEFAULT 20,
  max_chars_per_request INTEGER NOT NULL DEFAULT 60000,
  expires_at TEXT,
  revoked_at TEXT,
  last_used_at TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_access_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token_id TEXT,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  agent_name TEXT,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  request_id TEXT,
  status TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vault_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  request_id TEXT,
  meta TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_findings_review_status ON findings(review_id, status, severity);
CREATE INDEX IF NOT EXISTS idx_finding_evidence_finding ON finding_evidence(finding_id);
CREATE INDEX IF NOT EXISTS idx_finding_locations_finding ON finding_locations(finding_id);
CREATE INDEX IF NOT EXISTS idx_finding_decisions_finding ON finding_decisions(finding_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority, updated_at);
CREATE INDEX IF NOT EXISTS idx_packets_vault_created ON packets(vault_id, created_at);
CREATE INDEX IF NOT EXISTS idx_provider_runs_provider_status ON provider_runs(provider, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_provider_runs_trace ON provider_runs(trace_id, packet_trace_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_vault_type ON graph_nodes(vault_id, node_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_from ON graph_edges(vault_id, from_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_to ON graph_edges(vault_id, to_node_id);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash ON agent_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_agent_access_events_token ON agent_access_events(token_id, created_at);
