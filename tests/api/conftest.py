"""Fixtures for the Phase 9a tests (specs/ui-foundation.md): SCHEMA, API-MINI, ``client``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from aml.common.db import DuckDb
from tests.cases.helpers import load_minic

from .helpers import api_settings, make_client, mod


@pytest.fixture
def schema(duck: DuckDb) -> DuckDb:
    """SCHEMA: ``duck`` after ``apply_schema`` (no case run yet)."""
    mod("aml.dba.schema").apply_schema(duck)
    return duck


@pytest.fixture
def api_mini(duck: DuckDb) -> DuckDb:
    """API-MINI: MINI-C then ``run_cases`` (run 1, as_of 2026-06-30)."""
    load_minic(duck)
    mod("aml.cases.runner").run_cases(duck, api_settings())
    return duck


@pytest.fixture
def client(duck: DuckDb) -> Callable[..., Any]:
    """``client(user=None, **env)``: a TestClient over ``create_app(settings, db=duck)``."""

    def make(user: str | None = None, **env: str) -> Any:
        return make_client(duck, api_settings(**env), user)

    return make
