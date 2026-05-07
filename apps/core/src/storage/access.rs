use rusqlite::{params, Connection};

use crate::error::CoreError;
use crate::storage::util::validate_id;

const DEFAULT_VAULT_ID: &str = "local-default";

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

fn open_connection(sqlite_path: &str) -> Result<Connection, CoreError> {
    let connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(connection)
}
