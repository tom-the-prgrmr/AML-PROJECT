"""The neutral mock feature that proves the sample-data mechanism (see ``aml.api.mock``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings
from aml.api.identity import User
from aml.api.mock import mock_or_live
from aml.common.config import Settings

router = APIRouter(prefix=API_PREFIX)


@router.get("/sample")
def sample(
    settings: Annotated[Settings, Depends(get_app_settings)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    return mock_or_live(settings, "sample", None)  # no real implementation exists
