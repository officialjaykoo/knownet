PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;

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

CREATE TABLE IF NOT EXISTS citation_evidence_snapshots (
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

CREATE TABLE IF NOT EXISTS citation_audit_events (
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

CREATE INDEX IF NOT EXISTS idx_citation_audits_status
  ON citation_audits(vault_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_citation_audits_page
  ON citation_audits(vault_id, page_id, revision_id);

CREATE INDEX IF NOT EXISTS idx_citation_audit_events_audit
  ON citation_audit_events(citation_audit_id, created_at);

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

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  path TEXT NOT NULL,
  status TEXT NOT NULL,
  related_page_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS suggestions (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  job_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  path TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  created_at TEXT NOT NULL,
  action TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT,
  session_id TEXT,
  ip_hash TEXT,
  user_agent_hash TEXT,
  target_type TEXT,
  target_id TEXT,
  before_revision_id TEXT,
  after_revision_id TEXT,
  model_provider TEXT,
  model_name TEXT,
  model_version TEXT,
  prompt_version TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
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

CREATE TABLE IF NOT EXISTS ai_actors (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  config_hash TEXT,
  operation_type TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS submissions (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  session_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending_review',
  reviewed_by TEXT,
  review_note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS graph_layout_cache (
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

CREATE TABLE IF NOT EXISTS graph_node_pins (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  node_id TEXT NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_vault_type
  ON graph_nodes(vault_id, node_type);

CREATE INDEX IF NOT EXISTS idx_graph_edges_from
  ON graph_edges(vault_id, from_node_id);

CREATE INDEX IF NOT EXISTS idx_graph_edges_to
  ON graph_edges(vault_id, to_node_id);

CREATE TABLE IF NOT EXISTS collaboration_reviews (
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

CREATE TABLE IF NOT EXISTS collaboration_findings (
  id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  area TEXT NOT NULL,
  title TEXT NOT NULL,
  evidence TEXT,
  proposed_change TEXT,
  raw_text TEXT,
  evidence_quality TEXT NOT NULL DEFAULT 'unspecified',
  status TEXT NOT NULL DEFAULT 'pending',
  decision_note TEXT,
  decided_by TEXT,
  decided_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(review_id) REFERENCES collaboration_reviews(id)
);

CREATE TABLE IF NOT EXISTS implementation_records (
  id TEXT PRIMARY KEY,
  finding_id TEXT,
  commit_sha TEXT,
  changed_files TEXT,
  verification TEXT,
  notes TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(finding_id) REFERENCES collaboration_findings(id)
);

CREATE TABLE IF NOT EXISTS finding_tasks (
  id TEXT PRIMARY KEY,
  finding_id TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'open',
  priority TEXT NOT NULL DEFAULT 'normal',
  owner TEXT,
  task_prompt TEXT NOT NULL,
  expected_verification TEXT,
  notes TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(finding_id) REFERENCES collaboration_findings(id)
);

CREATE TABLE IF NOT EXISTS context_bundle_manifests (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  filename TEXT NOT NULL,
  path TEXT NOT NULL,
  selected_pages TEXT NOT NULL DEFAULT '[]',
  included_sections TEXT NOT NULL DEFAULT '[]',
  excluded_sections TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_collaboration_reviews_vault_status
  ON collaboration_reviews(vault_id, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_collaboration_findings_review
  ON collaboration_findings(review_id, status, severity);

CREATE INDEX IF NOT EXISTS idx_implementation_records_finding
  ON implementation_records(finding_id);

CREATE INDEX IF NOT EXISTS idx_finding_tasks_status
  ON finding_tasks(status, priority, updated_at);

CREATE INDEX IF NOT EXISTS idx_context_bundle_manifests_vault
  ON context_bundle_manifests(vault_id, created_at);

CREATE TABLE IF NOT EXISTS experiment_packets (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  experiment_name TEXT NOT NULL,
  target_agent TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  content_path TEXT NOT NULL,
  node_slugs TEXT NOT NULL DEFAULT '[]',
  scenarios TEXT NOT NULL DEFAULT '[]',
  preflight_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiment_packet_responses (
  id TEXT PRIMARY KEY,
  packet_id TEXT NOT NULL,
  source_agent TEXT NOT NULL,
  source_model TEXT,
  response_markdown TEXT NOT NULL,
  dry_run_json TEXT NOT NULL DEFAULT '{}',
  imported_review_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(packet_id) REFERENCES experiment_packets(id)
);

CREATE INDEX IF NOT EXISTS idx_experiment_packets_vault_created
  ON experiment_packets(vault_id, created_at);

CREATE INDEX IF NOT EXISTS idx_experiment_packet_responses_packet
  ON experiment_packet_responses(packet_id, created_at);

CREATE TABLE IF NOT EXISTS project_snapshot_packets (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  target_agent TEXT NOT NULL,
  profile TEXT NOT NULL DEFAULT 'overview',
  output_mode TEXT NOT NULL DEFAULT 'top_findings',
  focus TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  content_path TEXT NOT NULL,
  warnings_json TEXT NOT NULL DEFAULT '[]',
  snapshot_quality_json TEXT NOT NULL DEFAULT '{}',
  contract_version TEXT NOT NULL DEFAULT 'p20.v1',
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_snapshot_packets_vault_created
  ON project_snapshot_packets(vault_id, created_at);

CREATE TABLE IF NOT EXISTS ai_state_pages (
  id TEXT PRIMARY KEY,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  page_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  title TEXT NOT NULL,
  source_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  state_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(vault_id, page_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_state_pages_vault_updated
  ON ai_state_pages(vault_id, updated_at);

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

CREATE INDEX IF NOT EXISTS idx_system_pages_kind
  ON system_pages(kind, tier, locked);

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

CREATE INDEX IF NOT EXISTS idx_agent_tokens_hash
  ON agent_tokens(token_hash);

CREATE INDEX IF NOT EXISTS idx_agent_access_events_token
  ON agent_access_events(token_id, created_at);

CREATE TABLE IF NOT EXISTS model_review_runs (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_profile TEXT NOT NULL,
  vault_id TEXT NOT NULL DEFAULT 'local-default',
  status TEXT NOT NULL,
  context_summary_json TEXT NOT NULL DEFAULT '{}',
  request_json TEXT NOT NULL DEFAULT '{}',
  response_json TEXT NOT NULL DEFAULT '{}',
  input_tokens INTEGER,
  output_tokens INTEGER,
  estimated_cost_usd REAL,
  review_id TEXT,
  trace_id TEXT,
  packet_trace_id TEXT,
  error_code TEXT,
  error_message TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_review_runs_provider_status
  ON model_review_runs(provider, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_model_review_runs_vault_updated
  ON model_review_runs(vault_id, updated_at);

CREATE INDEX IF NOT EXISTS idx_model_review_runs_trace
  ON model_review_runs(trace_id, packet_trace_id);

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

CREATE TRIGGER IF NOT EXISTS audit_log_to_events
AFTER INSERT ON audit_log
BEGIN
  INSERT INTO audit_events (
    vault_id, actor_type, actor_id, action, target_type, target_id, request_id, meta, created_at
  ) VALUES (
    NEW.vault_id,
    NEW.actor_type,
    COALESCE(NEW.actor_id, 'unknown'),
    NEW.action,
    NEW.target_type,
    NEW.target_id,
    NEW.session_id,
    NEW.metadata_json,
    NEW.created_at
  );
END;
