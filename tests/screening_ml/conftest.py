"""Fixtures for the Phase 7b-ii tests (specs/screening-ml.md): TINY-S, a screened TINY DuckDB."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from aml.common.db import DuckDb
from aml.datagen.load import load_parquet
from aml.screening.runner import run_screening
from tests.datagen.conftest import tiny_env, tiny_parquet, tiny_settings

from .helpers import AS_OF, settings_with

__all__ = ["make_tiny_s", "tiny_env", "tiny_loaded", "tiny_parquet", "tiny_s", "tiny_settings"]


@pytest.fixture(scope="module")
def tiny_loaded_path(tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """TINY loaded into DuckDB, not screened yet (read-only template)."""
    path = tmp_path_factory.mktemp("scrml_loaded") / "loaded.duckdb"
    with DuckDb(path) as db:
        load_parquet(db, tiny_parquet)
    return path


@pytest.fixture(scope="module")
def tiny_s_path(tiny_loaded_path: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """TINY-S: TINY loaded and screened, run 1 (55 pairs). Read-only template."""
    path = tmp_path_factory.mktemp("scrml_s") / "tiny_s.duckdb"
    shutil.copy(tiny_loaded_path, path)
    with DuckDb(path) as db:
        run_screening(db, settings_with(), as_of=AS_OF)
    return path


@pytest.fixture
def make_tiny_s(tiny_s_path: Path, tmp_path: Path) -> Iterator[Callable[[], DuckDb]]:
    """Factory of independent writable copies of TINY-S (all closed at the end)."""
    opened: list[DuckDb] = []

    def make() -> DuckDb:
        target = tmp_path / f"copy{len(opened)}.duckdb"
        shutil.copy(tiny_s_path, target)
        opened.append(DuckDb(target))
        return opened[-1]

    yield make
    for db in opened:
        db.close()


@pytest.fixture
def tiny_s(make_tiny_s: Callable[[], DuckDb]) -> DuckDb:
    return make_tiny_s()


@pytest.fixture
def tiny_loaded(tiny_loaded_path: Path, tmp_path: Path) -> Iterator[DuckDb]:
    """TINY loaded but not screened."""
    target = tmp_path / "loaded.duckdb"
    shutil.copy(tiny_loaded_path, target)
    db = DuckDb(target)
    yield db
    db.close()
