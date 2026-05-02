use std::fs;
use std::path::{Path, PathBuf};

use rusqlite::{params, Connection};

use crate::error::CoreError;
use crate::storage::util::validate_id;

const DEFAULT_VAULT_ID: &str = "local-default";
const DEFAULT_VAULT_NAME: &str = "Local";

pub struct CreateUserInput<'a> {
    pub sqlite_path: &'a str,
    pub user_id: &'a str,
    pub username: &'a str,
    pub password_hash: &'a str,
    pub role: &'a str,
    pub created_at: &'a str,
}

pub struct CreateSessionInput<'a> {
    pub sqlite_path: &'a str,
    pub session_id: &'a str,
    pub user_id: Option<&'a str>,
    pub actor_type: &'a str,
    pub session_meta: &'a str,
    pub expires_at: &'a str,
    pub created_at: &'a str,
}

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

pub struct TombstonePageInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub slug: &'a str,
    pub tombstoned_at: &'a str,
}

pub struct RecoverPageInput<'a> {
    pub sqlite_path: &'a str,
    pub slug: &'a str,
    pub recovered_at: &'a str,
}

pub struct CreateVaultInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub name: &'a str,
    pub owner_user_id: &'a str,
    pub created_at: &'a str,
}

pub struct AssignVaultMemberInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub user_id: &'a str,
    pub role: &'a str,
    pub created_at: &'a str,
}

