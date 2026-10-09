"""The real application.

Middleware, exception handlers and the ten routers of document 2 section 9.

Phase zero builds the shell and the handlers. The routers are empty and are
filled group by group in phase one, replacing the mock one group at a time.
While a group is empty the frontend keeps reading the mock for it, which is
why the two must return identical shapes.

    uvicorn app.main:app --port 8000 --reload
"""

import os

from fastapi import FastAPI, Request

# Imported first so a .env file is read before anything looks at the
# environment for a signing key or a model.
from app import config
from app import logging as app_logging
from app.middleware.request_context import RequestContextMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# JSON structured logs with per-request context (S9). Installed before
# anything else — a startup error should land in the JSON stream too.
app_logging.configure(level=os.environ.get("TREASURY_LOG_LEVEL", "INFO"))

from app.api import (
    accounting,
    activation,
    approvals,
    auth,
    admin,
    admin_mfa,
    admin_users,
    advisory,
    compliance,
    confirmations,
    control,
    counterparties,
    currency,
    deals,
    fx,
    jobs,
    mfa,
    performance,
    planner,
    rates,
    scenarios,
    state,
    system_policy,
)
from app.errors import TreasuryError

app = FastAPI(
    title="Treasury Register",
    version="0.1.0",
    description=(
        "A control system, not a register. Every path into the book passes "
        "through one CheckEngine."
    ),
)

# CORS (P0-03). Explicit allow-list — a wildcard is refused above.
# Credentials are enabled because the frontend sends the bearer token
# in the Authorization header; a preflight without allow_credentials
# would drop it.
_allowed_origins = config.cors_origins()
if "*" in _allowed_origins:
    raise RuntimeError(
        "TREASURY_CORS_ORIGINS contains '*' but this app allows credentials. "
        "Pick explicit origins."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    expose_headers=["X-Rows-Matching", "X-Rows-Exported", "X-Request-Id"],
    max_age=600,
)

# Runs after CORS (Starlette executes middleware LIFO on request) so
# preflights still short-circuit; on the request itself this is first
# and binds request_id + tenant_id into the log context (S9).
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(TreasuryError)
def handle_treasury_error(_request: Request, exc: TreasuryError) -> JSONResponse:
    """One handler. A service raises a code and never chooses a status."""
    return JSONResponse(status_code=exc.status, content=exc.body())


@app.exception_handler(RequestValidationError)
def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic's 422, reshaped into the standard error body.

    Two shapes of error would mean two shapes of error handling in the client,
    and the client would get one of them wrong.
    """
    first = exc.errors()[0] if exc.errors() else {}
    location = [part for part in first.get("loc", ()) if part != "body"]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": first.get("msg", "That request could not be read."),
                "field": ".".join(str(part) for part in location) or None,
            }
        },
    )


for router in (
    auth.router,
    state.router,
    deals.router,
    confirmations.router,
    accounting.router,
    counterparties.router,
    control.router,
    advisory.router,
    currency.router,
    fx.router,
    jobs.router,
    scenarios.router,
    planner.router,
    performance.router,
    rates.router,
    system_policy.router,
    admin.router,
    admin_mfa.router,
    admin_users.router,
    activation.router,
    compliance.router,
    approvals.router,
    mfa.router,
):
    app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "server": "api"}
