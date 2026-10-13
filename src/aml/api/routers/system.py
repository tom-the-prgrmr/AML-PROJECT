"""System endpoints: health (no database, no identity), status and the current user."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.constants import API_PREFIX, API_VERSION
from aml.api.deps import current_user, get_app_settings, get_database
from aml.api.identity import User
from aml.api.reads.cases import latest_run
from aml.common.config import Settings
from aml.common.db import Database

router = APIRouter(prefix=API_PREFIX)


@router.get("/health")
def health(settings: Annotated[Settings, Depends(get_app_settings)]) -> JSONResponse:
    data = {"status": "ok", "backend": settings.db.backend, "version": API_VERSION}
    return envelope.live("health", data)


@router.get("/status")
def status(
    settings: Annotated[Settings, Depends(get_app_settings)],
    db: Annotated[Database, Depends(get_database)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data = {
        "backend": settings.db.backend,
        "profile": settings.data.profile,
        "seed": settings.seed,
        "reference_date": settings.data.reference_date.isoformat(),
        "mock": settings.ui.mock.model_dump(),
        "case_run": latest_run(db),
    }
    return envelope.live("status", data)


@router.get("/me")
def me(
    settings: Annotated[Settings, Depends(get_app_settings)],
    user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    users = [{"actor": actor, "role": role} for actor, role in sorted(settings.ui.users.items())]
    data = {"actor": user.actor, "role": user.role, "pii": user.pii, "users": users}
    return envelope.live("identity", data)
