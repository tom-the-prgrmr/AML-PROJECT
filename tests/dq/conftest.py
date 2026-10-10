"""Fixtures for the Phase 2c-ii tests (specs/dq-framework.md): TINY and the MINI data set."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb
from tests.dba.conftest import audit_rows, tiny_env, tiny_parquet, tiny_settings

from .helpers import duck_settings, mod

__all__ = ["audit_rows", "tiny_env", "tiny_parquet", "tiny_run", "tiny_settings"]


@pytest.fixture
def dq_settings() -> Settings:
    return duck_settings()


@pytest.fixture(scope="module")
def tiny_run(
    tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[DuckDb, Settings, Any]]:
    """TINY loaded into a fresh DuckDB with one ``run_dq`` already done: (db, settings, run)."""
    db = DuckDb(tmp_path_factory.mktemp("dq_tiny") / "tiny.duckdb")
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    settings = duck_settings()
    run = mod("aml.dq.runner").run_dq(db, settings)
    yield db, settings, run
    db.close()
