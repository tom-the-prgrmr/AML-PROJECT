"""Priority scores of the queue and the stored case summary (Phase 9c).

Registered before ``routers/cases.py``: ``/cases/scores`` must not be read as a case id.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.assistant import case_summary
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.reads.scores import case_scores
from aml.common.config import Settings
from aml.common.db import Database

router = APIRouter(prefix=f"{API_PREFIX}/cases")


@router.get("/scores")
def get_scores(
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    return envelope.live("case_scores", case_scores(db))


@router.get("/{case_id}/summary")
def get_summary(
    case_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
    language: str | None = None,
) -> JSONResponse:
    return envelope.live(
        "case_summary", case_summary(db, settings, case_id, language), pii="masked"
    )
