use std::fs;
use std::path::Path;

use rusqlite::{params, Connection, TransactionBehavior};

use crate::error::CoreError;
use crate::storage::util::{
    escape_json, generated_revision_id, strip_frontmatter, validate_id, validate_slug, write_synced,
};

pub struct CompleteDraftInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub job_id: &'a str,
    pub suggestion_id: &'a str,
    pub markdown_path: &'a str,
    pub title: &'a str,
    pub created_at: &'a str,
}

pub struct ApplySuggestionInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub suggestion_id: &'a str,
    pub slug: &'a str,
    pub revision_id: &'a str,
    pub applied_at: &'a str,
}

pub struct RejectSuggestionInput<'a> {
    pub sqlite_path: &'a str,
    pub suggestion_id: &'a str,
    pub rejected_at: &'a str,
}

pub fn complete_draft_job(input: CompleteDraftInput<'_>) -> Result<String, CoreError> {
    validate_id(input.job_id)?;
    validate_id(input.suggestion_id)?;

    let draft = fs::read_to_string(input.markdown_path)
        .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
    let data_dir = Path::new(input.data_dir);
    let suggestions_dir = data_dir.join("suggestions");
    fs::create_dir_all(&suggestions_dir)
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    let final_path = suggestions_dir.join(format!("{}.md", input.suggestion_id.replace('_', "-")));
    let temp_path =
        suggestions_dir.join(format!("{}.md.tmp", input.suggestion_id.replace('_', "-")));
    write_synced(&temp_path, &draft)?;

    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let (target_type, message_id): (String, String) = tx
        .query_row(
            "SELECT target_type, target_id FROM jobs WHERE id = ?1 AND status = 'running'",
            params![input.job_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .map_err(|err| CoreError::new("job_not_found", err.to_string()))?;
    if target_type != "message" {
        return Err(CoreError::new(
            "validation_error",
            "draft jobs must target a message",
        ));
    }

    let final_path_string = final_path.to_string_lossy().replace('\\', "/");
    tx.execute(
        "INSERT INTO suggestions (id, job_id, message_id, path, title, status, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, 'pending', ?6, ?6)",
        params![
            input.suggestion_id,
            input.job_id,
            message_id,
            final_path_string,
            input.title,
            input.created_at
        ],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;
    tx.execute(
        "UPDATE messages SET status = 'processed', updated_at = ?1 WHERE id = ?2",
        params![input.created_at, message_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "UPDATE jobs SET status = 'completed', updated_at = ?1 WHERE id = ?2",
        params![input.created_at, input.job_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let payload = format!(
        "{{\"job_id\":\"{}\",\"status\":\"completed\",\"suggestion_id\":\"{}\"}}",
        escape_json(input.job_id),
        escape_json(input.suggestion_id)
    );
    tx.execute(
        "INSERT INTO job_events (job_id, event_type, payload, created_at)
         VALUES (?1, 'job.completed', ?2, ?3)",
        params![input.job_id, payload, input.created_at],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    fs::rename(&temp_path, &final_path).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let _ = fs::remove_file(input.markdown_path);

    Ok(final_path_string)
}

pub fn apply_suggestion(input: ApplySuggestionInput<'_>) -> Result<String, CoreError> {
    validate_id(input.suggestion_id)?;
    validate_slug(input.slug)?;
    validate_id(input.revision_id)?;

    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let (suggestion_path, title): (String, String) = connection
        .query_row(
            "SELECT path, title FROM suggestions WHERE id = ?1",
            params![input.suggestion_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .map_err(|err| CoreError::new("suggestion_not_found", err.to_string()))?;
    let suggestion = fs::read_to_string(&suggestion_path)
        .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
    let body = strip_frontmatter(&suggestion);

    let page_id = format!("page_{}", input.slug.replace('-', "_"));
    let data_dir = Path::new(input.data_dir);
    let pages_dir = data_dir.join("pages");
    let revision_dir = data_dir.join("revisions").join(&page_id);
    fs::create_dir_all(&pages_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    fs::create_dir_all(&revision_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;

    let page_markdown = format!(
        "---\nschema_version: 1\nid: {}\ntitle: {}\nslug: {}\nstatus: active\ncreated_at: {}\nupdated_at: {}\n---\n\n{}",
        page_id,
        title,
        input.slug,
        input.applied_at,
        input.applied_at,
        body.trim_start()
    );
    let page_path = pages_dir.join(format!("{}.md", input.slug));
    let page_temp_path = pages_dir.join(format!("{}.md.tmp", input.slug));
    let revision_path = revision_dir.join(format!("{}.md", input.revision_id));
    let revision_temp_path = revision_dir.join(format!("{}.md.tmp", input.revision_id));
    let previous_revision_id = if page_path.exists() {
        Some(generated_revision_id("pre_apply"))
    } else {
        None
    };
    let previous_revision_path = previous_revision_id
        .as_ref()
        .map(|id| revision_dir.join(format!("{}.md", id)));
    let previous_revision_temp_path = previous_revision_id
        .as_ref()
        .map(|id| revision_dir.join(format!("{}.md.tmp", id)));

    write_synced(&page_temp_path, &page_markdown)?;
    write_synced(&revision_temp_path, &page_markdown)?;
    if let (Some(_), Some(temp_path)) = (&previous_revision_id, &previous_revision_temp_path) {
        let previous_markdown = fs::read_to_string(&page_path)
            .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
        write_synced(temp_path, &previous_markdown)?;
    }

    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let page_path_string = page_path.to_string_lossy().replace('\\', "/");
    let revision_path_string = revision_path.to_string_lossy().replace('\\', "/");
    tx.execute(
        "INSERT INTO pages (id, title, slug, path, current_revision_id, status, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, 'active', ?6, ?6)
         ON CONFLICT(slug) DO UPDATE SET
           title = excluded.title,
           path = excluded.path,
           current_revision_id = excluded.current_revision_id,
           status = excluded.status,
           updated_at = excluded.updated_at",
        params![
            page_id,
            title,
            input.slug,
            page_path_string,
            input.revision_id,
            input.applied_at
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO revisions (id, page_id, path, author_type, change_note, created_at)
         VALUES (?1, ?2, ?3, 'ai', ?4, ?5)",
        params![
            input.revision_id,
            page_id,
            revision_path_string,
            format!("Applied suggestion {}", input.suggestion_id),
            input.applied_at
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if let (Some(previous_id), Some(previous_path)) =
        (&previous_revision_id, &previous_revision_path)
    {
        let previous_path_string = previous_path.to_string_lossy().replace('\\', "/");
        tx.execute(
            "INSERT INTO revisions (id, page_id, path, author_type, change_note, created_at)
             VALUES (?1, ?2, ?3, 'system', ?4, ?5)",
            params![
                previous_id,
                page_id,
                previous_path_string,
                format!("Pre-apply backup before suggestion {}", input.suggestion_id),
                input.applied_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    }
    tx.execute(
        "UPDATE suggestions SET status = 'applied', updated_at = ?1 WHERE id = ?2",
        params![input.applied_at, input.suggestion_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    fs::rename(&page_temp_path, &page_path)
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    fs::rename(&revision_temp_path, &revision_path)
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    if let (Some(temp_path), Some(final_path)) =
        (&previous_revision_temp_path, &previous_revision_path)
    {
        fs::rename(temp_path, final_path)
            .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    }
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(page_path_string)
}

pub fn reject_suggestion(input: RejectSuggestionInput<'_>) -> Result<(), CoreError> {
    validate_id(input.suggestion_id)?;

    let connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let updated = connection
        .execute(
            "UPDATE suggestions SET status = 'rejected', updated_at = ?1 WHERE id = ?2",
            params![input.rejected_at, input.suggestion_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if updated == 0 {
        return Err(CoreError::new(
            "suggestion_not_found",
            "Suggestion not found",
        ));
    }
    Ok(())
}
