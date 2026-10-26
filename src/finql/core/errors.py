"""Domain exceptions and one error format for every failing response.

    {"error": {"code": "forbidden", "message": "…", "request_id": "…", "details": null}}

Clients branch on `code` (stable, English); `message` is for people (Hungarian).
"""

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from finql.core.logging import REQUEST_ID_HEADER, current_request_id

logger = structlog.get_logger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Váratlan hiba történt."

    def __init__(self, message: str | None = None, *, headers: dict[str, str] | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message
        self.headers = headers


class NotAuthenticatedError(AppError):
    status_code = 401
    code = "not_authenticated"
    message = "Bejelentkezés szükséges."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    message = "Ehhez a művelethez nincs jogosultságod."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Nem található."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Ütközés egy meglévő adattal."


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# Framework-raised HTTP errors (unknown route, wrong method): stable code + Hungarian message.
HTTP_ERRORS = {
    400: ("bad_request", "Hibás kérés."),
    401: ("not_authenticated", "Bejelentkezés szükséges."),
    403: ("forbidden", "Ehhez a művelethez nincs jogosultságod."),
    404: ("not_found", "Nem található."),
    405: ("method_not_allowed", "Ez a HTTP-metódus itt nem engedélyezett."),
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = current_request_id()
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=details)
    )
    all_headers = dict(headers or {})
    if request_id:
        # The 500 handler runs outside the request middleware, so add the header here too.
        all_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(body.model_dump(), status_code=status_code, headers=all_headers)


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(exc.status_code, exc.code, exc.message, headers=exc.headers)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, message = HTTP_ERRORS.get(exc.status_code, ("http_error", str(exc.detail)))
    headers = dict(exc.headers) if exc.headers else None
    return error_response(exc.status_code, code, message, headers=headers)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # The submitted value ("input") is left out on purpose: it may be a password.
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return error_response(422, "validation_error", "Érvénytelen kérés.", details=details)


async def _unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error", exc_info=exc)
    return error_response(500, AppError.code, AppError.message)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
