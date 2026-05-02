use rusqlite::{params, Connection, TransactionBehavior};

use crate::error::CoreError;
use crate::storage::util::escape_json;

pub struct ClaimedJob {
    pub id: String,
    pub job_type: String,
    pub target_type: String,
    pub target_id: String,
    pub attempts: i64,
    pub max_attempts: i64,
}

pub fn claim_next_job(sqlite_path: &str, now: &str) -> Result<Option<ClaimedJob>, CoreError> {
    let mut connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let job = {
        let mut statement = tx
            .prepare(
                "SELECT id, job_type, target_type, target_id, attempts, max_attempts
                 FROM jobs
                 WHERE status IN ('queued', 'retry_scheduled')
                   AND (run_after IS NULL OR run_after <= ?1)
                   AND NOT EXISTS (
                     SELECT 1 FROM jobs running
                     WHERE running.target_type = jobs.target_type
                       AND running.target_id = jobs.target_id
                       AND running.status = 'running'
                   )
                 ORDER BY created_at ASC
                 LIMIT 1",
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let mut rows = statement
            .query(params![now])
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        if let Some(row) = rows
            .next()
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?
        {
            Some(ClaimedJob {
                id: row
                    .get(0)
                    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?,
                job_type: row
                    .get(1)
                    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?,
                target_type: row
                    .get(2)
                    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?,
                target_id: row
                    .get(3)
                    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?,
                attempts: row
                    .get(4)
                    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?,
                max_attempts: row
                    .get(5)
                    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?,
            })
        } else {
            None
        }
    };

    if let Some(job) = job {
        tx.execute(
            "UPDATE jobs
             SET status = 'running', attempts = attempts + 1, updated_at = ?1
             WHERE id = ?2",
            params![now, job.id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let payload = format!(
            "{{\"job_id\":\"{}\",\"status\":\"running\"}}",
            escape_json(&job.id)
        );
        tx.execute(
            "INSERT INTO job_events (job_id, event_type, payload, created_at)
             VALUES (?1, 'job.running', ?2, ?3)",
            params![job.id, payload, now],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        tx.commit()
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        Ok(Some(job))
    } else {
        tx.commit()
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        Ok(None)
    }
}

pub fn fail_job(
    sqlite_path: &str,
    job_id: &str,
    error_code: &str,
    error_message: &str,
    now: &str,
) -> Result<(), CoreError> {
    let mut connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "UPDATE jobs
         SET status = 'failed', error_code = ?1, error_message = ?2, updated_at = ?3
         WHERE id = ?4",
        params![error_code, error_message, now, job_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let payload = format!(
        "{{\"job_id\":\"{}\",\"status\":\"failed\",\"error_code\":\"{}\"}}",
        escape_json(job_id),
        escape_json(error_code)
    );
    tx.execute(
        "INSERT INTO job_events (job_id, event_type, payload, created_at)
         VALUES (?1, 'job.failed', ?2, ?3)",
        params![job_id, payload, now],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn recover_stale_jobs(
    sqlite_path: &str,
    stale_before: &str,
    now: &str,
) -> Result<i64, CoreError> {
    let mut connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let mut recovered = 0;
    {
        let mut statement = tx
            .prepare(
                "SELECT id, attempts, max_attempts
                 FROM jobs
                 WHERE status = 'running' AND updated_at <= ?1",
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let rows = statement
            .query_map(params![stale_before], |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, i64>(2)?,
                ))
            })
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        for row in rows {
            let (job_id, attempts, max_attempts) =
                row.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
            let (status, event_type) = if attempts >= max_attempts {
                ("failed", "job.failed")
            } else {
                ("retry_scheduled", "job.retry_scheduled")
            };
            tx.execute(
                "UPDATE jobs
                 SET status = ?1, run_after = ?2, error_code = ?3, error_message = ?4, updated_at = ?2
                 WHERE id = ?5",
                params![
                    status,
                    now,
                    "stale_job",
                    "Recovered stale running job",
                    job_id
                ],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
            let payload = format!(
                "{{\"job_id\":\"{}\",\"status\":\"{}\"}}",
                escape_json(&job_id),
                escape_json(status)
            );
            tx.execute(
                "INSERT INTO job_events (job_id, event_type, payload, created_at)
                 VALUES (?1, ?2, ?3, ?4)",
                params![job_id, event_type, payload, now],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
            recovered += 1;
        }
    }
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(recovered)
}
