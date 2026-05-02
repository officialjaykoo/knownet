use std::fs;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::error::CoreError;

pub fn parse_file(path: &str) -> Result<Value, CoreError> {
    let content = fs::read_to_string(path)
        .map_err(|err| CoreError::new("file_not_found", err.to_string()))?;
    let normalized;
    let parse_content = if content.contains("\r\n") {
        normalized = content.replace("\r\n", "\n");
        normalized.as_str()
    } else {
        content.as_str()
    };
    let (frontmatter, body) = split_frontmatter(parse_content)?;
    let links = extract_pagelinks(body);
    let citations = extract_citations(body);
    let sections = extract_sections(body);
    Ok(json!({
        "path": path,
        "frontmatter": frontmatter,
        "links": links,
        "citations": citations,
        "sections": sections
    }))
}

fn split_frontmatter(content: &str) -> Result<(Value, &str), CoreError> {
    if !content.starts_with("---\n") {
        return Err(CoreError::new("parse_error", "missing frontmatter"));
    }
    let rest = &content[4..];
    let Some(end) = rest.find("\n---\n") else {
        return Err(CoreError::new("parse_error", "unterminated frontmatter"));
    };
    let raw = &rest[..end];
    let body = &rest[end + 5..];
    let mut map = serde_json::Map::new();
    let lines: Vec<&str> = raw.lines().collect();
    let mut index = 0;
    while index < lines.len() {
        let line = lines[index];
        if let Some((key, value)) = line.split_once(':') {
            let key = key.trim().to_string();
            let value = value.trim().trim_matches('"');
            if value.is_empty() {
                let mut items = Vec::new();
                let mut next = index + 1;
                while next < lines.len() {
                    let item_line = lines[next];
                    let trimmed = item_line.trim_start();
                    if !item_line.starts_with(' ') || !trimmed.starts_with("- ") {
                        break;
                    }
                    items.push(json!(trimmed[2..].trim().trim_matches('"')));
                    next += 1;
                }
                if items.is_empty() {
                    map.insert(key, json!(""));
                } else {
                    map.insert(key, Value::Array(items));
                    index = next;
                    continue;
                }
            } else {
                map.insert(key, json!(value));
            }
        }
        index += 1;
    }
    Ok((Value::Object(map), body))
}

fn extract_pagelinks(body: &str) -> Vec<Value> {
    let mut links = Vec::new();
    let mut offset = 0;
    while let Some(start) = body[offset..].find("[[") {
        let absolute_start = offset + start + 2;
        if let Some(end) = body[absolute_start..].find("]]") {
            let raw = &body[absolute_start..absolute_start + end];
            let (target, display) = raw
                .split_once('|')
                .map_or((raw, None), |(left, right)| (left, Some(right)));
            links.push(json!({
                "raw": raw,
                "target": target.trim(),
                "display": display.map(str::trim),
                "status": "unresolved"
            }));
            offset = absolute_start + end + 2;
        } else {
            break;
        }
    }
    links
}

fn extract_citations(body: &str) -> Vec<Value> {
    let mut citations = Vec::new();
    let mut offset = 0;
    while let Some(start) = body[offset..].find("[^") {
        let absolute_marker = offset + start;
        let line_start = body[..absolute_marker]
            .rfind('\n')
            .map_or(0, |index| index + 1);
        if body[line_start..absolute_marker].trim().is_empty()
            && body[absolute_marker..].contains("]:")
            && body[absolute_marker..]
                .find("]:")
                .is_some_and(|definition_end| definition_end < 128)
        {
            offset = absolute_marker + 2;
            continue;
        }
        let absolute_start = offset + start + 2;
        if let Some(end) = body[absolute_start..].find(']') {
            let key = &body[absolute_start..absolute_start + end];
            if !key.trim().is_empty() {
                let claim_text = claim_paragraph(body, absolute_marker);
                let normalized_claim_text = normalize_claim_text(&claim_text);
                citations.push(json!({
                    "key": key.trim(),
                    "claim_text": claim_text,
                    "normalized_claim_text": normalized_claim_text,
                    "claim_hash": claim_hash(&normalized_claim_text)
                }));
            }
            offset = absolute_start + end + 1;
        } else {
            break;
        }
    }
    citations
}

fn claim_paragraph(body: &str, marker: usize) -> String {
    let before = &body[..marker];
    let after = &body[marker..];
    let start = before
        .rfind("\n\n")
        .map(|index| index + 2)
        .unwrap_or(0);
    let end = after
        .find("\n\n")
        .map(|index| marker + index)
        .unwrap_or(body.len());
    body[start..end].trim().to_string()
}

fn normalize_claim_text(value: &str) -> String {
    let mut cleaned = String::new();
    for ch in value.chars() {
        match ch {
            '*' | '_' | '#' | '[' | ']' | '(' | ')' | '`' | '>' | '!' => cleaned.push(' '),
            _ => cleaned.push(ch.to_ascii_lowercase()),
        }
    }
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn claim_hash(value: &str) -> String {
    let digest = Sha256::digest(value.as_bytes());
    format!("{digest:x}").chars().take(24).collect()
}

fn extract_sections(body: &str) -> Vec<Value> {
    let mut sections = Vec::new();
    for (position, line) in body.lines().enumerate() {
        let trimmed = line.trim_start();
        let level = trimmed.chars().take_while(|ch| *ch == '#').count();
        if level > 0 && level <= 6 && trimmed.chars().nth(level) == Some(' ') {
            let heading = trimmed[level + 1..].trim();
            sections.push(json!({
                "section_key": slugify(heading),
                "heading": heading,
                "level": level,
                "position": position
            }));
        }
    }
    sections
}

fn slugify(value: &str) -> String {
    let mut slug = String::new();
    let mut last_dash = false;
    for ch in value.chars() {
        if ch.is_ascii_alphanumeric() {
            slug.push(ch.to_ascii_lowercase());
            last_dash = false;
        } else if ('\u{AC00}'..='\u{D7A3}').contains(&ch) {
            slug.push(ch);
            last_dash = false;
        } else if !last_dash {
            slug.push('-');
            last_dash = true;
        }
    }
    slug.trim_matches('-').to_string()
}
