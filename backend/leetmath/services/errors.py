"""Error registry (docs/07 §7). Services raise ApiError; the API layer renders the unified body."""
from __future__ import annotations

STATUS_FOR = {
    "AUTH_REQUIRED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "VALIDATION_FAILED": 422,
    "INVALID_MATH_INPUT": 422,
    "PREFLIGHT_FAILED": 422,
    "MATH_PARSER_TIMEOUT": 503,
    "GRADER_UNAVAILABLE": 503,
    "CONTENT_RETRACTED": 409,
    "REVISION_SUPERSEDED": 409,
    "RIGHTS_HOLD": 409,
    "SOURCE_VERSION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "EDIT_CONFLICT": 412,
    "INVALID_STATE": 409,
    "SELF_APPROVAL_FORBIDDEN": 403,
    "IMPORT_SCHEMA_MISMATCH": 422,
    "IMPORT_FILE_HASH_MISMATCH": 422,
    "RATE_LIMITED": 429,\n    "RATE_LIMIT_BACKEND_UNAVAILABLE": 503,\n    "CSRF_TOKEN_MISSING": 403,\n    "CSRF_TOKEN_INVALID": 403,\n    "CSRF_ORIGIN_MISMATCH": 403,
    "CONFLICT": 409,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status = status or STATUS_FOR.get(code, 400)
