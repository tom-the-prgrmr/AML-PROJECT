"""Case endpoints: the queue, the subjects of a case (PII masked by role) and its disposition."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.decisions import audit_pii_view, record_case_decision
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.errors import ApiError
from aml.api.identity import User
from aml.api.reads.cases import case_subjects, list_cases
from aml.cases.dispositions import DISPOSITIONS
from aml.common.config import Settings
from aml.common.db import Database

FEATURE = "cases"
router = APIRouter(prefix=f"{API_PREFIX}/cases")


class DispositionBody(BaseModel):
    """No ``actor`` field: the actor is always the user of the request."""

    model_config = ConfigDict(extra="forbid")

    disposition: str
    reason: str

    @field_validator("disposition")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in DISPOSITIONS:
            raise ValueError(f"must be one of {', '.join(DISPOSITIONS)}")
        return value

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@router.get("")
def get_cases(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
    status: Literal["OPEN", "REOPENED", "CLOSED"] | None = None,
    limit: Annotated[int | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> JSONResponse:
    limit = settings.ui.page_size if limit is None else limit
    if not 1 <= limit <= settings.ui.max_page_size:
        raise ApiError(
            422, "invalid_request", f"limit must be between 1 and {settings.ui.max_page_size}"
        )
    rows, meta = list_cases(db, status=status, limit=limit, offset=offset)
    return envelope.live(FEATURE, rows, **meta)


@router.get("/{case_id}/subjects")
def get_subjects(
    case_id: str,
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    subjects = case_subjects(db, case_id, masked=user.pii == "masked")
    if user.pii == "full":
        audit_pii_view(db, user, case_id, [str(s["cif"]) for s in subjects])
    return envelope.live(FEATURE, subjects, pii=user.pii)


@router.post("/{case_id}/disposition")
def post_disposition(
    case_id: str,
    body: DispositionBody,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    disposition_id = record_case_decision(
        db, settings, user, case_id, body.disposition, body.reason
    )
    data = {
        "disposition_id": disposition_id,
        "case_id": case_id,
        "disposition": body.disposition,
        "actor": user.actor,
        "decided_on": settings.data.reference_date.isoformat(),
    }
    return envelope.live(FEATURE, data, status=201)
