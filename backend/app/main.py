"""FastAPI application: routers, error shape, security headers, 403 auditing, static frontend."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import audit
from .config import settings
from .db import SessionLocal, init_db
from .modules import (
    api_audit,
    api_auth,
    api_credentials,
    api_dashboard,
    api_imports,
    api_integration,
    api_issues,
    api_records,
    api_registry,
    api_students,
    api_verification,
)
from .modules.credentials import issuer_key
from .modules.rules import seed_rules
from .security import ANONYMOUS, ApiError

log = logging.getLogger("apaar")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_rules(db)
        db.commit()
    issuer_key()
    yield


app = FastAPI(
    title="APAAR-based Student Data Management and Verification System (prototype)",
    version="0.5.0",
    description="SIH26263 prototype. Synthetic data only. APAAR registry verification is SIMULATED.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
    lifespan=lifespan,
)

for r in (api_auth, api_registry, api_imports, api_records, api_issues, api_dashboard, api_credentials,
          api_verification, api_integration, api_audit, api_students):
    app.include_router(r.router)
app.include_router(api_credentials.wellknown)


def _error(request: Request, status: int, message: str, **extra) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:12]
    body = {"error": {**extra, "status": status, "message": message, "request_id": rid}}
    return JSONResponse(body, status_code=status)


def _audit_denied(request: Request, message: str) -> None:
    actor = getattr(request.state, "actor", None) or ANONYMOUS
    try:
        audit.record_now(actor, "access.denied", "route", request.url.path, "DENIED",
                         {"method": request.method, "path": request.url.path, "message": message})
    except Exception:  # noqa: BLE001
        log.exception("could not audit denied access")


@app.exception_handler(ApiError)
async def api_error(request: Request, exc: ApiError):
    if exc.status == 403:
        _audit_denied(request, exc.message)
    return _error(request, exc.status, exc.message, **exc.extra)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
    if exc.status_code == 404:
        msg = "Not found."
    if exc.status_code == 403:
        _audit_denied(request, msg)
    return _error(request, exc.status_code, msg)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = []
    for e in exc.errors():
        loc = [str(p) for p in e.get("loc", []) if p not in ("body", "query", "path")]
        fields.append({"field": ".".join(loc), "message": e.get("msg", "invalid")})
    return _error(request, 422, "Some fields are missing or invalid.", fields=fields)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error", exc_info=exc)
    return _error(request, 500, "Something went wrong on our side. The error was logged; try again.")


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
            "frame-ancestors 'none'")


@app.middleware("http")
async def headers(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    response = await call_next(request)
    path = request.url.path
    response.headers.setdefault("Content-Security-Policy", DOCS_CSP if path.startswith("/api/docs") else CSP)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Request-ID"] = request.state.request_id
    if path.startswith("/api/") or path.startswith("/.well-known/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health", tags=["meta"])
def health():
    with SessionLocal() as db:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
    return {"status": "ok", "apaar_registry": "SIMULATED", "data": "synthetic"}


_dist = settings.frontend_dist
if (_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")
if (_dist / "fonts").is_dir():
    app.mount("/fonts", StaticFiles(directory=_dist / "fonts"), name="fonts")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise ApiError(404, "Not found.")
    candidate = (_dist / path).resolve()
    if path and candidate.is_file() and _dist.resolve() in candidate.parents:
        return FileResponse(candidate)
    index = _dist / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"message": "Frontend not built. Run `make build` (or use the Vite dev server on :5173).",
                         "api_docs": "/api/docs"})
