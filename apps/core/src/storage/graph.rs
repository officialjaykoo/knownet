use std::collections::{HashMap, HashSet};

use rusqlite::{params, Connection, OptionalExtension, Transaction, TransactionBehavior};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::error::CoreError;
use crate::markdown;
use crate::storage::util::validate_id;

pub struct RebuildGraphInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub page_id: Option<&'a str>,
    pub rebuilt_at: &'a str,
}

pub struct UpsertGraphLayoutInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub layout_key: &'a str,
    pub node_id: &'a str,
    pub x: f64,
    pub y: f64,
    pub pinned: bool,
    pub updated_at: &'a str,
}

pub struct ClearGraphLayoutInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub layout_key: Option<&'a str>,
}

pub struct SetGraphNodePinInput<'a> {
    pub sqlite_path: &'a str,
    pub vault_id: &'a str,
    pub node_id: &'a str,
    pub pinned: bool,
    pub updated_at: &'a str,
}

pub struct GraphRebuildSummary {
    pub created: usize,
    pub skipped: usize,
    pub removed: usize,
    pub failed: usize,
    pub report: Vec<Value>,
}

#[derive(Clone)]
struct PageRow {
    id: String,
    vault_id: String,
    title: String,
    slug: String,
    path: String,
    current_revision_id: Option<String>,
}

