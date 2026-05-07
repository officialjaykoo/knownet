use serde_json::json;

use crate::commands::{failure, opt_i64_param, opt_str_param, str_param, success};
use crate::protocol::{Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "create_collaboration_review" => Some(create_collaboration_review(request)),
        "update_collaboration_review_status" => Some(update_collaboration_review_status(request)),
        "create_collaboration_finding" => Some(create_collaboration_finding(request)),
        "update_finding_decision" => Some(update_finding_decision(request)),
        "create_implementation_record" => Some(create_implementation_record(request)),
        "create_context_bundle_manifest" => Some(create_context_bundle_manifest(request)),
        _ => None,
    }
}

fn create_collaboration_review(request: &Request) -> Response {
    let data_dir = str_param(request, "data_dir", "data");
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let review_id = str_param(request, "review_id", "");
    let vault_id = str_param(request, "vault_id", "local-default");
    let title = str_param(request, "title", "Untitled review");
    let source_agent = str_param(request, "source_agent", "unknown");
    let source_model = opt_str_param(request, "source_model");
    let review_type = str_param(request, "review_type", "agent_review");
    let page_id = opt_str_param(request, "page_id");
    let markdown = str_param(request, "markdown", "");
    let meta = str_param(request, "meta", "{}");
    let created_at = str_param(request, "created_at", "");
    match storage::create_collaboration_review(storage::CreateCollaborationReviewInput {
        data_dir,
        sqlite_path,
        review_id,
        vault_id,
        title,
        source_agent,
        source_model,
        review_type,
        page_id,
        markdown,
        meta,
        created_at,
    }) {
        Ok(path) => success(
            request,
            json!({
                "id": review_id,
                "vault_id": vault_id,
                "title": title,
                "source_agent": source_agent,
                "source_model": source_model,
                "review_type": review_type,
                "status": "pending_review",
                "page_id": page_id,
                "path": path,
                "meta": meta,
                "created_at": created_at,
                "updated_at": created_at
            }),
        ),
        Err(error) => failure(request, error),
    }
}

fn update_collaboration_review_status(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let review_id = str_param(request, "review_id", "");
    let status = str_param(request, "status", "");
    let updated_at = str_param(request, "updated_at", "");
    match storage::update_collaboration_review_status(
        storage::UpdateCollaborationReviewStatusInput {
            sqlite_path,
            review_id,
            status,
            updated_at,
        },
    ) {
        Ok(()) => success(
            request,
            json!({
                "review_id": review_id,
                "status": status,
                "updated_at": updated_at
            }),
        ),
        Err(error) => failure(request, error),
    }
}

fn create_collaboration_finding(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let finding_id = str_param(request, "finding_id", "");
    let review_id = str_param(request, "review_id", "");
    let severity = str_param(request, "severity", "info");
    let area = str_param(request, "area", "general");
    let title = str_param(request, "title", "Finding");
    let evidence = opt_str_param(request, "evidence");
    let proposed_change = opt_str_param(request, "proposed_change");
    let raw_text = opt_str_param(request, "raw_text");
    let evidence_quality = str_param(request, "evidence_quality", "unspecified");
    let status = str_param(request, "status", "pending");
    let source_path = opt_str_param(request, "source_path");
    let source_start_line = opt_i64_param(request, "source_start_line");
    let source_end_line = opt_i64_param(request, "source_end_line");
    let source_snippet = opt_str_param(request, "source_snippet");
    let source_location_status = str_param(request, "source_location_status", "omitted");
    let created_at = str_param(request, "created_at", "");
    match storage::create_collaboration_finding(storage::CreateCollaborationFindingInput {
        sqlite_path,
        finding_id,
        review_id,
        severity,
        area,
        title,
        evidence,
        proposed_change,
        raw_text,
        evidence_quality,
        status,
        source_path,
        source_start_line,
        source_end_line,
        source_snippet,
        source_location_status,
        created_at,
    }) {
        Ok(()) => success(
            request,
            json!({
                "id": finding_id,
                "review_id": review_id,
                "severity": severity,
                "area": area,
                "title": title,
                "evidence": evidence,
                "proposed_change": proposed_change,
                "raw_text": raw_text,
                "evidence_quality": evidence_quality,
                "status": status,
                "source_path": source_path,
                "source_start_line": source_start_line,
                "source_end_line": source_end_line,
                "source_snippet": source_snippet,
                "source_location_status": source_location_status,
                "created_at": created_at,
                "updated_at": created_at
            }),
        ),
        Err(error) => failure(request, error),
    }
}

fn update_finding_decision(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let finding_id = str_param(request, "finding_id", "");
    let status = str_param(request, "status", "");
    let decision_note = opt_str_param(request, "decision_note");
    let decided_by = str_param(request, "decided_by", "");
    let decided_at = str_param(request, "decided_at", "");
    match storage::update_finding_decision(storage::UpdateFindingDecisionInput {
        sqlite_path,
        finding_id,
        status,
        decision_note,
        decided_by,
        decided_at,
    }) {
        Ok(()) => success(
            request,
            json!({
                "finding_id": finding_id,
                "status": status,
                "decision_note": decision_note,
                "decided_by": decided_by,
                "decided_at": decided_at
            }),
        ),
        Err(error) => failure(request, error),
    }
}

fn create_implementation_record(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let record_id = str_param(request, "record_id", "");
    let finding_id = str_param(request, "finding_id", "");
    let commit_sha = opt_str_param(request, "commit_sha");
    let changed_files = str_param(request, "changed_files", "[]");
    let verification = str_param(request, "verification", "");
    let notes = opt_str_param(request, "notes");
    let created_at = str_param(request, "created_at", "");
    match storage::create_implementation_record(storage::CreateImplementationRecordInput {
        sqlite_path,
        record_id,
        finding_id,
        commit_sha,
        changed_files,
        verification,
        notes,
        created_at,
    }) {
        Ok(()) => success(
            request,
            json!({
                "id": record_id,
                "finding_id": finding_id,
                "commit_sha": commit_sha,
                "changed_files": changed_files,
                "verification": verification,
                "notes": notes,
                "created_at": created_at
            }),
        ),
        Err(error) => failure(request, error),
    }
}

fn create_context_bundle_manifest(request: &Request) -> Response {
    let data_dir = str_param(request, "data_dir", "data");
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let manifest_id = str_param(request, "manifest_id", "");
    let vault_id = str_param(request, "vault_id", "local-default");
    let filename = str_param(request, "filename", "");
    let content = str_param(request, "content", "");
    let selected_pages = str_param(request, "selected_pages", "[]");
    let included_sections = str_param(request, "included_sections", "[]");
    let excluded_sections = str_param(request, "excluded_sections", "[]");
    let content_hash = str_param(request, "content_hash", "");
    let created_by = str_param(request, "created_by", "");
    let created_at = str_param(request, "created_at", "");
    match storage::create_context_bundle_manifest(storage::CreateContextBundleManifestInput {
        data_dir,
        sqlite_path,
        manifest_id,
        vault_id,
        filename,
        content,
        selected_pages,
        included_sections,
        excluded_sections,
        content_hash,
        created_by,
        created_at,
    }) {
        Ok(path) => success(
            request,
            json!({
                "id": manifest_id,
                "vault_id": vault_id,
                "filename": filename,
                "path": path,
                "selected_pages": selected_pages,
                "included_sections": included_sections,
                "excluded_sections": excluded_sections,
                "content_hash": content_hash,
                "created_by": created_by,
                "created_at": created_at
            }),
        ),
        Err(error) => failure(request, error),
    }
}
