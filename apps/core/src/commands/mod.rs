use serde_json::{json, Value};

use crate::error::CoreError;
use crate::protocol::{ErrorBody, Request, Response};

pub mod citations;
pub mod collaboration;
pub mod graph;
pub mod pages;
pub mod access;
pub mod submissions;
pub mod suggestions;

pub fn handle_request(request: &Request) -> Option<Response> {
    pages::handle(request)
        .or_else(|| access::handle(request))
        .or_else(|| submissions::handle(request))
        .or_else(|| collaboration::handle(request))
        .or_else(|| citations::handle(request))
        .or_else(|| graph::handle(request))
        .or_else(|| suggestions::handle(request))
}

pub fn str_param<'a>(request: &'a Request, name: &str, default: &'a str) -> &'a str {
    request
        .params
        .get(name)
        .and_then(|value| value.as_str())
        .unwrap_or(default)
}

pub fn opt_str_param<'a>(request: &'a Request, name: &str) -> Option<&'a str> {
    request.params.get(name).and_then(|value| value.as_str())
}

pub fn f64_param(request: &Request, name: &str, default: f64) -> f64 {
    request
        .params
        .get(name)
        .and_then(|value| value.as_f64())
        .unwrap_or(default)
}

pub fn i64_param(request: &Request, name: &str, default: i64) -> i64 {
    request
        .params
        .get(name)
        .and_then(|value| value.as_i64())
        .unwrap_or(default)
}

pub fn opt_i64_param(request: &Request, name: &str) -> Option<i64> {
    request.params.get(name).and_then(|value| value.as_i64())
}

pub fn bool_param(request: &Request, name: &str, default: bool) -> bool {
    request
        .params
        .get(name)
        .and_then(|value| value.as_bool())
        .unwrap_or(default)
}

pub fn success(request: &Request, result: Value) -> Response {
    Response::Success {
        id: request.id.clone(),
        ok: true,
        result,
    }
}

pub fn failure(request: &Request, error: CoreError) -> Response {
    Response::Failure {
        id: request.id.clone(),
        ok: false,
        error: ErrorBody {
            code: error.code.to_string(),
            message: error.message,
            details: json!({}),
        },
    }
}
