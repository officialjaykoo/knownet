use serde_json::json;

use crate::protocol::{ErrorBody, Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "create_page" => Some(create_page(request)),
        "import_obsidian_page" => Some(import_obsidian_page(request)),
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

fn import_obsidian_page(request: &Request) -> Response {
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
    let source_path = request
        .params
        .get("source_path")
        .and_then(|value| value.as_str())
        .unwrap_or("");
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
    let imported_at = request
        .params
        .get("imported_at")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    match storage::import_obsidian_page(storage::ImportObsidianPageInput {
        data_dir,
        sqlite_path,
        source_path,
        page_id,
        revision_id,
        slug,
        title,
        imported_at,
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
