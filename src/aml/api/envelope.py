"""The success envelope: ``{source, feature, data, meta}`` plus the ``X-AML-Source`` header.

One response is one feature from one source. A mock response also says so in ``meta.mock``.
"""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

LIVE, MOCK = "live", "mock"
SOURCE_HEADER = "X-AML-Source"
MOCK_NOTICE = "Sample data - not a measured result"


def _respond(
    source: str, feature: str, data: Any, status: int, meta: dict[str, Any]
) -> JSONResponse:
    body = {"source": source, "feature": feature, "data": data, "meta": meta}
    return JSONResponse(body, status_code=status, headers={SOURCE_HEADER: source})


def live(feature: str, data: Any, *, status: int = 200, **meta: Any) -> JSONResponse:
    """Data that was read from the database or computed by a real module."""
    return _respond(LIVE, feature, data, status, meta)


def mock(feature: str, data: Any, *, fixture: str, **meta: Any) -> JSONResponse:
    """Sample data, labelled as such in the body and in the header."""
    meta["mock"] = {"fixture": fixture, "notice": MOCK_NOTICE}
    return _respond(MOCK, feature, data, 200, meta)
