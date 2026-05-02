use std::fs;
use std::path::Path;

use rusqlite::Connection;

use crate::error::CoreError;

pub mod embeddings;
pub mod collaboration;
pub mod graph;
pub mod jobs;
pub mod messages;
pub mod pages;
pub mod phase3;
pub mod phase4;
pub mod suggestions;
pub mod util;

pub use embeddings::{embedding_upsert, EmbeddingUpsertInput};
pub use collaboration::{
    create_collaboration_finding, create_collaboration_review, create_context_bundle_manifest,
    create_implementation_record, update_collaboration_review_status, update_finding_decision,
    CreateCollaborationFindingInput, CreateCollaborationReviewInput,
    CreateContextBundleManifestInput, CreateImplementationRecordInput,
    UpdateCollaborationReviewStatusInput, UpdateFindingDecisionInput,
};
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
    create_page, import_obsidian_page, index_page_file, restore_revision, CreatePageInput,
    ImportObsidianPageInput, RestoreRevisionInput,
};
pub use phase3::{
    assign_vault_member, create_session, create_submission, create_user, create_vault,
    recover_page, revoke_session, run_phase3_migration, tombstone_page, update_submission_status,
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
    connection
        .execute_batch(SCHEMA_SQL)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let journal_mode: String = connection
        .query_row("PRAGMA journal_mode;", [], |row| row.get(0))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(InitDbResult {
        sqlite_path: sqlite_path.to_string(),
        journal_mode,
    })
}
