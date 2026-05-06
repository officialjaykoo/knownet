use std::fs;
use std::path::Path;

use rusqlite::Connection;

use crate::error::CoreError;

pub mod collaboration;
pub mod embeddings;
pub mod graph;
pub mod jobs;
pub mod messages;
pub mod pages;
pub mod phase3;
pub mod phase4;
pub mod suggestions;
pub mod util;

pub use collaboration::{
    create_collaboration_finding, create_collaboration_review, create_context_bundle_manifest,
    create_implementation_record, update_collaboration_review_status, update_finding_decision,
    CreateCollaborationFindingInput, CreateCollaborationReviewInput,
    CreateContextBundleManifestInput, CreateImplementationRecordInput,
    UpdateCollaborationReviewStatusInput, UpdateFindingDecisionInput,
};
pub use embeddings::{embedding_upsert, EmbeddingUpsertInput};
pub use graph::{
    clear_graph_layout_cache, ensure_graph_schema, rebuild_graph_for_page, rebuild_graph_for_vault,
    set_graph_node_pin, upsert_graph_layout_node, ClearGraphLayoutInput, GraphRebuildSummary,
    RebuildGraphInput, SetGraphNodePinInput, UpsertGraphLayoutInput,
};
pub use jobs::{claim_next_job, fail_job, recover_stale_jobs};
pub use messages::{
    write_message, write_pending_message, WriteMessageInput, WritePendingMessageInput,
};
pub use pages::{
    create_page, index_page_file, restore_revision, CreatePageInput, RestoreRevisionInput,
};
pub use phase3::{
    assign_vault_member, create_session, create_submission, create_user, create_vault,
    recover_page, revoke_session, tombstone_page, update_submission_status,
    AssignVaultMemberInput, CreateSessionInput, CreateSubmissionInput, CreateUserInput,
    CreateVaultInput, RecoverPageInput, TombstonePageInput, UpdateSubmissionStatusInput,
};
pub use phase4::{
    ensure_phase4_schema, rebuild_citation_audits_for_page, update_citation_audit_status,
    update_citation_validation_status, RebuildCitationAuditsInput, UpdateCitationAuditStatusInput,
    UpdateCitationValidationStatusInput,
};
pub use suggestions::{
    apply_suggestion, complete_draft_job, reject_suggestion, ApplySuggestionInput,
    CompleteDraftInput, RejectSuggestionInput,
};

const SCHEMA_SQL: &str = include_str!("../../../api/knownet_api/db/schema.sql");

pub struct InitDbResult {
    pub sqlite_path: String,
    pub journal_mode: String,
}

pub fn init_db(sqlite_path: &str) -> Result<InitDbResult, CoreError> {
    let path = Path::new(sqlite_path);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    }
    let connection =
        Connection::open(path).map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    ensure_model_review_run_columns(&connection)?;
    connection
        .execute_batch(SCHEMA_SQL)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .execute(
            "INSERT OR IGNORE INTO vaults (id, name, created_at) VALUES ('local-default', 'Local', datetime('now'))",
            [],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let journal_mode: String = connection
        .query_row("PRAGMA journal_mode;", [], |row| row.get(0))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(InitDbResult {
        sqlite_path: sqlite_path.to_string(),
        journal_mode,
    })
}

fn ensure_model_review_run_columns(connection: &Connection) -> Result<(), CoreError> {
    let table_exists: i64 = connection
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'model_review_runs'",
            [],
            |row| row.get(0),
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if table_exists == 0 {
        return Ok(());
    }

    let mut statement = connection
        .prepare("PRAGMA table_info(model_review_runs)")
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let columns = statement
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut existing = std::collections::HashSet::new();
    for column in columns {
        existing.insert(column.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?);
    }

    for column in ["trace_id", "packet_trace_id", "error_code", "error_message"] {
        if !existing.contains(column) {
            connection
                .execute(&format!("ALTER TABLE model_review_runs ADD COLUMN {column} TEXT"), [])
                .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        }
    }
    Ok(())
}
