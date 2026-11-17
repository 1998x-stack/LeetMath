"""FastAPI application: modular monolith (catalog · learning · grading · ingestion · CMS · reasoning practice)."""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ROOT, settings
from .db import create_all, new_session
from .services.audit import request_id_var
from .services.errors import ApiError
from .services.rate_limit import rate_limit
from .services.security import csrf_error

log = logging.getLogger("leetmath")
FRONTEND = ROOT / "frontend"

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def _err(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
                                                               "request_id": request_id_var.get(), "details": details or {}}})


def create_app(init_db: bool | None = None) -> FastAPI:
    import os

    if settings.environment == "production":
        if not settings.cookie_secure:
            raise RuntimeError("LEETMATH_COOKIE_SECURE=1 is required in production")
        if not settings.redis_url:
            raise RuntimeError("LEETMATH_REDIS_URL is required in production")
        if settings.csrf_secret == "leetmath-dev-only-change-this-secret" or len(settings.csrf_secret) < 32:
            raise RuntimeError("a unique LEETMATH_CSRF_SECRET (at least 32 characters) is required in production")

    if init_db is None:  # production runs `leetmath.cli migrate` and sets LEETMATH_AUTO_CREATE=0
        init_db = os.environ.get("LEETMATH_AUTO_CREATE", "1") == "1"
    if init_db:
        create_all()
    app = FastAPI(title="LeetMath API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def per_request(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        s = new_session()
        request.state.db = s
        try:
            if request.url.path.startswith("/api/v1/"):
                csrf_code = csrf_error(request)
                if csrf_code:
                    raise ApiError(csrf_code, "request origin or CSRF token is invalid")
                client_ip = request.client.host if request.client else "unknown"
                path = request.url.path
                if path.endswith("/auth/login"):
                    operation, limit = "auth-login", 60
                elif path.endswith("/auth/register"):
                    operation, limit = "auth-register", 10
                elif path.endswith("/submissions"):
                    operation, limit = "submission", 240
                elif path.endswith("/content-reports"):
                    operation, limit = "content-report", 30
                elif "/admin/" in path:
                    operation, limit = "cms-write" if request.method not in {"GET", "HEAD"} else "cms-read", 180
                elif request.method in {"GET", "HEAD", "OPTIONS"}:
                    operation, limit = "read", 600
                else:
                    operation, limit = "write", 180
                rate_limit(f"ip:{client_ip}:{operation}", limit)
            response = await call_next(request)
            if response.status_code < 400:
                s.commit()
            else:
                s.rollback()
        except ApiError as exc:
            s.rollback()
            response = _err(exc.status, exc.code, exc.message, exc.details)
            if exc.status == 429:
                response.headers["Retry-After"] = str(max(1, int(exc.details.get("retry_after_s", 1))))
        except Exception:
            s.rollback()
            log.exception("unhandled error rid=%s", rid)
            response = _err(500, "INTERNAL_ERROR", "internal error")
        finally:
            s.close()
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = CSP
        return response

    @app.exception_handler(ApiError)
    async def api_error(_req: Request, exc: ApiError):
        return _err(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_req: Request, exc: RequestValidationError):
        return _err(422, "VALIDATION_FAILED", "request validation failed",
                    {"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()][:20]})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_req: Request, exc: StarletteHTTPException):
        code = {401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "ERROR")
        return _err(exc.status_code, code, str(exc.detail))

    from .api import admin, public, reasoning_routes

    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(reasoning_routes.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    if FRONTEND.is_dir():
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return _err(404, "NOT_FOUND", "not found")
            return FileResponse(FRONTEND / "index.html")

    return app
