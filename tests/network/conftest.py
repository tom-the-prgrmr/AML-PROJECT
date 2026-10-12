"""Fixtures for the Phase 5c tests (specs/network-detections.md)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from aml.common.db import DuckDb
from tests.dba.conftest import tiny_env, tiny_parquet, tiny_settings

from .helpers import duck_settings, load_cyc, load_hub, load_shr, load_tiny_duck, run_er

__all__ = ["tiny_env", "tiny_parquet", "tiny_settings"]

# TINY is deterministic (seed 42): load + ER is done once per pytest session and copied.
_ER_TEMPLATE: dict[str, Path] = {}


@pytest.fixture
def shr(duck: DuckDb) -> DuckDb:
    """MINI-SHR of the spec."""
    load_shr(duck)
    return duck


@pytest.fixture
def cyc(duck: DuckDb) -> DuckDb:
    """MINI-CYC of the spec."""
    load_cyc(duck)
    return duck


@pytest.fixture
def hub(duck: DuckDb) -> DuckDb:
    """MINI-HUB of the spec."""
    load_hub(duck)
    return duck


@pytest.fixture(scope="module")
def er_template(tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A DuckDB file holding TINY after `load_parquet` and `run_er` (never modified by tests)."""
    if "path" not in _ER_TEMPLATE:
        path = tmp_path_factory.mktemp("net_er_template") / "tiny_er.duckdb"
        db = load_tiny_duck(tiny_parquet, path)
        try:
            run_er(db, duck_settings())
        finally:
            db.close()
        _ER_TEMPLATE["path"] = path
    return _ER_TEMPLATE["path"]


@pytest.fixture
def tiny_er(er_template: Path, tmp_path: Path) -> Iterator[DuckDb]:
    """A private writable copy of the TINY + ER database."""
    target = tmp_path / "tiny.duckdb"
    shutil.copy(er_template, target)
    db = DuckDb(target)
    yield db
    db.close()
