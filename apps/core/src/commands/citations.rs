use serde_json::json;

use crate::protocol::{ErrorBody, Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "update_citation_validation_status" => Some(update_citation_validation_status(request)),
        _ => None,
    }
}

fn update_citation_validation_status(request: &Request) -> Response {
    let sqlite_path = request
        .params
        .get("sqlite_path")
        .and_then(|value| value.as_str())
        .unwrap_or("data/knownet.db");
    let citation_id = request
        .params
        .get("citation_id")
        .and_then(|value| value.as_i64())
        .unwrap_or(0);
    let status = request
        .params
        .get("status")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    match storage::update_citation_validation_status(storage::UpdateCitationValidationStatusInput {
        sqlite_path,
        citation_id,
        status,
    }) {
        Ok(()) => Response::Success {
            id: request.id.clone(),
            ok: true,
            result: json!({"citation_id": citation_id, "validation_status": status}),
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
