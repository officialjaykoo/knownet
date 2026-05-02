use serde_json::json;

use crate::protocol::{ErrorBody, Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "reject_suggestion" => Some(reject_suggestion(request)),
        _ => None,
    }
}

fn reject_suggestion(request: &Request) -> Response {
    let sqlite_path = request
        .params
        .get("sqlite_path")
        .and_then(|value| value.as_str())
        .unwrap_or("data/knownet.db");
    let suggestion_id = request
        .params
        .get("suggestion_id")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    let rejected_at = request
        .params
        .get("rejected_at")
        .and_then(|value| value.as_str())
        .unwrap_or("");
    match storage::reject_suggestion(storage::RejectSuggestionInput {
        sqlite_path,
        suggestion_id,
        rejected_at,
    }) {
        Ok(()) => Response::Success {
            id: request.id.clone(),
            ok: true,
            result: json!({"suggestion_id": suggestion_id, "status": "rejected"}),
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
