"""The real application.

Middleware, exception handlers and the ten routers of document 2 section 9.

Phase zero builds the shell and the handlers. The routers are empty and are
filled group by group in phase one, replacing the mock one group at a time.
While a group is empty the frontend keeps reading the mock for it, which is
why the two must return identical shapes.

    uvicorn app.main:app --port 8000 --reload
"""

from fastapi import FastAPI, Request

# Imported first so a .env file is read before anything looks at the
# environment for a signing key or a model.
from app import config  # noqa: F401
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import (
    accounting,
    auth,
    admin,
    advisory,
    confirmations,
    control,
    counterparties,
    currency,
    deals,
    jobs,
    state,
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
    jobs.router,
    admin.router,
):
    app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "server": "api"}
