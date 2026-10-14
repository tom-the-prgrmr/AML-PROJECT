"""Benchmark endpoint: the stored result files of ``aml bench`` (read-only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from aml.api import envelope
from aml.api.constants import API_PREFIX
from aml.api.deps import current_user, get_app_settings
from aml.api.identity import User
from aml.api.reads.benchmark import benchmark
from aml.common.config import Settings

FEATURE = "benchmark"
router = APIRouter(prefix=API_PREFIX)


@router.get("/benchmark")
def get_benchmark(
    settings: Annotated[Settings, Depends(get_app_settings)],
    _user: Annotated[User, Depends(current_user)],
) -> JSONResponse:
    data = benchmark(settings)
    return envelope.live(FEATURE, data, files=len(data["runs"]))
