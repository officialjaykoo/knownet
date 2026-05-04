use std::io::{self, BufRead, Write};

use serde_json::json;

use crate::error::CoreError;
use crate::markdown;
use crate::protocol::{ErrorBody, Request, Response};
use crate::storage;

pub fn run() -> Result<(), CoreError> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().split(b'\n') {
        let bytes = line.map_err(|err| CoreError::new("io_error", err.to_string()))?;
        let line = String::from_utf8_lossy(&bytes)
            .trim_end_matches('\r')
            .to_string();
        if line.trim().is_empty() {
            continue;
        }
        let response = handle_line(&line);
        let encoded = serde_json::to_string(&response)
            .map_err(|err| CoreError::new("serialization_error", err.to_string()))?;
        writeln!(stdout, "{encoded}").map_err(|err| CoreError::new("io_error", err.to_string()))?;
        stdout
            .flush()
            .map_err(|err| CoreError::new("io_error", err.to_string()))?;
    }

    Ok(())
}

fn handle_line(line: &str) -> Response {
    let parsed: Result<Request, _> = serde_json::from_str(line);
    match parsed {
        Ok(request) => handle_request(request),
        Err(error) => Response::Failure {
            id: "unknown".to_string(),
            ok: false,
            error: ErrorBody {
                code: "validation_error".to_string(),
                message: error.to_string(),
                details: json!({}),
            },
        },
    }
}

