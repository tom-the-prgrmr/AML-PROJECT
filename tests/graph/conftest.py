"""Fixtures for the Phase 5b tests (specs/fund-flow-trace.md)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from aml.common.config import Settings, load_settings
from aml.common.db import DuckDb
from tests.dba.conftest import tiny_env, tiny_parquet, tiny_settings

from .helpers import load_mini

__all__ = ["mini", "settings", "tiny_env", "tiny_parquet", "tiny_settings"]


@pytest.fixture
def settings() -> Settings:
    return load_settings(environ={})


@pytest.fixture
def mini(duck: DuckDb) -> Iterator[DuckDb]:
    """MINI of the spec: empty DuckDB after apply_schema + 14 transactions + acct_edge_daily."""
    load_mini(duck)
    yield duck
