use serde_json::json;

use crate::commands::{failure, i64_param, opt_str_param, str_param, success};
use crate::protocol::{Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "ensure_citation_audit_schema" => Some(ensure_citation_audit_schema(request)),
        "rebuild_citation_audits_for_page" => Some(rebuild_citation_audits_for_page(request)),
        "update_citation_audit_status" => Some(update_citation_audit_status(request)),
        "update_citation_validation_status" => Some(update_citation_validation_status(request)),
        _ => None,
    }
}

fn ensure_citation_audit_schema(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    match storage::ensure_citation_audit_schema(sqlite_path) {
        Ok(()) => success(request, json!({"status": "ok"})),
        Err(error) => failure(request, error),
    }
}

fn rebuild_citation_audits_for_page(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "local-default");
    let page_id = str_param(request, "page_id", "");
    let revision_id = opt_str_param(request, "revision_id");
    let path = str_param(request, "path", "");
    let rebuilt_at = str_param(request, "rebuilt_at", "");
    match storage::rebuild_citation_audits_for_page(storage::RebuildCitationAuditsInput {
        sqlite_path,
        vault_id,
        page_id,
        revision_id,
        path,
        rebuilt_at,
    }) {
        Ok(summary) => success(
            request,
            json!({
                "created": summary.created,
                "skipped": summary.skipped,
                "failed": summary.failed,
                "citation_warnings": summary.warnings
            }),
        ),
        Err(error) => failure(request, error),
    }
}

fn update_citation_audit_status(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let audit_id = str_param(request, "audit_id", "");
    let actor_type = str_param(request, "actor_type", "user");
    let actor_id = str_param(request, "actor_id", "");
    let status = str_param(request, "status", "");
    let reason = str_param(request, "reason", "");
    let updated_at = str_param(request, "updated_at", "");
    match storage::update_citation_audit_status(storage::UpdateCitationAuditStatusInput {
        sqlite_path,
        audit_id,
        actor_type,
        actor_id,
        status,
        reason,
        updated_at,
    }) {
        Ok(()) => success(request, json!({"audit_id": audit_id, "status": status})),
        Err(error) => failure(request, error),
    }
}

fn update_citation_validation_status(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let citation_id = i64_param(request, "citation_id", 0);
    let status = str_param(request, "status", "");
    match storage::update_citation_validation_status(storage::UpdateCitationValidationStatusInput {
        sqlite_path,
        citation_id,
        status,
    }) {
        Ok(()) => success(request, json!({"citation_id": citation_id, "validation_status": status})),
        Err(error) => failure(request, error),
    }
}
