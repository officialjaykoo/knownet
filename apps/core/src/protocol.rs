use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Deserialize)]
pub struct Request {
    pub id: String,
    pub cmd: String,
    #[serde(default)]
    pub params: Value,
}

#[derive(Debug, Serialize)]
#[serde(untagged)]
pub enum Response {
    Success {
        id: String,
        ok: bool,
        result: Value,
    },
    Failure {
        id: String,
        ok: bool,
        error: ErrorBody,
    },
}

#[derive(Debug, Serialize)]
pub struct ErrorBody {
    pub code: String,
    pub message: String,
    pub details: Value,
}
