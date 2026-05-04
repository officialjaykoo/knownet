use std::fs;
use std::path::Path;

use rusqlite::{params, Connection};

use crate::error::CoreError;
use crate::storage::util::{validate_id, write_synced};

pub struct CreateCollaborationReviewInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub review_id: &'a str,
    pub vault_id: &'a str,
    pub title: &'a str,
    pub source_agent: &'a str,
    pub source_model: Option<&'a str>,
    pub review_type: &'a str,
    pub page_id: Option<&'a str>,
    pub markdown: &'a str,
    pub meta: &'a str,
    pub created_at: &'a str,
}

pub struct CreateCollaborationFindingInput<'a> {
    pub sqlite_path: &'a str,
    pub finding_id: &'a str,
    pub review_id: &'a str,
    pub severity: &'a str,
    pub area: &'a str,
    pub title: &'a str,
    pub evidence: Option<&'a str>,
    pub proposed_change: Option<&'a str>,
    pub raw_text: Option<&'a str>,
    pub evidence_quality: &'a str,
    pub status: &'a str,
    pub created_at: &'a str,
}

pub struct UpdateFindingDecisionInput<'a> {
    pub sqlite_path: &'a str,
    pub finding_id: &'a str,
    pub status: &'a str,
    pub decision_note: Option<&'a str>,
    pub decided_by: &'a str,
    pub decided_at: &'a str,
}

pub struct UpdateCollaborationReviewStatusInput<'a> {
    pub sqlite_path: &'a str,
    pub review_id: &'a str,
    pub status: &'a str,
    pub updated_at: &'a str,
}

pub struct CreateImplementationRecordInput<'a> {
    pub sqlite_path: &'a str,
    pub record_id: &'a str,
    pub finding_id: &'a str,
    pub commit_sha: Option<&'a str>,
    pub changed_files: &'a str,
    pub verification: &'a str,
    pub notes: Option<&'a str>,
    pub created_at: &'a str,
}

pub struct CreateContextBundleManifestInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub manifest_id: &'a str,
    pub vault_id: &'a str,
    pub filename: &'a str,
    pub content: &'a str,
    pub selected_pages: &'a str,
    pub included_sections: &'a str,
    pub excluded_sections: &'a str,
    pub content_hash: &'a str,
    pub created_by: &'a str,
    pub created_at: &'a str,
}

fn connection(sqlite_path: &str) -> Result<Connection, CoreError> {
    let connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(connection)
}

fn validate_status(status: &str, allowed: &[&str]) -> Result<(), CoreError> {
    if allowed.contains(&status) {
        Ok(())
    } else {
        Err(CoreError::new(
            "collaboration_invalid_status",
            "Invalid collaboration status",
        ))
    }
}

fn validate_filename(filename: &str) -> Result<(), CoreError> {
    let valid = filename
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.'));
    if filename.is_empty() || filename.contains("..") || !valid || !filename.ends_with(".md") {
        return Err(CoreError::new(
            "context_bundle_forbidden_path",
            "Invalid context bundle filename",
        ));
    }
    Ok(())
}