pub fn run_phase3_migration(
    sqlite_path: &str,
    backup_dir: &str,
    migrated_at: &str,
) -> Result<String, CoreError> {
    let db_path = Path::new(sqlite_path);
    if db_path.exists() {
        let backup_root = Path::new(backup_dir);
        fs::create_dir_all(backup_root)
            .map_err(|err| CoreError::new("io_error", err.to_string()))?;
        let backup_path = backup_root.join(format!(
            "knownet-phase3-{}.db",
            sanitize_timestamp(migrated_at)
        ));
        fs::copy(db_path, backup_path)
            .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    }

    let connection = open_connection(sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    tx.execute(
        "CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'viewer',
          created_at TEXT NOT NULL
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TABLE IF NOT EXISTS sessions (
          id TEXT PRIMARY KEY,
          user_id TEXT,
          actor_type TEXT NOT NULL,
          session_meta TEXT,
          expires_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TABLE IF NOT EXISTS ai_actors (
          id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          config_hash TEXT,
          operation_type TEXT NOT NULL,
          created_at TEXT NOT NULL
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TABLE IF NOT EXISTS vaults (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          created_at TEXT NOT NULL
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TABLE IF NOT EXISTS vault_members (
          vault_id TEXT NOT NULL,
          user_id TEXT NOT NULL,
          role TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY (vault_id, user_id)
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TABLE IF NOT EXISTS submissions (
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL,
          actor_type TEXT NOT NULL,
          session_id TEXT,
          status TEXT NOT NULL DEFAULT 'pending_review',
          reviewed_by TEXT,
          review_note TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TABLE IF NOT EXISTS audit_events (
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
        )",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_log_to_events
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
         END",
        [],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    for table in [
        "pages",
        "revisions",
        "messages",
        "jobs",
        "suggestions",
        "embeddings",
        "audit_log",
    ] {
        add_vault_id_if_missing(&tx, table)?;
    }

    tx.execute(
        "INSERT OR IGNORE INTO vaults (id, name, created_at) VALUES (?1, ?2, ?3)",
        params![DEFAULT_VAULT_ID, DEFAULT_VAULT_NAME, migrated_at],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    Ok(DEFAULT_VAULT_ID.to_string())
}

pub fn create_user(input: CreateUserInput<'_>) -> Result<(), CoreError> {
    validate_id(input.user_id)?;
    if input.username.trim().is_empty() {
        return Err(CoreError::new("validation_error", "username is required"));
    }
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
        params![input.user_id, input.username, input.password_hash, input.role, input.created_at],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT OR IGNORE INTO vault_members (vault_id, user_id, role, created_at) VALUES (?1, ?2, ?3, ?4)",
        params![DEFAULT_VAULT_ID, input.user_id, input.role, input.created_at],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn create_vault(input: CreateVaultInput<'_>) -> Result<(), CoreError> {
    validate_id(input.vault_id)?;
    validate_id(input.owner_user_id)?;
    if input.name.trim().is_empty() {
        return Err(CoreError::new("validation_error", "vault name is required"));
    }
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO vaults (id, name, created_at) VALUES (?1, ?2, ?3)",
        params![input.vault_id, input.name, input.created_at],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO vault_members (vault_id, user_id, role, created_at) VALUES (?1, ?2, 'owner', ?3)",
        params![input.vault_id, input.owner_user_id, input.created_at],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn assign_vault_member(input: AssignVaultMemberInput<'_>) -> Result<(), CoreError> {
    validate_id(input.vault_id)?;
    validate_id(input.user_id)?;
    if !["owner", "admin", "editor", "reviewer", "viewer"].contains(&input.role) {
        return Err(CoreError::new("validation_error", "unsupported vault role"));
    }
    let connection = open_connection(input.sqlite_path)?;
    connection
        .execute(
            "INSERT INTO vault_members (vault_id, user_id, role, created_at)
             VALUES (?1, ?2, ?3, ?4)
             ON CONFLICT(vault_id, user_id) DO UPDATE SET role = excluded.role",
            params![input.vault_id, input.user_id, input.role, input.created_at],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn create_session(input: CreateSessionInput<'_>) -> Result<(), CoreError> {
    validate_id(input.session_id)?;
    let connection = open_connection(input.sqlite_path)?;
    connection
        .execute(
            "INSERT INTO sessions (id, user_id, actor_type, session_meta, expires_at, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                input.session_id,
                input.user_id,
                input.actor_type,
                input.session_meta,
                input.expires_at,
                input.created_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn revoke_session(sqlite_path: &str, session_id: &str) -> Result<(), CoreError> {
    validate_id(session_id)?;
    let connection = open_connection(sqlite_path)?;
    connection
        .execute("DELETE FROM sessions WHERE id = ?1", params![session_id])
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
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

pub fn tombstone_page(input: TombstonePageInput<'_>) -> Result<String, CoreError> {
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let (page_id, page_path, status): (String, String, String) = tx
        .query_row(
            "SELECT id, path, status FROM pages WHERE slug = ?1",
            params![input.slug],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .map_err(|err| CoreError::new("page_not_found", err.to_string()))?;
    if status == "tombstone" {
        return Err(CoreError::new(
            "page_already_tombstoned",
            "page is already tombstoned",
        ));
    }

    let source_path = Path::new(&page_path);
    if !source_path.exists() {
        return Err(CoreError::new(
            "file_not_found",
            "page markdown file not found",
        ));
    }
    let tombstone_dir = Path::new(input.data_dir).join("revisions").join(&page_id);
    fs::create_dir_all(&tombstone_dir)
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    let tombstone_path = tombstone_dir.join(format!(
        "tombstone-{}.md",
        sanitize_timestamp(input.tombstoned_at)
    ));
    fs::rename(source_path, &tombstone_path)
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;

    tx.execute(
        "UPDATE pages SET status = 'tombstone', updated_at = ?1 WHERE id = ?2",
        params![input.tombstoned_at, page_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(tombstone_path.to_string_lossy().replace('\\', "/"))
}

pub fn recover_page(input: RecoverPageInput<'_>) -> Result<String, CoreError> {
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let (page_id, page_path, status): (String, String, String) = tx
        .query_row(
            "SELECT id, path, status FROM pages WHERE slug = ?1",
            params![input.slug],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .map_err(|err| CoreError::new("page_not_found", err.to_string()))?;
    if status != "tombstone" {
        return Err(CoreError::new(
            "page_not_tombstoned",
            "page is not tombstoned",
        ));
    }
    let tombstone_path = latest_tombstone_path(&page_id, Path::new(&page_path))?;
    let restore_path = Path::new(&page_path);
    if let Some(parent) = restore_path.parent() {
        fs::create_dir_all(parent).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    }
    fs::rename(&tombstone_path, restore_path)
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    tx.execute(
        "UPDATE pages SET status = 'active', updated_at = ?1 WHERE id = ?2",
        params![input.recovered_at, page_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(page_path)
}

fn add_vault_id_if_missing(connection: &Connection, table: &str) -> Result<(), CoreError> {
    if !table_exists(connection, table)? || column_exists(connection, table, "vault_id")? {
        return Ok(());
    }
    let sql = format!(
        "ALTER TABLE {table} ADD COLUMN vault_id TEXT NOT NULL DEFAULT '{DEFAULT_VAULT_ID}'"
    );
    connection
        .execute(&sql, [])
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

fn table_exists(connection: &Connection, table: &str) -> Result<bool, CoreError> {
    let count: i64 = connection
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = ?1",
            params![table],
            |row| row.get(0),
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(count > 0)
}

fn column_exists(connection: &Connection, table: &str, column: &str) -> Result<bool, CoreError> {
    let mut statement = connection
        .prepare(&format!("PRAGMA table_info({table})"))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut rows = statement
        .query([])
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    while let Some(row) = rows
        .next()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?
    {
        let name: String = row
            .get(1)
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        if name == column {
            return Ok(true);
        }
    }
    Ok(false)
}

fn open_connection(sqlite_path: &str) -> Result<Connection, CoreError> {
    let connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(connection)
}

fn latest_tombstone_path(page_id: &str, page_path: &Path) -> Result<PathBuf, CoreError> {
    let revisions_dir = page_path
        .parent()
        .and_then(|pages_dir| pages_dir.parent())
        .ok_or_else(|| CoreError::new("io_error", "page path has no data root"))?
        .join("revisions")
        .join(page_id);
    let mut candidates = Vec::new();
    for entry in
        fs::read_dir(&revisions_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?
    {
        let path = entry
            .map_err(|err| CoreError::new("io_error", err.to_string()))?
            .path();
        let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
            continue;
        };
        if name.starts_with("tombstone-") && name.ends_with(".md") {
            candidates.push(path);
        }
    }
    candidates.sort();
    candidates
        .pop()
        .ok_or_else(|| CoreError::new("tombstone_not_found", "no tombstone markdown found"))
}

fn sanitize_timestamp(timestamp: &str) -> String {
    timestamp
        .chars()
        .map(|value| {
            if value.is_ascii_alphanumeric() {
                value
            } else {
                '-'
            }
        })
        .collect()
}
