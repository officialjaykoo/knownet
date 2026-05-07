use serde_json::json;

use crate::commands::{failure, opt_str_param, str_param, success};
use crate::protocol::{Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "create_user" => Some(create_user(request)),
        "create_vault" => Some(create_vault(request)),
        "assign_vault_member" => Some(assign_vault_member(request)),
        "create_session" => Some(create_session(request)),
        "revoke_session" => Some(revoke_session(request)),
        _ => None,
    }
}

fn create_user(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let user_id = str_param(request, "user_id", "");
    let username = str_param(request, "username", "");
    let password_hash = str_param(request, "password_hash", "");
    let role = str_param(request, "role", "viewer");
    let created_at = str_param(request, "created_at", "");
    match storage::create_user(storage::CreateUserInput {
        sqlite_path,
        user_id,
        username,
        password_hash,
        role,
        created_at,
    }) {
        Ok(()) => success(request, json!({"user_id": user_id, "username": username, "role": role})),
        Err(error) => failure(request, error),
    }
}

fn create_vault(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "");
    let name = str_param(request, "name", "");
    let owner_user_id = str_param(request, "owner_user_id", "");
    let created_at = str_param(request, "created_at", "");
    match storage::create_vault(storage::CreateVaultInput {
        sqlite_path,
        vault_id,
        name,
        owner_user_id,
        created_at,
    }) {
        Ok(()) => success(request, json!({"vault_id": vault_id, "name": name, "role": "owner"})),
        Err(error) => failure(request, error),
    }
}

fn assign_vault_member(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "");
    let user_id = str_param(request, "user_id", "");
    let role = str_param(request, "role", "viewer");
    let created_at = str_param(request, "created_at", "");
    match storage::assign_vault_member(storage::AssignVaultMemberInput {
        sqlite_path,
        vault_id,
        user_id,
        role,
        created_at,
    }) {
        Ok(()) => success(request, json!({"vault_id": vault_id, "user_id": user_id, "role": role})),
        Err(error) => failure(request, error),
    }
}

fn create_session(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let session_id = str_param(request, "session_id", "");
    let user_id = opt_str_param(request, "user_id");
    let actor_type = str_param(request, "actor_type", "user");
    let session_meta = str_param(request, "session_meta", "{}");
    let expires_at = str_param(request, "expires_at", "");
    let created_at = str_param(request, "created_at", "");
    match storage::create_session(storage::CreateSessionInput {
        sqlite_path,
        session_id,
        user_id,
        actor_type,
        session_meta,
        expires_at,
        created_at,
    }) {
        Ok(()) => success(request, json!({"session_id": session_id, "actor_type": actor_type})),
        Err(error) => failure(request, error),
    }
}

fn revoke_session(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let session_id = str_param(request, "session_id", "");
    match storage::revoke_session(sqlite_path, session_id) {
        Ok(()) => success(request, json!({"session_id": session_id, "status": "revoked"})),
        Err(error) => failure(request, error),
    }
}
