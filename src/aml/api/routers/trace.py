"""Fund-flow trace endpoints: which methods can run, and the trace itself."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.reads.trace import methods_meta, run_trace
from aml.common.config import Settings
from aml.common.db import Database
from aml.graph.availability import trace_methods

FEATURE = "trace"
router = APIRouter(prefix=API_PREFIX)


@router.get("/trace/methods")
def get_trace_methods(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data = [asdict(m) for m in trace_methods(db, settings)]
    return envelope.live(FEATURE, data, **methods_meta(db, settings))


@router.get("/accounts/{account_id}/trace")
def get_trace(
    account_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
    method: str = "cte_raw",
    hops: int | None = None,
    hours: int | None = None,
    since: datetime | None = None,
    min_amount_vnd: int | None = None,
    top_k: int | None = None,
    limit: int | None = None,
    offset: Annotated[int, Query()] = 0,
) -> JSONResponse:
    rows, meta = run_trace(
        db,
        settings,
        account_id,
        actor=user.actor,
        method=method,
        hops=hops,
        hours=hours,
        since=since,
        min_amount_vnd=min_amount_vnd,
        top_k=top_k,
        limit=limit,
        offset=offset,
    )
    return envelope.live(FEATURE, rows, **meta)
