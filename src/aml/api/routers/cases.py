"""Case endpoints: the queue, the subjects of a case (PII masked by role) and its disposition."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.decisions import pii_viewed, record_case_decision
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.paging import check_offset, resolve_limit
from aml.api.reads.cases import case_detail, case_subjects, case_transactions, list_cases
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
    limit = resolve_limit(settings, limit)
    check_offset(offset)
    rows, meta = list_cases(db, status=status, limit=limit, offset=offset)
    return envelope.live(FEATURE, rows, **meta)


@router.get("/{case_id}")
def get_case(
    case_id: str,
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    return envelope.live(FEATURE, case_detail(db, case_id))


@router.get("/{case_id}/transactions")
def get_transactions(
    case_id: str,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
    limit: Annotated[int | None, Query()] = None,
    offset: Annotated[int, Query()] = 0,
) -> JSONResponse:
    limit = resolve_limit(settings, limit)
    check_offset(offset)
    rows, total = case_transactions(
        db, case_id, masked=user.pii == "masked", limit=limit, offset=offset
    )
    if user.pii == "full" and rows:
        pii_viewed(
            db,
            user,
            entity_type="case",
            entity_id=case_id,
            what=f"transaction data of case {case_id}",
            details={"transactions": len(rows)},
        )
    return envelope.live(FEATURE, rows, pii=user.pii, total=total, limit=limit, offset=offset)


@router.get("/{case_id}/subjects")
def get_subjects(
    case_id: str,
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    subjects = case_subjects(db, case_id, masked=user.pii == "masked")
    if user.pii == "full":
        pii_viewed(
            db,
            user,
            entity_type="case",
            entity_id=case_id,
            what=f"subject data of case {case_id}",
            details={"cifs": [str(s["cif"]) for s in subjects]},
        )
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
