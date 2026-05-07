use serde_json::json;

use crate::commands::{failure, opt_str_param, str_param, success};
use crate::protocol::{Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "create_submission" => Some(create_submission(request)),
        "update_submission_status" => Some(update_submission_status(request)),
        _ => None,
    }
}

fn create_submission(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let submission_id = str_param(request, "submission_id", "");
    let message_id = str_param(request, "message_id", "");
    let actor_type = str_param(request, "actor_type", "anonymous");
    let session_id = opt_str_param(request, "session_id");
    let created_at = str_param(request, "created_at", "");
    match storage::create_submission(storage::CreateSubmissionInput {
        sqlite_path,
        submission_id,
        message_id,
        actor_type,
        session_id,
        created_at,
    }) {
        Ok(()) => success(request, json!({"submission_id": submission_id, "status": "pending_review"})),
        Err(error) => failure(request, error),
    }
}

fn update_submission_status(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let submission_id = str_param(request, "submission_id", "");
    let status = str_param(request, "status", "");
    let reviewed_by = str_param(request, "reviewed_by", "");
    let review_note = opt_str_param(request, "review_note");
    let updated_at = str_param(request, "updated_at", "");
    match storage::update_submission_status(storage::UpdateSubmissionStatusInput {
        sqlite_path,
        submission_id,
        status,
        reviewed_by,
        review_note,
        updated_at,
    }) {
        Ok(job_id) => success(request, json!({"submission_id": submission_id, "status": status, "job_id": job_id})),
        Err(error) => failure(request, error),
    }
}
