from typing import Any

from .services.rust_core import RustCoreError


def operation_failure_status(error: Exception) -> dict[str, Any]:
    if isinstance(error, RustCoreError):
        return {"status": "failed", "code": error.code, "message": error.message, "details": error.details}
    return {"status": "failed", "code": "unexpected_error", "message": str(error)[:300], "details": {}}
