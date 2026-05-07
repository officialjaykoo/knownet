use std::fs;
use std::io::Write;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::error::CoreError;

pub fn validate_id(id: &str) -> Result<(), CoreError> {
    let valid = id
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-');
    if id.is_empty() || !valid {
        return Err(CoreError::new("validation_error", "invalid id"));
    }
    Ok(())
}

pub fn validate_slug(slug: &str) -> Result<(), CoreError> {
    let valid = slug
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_');
    if slug.is_empty() || !valid || slug == "." || slug == ".." {
        return Err(CoreError::new("validation_error", "invalid slug"));
    }
    Ok(())
}

pub fn strip_frontmatter(markdown: &str) -> &str {
    if let Some(stripped) = markdown.strip_prefix("---\n") {
        let Some(end) = stripped.find("\n---\n") else {
            return markdown;
        };
        return &markdown[end + 9..];
    }
    if let Some(stripped) = markdown.strip_prefix("---\r\n") {
        let Some(end) = stripped.find("\r\n---\r\n") else {
            return markdown;
        };
        return &markdown[end + 12..];
    }
    markdown
}

pub fn write_synced(path: &Path, content: &str) -> Result<(), CoreError> {
    let mut file =
        fs::File::create(path).map_err(|err| CoreError::new("io_error", err.to_string()))?;
    file.write_all(content.as_bytes())
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    file.sync_all()
        .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    Ok(())
}

pub fn escape_json(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"")
}

pub fn generated_revision_id(prefix: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    format!("rev_{}_{}", prefix, nanos)
}
