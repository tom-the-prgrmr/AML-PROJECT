"""The FastAPI app of the investigator UI: JSON under ``/api/v1``, the built SPA elsewhere."""

from __future__ import annotations

from fastapi import FastAPI

from aml.api.constants import API_PREFIX, API_VERSION
from aml.api.errors import install_error_handlers
from aml.api.routers import (
    assistant,
    benchmark,
    case_insights,
    cases,
    dq,
    graph,
    memos,
    metrics,
    sample,
    screening,
    system,
    trace,
)
from aml.common.config import Settings, get_settings
from aml.common.db import Database

__all__ = ["API_PREFIX", "API_VERSION", "create_app"]


def create_app(settings: Settings | None = None, *, db: Database | None = None) -> FastAPI:
    """Build the app. ``db=None``: each request opens ``get_db(settings)`` and closes it.

    A given ``db`` (tests) is shared by all requests and never closed. No docs or OpenAPI routes:
    the only routes under ``/api/v1`` are the ones the UI uses.
    """
    app = FastAPI(title="AML investigation UI", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings or get_settings()
    app.state.db = db
    install_error_handlers(app)
    for router in (
        system.router,
        case_insights.router,  # before cases: /cases/scores is not a case id
        cases.router,
        memos.router,
        graph.router,
        trace.router,
        screening.router,
        dq.router,
        benchmark.router,
        sample.router,
        assistant.router,
        metrics.router,
    ):
        # Not include_router: newer FastAPI wraps an included router in a lazy node, and the
        # routes must be plain top-level entries with their full /api/v1 paths.
        app.router.routes.extend(router.routes)
    return app
