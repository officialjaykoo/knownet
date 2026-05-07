use rusqlite::{params, Connection};

use crate::error::CoreError;
use crate::storage::util::validate_id;

pub struct CreateSubmissionInput<'a> {
    pub sqlite_path: &'a str,
    pub submission_id: &'a str,
    pub message_id: &'a str,
    pub actor_type: &'a str,
    pub session_id: Option<&'a str>,
    pub created_at: &'a str,
}

pub struct UpdateSubmissionStatusInput<'a> {
    pub sqlite_path: &'a str,
    pub submission_id: &'a str,
    pub status: &'a str,
    pub reviewed_by: &'a str,
    pub review_note: Option<&'a str>,
    pub updated_at: &'a str,
}

pub fn create_submission(input: CreateSubmissionInput<'_>) -> Result<(), CoreError> {
    validate_id(input.submission_id)?;
    validate_id(input.message_id)?;
    let connection = open_connection(input.sqlite_path)?;
    connection
        .execute(
            "INSERT INTO submissions (id, message_id, actor_type, session_id, status, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, 'pending_review', ?5, ?5)",
            params![
                input.submission_id,
                input.message_id,
                input.actor_type,
                input.session_id,
                input.created_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn update_submission_status(
    input: UpdateSubmissionStatusInput<'_>,
) -> Result<String, CoreError> {
    validate_id(input.submission_id)?;
    validate_id(input.reviewed_by)?;
    if input.status != "queued" && input.status != "rejected" {
        return Err(CoreError::new(
            "validation_error",
            "unsupported submission status",
        ));
    }
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let message_id: String = tx
        .query_row(
            "SELECT message_id FROM submissions WHERE id = ?1",
            params![input.submission_id],
            |row| row.get(0),
        )
        .map_err(|err| CoreError::new("submission_not_found", err.to_string()))?;
    tx.execute(
        "UPDATE submissions SET status = ?1, reviewed_by = ?2, review_note = ?3, updated_at = ?4 WHERE id = ?5",
        params![
            input.status,
            input.reviewed_by,
            input.review_note,
            input.updated_at,
            input.submission_id
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    if input.status == "queued" {
        let job_id = message_id.replacen("msg", "job", 1);
        tx.execute(
            "UPDATE messages SET status = 'queued', updated_at = ?1 WHERE id = ?2",
            params![input.updated_at, message_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        tx.execute(
            "INSERT INTO jobs (id, job_type, target_type, target_id, status, attempts, max_attempts, created_at, updated_at)
             VALUES (?1, 'draft_page', 'message', ?2, 'queued', 0, 3, ?3, ?3)",
            params![job_id, message_id, input.updated_at],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        tx.execute(
            "INSERT INTO job_events (job_id, event_type, payload, created_at)
             VALUES (?1, 'job.queued', ?2, ?3)",
            params![
                job_id,
                "{\"status\":\"queued\",\"source\":\"submission\"}",
                input.updated_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        tx.commit()
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        return Ok(job_id);
    }

    tx.execute(
        "UPDATE messages SET status = 'rejected', updated_at = ?1 WHERE id = ?2",
        params![input.updated_at, message_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(String::new())
}

fn open_connection(sqlite_path: &str) -> Result<Connection, CoreError> {
    let connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(connection)
}
