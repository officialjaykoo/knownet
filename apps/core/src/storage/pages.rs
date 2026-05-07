use std::fs;
use std::path::{Path, PathBuf};

use rusqlite::{params, Connection, TransactionBehavior};
use serde_json::Value;

use crate::error::CoreError;
use crate::markdown;
use crate::storage::util::{generated_revision_id, validate_id, validate_slug, write_synced};

pub struct CreatePageInput<'a> {
    pub data_dir: &'a str,
    pub sqlite_path: &'a str,
    pub page_id: &'a str,
    pub revision_id: &'a str,
    pub slug: &'a str,
    pub title: &'a str,
    pub created_at: &'a str,
}

pub struct RestoreRevisionInput<'a> {
    pub sqlite_path: &'a str,
    pub slug: &'a str,
    pub revision_id: &'a str,
    pub restored_at: &'a str,
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

pub struct CreatePageResult {
    pub slug: String,
    pub title: String,
    pub path: String,
    pub revision_id: String,
    pub revision_path: String,
}

pub fn create_page(input: CreatePageInput<'_>) -> Result<CreatePageResult, CoreError> {
    validate_id(input.page_id)?;
    validate_id(input.revision_id)?;
    validate_slug(input.slug)?;

    let data_dir = Path::new(input.data_dir);
    let pages_dir = data_dir.join("pages");
    let revision_dir = data_dir.join("revisions").join(input.page_id);
    fs::create_dir_all(&pages_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    fs::create_dir_all(&revision_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;

    let page_path = pages_dir.join(format!("{}.md", input.slug));
    if page_path.exists() {
        return Err(CoreError::new("page_exists", "Page already exists"));
    }
    let revision_path = revision_dir.join(format!("{}.md", input.revision_id));
    let page_temp_path = pages_dir.join(format!("{}.md.tmp", input.slug));
    let revision_temp_path = revision_dir.join(format!("{}.md.tmp", input.revision_id));
    let markdown = format!(
        "---\nschema_version: 1\nid: {}\ntitle: {}\nslug: {}\nstatus: active\ncreated_at: {}\nupdated_at: {}\n---\n\n# {}\n",
        input.page_id, input.title, input.slug, input.created_at, input.created_at, input.title
    );
    write_synced(&page_temp_path, &markdown)?;
    write_synced(&revision_temp_path, &markdown)?;

    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let page_path_string = page_path.to_string_lossy().replace('\\', "/");
    let revision_path_string = revision_path.to_string_lossy().replace('\\', "/");
    tx.execute(
        "INSERT INTO pages (id, title, slug, path, current_revision_id, status, created_at, updated_at)
         VALUES (?1, ?2, ?3, ?4, ?5, 'active', ?6, ?6)",
        params![
            input.page_id,
            input.title,
            input.slug,
            page_path_string,
            input.revision_id,
            input.created_at
        ],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&page_temp_path);
        let _ = fs::remove_file(&revision_temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;
    tx.execute(
        "INSERT INTO revisions (id, page_id, path, author_type, change_note, created_at)
         VALUES (?1, ?2, ?3, 'human', 'Created from unresolved link', ?4)",
        params![
            input.revision_id,
            input.page_id,
            revision_path_string,
            input.created_at
        ],
    )
    .map_err(|err| {
        let _ = fs::remove_file(&page_temp_path);
        let _ = fs::remove_file(&revision_temp_path);
        CoreError::new("sqlite_error", err.to_string())
    })?;
    fs::rename(&page_temp_path, &page_path).map_err(|err| {
        let _ = fs::remove_file(&page_temp_path);
        let _ = fs::remove_file(&revision_temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    fs::rename(&revision_temp_path, &revision_path).map_err(|err| {
        let _ = fs::remove_file(&revision_temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    Ok(CreatePageResult {
        slug: input.slug.to_string(),
        title: input.title.to_string(),
        path: page_path_string,
        revision_id: input.revision_id.to_string(),
        revision_path: revision_path_string,
    })
}

pub fn restore_revision(input: RestoreRevisionInput<'_>) -> Result<String, CoreError> {
    validate_slug(input.slug)?;
    validate_id(input.revision_id)?;

    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    let (page_id, page_path, current_revision_id): (String, String, Option<String>) = connection
        .query_row(
            "SELECT id, path, current_revision_id FROM pages WHERE slug = ?1",
            params![input.slug],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .map_err(|err| CoreError::new("page_not_found", err.to_string()))?;
    let revision_path: String = connection
        .query_row(
            "SELECT path FROM revisions WHERE id = ?1 AND page_id = ?2",
            params![input.revision_id, page_id],
            |row| row.get(0),
        )
        .map_err(|err| CoreError::new("revision_not_found", err.to_string()))?;

    let revision_markdown = fs::read_to_string(&revision_path)
        .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
    let page_path_buf = Path::new(&page_path);
    let temp_path = page_path_buf.with_extension("md.tmp");
    let revision_dir = Path::new(&revision_path)
        .parent()
        .ok_or_else(|| CoreError::new("io_error", "revision path has no parent"))?;
    fs::create_dir_all(revision_dir).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    let backup_revision_id = generated_revision_id("pre_restore");
    let backup_revision_path = revision_dir.join(format!("{}.md", backup_revision_id));
    let backup_revision_temp_path = revision_dir.join(format!("{}.md.tmp", backup_revision_id));
    let current_markdown = fs::read_to_string(page_path_buf)
        .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
    write_synced(&temp_path, &revision_markdown)?;
    write_synced(&backup_revision_temp_path, &current_markdown)?;

    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let backup_revision_path_string = backup_revision_path.to_string_lossy().replace('\\', "/");
    tx.execute(
        "INSERT INTO revisions (id, page_id, path, author_type, change_note, created_at)
         VALUES (?1, ?2, ?3, 'system', ?4, ?5)",
        params![
            backup_revision_id,
            page_id,
            backup_revision_path_string,
            format!(
                "Pre-restore backup before restoring {} from {}",
                input.revision_id,
                current_revision_id.as_deref().unwrap_or("unknown")
            ),
            input.restored_at
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "UPDATE pages SET current_revision_id = ?1, updated_at = ?2 WHERE id = ?3",
        params![input.revision_id, input.restored_at, page_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    fs::rename(&temp_path, page_path_buf).map_err(|err| {
        let _ = fs::remove_file(&temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    fs::rename(&backup_revision_temp_path, &backup_revision_path).map_err(|err| {
        let _ = fs::remove_file(&backup_revision_temp_path);
        CoreError::new("io_error", err.to_string())
    })?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    Ok(page_path)
}

pub fn tombstone_page(input: TombstonePageInput<'_>) -> Result<String, CoreError> {
    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
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
    let mut connection = Connection::open(input.sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
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

pub fn index_page_file(
    sqlite_path: &str,
    path: &str,
    page_id: &str,
    revision_id: Option<&str>,
    indexed_at: &str,
) -> Result<(), CoreError> {
    validate_id(page_id)?;
    let parsed = markdown::parse_file(path)?;
    let mut connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    tx.execute(
        "DELETE FROM links WHERE page_id = ?1 AND (revision_id IS ?2 OR revision_id = ?2)",
        params![page_id, revision_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "DELETE FROM citations WHERE page_id = ?1 AND (revision_id IS ?2 OR revision_id = ?2)",
        params![page_id, revision_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "DELETE FROM sections WHERE page_id = ?1 AND (revision_id IS ?2 OR revision_id = ?2)",
        params![page_id, revision_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    if let Some(links) = parsed.get("links").and_then(Value::as_array) {
        for link in links {
            tx.execute(
                "INSERT INTO links (page_id, revision_id, source_path, raw, target, display, status, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
                params![
                    page_id,
                    revision_id,
                    path,
                    link.get("raw").and_then(Value::as_str).unwrap_or(""),
                    link.get("target").and_then(Value::as_str).unwrap_or(""),
                    link.get("display").and_then(Value::as_str),
                    link.get("status").and_then(Value::as_str).unwrap_or("unresolved"),
                    indexed_at
                ],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        }
    }

    if let Some(citations) = parsed.get("citations").and_then(Value::as_array) {
        for citation in citations {
            tx.execute(
                "INSERT OR IGNORE INTO citations (page_id, revision_id, citation_key, display_title, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    page_id,
                    revision_id,
                    citation.get("key").and_then(Value::as_str).unwrap_or(""),
                    citation.get("display_title").and_then(Value::as_str),
                    indexed_at
                ],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        }
    }

    if let Some(sections) = parsed.get("sections").and_then(Value::as_array) {
        for section in sections {
            tx.execute(
                "INSERT INTO sections (page_id, revision_id, section_key, heading, level, position, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    page_id,
                    revision_id,
                    section.get("section_key").and_then(Value::as_str).unwrap_or(""),
                    section.get("heading").and_then(Value::as_str).unwrap_or(""),
                    section.get("level").and_then(Value::as_i64).unwrap_or(0),
                    section.get("position").and_then(Value::as_i64).unwrap_or(0),
                    indexed_at
                ],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        }
    }

    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
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
