use std::collections::HashSet;
use std::fs;

use rusqlite::{params, Connection};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::error::CoreError;
use crate::markdown;
use crate::storage::util::validate_id;

const EXCERPT_MAX_CHARS: usize = 500;
const SUPPORTED_THRESHOLD: f64 = 0.5;
const PARTIAL_THRESHOLD: f64 = 0.2;

pub struct RebuildCitationAuditsInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub page_id: &'a str,
    pub revision_id: Option<&'a str>,
    pub path: &'a str,
    pub rebuilt_at: &'a str,
}

pub struct UpdateCitationAuditStatusInput<'a> {
    pub sqlite_path: &'a str,
    pub audit_id: &'a str,
    pub actor_type: &'a str,
    pub actor_id: &'a str,
    pub status: &'a str,
    pub reason: &'a str,
    pub updated_at: &'a str,
}

pub struct UpdateCitationValidationStatusInput<'a> {
    pub sqlite_path: &'a str,
    pub citation_id: i64,
    pub status: &'a str,
}

pub struct CitationAuditSummary {
    pub created: usize,
    pub skipped: usize,
    pub failed: usize,
    pub warnings: Vec<Value>,
}

pub fn ensure_phase4_schema(sqlite_path: &str) -> Result<(), CoreError> {
    let connection = open_connection(sqlite_path)?;
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS citation_audits (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              page_id TEXT NOT NULL,
              revision_id TEXT,
              citation_key TEXT NOT NULL,
              claim_hash TEXT NOT NULL,
              claim_text TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'unchecked',
              confidence REAL,
              verifier_type TEXT NOT NULL,
              verifier_id TEXT,
              reason TEXT,
              source_hash TEXT,
              evidence_snapshot_id TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(vault_id, page_id, revision_id, citation_key, claim_hash)
            );
            CREATE TABLE IF NOT EXISTS citation_evidence_snapshots (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              citation_key TEXT NOT NULL,
              source_type TEXT NOT NULL,
              source_id TEXT,
              source_path TEXT,
              excerpt TEXT NOT NULL,
              excerpt_hash TEXT NOT NULL,
              source_hash TEXT NOT NULL,
              captured_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS citation_audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              citation_audit_id TEXT NOT NULL,
              actor_type TEXT NOT NULL,
              actor_id TEXT NOT NULL,
              from_status TEXT,
              to_status TEXT NOT NULL,
              reason TEXT,
              meta TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_citation_audits_status
              ON citation_audits(vault_id, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_citation_audits_page
              ON citation_audits(vault_id, page_id, revision_id);
            CREATE INDEX IF NOT EXISTS idx_citation_audit_events_audit
              ON citation_audit_events(citation_audit_id, created_at);",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn rebuild_citation_audits_for_page(
    input: RebuildCitationAuditsInput<'_>,
) -> Result<CitationAuditSummary, CoreError> {
    validate_id(input.page_id)?;
    ensure_phase4_schema(input.sqlite_path)?;
    let parsed = markdown::parse_file(input.path)?;
    let citations = parsed
        .get("citations")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut created = 0;
    let mut skipped = 0;
    let mut failed = 0;
    let mut warnings = Vec::new();

    for citation in citations {
        let citation_key = citation
            .get("key")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        let claim_text = citation
            .get("claim_text")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        let claim_hash = citation
            .get("claim_hash")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if citation_key.is_empty() || claim_text.is_empty() || claim_hash.is_empty() {
            failed += 1;
            continue;
        }
        let audit_id = format!(
            "ca_{}",
            hash24(&format!(
                "{}:{}:{}:{}",
                input.vault_id, input.page_id, citation_key, claim_hash
            ))
        );
        let existing: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM citation_audits WHERE vault_id = ?1 AND page_id = ?2 AND (revision_id IS ?3 OR revision_id = ?3) AND citation_key = ?4 AND claim_hash = ?5",
                params![input.vault_id, input.page_id, input.revision_id, citation_key, claim_hash],
                |row| row.get(0),
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let evidence = resolve_evidence(&tx, citation_key)?;
        let (status, reason, confidence, snapshot_id, source_hash) = match evidence {
            Some(evidence) => {
                let ratio = keyword_overlap(claim_text, &evidence.text);
                let status = if ratio >= SUPPORTED_THRESHOLD {
                    "supported"
                } else if ratio >= PARTIAL_THRESHOLD {
                    "partially_supported"
                } else {
                    "unsupported"
                };
                let reason = format!("keyword overlap {:.2}", ratio);
                let source_hash = sha256_hex(&evidence.text);
                let excerpt = evidence_excerpt(&evidence.text);
                let excerpt_hash = sha256_hex(&excerpt);
                let snapshot_id = format!(
                    "ev_{}",
                    hash24(&format!(
                        "{}:{}:{}",
                        citation_key, source_hash, excerpt_hash
                    ))
                );
                tx.execute(
                    "INSERT OR IGNORE INTO citation_evidence_snapshots
                     (id, vault_id, citation_key, source_type, source_id, source_path, excerpt, excerpt_hash, source_hash, captured_at)
                     VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                    params![
                        snapshot_id,
                        input.vault_id,
                        citation_key,
                        evidence.source_type,
                        evidence.source_id,
                        evidence.source_path,
                        excerpt,
                        excerpt_hash,
                        source_hash,
                        input.rebuilt_at
                    ],
                )
                .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
                (
                    status.to_string(),
                    reason,
                    ratio,
                    Some(snapshot_id),
                    Some(source_hash),
                )
            }
            None => (
                "stale".to_string(),
                "citation source missing".to_string(),
                0.0,
                None,
                None,
            ),
        };

        tx.execute(
            "INSERT INTO citation_audits
             (id, vault_id, page_id, revision_id, citation_key, claim_hash, claim_text, status, confidence, verifier_type, verifier_id, reason, source_hash, evidence_snapshot_id, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, 'deterministic', 'keyword-overlap-v1', ?10, ?11, ?12, ?13, ?13)
             ON CONFLICT(vault_id, page_id, revision_id, citation_key, claim_hash) DO UPDATE SET
               status = excluded.status,
               confidence = excluded.confidence,
               verifier_type = excluded.verifier_type,
               verifier_id = excluded.verifier_id,
               reason = excluded.reason,
               source_hash = excluded.source_hash,
               evidence_snapshot_id = excluded.evidence_snapshot_id,
               updated_at = excluded.updated_at",
            params![
                audit_id,
                input.vault_id,
                input.page_id,
                input.revision_id,
                citation_key,
                claim_hash,
                claim_text,
                status,
                confidence,
                reason,
                source_hash,
                snapshot_id,
                input.rebuilt_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

        if existing == 0 {
            created += 1;
        } else {
            skipped += 1;
        }
        if matches!(
            status.as_str(),
            "unsupported" | "contradicted" | "stale" | "needs_review"
        ) {
            warnings
                .push(json!({"citation_key": citation_key, "status": status, "reason": reason}));
        }
    }
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(CitationAuditSummary {
        created,
        skipped,
        failed,
        warnings,
    })
}

pub fn update_citation_audit_status(
    input: UpdateCitationAuditStatusInput<'_>,
) -> Result<(), CoreError> {
    validate_id(input.audit_id)?;
    ensure_phase4_schema(input.sqlite_path)?;
    let connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .unchecked_transaction()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let (vault_id, from_status): (String, String) = tx
        .query_row(
            "SELECT vault_id, status FROM citation_audits WHERE id = ?1",
            params![input.audit_id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .map_err(|err| CoreError::new("citation_audit_not_found", err.to_string()))?;
    if from_status == input.status {
        return Err(CoreError::new(
            "citation_already_resolved",
            "citation audit already has this status",
        ));
    }
    tx.execute(
        "UPDATE citation_audits SET status = ?1, verifier_type = 'human', verifier_id = ?2, reason = ?3, updated_at = ?4 WHERE id = ?5",
        params![input.status, input.actor_id, input.reason, input.updated_at, input.audit_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.execute(
        "INSERT INTO citation_audit_events (vault_id, citation_audit_id, actor_type, actor_id, from_status, to_status, reason, meta, created_at)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, '{}', ?8)",
        params![
            vault_id,
            input.audit_id,
            input.actor_type,
            input.actor_id,
            from_status,
            input.status,
            input.reason,
            input.updated_at
        ],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    tx.commit()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn update_citation_validation_status(
    input: UpdateCitationValidationStatusInput<'_>,
) -> Result<(), CoreError> {
    if !matches!(
        input.status,
        "unchecked" | "supported" | "partially_supported" | "unsupported"
    ) {
        return Err(CoreError::new(
            "validation_error",
            "invalid citation validation status",
        ));
    }
    let connection = open_connection(input.sqlite_path)?;
    let updated = connection
        .execute(
            "UPDATE citations SET validation_status = ?1 WHERE id = ?2",
            params![input.status, input.citation_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if updated == 0 {
        return Err(CoreError::new("citation_not_found", "Citation not found"));
    }
    Ok(())
}

struct Evidence {
    source_type: String,
    source_id: String,
    source_path: String,
    text: String,
}

fn resolve_evidence(
    connection: &Connection,
    citation_key: &str,
) -> Result<Option<Evidence>, CoreError> {
    let row: Result<(String,), _> = connection.query_row(
        "SELECT path FROM messages WHERE id = ?1",
        params![citation_key],
        |row| Ok((row.get(0)?,)),
    );
    let Ok((path,)) = row else {
        return Ok(None);
    };
    let text = fs::read_to_string(&path)
        .map_err(|_| CoreError::new("citation_source_missing", "citation source missing"))?;
    Ok(Some(Evidence {
        source_type: "message".to_string(),
        source_id: citation_key.to_string(),
        source_path: path,
        text: strip_frontmatter(&text).to_string(),
    }))
}

fn strip_frontmatter(markdown: &str) -> &str {
    if !markdown.starts_with("---\n") {
        return markdown;
    }
    let Some(end) = markdown[4..].find("\n---\n") else {
        return markdown;
    };
    &markdown[end + 9..]
}

fn evidence_excerpt(text: &str) -> String {
    text.chars().take(EXCERPT_MAX_CHARS).collect()
}

fn keyword_overlap(claim_text: &str, source_text: &str) -> f64 {
    let claim = terms(claim_text);
    if claim.is_empty() {
        return 0.0;
    }
    let source = terms(source_text);
    let matched = claim.iter().filter(|term| source.contains(*term)).count();
    matched as f64 / claim.len() as f64
}

fn terms(value: &str) -> HashSet<String> {
    value
        .split(|ch: char| !ch.is_alphanumeric())
        .filter_map(|term| {
            let term = term.trim().to_lowercase();
            if term.chars().count() >= 2 {
                Some(term)
            } else {
                None
            }
        })
        .collect()
}

fn hash24(value: &str) -> String {
    sha256_hex(value).chars().take(24).collect()
}

fn sha256_hex(value: &str) -> String {
    let digest = Sha256::digest(value.as_bytes());
    format!("{digest:x}")
}

fn open_connection(sqlite_path: &str) -> Result<Connection, CoreError> {
    let connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(connection)
}