fn handle_request(request: Request) -> Response {
    if let Some(response) = crate::commands::handle_request(&request) {
        return response;
    }
    match request.cmd.as_str() {
        "ping" => Response::Success {
            id: request.id,
            ok: true,
            result: json!({"status": "ok", "version": env!("CARGO_PKG_VERSION")}),
        },
        "init_db" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            match storage::init_db(sqlite_path) {
                Ok(result) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "sqlite_path": result.sqlite_path,
                        "journal_mode": result.journal_mode
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "ensure_phase4_schema" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            match storage::ensure_phase4_schema(sqlite_path) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"status": "ok"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "ensure_graph_schema" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            match storage::ensure_graph_schema(sqlite_path) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"status": "ok"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "rebuild_citation_audits_for_page" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let vault_id = request
                .params
                .get("vault_id")
                .and_then(|value| value.as_str())
                .unwrap_or("local-default");
            let page_id = request
                .params
                .get("page_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let revision_id = request
                .params
                .get("revision_id")
                .and_then(|value| value.as_str());
            let path = request
                .params
                .get("path")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let rebuilt_at = request
                .params
                .get("rebuilt_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::rebuild_citation_audits_for_page(storage::RebuildCitationAuditsInput {
                sqlite_path,
                vault_id,
                page_id,
                revision_id,
                path,
                rebuilt_at,
            }) {
                Ok(summary) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "created": summary.created,
                        "skipped": summary.skipped,
                        "failed": summary.failed,
                        "citation_warnings": summary.warnings
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "update_citation_audit_status" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let audit_id = request
                .params
                .get("audit_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let actor_type = request
                .params
                .get("actor_type")
                .and_then(|value| value.as_str())
                .unwrap_or("user");
            let actor_id = request
                .params
                .get("actor_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let status = request
                .params
                .get("status")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let reason = request
                .params
                .get("reason")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let updated_at = request
                .params
                .get("updated_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::update_citation_audit_status(storage::UpdateCitationAuditStatusInput {
                sqlite_path,
                audit_id,
                actor_type,
                actor_id,
                status,
                reason,
                updated_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"audit_id": audit_id, "status": status}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "create_user" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let user_id = request
                .params
                .get("user_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let username = request
                .params
                .get("username")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let password_hash = request
                .params
                .get("password_hash")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let role = request
                .params
                .get("role")
                .and_then(|value| value.as_str())
                .unwrap_or("viewer");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::create_user(storage::CreateUserInput {
                sqlite_path,
                user_id,
                username,
                password_hash,
                role,
                created_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"user_id": user_id, "username": username, "role": role}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "create_vault" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let vault_id = request
                .params
                .get("vault_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let name = request
                .params
                .get("name")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let owner_user_id = request
                .params
                .get("owner_user_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::create_vault(storage::CreateVaultInput {
                sqlite_path,
                vault_id,
                name,
                owner_user_id,
                created_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"vault_id": vault_id, "name": name, "role": "owner"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "assign_vault_member" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let vault_id = request
                .params
                .get("vault_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let user_id = request
                .params
                .get("user_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let role = request
                .params
                .get("role")
                .and_then(|value| value.as_str())
                .unwrap_or("viewer");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::assign_vault_member(storage::AssignVaultMemberInput {
                sqlite_path,
                vault_id,
                user_id,
                role,
                created_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"vault_id": vault_id, "user_id": user_id, "role": role}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "create_session" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let session_id = request
                .params
                .get("session_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let user_id = request
                .params
                .get("user_id")
                .and_then(|value| value.as_str());
            let actor_type = request
                .params
                .get("actor_type")
                .and_then(|value| value.as_str())
                .unwrap_or("user");
            let session_meta = request
                .params
                .get("session_meta")
                .and_then(|value| value.as_str())
                .unwrap_or("{}");
            let expires_at = request
                .params
                .get("expires_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::create_session(storage::CreateSessionInput {
                sqlite_path,
                session_id,
                user_id,
                actor_type,
                session_meta,
                expires_at,
                created_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"session_id": session_id, "actor_type": actor_type}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "revoke_session" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let session_id = request
                .params
                .get("session_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::revoke_session(sqlite_path, session_id) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"session_id": session_id, "status": "revoked"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "create_submission" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let submission_id = request
                .params
                .get("submission_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let message_id = request
                .params
                .get("message_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let actor_type = request
                .params
                .get("actor_type")
                .and_then(|value| value.as_str())
                .unwrap_or("anonymous");
            let session_id = request
                .params
                .get("session_id")
                .and_then(|value| value.as_str());
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::create_submission(storage::CreateSubmissionInput {
                sqlite_path,
                submission_id,
                message_id,
                actor_type,
                session_id,
                created_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"submission_id": submission_id, "status": "pending_review"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "update_submission_status" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let submission_id = request
                .params
                .get("submission_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let status = request
                .params
                .get("status")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let reviewed_by = request
                .params
                .get("reviewed_by")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let review_note = request
                .params
                .get("review_note")
                .and_then(|value| value.as_str());
            let updated_at = request
                .params
                .get("updated_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::update_submission_status(storage::UpdateSubmissionStatusInput {
                sqlite_path,
                submission_id,
                status,
                reviewed_by,
                review_note,
                updated_at,
            }) {
                Ok(job_id) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"submission_id": submission_id, "status": status, "job_id": job_id}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "tombstone_page" => {
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
            let slug = request
                .params
                .get("slug")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let tombstoned_at = request
                .params
                .get("tombstoned_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::tombstone_page(storage::TombstonePageInput {
                data_dir,
                sqlite_path,
                slug,
                tombstoned_at,
            }) {
                Ok(path) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"slug": slug, "path": path, "status": "tombstone"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "recover_page" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let slug = request
                .params
                .get("slug")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let recovered_at = request
                .params
                .get("recovered_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::recover_page(storage::RecoverPageInput {
                sqlite_path,
                slug,
                recovered_at,
            }) {
                Ok(path) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"slug": slug, "path": path, "status": "active"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "write_message" => {
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
            let message_id = request
                .params
                .get("message_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let content = request
                .params
                .get("content")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::write_message(storage::WriteMessageInput {
                data_dir,
                sqlite_path,
                message_id,
                content,
                created_at,
            }) {
                Ok(result) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "message_id": result.message_id,
                        "job_id": result.job_id,
                        "path": result.path,
                        "status": result.status
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "write_pending_message" => {
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
            let message_id = request
                .params
                .get("message_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let content = request
                .params
                .get("content")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::write_pending_message(storage::WritePendingMessageInput {
                data_dir,
                sqlite_path,
                message_id,
                content,
                created_at,
            }) {
                Ok(result) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "message_id": result.message_id,
                        "job_id": null,
                        "path": result.path,
                        "status": result.status
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "parse" => {
            let path = request
                .params
                .get("path")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match markdown::parse_file(path) {
                Ok(result) => Response::Success {
                    id: request.id,
                    ok: true,
                    result,
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "claim_next_job" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let now = request
                .params
                .get("now")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::claim_next_job(sqlite_path, now) {
                Ok(Some(job)) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "claimed": true,
                        "job": {
                            "id": job.id,
                            "job_type": job.job_type,
                            "target_type": job.target_type,
                            "target_id": job.target_id,
                            "attempts": job.attempts + 1,
                            "max_attempts": job.max_attempts
                        }
                    }),
                },
                Ok(None) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"claimed": false}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "recover_stale_jobs" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let stale_before = request
                .params
                .get("stale_before")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let now = request
                .params
                .get("now")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::recover_stale_jobs(sqlite_path, stale_before, now) {
                Ok(recovered) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"recovered": recovered}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "complete_draft_job" => {
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
            let job_id = request
                .params
                .get("job_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let suggestion_id = request
                .params
                .get("suggestion_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let markdown_path = request
                .params
                .get("markdown_path")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let title = request
                .params
                .get("title")
                .and_then(|value| value.as_str())
                .unwrap_or("Draft suggestion");
            let created_at = request
                .params
                .get("created_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::complete_draft_job(storage::CompleteDraftInput {
                data_dir,
                sqlite_path,
                job_id,
                suggestion_id,
                markdown_path,
                title,
                created_at,
            }) {
                Ok(path) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "job_id": job_id,
                        "suggestion_id": suggestion_id,
                        "path": path,
                        "status": "completed"
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "fail_job" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let job_id = request
                .params
                .get("job_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let error_code = request
                .params
                .get("error_code")
                .and_then(|value| value.as_str())
                .unwrap_or("job_failed");
            let error_message = request
                .params
                .get("error_message")
                .and_then(|value| value.as_str())
                .unwrap_or("Job failed");
            let now = request
                .params
                .get("now")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::fail_job(sqlite_path, job_id, error_code, error_message, now) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"job_id": job_id, "status": "failed"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "apply_suggestion" => {
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
            let suggestion_id = request
                .params
                .get("suggestion_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let slug = request
                .params
                .get("slug")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let revision_id = request
                .params
                .get("revision_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let applied_at = request
                .params
                .get("applied_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::apply_suggestion(storage::ApplySuggestionInput {
                data_dir,
                sqlite_path,
                suggestion_id,
                slug,
                revision_id,
                applied_at,
            }) {
                Ok(path) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "suggestion_id": suggestion_id,
                        "slug": slug,
                        "revision_id": revision_id,
                        "path": path,
                        "status": "applied"
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "restore_revision" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let slug = request
                .params
                .get("slug")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let revision_id = request
                .params
                .get("revision_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let restored_at = request
                .params
                .get("restored_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::restore_revision(storage::RestoreRevisionInput {
                sqlite_path,
                slug,
                revision_id,
                restored_at,
            }) {
                Ok(path) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({
                        "slug": slug,
                        "revision_id": revision_id,
                        "path": path,
                        "status": "restored"
                    }),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "index_page" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let path = request
                .params
                .get("path")
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
                .and_then(|value| value.as_str());
            let indexed_at = request
                .params
                .get("indexed_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::index_page_file(sqlite_path, path, page_id, revision_id, indexed_at) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"page_id": page_id, "revision_id": revision_id, "status": "indexed"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        "embedding_upsert" => {
            let sqlite_path = request
                .params
                .get("sqlite_path")
                .and_then(|value| value.as_str())
                .unwrap_or("data/knownet.db");
            let embedding_id = request
                .params
                .get("embedding_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let owner_type = request
                .params
                .get("owner_type")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let owner_id = request
                .params
                .get("owner_id")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let model = request
                .params
                .get("model")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let vector_path = request
                .params
                .get("vector_path")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            let dims = request
                .params
                .get("dims")
                .and_then(|value| value.as_i64())
                .unwrap_or(0);
            let updated_at = request
                .params
                .get("updated_at")
                .and_then(|value| value.as_str())
                .unwrap_or("");
            match storage::embedding_upsert(storage::EmbeddingUpsertInput {
                sqlite_path,
                embedding_id,
                owner_type,
                owner_id,
                model,
                vector_path,
                dims,
                updated_at,
            }) {
                Ok(()) => Response::Success {
                    id: request.id,
                    ok: true,
                    result: json!({"embedding_id": embedding_id, "status": "stored"}),
                },
                Err(error) => Response::Failure {
                    id: request.id,
                    ok: false,
                    error: ErrorBody {
                        code: error.code.to_string(),
                        message: error.message,
                        details: json!({}),
                    },
                },
            }
        }
        _ => Response::Failure {
            id: request.id,
            ok: false,
            error: ErrorBody {
                code: "validation_error".to_string(),
                message: format!("unknown command: {}", request.cmd),
                details: json!({}),
            },
        },
    }
}
