use std::fs;

use rusqlite::{params, Connection, TransactionBehavior};

use crate::error::CoreError;
use crate::storage::util::validate_id;

pub struct EmbeddingUpsertInput<'a> {
    pub sqlite_path: &'a str,
    pub embedding_id: &'a str,
    pub owner_type: &'a str,
    pub owner_id: &'a str,
    pub model: &'a str,
    pub vector_path: &'a str,
    pub dims: i64,
    pub updated_at: &'a str,
}

pub fn embedding_upsert(input: EmbeddingUpsertInput<'_>) -> Result<(), CoreError> {
    validate_id(input.embedding_id)?;
    validate_id(input.owner_id)?;
    if input.dims <= 0 {
        return Err(CoreError::new("validation_error", "dims must be positive"));
    }
    let vector = fs::read(input.vector_path)
        .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
    let expected = input.dims as usize * 4;
    if vector.len() != expected {
        return Err(CoreError::new(
            "validation_error",
            "vector byte length does not match dims",
        ));
    }

    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO embeddings (id, owner_type, owner_id, vector, dims, model, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7)
         ON CONFLICT(owner_type, owner_id, model) DO UPDATE SET
           vector = excluded.vector,
           dims = excluded.dims,
           updated_at = excluded.updated_at",
        params![
            input.embedding_id,
            input.owner_type,
            input.owner_id,
            vector,
            input.dims,
            input.model,
            input.updated_at
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let _ = fs::remove_file(input.vector_path);
    Ok(())
}
