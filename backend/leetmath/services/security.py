"""Cookie-session and signed double-submit CSRF helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlsplit

from fastapi import Request

from ..config import settings


def session_cookie_name() -> str:
    # __Host- cookies must be Secure, host-only, and Path=/.
    return "__Host-leetmath_session" if settings.cookie_secure else "leetmath_session"


def csrf_cookie_name() -> str:
    return "__Host-leetmath_csrf" if settings.cookie_secure else "leetmath_csrf"


def create_csrf_token() -> str:
    nonce = secrets.token_urlsafe(32)
    signature = hmac.new(settings.csrf_secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return nonce + "." + signature


def valid_csrf_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, supplied = token.rsplit(".", 1)
    if not nonce or len(supplied) != 64:
        return False
    expected = hmac.new(settings.csrf_secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(supplied, expected)


def same_origin(request: Request, origin: str) -> bool:
    if origin == "null":
        return False
    try:
        candidate = urlsplit(origin)
        expected = urlsplit(str(request.base_url))
        return (candidate.scheme.lower(), candidate.netloc.lower()) == (
            expected.scheme.lower(), expected.netloc.lower()
        )
    except ValueError:
        return False


def csrf_error(request: Request) -> str | None:
    """Return a safe error code when an unsafe request fails origin/CSRF checks."""
    origin = request.headers.get("origin")
    if origin and not same_origin(request, origin):
        return "CSRF_ORIGIN_MISMATCH"
    if request.method.upper() in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return None
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        # Explicit Authorization headers are not ambient browser credentials.
        return None
    cookie_token = request.cookies.get(csrf_cookie_name())
    header_token = request.headers.get("x-csrf-token")
    if not cookie_token or not header_token:
        return "CSRF_TOKEN_MISSING"
    if not hmac.compare_digest(cookie_token, header_token) or not valid_csrf_token(cookie_token):
        return "CSRF_TOKEN_INVALID"
    return None