pub fn create_collaboration_review(
    input: CreateCollaborationReviewInput<'_>,
) -> Result<String, CoreError> {
    validate_id(input.review_id)?;
    validate_id(input.vault_id)?;
    if let Some(page_id) = input.page_id {
        validate_id(page_id)?;
    }
    validate_status(input.review_type, &["agent_review"])?;

    let review_dir = Path::new(input.data_dir).join("pages").join("reviews");
    fs::create_dir_all(&review_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    let review_path = review_dir.join(format!("{}.md", input.review_id));
    let temp_path = review_dir.join(format!("{}.md.tmp", input.review_id));
    if review_path.exists() {
        return Err(CoreError::new(
            "collaboration_review_exists",
            "Collaboration review already exists",
        ));
    }
    write_synced(&temp_path, input.markdown)?;

    let mut connection = connection(input.sqlite_path)?;
    let tx = connection
        .transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO collaboration_reviews (
          id, vault_id, title, source_agent, source_model, review_type, status,
          page_id, meta, created_at, updated_at
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'pending_review', ?7, ?8, ?9, ?9)",
        params![
            input.review_id,
            input.vault_id,
            input.title,
            input.source_agent,
            input.source_model,
            input.review_type,
            input.page_id,
            input.meta,
            input.created_at
        ],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;
    fs::rename(&temp_path, &review_path).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(review_path.to_string_lossy().replace('\\', "/"))
}

pub fn create_collaboration_finding(
    input: CreateCollaborationFindingInput<'_>,
) -> Result<(), CoreError> {
    validate_id(input.finding_id)?;
    validate_id(input.review_id)?;
    validate_status(
        input.status,
        &[
            "pending",
            "accepted",
            "rejected",
            "deferred",
            "needs_more_context",
            "implemented",
        ],
    )?;
    validate_status(
        input.severity,
        &["critical", "high", "medium", "low", "info"],
    )?;
    let connection = connection(input.sqlite_path)?;
    connection
        .execute(
            "INSERT INTO collaboration_findings (
              id, review_id, severity, area, title, evidence, proposed_change,
              raw_text, evidence_quality, status, created_at, updated_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?11)",
            params![
                input.finding_id,
                input.review_id,
                input.severity,
                input.area,
                input.title,
                input.evidence,
                input.proposed_change,
                input.raw_text,
                input.evidence_quality,
                input.status,
                input.created_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn update_finding_decision(input: UpdateFindingDecisionInput<'_>) -> Result<(), CoreError> {
    validate_id(input.finding_id)?;
    validate_status(
        input.status,
        &["accepted", "rejected", "deferred", "needs_more_context"],
    )?;
    let connection = connection(input.sqlite_path)?;
    let changed = connection
        .execute(
            "UPDATE collaboration_findings
             SET status = ?1, decision_note = ?2, decided_by = ?3, decided_at = ?4, updated_at = ?4
             WHERE id = ?5",
            params![
                input.status,
                input.decision_note,
                input.decided_by,
                input.decided_at,
                input.finding_id
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if changed == 0 {
        return Err(CoreError::new(
            "collaboration_finding_not_found",
            "Collaboration finding not found",
        ));
    }
    Ok(())
}

pub fn update_collaboration_review_status(
    input: UpdateCollaborationReviewStatusInput<'_>,
) -> Result<(), CoreError> {
    validate_id(input.review_id)?;
    validate_status(
        input.status,
        &["pending_review", "triaged", "implemented", "archived"],
    )?;
    let connection = connection(input.sqlite_path)?;
    let changed = connection
        .execute(
            "UPDATE collaboration_reviews SET status = ?1, updated_at = ?2 WHERE id = ?3",
            params![input.status, input.updated_at, input.review_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if changed == 0 {
        return Err(CoreError::new(
            "collaboration_review_not_found",
            "Collaboration review not found",
        ));
    }
    Ok(())
}

pub fn create_implementation_record(
    input: CreateImplementationRecordInput<'_>,
) -> Result<(), CoreError> {
    validate_id(input.record_id)?;
    validate_id(input.finding_id)?;
    let mut connection = connection(input.sqlite_path)?;
    let tx = connection
        .transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let finding_exists: i64 = tx
        .query_row(
            "SELECT COUNT(*) FROM collaboration_findings WHERE id = ?1",
            params![input.finding_id],
            |row| row.get(0),
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if finding_exists == 0 {
        return Err(CoreError::new(
            "collaboration_finding_not_found",
            "Collaboration finding not found",
        ));
    }
    tx.execute(
        "INSERT INTO implementation_records (
          id, finding_id, commit_sha, changed_files, verification, notes, created_at
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            input.record_id,
            input.finding_id,
            input.commit_sha,
            input.changed_files,
            input.verification,
            input.notes,
            input.created_at
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "UPDATE collaboration_findings SET status = 'implemented', updated_at = ?1 WHERE id = ?2 AND status = 'accepted'",
        params![input.created_at, input.finding_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn create_context_bundle_manifest(
    input: CreateContextBundleManifestInput<'_>,
) -> Result<String, CoreError> {
    validate_id(input.manifest_id)?;
    validate_id(input.vault_id)?;
    validate_filename(input.filename)?;
    let bundle_dir = Path::new(input.data_dir).join("context-bundles");
    fs::create_dir_all(&bundle_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    let bundle_path = bundle_dir.join(input.filename);
    let temp_path = bundle_dir.join(format!("{}.tmp", input.filename));
    write_synced(&temp_path, input.content)?;
    let path_string = bundle_path.to_string_lossy().replace('\\', "/");
    let mut connection = connection(input.sqlite_path)?;
    let tx = connection
        .transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO context_bundle_manifests (
          id, vault_id, filename, path, selected_pages, included_sections,
          excluded_sections, content_hash, created_by, created_at
        ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
        params![
            input.manifest_id,
            input.vault_id,
            input.filename,
            path_string,
            input.selected_pages,
            input.included_sections,
            input.excluded_sections,
            input.content_hash,
            input.created_by,
            input.created_at
        ],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;
    fs::rename(&temp_path, &bundle_path).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(path_string)
}
