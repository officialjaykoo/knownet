use std::fs;
use std::path::Path;

use rusqlite::{params, Connection};

use crate::error::CoreError;
use crate::storage::util::{escape_json, validate_id, write_synced};

pub struct WriteMessageInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub message_id: &'a str,
    pub content: &'a str,
    pub created_at: &'a str,
}

pub struct WritePendingMessageInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub message_id: &'a str,
    pub content: &'a str,
    pub created_at: &'a str,
}

pub struct WriteMessageResult {
    pub message_id: String,
    pub job_id: String,
    pub path: String,
    pub status: String,
}

pub struct WritePendingMessageResult {
    pub message_id: String,
    pub path: String,
    pub status: String,
}

pub fn write_message(input: WriteMessageInput<'_>) -> Result<WriteMessageResult, CoreError> {
    validate_id(input.message_id)?;
    let data_dir = Path::new(input.data_dir);
    let inbox_dir = data_dir.join("inbox");
    fs::create_dir_all(&inbox_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;

    let file_stem = input.message_id.replace('_', "-");
    let final_path = inbox_dir.join(format!("{file_stem}.md"));
    let temp_path = inbox_dir.join(format!("{file_stem}.md.tmp"));
    let markdown = format!(
        "---\nschema_version: 1\nid: {}\nstatus: queued\nrelated_page: null\ncreated_at: {}\n---\n\n{}\n",
        input.message_id, input.created_at, input.content
    );
    write_synced(&temp_path, &markdown)?;

    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let job_id = input.message_id.replacen("msg", "job", 1);
    let final_path_string = final_path.to_string_lossy().replace('\\', "/");

    tx.execute(
        "INSERT INTO messages (id, path, status, related_page_id, created_at, updated_at)
         VALUES (?1, ?2, 'queued', NULL, ?3, ?3)",
        params![input.message_id, final_path_string, input.created_at],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;

    tx.execute(
        "INSERT INTO jobs (id, job_type, target_type, target_id, status, attempts, max_attempts, created_at, updated_at)
         VALUES (?1, 'draft_page', 'message', ?2, 'queued', 0, 3, ?3, ?3)",
        params![job_id, input.message_id, input.created_at],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;

    let event_payload = format!(
        "{{\"job_id\":\"{}\",\"status\":\"queued\"}}",
        escape_json(&job_id)
    );
    tx.execute(
        "INSERT INTO job_events (job_id, event_type, payload, created_at)
         VALUES (?1, 'job.queued', ?2, ?3)",
        params![job_id, event_payload, input.created_at],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;

    fs::rename(&temp_path, &final_path).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("io_error", err.to_string())
    })?;

    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    Ok(WriteMessageResult {
        message_id: input.message_id.to_string(),
        job_id,
        path: final_path_string,
        status: "queued".to_string(),
    })
}

pub fn write_pending_message(
    input: WritePendingMessageInput<'_>,
) -> Result<WritePendingMessageResult, CoreError> {
    validate_id(input.message_id)?;
    let data_dir = Path::new(input.data_dir);
    let inbox_dir = data_dir.join("inbox");
    fs::create_dir_all(&inbox_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;

    let file_stem = input.message_id.replace('_', "-");
    let final_path = inbox_dir.join(format!("{file_stem}.md"));
    let temp_path = inbox_dir.join(format!("{file_stem}.md.tmp"));
    let markdown = format!(
        "---\nschema_version: 1\nid: {}\nstatus: pending_review\nrelated_page: null\ncreated_at: {}\n---\n\n{}\n",
        input.message_id, input.created_at, input.content
    );
    write_synced(&temp_path, &markdown)?;

    let connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let final_path_string = final_path.to_string_lossy().replace('\\', "/");
    connection
        .execute(
            "INSERT INTO messages (id, path, status, related_page_id, created_at, updated_at)
             VALUES (?1, ?2, 'pending_review', NULL, ?3, ?3)",
            params![input.message_id, final_path_string, input.created_at],
        )
        .map_err(|err| {
            let _ = fs::remove_file(&temp_path);
            CoreError::new("sqlite_error", err.to_string())
        })?;

    fs::rename(&temp_path, &final_path).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("io_error", err.to_string())
    })?;

    Ok(WritePendingMessageResult {
        message_id: input.message_id.to_string(),
        path: final_path_string,
        status: "pending_review".to_string(),
    })
}
