"""Memo endpoints: the labels in force and a person's relabel of one memo key."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, field_validator

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.errors import ApiError
from aml.api.identity import User
from aml.api.memos import record_memo_relabel
from aml.api.paging import check_offset, resolve_limit
from aml.api.reads.memos import list_memo_labels
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.classify import CATEGORIES
from aml.memo.relabel import MAX_REASON, METHODS

FEATURE = "memos"
router = APIRouter(prefix=f"{API_PREFIX}/memos")


class RelabelBody(BaseModel):
    """No ``actor`` field: the actor is always the user of the request."""

    model_config = ConfigDict(extra="forbid")

    category: str
    reason: str

    @field_validator("category")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in CATEGORIES:
            raise ValueError(f"must be one of {', '.join(CATEGORIES)}")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        if len(value) > MAX_REASON:
            raise ValueError(f"must be at most {MAX_REASON} characters")
        return value


def _one_of(name: str, value: str | None, allowed: tuple[str, ...]) -> None:
    if value is not None and value not in allowed:
        raise ApiError(422, "invalid_request", f"{name} must be one of {', '.join(allowed)}")


@router.get("")
def get_memos(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
    category: str | None = None,
    method: str | None = None,
    limit: Annotated[int | None, Query()] = None,
    offset: Annotated[int, Query()] = 0,
) -> JSONResponse:
    _one_of("category", category, tuple(CATEGORIES))
    _one_of("method", method, tuple(METHODS))
    limit = resolve_limit(settings, limit)
    check_offset(offset)
    rows, meta = list_memo_labels(
        db, settings, category=category, method=method, limit=limit, offset=offset
    )
    return envelope.live(FEATURE, rows, **meta)


@router.post("/{memo_key}/relabel")
def post_relabel(
    memo_key: str,
    body: RelabelBody,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    relabel = record_memo_relabel(db, settings, user, memo_key, body.category, body.reason)
    return envelope.live(FEATURE, asdict(relabel), status=201)
