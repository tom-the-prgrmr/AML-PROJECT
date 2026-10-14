"""The dashboard endpoints (Phase 9c): funnel, detections, below-the-line samples."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.errors import ApiError
from aml.api.identity import User
from aml.common.config import Settings
from aml.common.db import Database
from aml.metrics import auto_cleared_sample, detections, funnel, suppression

router = APIRouter(prefix=f"{API_PREFIX}/metrics")
Db = Annotated[Database, Depends(get_database)]
Cfg = Annotated[Settings, Depends(get_app_settings)]
Who = Annotated[User, Depends(current_user)]


def _size(request: Request, settings: Settings) -> int:
    """``?size=`` as an int in 1..max_sample_size; the default is ``metrics.sample_size``."""
    raw = request.query_params.get("size")
    if raw is None:
        return settings.metrics.sample_size
    limit = settings.metrics.max_sample_size
    try:
        size = int(raw)
    except ValueError:
        size = 0
    if not 1 <= size <= limit:
        raise ApiError(422, "invalid_request", f"size must be between 1 and {limit}")
    return size


@router.get("/funnel")
def get_funnel(db: Db, settings: Cfg, _user: Who) -> JSONResponse:
    return envelope.live("metrics_funnel", funnel(db, settings))


@router.get("/detections")
def get_detections(db: Db, settings: Cfg, _user: Who) -> JSONResponse:
    return envelope.live("metrics_detections", detections(db, settings))


@router.get("/below-the-line/auto-cleared")
def get_auto_cleared(request: Request, db: Db, settings: Cfg, _user: Who) -> JSONResponse:
    data = auto_cleared_sample(db, settings, size=_size(request, settings))
    return envelope.live("metrics_auto_cleared", data)


@router.get("/suppression")
def get_suppression(request: Request, db: Db, settings: Cfg, _user: Who) -> JSONResponse:
    data = suppression(db, settings, size=_size(request, settings))
    return envelope.live("metrics_suppression", data)
