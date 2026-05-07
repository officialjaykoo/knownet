use serde_json::json;

use crate::commands::{failure, str_param, success};
use crate::protocol::{ErrorBody, Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "create_page" => Some(create_page(request)),
        "tombstone_page" => Some(tombstone_page(request)),
        "recover_page" => Some(recover_page(request)),
        _ => None,
    }
}

fn create_page(request: &Request) -> Response {
    let data_dir = request
        .params
        .get("data_dir")
        .and_then(|value| value.as_str())
        .unwrap_or("data");
    let sqlite_path = request
        .params
        .get("sqlite_path")
        .and_then(|value| value.as_str())
        .unwrap_or("data/knownet.db");
    let page_id = request
        .params
        .get("page_id")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let revision_id = request
        .params
        .get("revision_id")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let slug = request
        .params
        .get("slug")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let title = request
        .params
        .get("title")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let created_at = request
        .params
        .get("created_at")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    match storage::create_page(storage::CreatePageInput {
        data_dir,
        sqlite_path,
        page_id,
        revision_id,
        slug,
        title,
        created_at,
    }) {
        Ok(result) => Response::Success {
            id: request.id.clone(),
            ok: true,
            result: json!({
                "slug": result.slug,
                "title": result.title,
                "path": result.path,
                "revision_id": result.revision_id,
                "revision_path": result.revision_path
            }),
        },
        Err(error) => Response::Failure {
            id: request.id.clone(),
            ok: false,
            error: ErrorBody {
                code: error.code.to_string(),
                message: error.message,
                details: json!({}),
            },
        },
    }
}

fn tombstone_page(request: &Request) -> Response {
    let data_dir = str_param(request, "data_dir", "data");
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let slug = str_param(request, "slug", "");
    let tombstoned_at = str_param(request, "tombstoned_at", "");
    match storage::tombstone_page(storage::TombstonePageInput {
        data_dir,
        sqlite_path,
        slug,
        tombstoned_at,
    }) {
        Ok(path) => success(request, json!({"slug": slug, "path": path, "status": "tombstone"})),
        Err(error) => failure(request, error),
    }
}

fn recover_page(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let slug = str_param(request, "slug", "");
    let recovered_at = str_param(request, "recovered_at", "");
    match storage::recover_page(storage::RecoverPageInput {
        sqlite_path,
        slug,
        recovered_at,
    }) {
        Ok(path) => success(request, json!({"slug": slug, "path": path, "status": "active"})),
        Err(error) => failure(request, error),
    }
}
