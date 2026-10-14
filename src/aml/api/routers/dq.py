"""Data quality endpoints: the results of a run and the trend of the rules (read-only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.paging import resolve_limit
from aml.api.reads.dq import dq_results, dq_trend
from aml.common.config import Settings
from aml.common.db import Database

FEATURE = "dq"
router = APIRouter(prefix=f"{API_PREFIX}/dq")


@router.get("/results")
def get_results(
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
    run_id: int | None = None,
) -> JSONResponse:
    rows, meta = dq_results(db, run_id)
    return envelope.live(FEATURE, rows, **meta)


@router.get("/trend")
def get_trend(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
    rule_id: str | None = None,
    runs: Annotated[int | None, Query()] = None,
) -> JSONResponse:
    rows, meta = dq_trend(db, rule_id=rule_id, runs=resolve_limit(settings, runs, name="runs"))
    return envelope.live(FEATURE, rows, **meta)