pub fn ensure_graph_schema(sqlite_path: &str) -> Result<(), CoreError> {
    let connection = open_connection(sqlite_path)?;
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS graph_nodes (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              node_type TEXT NOT NULL,
              label TEXT NOT NULL,
              target_type TEXT,
              target_id TEXT,
              status TEXT,
              weight REAL NOT NULL DEFAULT 1.0,
              meta TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS graph_edges (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              edge_type TEXT NOT NULL,
              from_node_id TEXT NOT NULL,
              to_node_id TEXT NOT NULL,
              weight REAL NOT NULL DEFAULT 1.0,
              status TEXT,
              meta TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(vault_id, edge_type, from_node_id, to_node_id)
            );
            CREATE TABLE IF NOT EXISTS graph_layout_cache (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              layout_key TEXT NOT NULL,
              node_id TEXT NOT NULL,
              x REAL NOT NULL,
              y REAL NOT NULL,
              pinned INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL,
              UNIQUE(vault_id, layout_key, node_id)
            );
            CREATE TABLE IF NOT EXISTS graph_node_pins (
              id TEXT PRIMARY KEY,
              vault_id TEXT NOT NULL DEFAULT 'local-default',
              node_id TEXT NOT NULL,
              pinned INTEGER NOT NULL DEFAULT 1,
              updated_at TEXT NOT NULL,
              UNIQUE(vault_id, node_id)
            );
            CREATE INDEX IF NOT EXISTS idx_graph_nodes_vault_type
              ON graph_nodes(vault_id, node_type);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_from
              ON graph_edges(vault_id, from_node_id);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_to
              ON graph_edges(vault_id, to_node_id);",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn rebuild_graph_for_page(
    input: RebuildGraphInput<'_>,
) -> Result<GraphRebuildSummary, CoreError> {
    let Some(page_id) = input.page_id else {
        return Err(CoreError::new("validation_error", "page_id is required"));
    };
    validate_id(page_id)?;
    ensure_graph_schema(input.sqlite_path)?;
    let mut connection = open_connection(input.sqlite_path)?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let removed = delete_page_graph(&tx, input.vault_id, page_id)?;
    let mut summary = GraphRebuildSummary {
        created: 0,
        skipped: 0,
        removed,
        failed: 0,
        report: Vec::new(),
    };
    if let Some(page) = fetch_page_tx(&tx, input.vault_id, page_id)? {
        build_page_graph(&tx, &page, input.rebuilt_at, &mut summary)?;
    } else {
        summary.skipped += 1;
        summary
            .report
            .push(json!({"page_id": page_id, "code": "page_inactive_or_missing"}));
    }
    summary.removed += cleanup_orphan_derived_nodes(&tx, input.vault_id)?;
    update_graph_signals(&tx, input.vault_id, input.rebuilt_at)?;
    tx.commit()
        .map_err(|err| CoreError::new("graph_rebuild_failed", err.to_string()))?;
    Ok(summary)
}

pub fn rebuild_graph_for_vault(
    input: RebuildGraphInput<'_>,
) -> Result<GraphRebuildSummary, CoreError> {
    ensure_graph_schema(input.sqlite_path)?;
    let mut connection = open_connection(input.sqlite_path)?;
    let pages = fetch_vault_pages(&connection, input.vault_id)?;
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let removed_edges = tx
        .execute(
            "DELETE FROM graph_edges WHERE vault_id = ?1",
            params![input.vault_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let removed_nodes = tx
        .execute(
            "DELETE FROM graph_nodes WHERE vault_id = ?1",
            params![input.vault_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut summary = GraphRebuildSummary {
        created: 0,
        skipped: 0,
        removed: removed_edges + removed_nodes,
        failed: 0,
        report: Vec::new(),
    };
    for page in pages {
        if let Err(error) = build_page_graph(&tx, &page, input.rebuilt_at, &mut summary) {
            summary.failed += 1;
            summary.report.push(json!({
                "page_id": page.id,
                "code": error.code,
                "message": error.message
            }));
        }
    }
    build_collaboration_graph(&tx, input.vault_id, input.rebuilt_at, &mut summary)?;
    update_graph_signals(&tx, input.vault_id, input.rebuilt_at)?;
    tx.commit()
        .map_err(|err| CoreError::new("graph_rebuild_failed", err.to_string()))?;
    Ok(summary)
}

pub fn upsert_graph_layout_node(input: UpsertGraphLayoutInput<'_>) -> Result<(), CoreError> {
    ensure_graph_schema(input.sqlite_path)?;
    let connection = open_connection(input.sqlite_path)?;
    let id = format!(
        "layout_{}",
        hash24(&format!(
            "{}:{}:{}",
            input.vault_id, input.layout_key, input.node_id
        ))
    );
    connection
        .execute(
            "INSERT INTO graph_layout_cache (id, vault_id, layout_key, node_id, x, y, pinned, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
             ON CONFLICT(vault_id, layout_key, node_id) DO UPDATE SET
               x = excluded.x,
               y = excluded.y,
               pinned = excluded.pinned,
               updated_at = excluded.updated_at",
            params![
                id,
                input.vault_id,
                input.layout_key,
                input.node_id,
                input.x,
                input.y,
                if input.pinned { 1 } else { 0 },
                input.updated_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

pub fn clear_graph_layout_cache(input: ClearGraphLayoutInput<'_>) -> Result<usize, CoreError> {
    ensure_graph_schema(input.sqlite_path)?;
    let connection = open_connection(input.sqlite_path)?;
    let removed = if let Some(layout_key) = input.layout_key {
        connection
            .execute(
                "DELETE FROM graph_layout_cache WHERE vault_id = ?1 AND layout_key = ?2",
                params![input.vault_id, layout_key],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?
    } else {
        connection
            .execute(
                "DELETE FROM graph_layout_cache WHERE vault_id = ?1",
                params![input.vault_id],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?
    };
    Ok(removed)
}

pub fn set_graph_node_pin(input: SetGraphNodePinInput<'_>) -> Result<(), CoreError> {
    ensure_graph_schema(input.sqlite_path)?;
    let connection = open_connection(input.sqlite_path)?;
    let exists: Option<String> = connection
        .query_row(
            "SELECT id FROM graph_nodes WHERE vault_id = ?1 AND id = ?2",
            params![input.vault_id, input.node_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if exists.is_none() {
        return Err(CoreError::new(
            "graph_node_not_found",
            "Graph node not found",
        ));
    }
    let id = format!(
        "pin_{}",
        hash24(&format!("{}:{}", input.vault_id, input.node_id))
    );
    connection
        .execute(
            "INSERT INTO graph_node_pins (id, vault_id, node_id, pinned, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5)
             ON CONFLICT(vault_id, node_id) DO UPDATE SET
               pinned = excluded.pinned,
               updated_at = excluded.updated_at",
            params![
                id,
                input.vault_id,
                input.node_id,
                if input.pinned { 1 } else { 0 },
                input.updated_at
            ],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(())
}

fn build_page_graph(
    tx: &Transaction<'_>,
    page: &PageRow,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let page_node_id = format!("page:{}", page.id);
    upsert_node(
        tx,
        &page_node_id,
        &page.vault_id,
        "page",
        &page.title,
        Some("page"),
        Some(&page.id),
        Some("active"),
        1.0,
        json!({"slug": page.slug, "revision_id": page.current_revision_id}),
        now,
        summary,
    )?;
    let parsed = markdown::parse_file(&page.path)?;
    build_tag_nodes(tx, page, &page_node_id, &parsed, now, summary)?;
    build_section_nodes(tx, page, &page_node_id, now, summary)?;
    build_link_edges(tx, page, &page_node_id, now, summary)?;
    build_citation_edges(tx, page, &page_node_id, now, summary)?;
    build_semantic_edges(tx, page, summary)?;
    Ok(())
}

fn build_tag_nodes(
    tx: &Transaction<'_>,
    page: &PageRow,
    page_node_id: &str,
    parsed: &Value,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let frontmatter = parsed.get("frontmatter").unwrap_or(&Value::Null);
    let mut tags = Vec::new();
    if let Some(items) = frontmatter.get("tags").and_then(Value::as_array) {
        for item in items {
            if let Some(tag) = item.as_str() {
                tags.push(tag.to_string());
            }
        }
    }
    if let Some(tag) = frontmatter.get("tag").and_then(Value::as_str) {
        tags.push(tag.to_string());
    }
    for tag in tags {
        let normalized = normalize_tag(&tag);
        if normalized.is_empty() {
            continue;
        }
        let node_id = format!("tag:{}", normalized);
        upsert_node(
            tx,
            &node_id,
            &page.vault_id,
            "tag",
            &tag,
            Some("tag"),
            Some(&normalized),
            None,
            1.0,
            json!({}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            &page.vault_id,
            "tagged",
            page_node_id,
            &node_id,
            1.0,
            None,
            json!({}),
            now,
            summary,
        )?;
    }
    Ok(())
}

fn build_section_nodes(
    tx: &Transaction<'_>,
    page: &PageRow,
    page_node_id: &str,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let mut statement = tx
        .prepare(
            "SELECT section_key, heading, level, position FROM sections
             WHERE page_id = ?1 AND (revision_id IS ?2 OR revision_id = ?2)
             ORDER BY position",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let sections = statement
        .query_map(params![page.id, page.current_revision_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, i64>(2)?,
                row.get::<_, i64>(3)?,
            ))
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    for section in sections {
        let (section_key, heading, level, position) =
            section.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let node_id = format!(
            "section:{}:{}:{}",
            page.id,
            page.current_revision_id.as_deref().unwrap_or("current"),
            section_key
        );
        upsert_node(
            tx,
            &node_id,
            &page.vault_id,
            "section",
            &heading,
            Some("section"),
            Some(&section_key),
            None,
            1.0,
            json!({"page_id": page.id, "level": level, "position": position}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            &page.vault_id,
            "contains_section",
            page_node_id,
            &node_id,
            1.0,
            None,
            json!({"position": position}),
            now,
            summary,
        )?;
    }
    Ok(())
}

fn build_link_edges(
    tx: &Transaction<'_>,
    page: &PageRow,
    page_node_id: &str,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let page_lookup = page_lookup(tx, &page.vault_id)?;
    let mut statement = tx
        .prepare(
            "SELECT target, display FROM links
             WHERE page_id = ?1 AND (revision_id IS ?2 OR revision_id = ?2)
             ORDER BY target",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let links = statement
        .query_map(params![page.id, page.current_revision_id], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?))
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    for link in links {
        let (target, display) =
            link.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let normalized = normalize_link_target(&target);
        if let Some(target_page) = page_lookup.get(&normalized) {
            let target_node_id = format!("page:{}", target_page.id);
            upsert_edge(
                tx,
                &page.vault_id,
                "page_link",
                page_node_id,
                &target_node_id,
                1.0,
                Some("resolved"),
                json!({"target": target, "display": display}),
                now,
                summary,
            )?;
        } else {
            let unresolved_id = format!("unresolved:{}", normalized);
            upsert_node(
                tx,
                &unresolved_id,
                &page.vault_id,
                "unresolved",
                &target,
                Some("pagelink"),
                Some(&normalized),
                Some("unresolved"),
                1.0,
                json!({"target": target}),
                now,
                summary,
            )?;
            upsert_edge(
                tx,
                &page.vault_id,
                "page_link",
                page_node_id,
                &unresolved_id,
                1.0,
                Some("unresolved"),
                json!({"target": target, "display": display}),
                now,
                summary,
            )?;
        }
    }
    Ok(())
}

fn build_citation_edges(
    tx: &Transaction<'_>,
    page: &PageRow,
    page_node_id: &str,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let mut statement = tx
        .prepare(
            "SELECT citation_key FROM citations
             WHERE page_id = ?1 AND (revision_id IS ?2 OR revision_id = ?2)
             ORDER BY citation_key",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let citation_keys = statement
        .query_map(params![page.id, page.current_revision_id], |row| {
            row.get::<_, String>(0)
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut seen = HashSet::new();
    for key in citation_keys {
        let citation_key = key.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        if !seen.insert(citation_key.clone()) {
            continue;
        }
        let source_node_id = format!("source:message:{}", citation_key);
        let source_status = source_status(tx, &citation_key)?;
        upsert_node(
            tx,
            &source_node_id,
            &page.vault_id,
            "source",
            &citation_key,
            Some("message"),
            Some(&citation_key),
            Some(source_status),
            1.0,
            json!({"source_type": "message"}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            &page.vault_id,
            "cites",
            page_node_id,
            &source_node_id,
            1.0,
            Some(source_status),
            json!({"citation_key": citation_key}),
            now,
            summary,
        )?;
    }

    let mut audit_statement = tx
        .prepare(
            "SELECT id, citation_key, status, reason FROM citation_audits
             WHERE vault_id = ?1 AND page_id = ?2 AND (revision_id IS ?3 OR revision_id = ?3)
             ORDER BY updated_at DESC",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let audits = audit_statement
        .query_map(
            params![page.vault_id, page.id, page.current_revision_id],
            |row| {
                Ok((
                    row.get::<_, String>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, Option<String>>(3)?,
                ))
            },
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    for audit in audits {
        let (audit_id, citation_key, status, reason) =
            audit.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let audit_node_id = format!("citation_audit:{}", audit_id);
        let source_node_id = format!("source:message:{}", citation_key);
        upsert_node(
            tx,
            &audit_node_id,
            &page.vault_id,
            "citation_audit",
            &citation_key,
            Some("citation_audit"),
            Some(&audit_id),
            Some(&status),
            audit_weight(&status),
            json!({"page_id": page.id, "citation_key": citation_key, "reason": reason}),
            now,
            summary,
        )?;
        upsert_node(
            tx,
            &source_node_id,
            &page.vault_id,
            "source",
            &citation_key,
            Some("message"),
            Some(&citation_key),
            Some(source_status(tx, &citation_key)?),
            1.0,
            json!({"source_type": "message"}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            &page.vault_id,
            "has_audit",
            page_node_id,
            &audit_node_id,
            audit_weight(&status),
            Some(&status),
            json!({"citation_key": citation_key}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            &page.vault_id,
            "audit_source",
            &audit_node_id,
            &source_node_id,
            1.0,
            Some(&status),
            json!({"citation_key": citation_key}),
            now,
            summary,
        )?;
    }
    Ok(())
}

fn build_semantic_edges(
    tx: &Transaction<'_>,
    page: &PageRow,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let embedding_exists: i64 = tx
        .query_row(
            "SELECT COUNT(*) FROM embeddings WHERE owner_type = 'page' AND owner_id = ?1",
            params![page.id],
            |row| row.get(0),
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    if embedding_exists == 0 {
        summary.skipped += 1;
        summary
            .report
            .push(json!({"page_id": page.id, "code": "embedding_missing"}));
    }
    Ok(())
}

fn build_collaboration_graph(
    tx: &Transaction<'_>,
    vault_id: &str,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let mut review_statement = tx
        .prepare(
            "SELECT id, title, source_agent, source_model, status, page_id, created_at
             FROM collaboration_reviews
             WHERE vault_id = ?1
             ORDER BY updated_at DESC",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let reviews = review_statement
        .query_map(params![vault_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, Option<String>>(5)?,
                row.get::<_, String>(6)?,
            ))
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    for review in reviews {
        let (review_id, title, source_agent, source_model, status, page_id, created_at) =
            review.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let review_node_id = format!("review:{}", review_id);
        upsert_node(
            tx,
            &review_node_id,
            vault_id,
            "review",
            &title,
            Some("collaboration_review"),
            Some(&review_id),
            Some(&status),
            2.0,
            json!({
                "source_agent": source_agent,
                "source_model": source_model,
                "created_at": created_at,
                "page_id": page_id
            }),
            now,
            summary,
        )?;
        if let Some(page_id) = page_id.as_deref() {
            upsert_edge(
                tx,
                vault_id,
                "review_affects_page",
                &review_node_id,
                &format!("page:{}", page_id),
                1.0,
                Some(&status),
                json!({}),
                now,
                summary,
            )?;
        }
    }

    let mut finding_statement = tx
        .prepare(
            "SELECT f.id, f.review_id, f.severity, f.area, f.title, f.status, r.page_id
             FROM collaboration_findings f
             JOIN collaboration_reviews r ON r.id = f.review_id
             WHERE r.vault_id = ?1
             ORDER BY f.updated_at DESC",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let findings = finding_statement
        .query_map(params![vault_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, String>(3)?,
                row.get::<_, String>(4)?,
                row.get::<_, String>(5)?,
                row.get::<_, Option<String>>(6)?,
            ))
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    for finding in findings {
        let (finding_id, review_id, severity, area, title, status, page_id) =
            finding.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let finding_node_id = format!("finding:{}", finding_id);
        let review_node_id = format!("review:{}", review_id);
        upsert_node(
            tx,
            &finding_node_id,
            vault_id,
            "finding",
            &title,
            Some("collaboration_finding"),
            Some(&finding_id),
            Some(&status),
            finding_weight(&severity, &status),
            json!({"review_id": review_id, "severity": severity, "area": area, "page_id": page_id}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            vault_id,
            "review_contains_finding",
            &review_node_id,
            &finding_node_id,
            1.0,
            Some(&status),
            json!({"severity": severity}),
            now,
            summary,
        )?;
        if let Some(page_id) = page_id.as_deref() {
            upsert_edge(
                tx,
                vault_id,
                "finding_affects_page",
                &finding_node_id,
                &format!("page:{}", page_id),
                1.0,
                Some(&status),
                json!({"area": area}),
                now,
                summary,
            )?;
        }
    }

    let mut implementation_statement = tx
        .prepare(
            "SELECT ir.id, ir.finding_id, ir.commit_sha
             FROM implementation_records ir
             JOIN collaboration_findings f ON f.id = ir.finding_id
             JOIN collaboration_reviews r ON r.id = f.review_id
             WHERE r.vault_id = ?1
             ORDER BY ir.created_at DESC",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let records = implementation_statement
        .query_map(params![vault_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, Option<String>>(2)?,
            ))
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;

    for record in records {
        let (record_id, finding_id, commit_sha) =
            record.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let label = commit_sha.as_deref().unwrap_or(&record_id);
        let commit_node_id = format!("commit:{}", label);
        upsert_node(
            tx,
            &commit_node_id,
            vault_id,
            "commit",
            label,
            Some("implementation_record"),
            Some(&record_id),
            Some("implemented"),
            1.0,
            json!({"finding_id": finding_id, "commit_sha": commit_sha}),
            now,
            summary,
        )?;
        upsert_edge(
            tx,
            vault_id,
            "finding_implemented_by_commit",
            &format!("finding:{}", finding_id),
            &commit_node_id,
            1.0,
            Some("implemented"),
            json!({"record_id": record_id}),
            now,
            summary,
        )?;
    }
    Ok(())
}

fn delete_page_graph(
    tx: &Transaction<'_>,
    vault_id: &str,
    page_id: &str,
) -> Result<usize, CoreError> {
    let page_prefix = format!("section:{}:", page_id);
    let audit_prefix = "citation_audit:%".to_string();
    let mut owned_nodes = vec![format!("page:{}", page_id)];
    let mut statement = tx
        .prepare(
            "SELECT id FROM graph_nodes
             WHERE vault_id = ?1 AND (id LIKE ?2 OR (id LIKE ?3 AND json_extract(meta, '$.page_id') = ?4))",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let rows = statement
        .query_map(
            params![vault_id, format!("{}%", page_prefix), audit_prefix, page_id],
            |row| row.get::<_, String>(0),
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    for row in rows {
        owned_nodes.push(row.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?);
    }
    let mut removed = 0;
    for node_id in &owned_nodes {
        removed += tx
            .execute(
                "DELETE FROM graph_edges WHERE vault_id = ?1 AND (from_node_id = ?2 OR to_node_id = ?2)",
                params![vault_id, node_id],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    }
    for node_id in &owned_nodes {
        removed += tx
            .execute(
                "DELETE FROM graph_nodes WHERE vault_id = ?1 AND id = ?2",
                params![vault_id, node_id],
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    }
    Ok(removed)
}

fn cleanup_orphan_derived_nodes(tx: &Transaction<'_>, vault_id: &str) -> Result<usize, CoreError> {
    tx.execute(
        "DELETE FROM graph_nodes
         WHERE vault_id = ?1
           AND node_type IN ('source', 'tag', 'unresolved')
           AND NOT EXISTS (
             SELECT 1 FROM graph_edges
             WHERE graph_edges.vault_id = graph_nodes.vault_id
               AND (graph_edges.from_node_id = graph_nodes.id OR graph_edges.to_node_id = graph_nodes.id)
           )",
        params![vault_id],
    )
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))
}

fn update_graph_signals(tx: &Transaction<'_>, vault_id: &str, now: &str) -> Result<(), CoreError> {
    let mut statement = tx
        .prepare(
            "SELECT gn.id, gn.target_id, gn.label, p.slug
             FROM graph_nodes gn
             LEFT JOIN pages p ON p.id = gn.target_id AND p.vault_id = gn.vault_id
             WHERE gn.vault_id = ?1 AND gn.node_type = 'page'",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let pages = statement
        .query_map(params![vault_id], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, String>(2)?,
                row.get::<_, Option<String>>(3)?,
            ))
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut metrics = Vec::new();
    for row in pages {
        let (node_id, target_id, title, slug) =
            row.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let degree: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM graph_edges
                 WHERE vault_id = ?1 AND edge_type = 'page_link' AND (from_node_id = ?2 OR to_node_id = ?2)",
                params![vault_id, node_id],
                |row| row.get(0),
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let weak_count: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM graph_edges
                 WHERE vault_id = ?1 AND edge_type = 'has_audit' AND from_node_id = ?2
                   AND status IN ('unsupported', 'stale', 'needs_review', 'contradicted')",
                params![vault_id, node_id],
                |row| row.get(0),
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let audit_count: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM graph_edges
                 WHERE vault_id = ?1 AND edge_type = 'has_audit' AND from_node_id = ?2",
                params![vault_id, node_id],
                |row| row.get(0),
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let incoming_links: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM graph_edges
                 WHERE vault_id = ?1 AND edge_type = 'page_link' AND to_node_id = ?2",
                params![vault_id, node_id],
                |row| row.get(0),
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        let outgoing_links: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM graph_edges
                 WHERE vault_id = ?1 AND edge_type = 'page_link' AND from_node_id = ?2",
                params![vault_id, node_id],
                |row| row.get(0),
            )
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        metrics.push((
            node_id,
            target_id.unwrap_or_default(),
            title,
            slug.unwrap_or_default(),
            degree,
            incoming_links,
            outgoing_links,
            weak_count,
            audit_count,
        ));
    }
    let mut degrees: Vec<i64> = metrics
        .iter()
        .map(|(_, _, _, _, degree, _, _, _, _)| *degree)
        .collect();
    degrees.sort_unstable();
    let hub_threshold = if degrees.is_empty() {
        i64::MAX
    } else {
        let index = ((degrees.len() as f64) * 0.9).floor() as usize;
        degrees[index.min(degrees.len() - 1)].max(1)
    };
    let incoming_threshold = signal_threshold(
        metrics
            .iter()
            .map(|(_, _, _, _, _, incoming, _, _, _)| *incoming)
            .collect(),
        0.9,
    );
    let outgoing_threshold = signal_threshold(
        metrics
            .iter()
            .map(|(_, _, _, _, _, _, outgoing, _, _)| *outgoing)
            .collect(),
        0.9,
    );
    let mut auto_core_scores: Vec<(String, f64)> = Vec::new();
    for (node_id, _, title, _, degree, incoming_links, outgoing_links, weak_count, _) in &metrics {
        let title_core = title_marks_core(title);
        let score = *degree as f64 * 2.0
            + *incoming_links as f64 * 3.0
            + *outgoing_links as f64
            + *weak_count as f64
            + if title_core { 2.0 } else { 0.0 };
        auto_core_scores.push((node_id.clone(), score));
    }
    auto_core_scores.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.0.cmp(&right.0))
    });
    let auto_core_limit = if metrics.len() <= 8 {
        1
    } else {
        ((metrics.len() as f64) * 0.15).ceil() as usize
    }
    .max(1);
    let auto_core_ids: HashSet<String> = auto_core_scores
        .into_iter()
        .take(auto_core_limit)
        .map(|(node_id, _)| node_id)
        .collect();

    for (
        node_id,
        page_id,
        title,
        slug,
        degree,
        incoming_links,
        outgoing_links,
        weak_count,
        audit_count,
    ) in metrics
    {
        let orphan = degree == 0;
        let hub = degree >= hub_threshold && !orphan;
        let title_core = title_marks_core(&title);
        let many_incoming_links = incoming_links >= incoming_threshold && incoming_links > 0;
        let many_outgoing_links = outgoing_links >= outgoing_threshold && outgoing_links > 0;
        let bridge = incoming_links > 0 && outgoing_links > 0 && degree >= hub_threshold;
        let core_candidate =
            hub || many_incoming_links || many_outgoing_links || bridge || title_core;
        let auto_core = core_candidate && auto_core_ids.contains(&node_id);
        let user_pinned: bool = tx
            .query_row(
                "SELECT pinned FROM graph_node_pins WHERE vault_id = ?1 AND node_id = ?2",
                params![vault_id, node_id],
                |row| row.get::<_, i64>(0),
            )
            .optional()
            .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?
            .unwrap_or(0)
            != 0;
        let mut core_reasons = Vec::new();
        if auto_core && many_incoming_links {
            core_reasons.push("many_incoming_links");
        }
        if auto_core && many_outgoing_links {
            core_reasons.push("many_outgoing_links");
        }
        if auto_core && bridge {
            core_reasons.push("bridge_page");
        }
        if auto_core && title_core {
            core_reasons.push("title_keyword");
        }
        if auto_core && hub {
            core_reasons.push("hub_degree");
        }
        if user_pinned {
            core_reasons.push("user_pinned");
        }
        let weak_ratio = if audit_count == 0 {
            0.0
        } else {
            weak_count as f64 / audit_count as f64
        };
        let weak_cluster = weak_ratio > 0.5;
        let weight = 1.0
            + degree as f64
            + weak_count as f64 * 2.0
            + if auto_core { 3.0 } else { 0.0 }
            + if user_pinned { 5.0 } else { 0.0 };
        let meta = json!({
            "page_id": page_id,
            "slug": slug,
            "degree": degree,
            "incoming_links": incoming_links,
            "outgoing_links": outgoing_links,
            "incoming_threshold": incoming_threshold,
            "outgoing_threshold": outgoing_threshold,
            "weak_citation_count": weak_count,
            "citation_audit_count": audit_count,
            "orphan": orphan,
            "hub": hub,
            "bridge": bridge,
            "title_core": title_core,
            "core_candidate": core_candidate,
            "auto_core": auto_core,
            "user_pinned": user_pinned,
            "core": auto_core || user_pinned,
            "core_reasons": core_reasons,
            "weak_citation_cluster": weak_cluster
        });
        tx.execute(
            "UPDATE graph_nodes SET weight = ?1, meta = ?2, updated_at = ?3 WHERE id = ?4 AND vault_id = ?5",
            params![weight, meta.to_string(), now, node_id, vault_id],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn upsert_node(
    tx: &Transaction<'_>,
    id: &str,
    vault_id: &str,
    node_type: &str,
    label: &str,
    target_type: Option<&str>,
    target_id: Option<&str>,
    status: Option<&str>,
    weight: f64,
    meta: Value,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    let changed = tx
        .execute(
            "INSERT INTO graph_nodes
             (id, vault_id, node_type, label, target_type, target_id, status, weight, meta, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?10)
             ON CONFLICT(id) DO UPDATE SET
               vault_id = excluded.vault_id,
               node_type = excluded.node_type,
               label = excluded.label,
               target_type = excluded.target_type,
               target_id = excluded.target_id,
               status = excluded.status,
               weight = excluded.weight,
               meta = excluded.meta,
               updated_at = excluded.updated_at",
            params![id, vault_id, node_type, label, target_type, target_id, status, weight, meta.to_string(), now],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    summary.created += changed;
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn upsert_edge(
    tx: &Transaction<'_>,
    vault_id: &str,
    edge_type: &str,
    from_node_id: &str,
    to_node_id: &str,
    weight: f64,
    status: Option<&str>,
    meta: Value,
    now: &str,
    summary: &mut GraphRebuildSummary,
) -> Result<(), CoreError> {
    if from_node_id == to_node_id {
        summary.skipped += 1;
        return Ok(());
    }
    let id = format!(
        "edge:{}",
        hash24(&format!(
            "{}:{}:{}:{}",
            edge_type, from_node_id, to_node_id, vault_id
        ))
    );
    let changed = tx
        .execute(
            "INSERT INTO graph_edges
             (id, vault_id, edge_type, from_node_id, to_node_id, weight, status, meta, created_at, updated_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?9)
             ON CONFLICT(vault_id, edge_type, from_node_id, to_node_id) DO UPDATE SET
               weight = excluded.weight,
               status = excluded.status,
               meta = excluded.meta,
               updated_at = excluded.updated_at",
            params![id, vault_id, edge_type, from_node_id, to_node_id, weight, status, meta.to_string(), now],
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    summary.created += changed;
    Ok(())
}

fn fetch_page_tx(
    tx: &Transaction<'_>,
    vault_id: &str,
    page_id: &str,
) -> Result<Option<PageRow>, CoreError> {
    tx.query_row(
        "SELECT id, vault_id, title, slug, path, current_revision_id
         FROM pages WHERE id = ?1 AND vault_id = ?2 AND status = 'active'",
        params![page_id, vault_id],
        |row| {
            Ok(PageRow {
                id: row.get(0)?,
                vault_id: row.get(1)?,
                title: row.get(2)?,
                slug: row.get(3)?,
                path: row.get(4)?,
                current_revision_id: row.get(5)?,
            })
        },
    )
    .optional()
    .map_err(|err| CoreError::new("sqlite_error", err.to_string()))
}

fn fetch_vault_pages(connection: &Connection, vault_id: &str) -> Result<Vec<PageRow>, CoreError> {
    let mut statement = connection
        .prepare(
            "SELECT id, vault_id, title, slug, path, current_revision_id
             FROM pages WHERE vault_id = ?1 AND status = 'active' ORDER BY slug",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let rows = statement
        .query_map(params![vault_id], |row| {
            Ok(PageRow {
                id: row.get(0)?,
                vault_id: row.get(1)?,
                title: row.get(2)?,
                slug: row.get(3)?,
                path: row.get(4)?,
                current_revision_id: row.get(5)?,
            })
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let mut pages = Vec::new();
    for row in rows {
        pages.push(row.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?);
    }
    Ok(pages)
}

fn page_lookup(
    tx: &Transaction<'_>,
    vault_id: &str,
) -> Result<HashMap<String, PageRow>, CoreError> {
    let mut lookup = HashMap::new();
    let mut statement = tx
        .prepare(
            "SELECT id, vault_id, title, slug, path, current_revision_id
             FROM pages WHERE vault_id = ?1 AND status = 'active'",
        )
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    let rows = statement
        .query_map(params![vault_id], |row| {
            Ok(PageRow {
                id: row.get(0)?,
                vault_id: row.get(1)?,
                title: row.get(2)?,
                slug: row.get(3)?,
                path: row.get(4)?,
                current_revision_id: row.get(5)?,
            })
        })
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    for row in rows {
        let page = row.map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
        lookup.insert(normalize_link_target(&page.slug), page.clone());
    }
    Ok(lookup)
}

fn source_status(tx: &Transaction<'_>, citation_key: &str) -> Result<&'static str, CoreError> {
    let exists: Option<String> = tx
        .query_row(
            "SELECT id FROM messages WHERE id = ?1",
            params![citation_key],
            |row| row.get(0),
        )
        .optional()
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(if exists.is_some() {
        "available"
    } else {
        "stale"
    })
}

fn audit_weight(status: &str) -> f64 {
    match status {
        "unsupported" | "contradicted" => 4.0,
        "stale" | "needs_review" => 3.0,
        "partially_supported" => 2.0,
        _ => 1.0,
    }
}

fn finding_weight(severity: &str, status: &str) -> f64 {
    let severity_weight = match severity {
        "critical" => 5.0,
        "high" => 4.0,
        "medium" => 3.0,
        "low" => 2.0,
        _ => 1.0,
    };
    let status_weight = match status {
        "accepted" => 2.0,
        "needs_more_context" => 1.5,
        "implemented" => 0.8,
        "rejected" => 0.5,
        _ => 1.0,
    };
    severity_weight + status_weight
}

fn normalize_link_target(value: &str) -> String {
    let mut normalized = String::new();
    let mut last_dash = false;
    for ch in value.trim().chars() {
        if ch.is_ascii_alphanumeric() {
            normalized.push(ch.to_ascii_lowercase());
            last_dash = false;
        } else if (ch.is_whitespace() || ch == '-' || ch == '_') && !last_dash && !normalized.is_empty() {
            normalized.push('-');
            last_dash = true;
        }
    }
    normalized.trim_matches('-').to_string()
}

fn normalize_tag(value: &str) -> String {
    normalize_link_target(value.trim_start_matches('#'))
}

fn title_marks_core(title: &str) -> bool {
    let lower = title.to_ascii_lowercase();
    ["overview", "primer", "reference", "guide"]
        .iter()
        .any(|keyword| lower.contains(keyword))
}

fn signal_threshold(mut values: Vec<i64>, percentile: f64) -> i64 {
    values.retain(|value| *value > 0);
    if values.is_empty() {
        return i64::MAX;
    }
    values.sort_unstable();
    let index = ((values.len() as f64) * percentile).floor() as usize;
    values[index.min(values.len() - 1)].max(1)
}

fn hash24(value: &str) -> String {
    let digest = Sha256::digest(value.as_bytes());
    format!("{digest:x}").chars().take(24).collect()
}

fn open_connection(sqlite_path: &str) -> Result<Connection, CoreError> {
    let connection = Connection::open(sqlite_path)
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .busy_timeout(std::time::Duration::from_millis(5000))
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    connection
        .execute_batch("PRAGMA foreign_keys=ON;")
        .map_err(|err| CoreError::new("sqlite_error", err.to_string()))?;
    Ok(connection)
}
