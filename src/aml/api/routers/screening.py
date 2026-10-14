"""Screening endpoints: the current hits (PII masked by role) and a human review of one hit."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.decisions import pii_viewed
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.paging import check_offset, resolve_limit
from aml.api.reads.screening import list_hits
from aml.api.reviews import record_hit_review
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.review import REVIEW_DECISIONS

FEATURE = "screening"
router = APIRouter(prefix=f"{API_PREFIX}/screening")


class ReviewBody(BaseModel):
    """No ``actor`` field: the actor is always the user of the request."""

    model_config = ConfigDict(extra="forbid")

    decision: str
    reason: str

    @field_validator("decision")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in REVIEW_DECISIONS:
            raise ValueError(f"must be one of {', '.join(REVIEW_DECISIONS)}")
        return value

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@router.get("/hits")
def get_hits(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
    decision: Literal["ALERT", "REVIEW", "AUTO_CLEARED"] | None = None,
    limit: Annotated[int | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    limit = resolve_limit(settings, limit)
    check_offset(offset)
    rows, meta = list_hits(
        db, settings, decision=decision, limit=limit, offset=offset, masked=user.pii == "masked"
    )
    if user.pii == "full" and rows:
        cifs = sorted({str(h["cif"]) for h in rows})
        pii_viewed(
            db,
            user,
            entity_type="screening",
            entity_id="hits",
            what="screening hits",
            details={"cifs": cifs},
        )
    return envelope.live(FEATURE, rows, pii=user.pii, **meta)


@router.post("/hits/{cif}/{entry_id}/review")
def post_review(
    cif: str,
    entry_id: str,
    body: ReviewBody,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    review = record_hit_review(db, settings, user, cif, entry_id, body.decision, body.reason)
    data = {
        "cif": review.cif,
        "entry_id": review.entry_id,
        "decision": review.decision,
        "reason": review.reason,
        "actor": review.actor,
        "decided_on": review.decided_on.isoformat(),
        "run_id": review.run_id,
        "system_decision": review.system_decision,
    }
    return envelope.live(FEATURE, data, status=201)
