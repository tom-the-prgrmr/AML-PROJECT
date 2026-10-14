"""One error envelope for every failure: ``{"error": {"code", "message"}}``, no ``source``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from aml.api import static
from aml.common.db import ServiceUnavailableError

log = logging.getLogger(__name__)

HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


class ApiError(Exception):
    """A failure the caller should see: HTTP status, stable code, English message."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message}}, status_code=status, headers=headers
    )


def _api_error(_: Request, exc: ApiError) -> Response:
    return error_response(exc.status, exc.code, exc.message)


def _invalid_request(_: Request, exc: RequestValidationError) -> Response:
    # Name the field and the rule only: the input value may be PII or a reason text.
    problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return error_response(422, "invalid_request", "; ".join(problems))


def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
    """Routing failures. A 404 outside /api/ is a SPA route (or "not built"), never JSON data."""
    path = request.url.path
    is_api = path == "/api" or path.startswith("/api/")
    if exc.status_code == 404 and not is_api:
        root = static.dist_dir(request.app.state.settings)
        if root is None:
            return error_response(404, "not_found", static.NOT_BUILT)
        if request.method in ("GET", "HEAD"):
            page = static.spa_response(root, path)
            if page is not None:
                return page
            return error_response(404, "not_found", f"no such file: {path}")
    if exc.status_code == 404:
        return error_response(404, "not_found", f"no such endpoint: {path}")
    code = HTTP_CODES.get(exc.status_code, "http_error")
    return error_response(exc.status_code, code, str(exc.detail), dict(exc.headers or {}))


def _unavailable(_: Request, exc: ServiceUnavailableError) -> Response:
    return error_response(503, "unavailable", "service unavailable")


def _internal(_: Request, exc: Exception) -> Response:
    log.error("unhandled error in the API", exc_info=exc)
    return error_response(500, "internal_error", "internal error")  # never the SQL or the stack


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _invalid_request)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(ServiceUnavailableError, _unavailable)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _internal)
