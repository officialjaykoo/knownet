use serde_json::json;

use crate::commands::{bool_param, f64_param, failure, opt_str_param, str_param, success};
use crate::protocol::{Request, Response};
use crate::storage;

pub fn handle(request: &Request) -> Option<Response> {
    match request.cmd.as_str() {
        "rebuild_graph_for_page" => Some(rebuild_graph_for_page(request)),
        "rebuild_graph_for_vault" => Some(rebuild_graph_for_vault(request)),
        "upsert_graph_layout_node" => Some(upsert_graph_layout_node(request)),
        "clear_graph_layout_cache" => Some(clear_graph_layout_cache(request)),
        "set_graph_node_pin" => Some(set_graph_node_pin(request)),
        _ => None,
    }
}

fn rebuild_graph_for_page(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "local-default");
    let page_id = opt_str_param(request, "page_id");
    let rebuilt_at = str_param(request, "rebuilt_at", "");
    match storage::rebuild_graph_for_page(storage::RebuildGraphInput {
        sqlite_path,
        vault_id,
        page_id,
        rebuilt_at,
    }) {
        Ok(summary) => graph_rebuild_success(request, summary),
        Err(error) => failure(request, error),
    }
}

fn rebuild_graph_for_vault(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "local-default");
    let rebuilt_at = str_param(request, "rebuilt_at", "");
    match storage::rebuild_graph_for_vault(storage::RebuildGraphInput {
        sqlite_path,
        vault_id,
        page_id: None,
        rebuilt_at,
    }) {
        Ok(summary) => graph_rebuild_success(request, summary),
        Err(error) => failure(request, error),
    }
}

fn upsert_graph_layout_node(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "local-default");
    let layout_key = str_param(request, "layout_key", "");
    let node_id = str_param(request, "node_id", "");
    let x = f64_param(request, "x", 0.0);
    let y = f64_param(request, "y", 0.0);
    let pinned = bool_param(request, "pinned", true);
    let updated_at = str_param(request, "updated_at", "");
    match storage::upsert_graph_layout_node(storage::UpsertGraphLayoutInput {
        sqlite_path,
        vault_id,
        layout_key,
        node_id,
        x,
        y,
        pinned,
        updated_at,
    }) {
        Ok(()) => success(request, json!({"status": "ok"})),
        Err(error) => failure(request, error),
    }
}

fn clear_graph_layout_cache(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "local-default");
    let layout_key = opt_str_param(request, "layout_key");
    match storage::clear_graph_layout_cache(storage::ClearGraphLayoutInput {
        sqlite_path,
        vault_id,
        layout_key,
    }) {
        Ok(removed) => success(request, json!({"removed": removed})),
        Err(error) => failure(request, error),
    }
}

fn set_graph_node_pin(request: &Request) -> Response {
    let sqlite_path = str_param(request, "sqlite_path", "data/knownet.db");
    let vault_id = str_param(request, "vault_id", "local-default");
    let node_id = str_param(request, "node_id", "");
    let pinned = bool_param(request, "pinned", true);
    let updated_at = str_param(request, "updated_at", "");
    match storage::set_graph_node_pin(storage::SetGraphNodePinInput {
        sqlite_path,
        vault_id,
        node_id,
        pinned,
        updated_at,
    }) {
        Ok(()) => success(
            request,
            json!({"status": "ok", "node_id": node_id, "pinned": pinned}),
        ),
        Err(error) => failure(request, error),
    }
}

fn graph_rebuild_success(request: &Request, summary: storage::GraphRebuildSummary) -> Response {
    success(
        request,
        json!({
            "created": summary.created,
            "skipped": summary.skipped,
            "removed": summary.removed,
            "failed": summary.failed,
            "report": summary.report
        }),
    )
}
