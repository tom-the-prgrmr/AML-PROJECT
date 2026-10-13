"""Fixtures for the Phase 7a tests (specs/case-consolidation.md): MINI-C and TINY stages."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.db import DuckDb
from tests.dba.conftest import tiny_env, tiny_parquet, tiny_settings

from .helpers import duck_settings, load_minic, load_tiny_duck, mod

__all__ = ["tiny_env", "tiny_parquet", "tiny_settings"]

# TINY is deterministic (seed 42): each stage is built once per pytest session and copied.
_STAGES: dict[str, Path] = {}


def _snapshot(db: DuckDb, root: Path, name: str) -> DuckDb:
    """Close ``db``, keep a copy named ``name`` and reopen it (a file copy needs a closed db)."""
    path = db.path
    db.close()
    shutil.copy(path, root / f"{name}.duckdb")
    _STAGES[name] = root / f"{name}.duckdb"
    return DuckDb(path)


@pytest.fixture(scope="module")
def tiny_stages(tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """DuckDB files of TINY after `load`, `er`, the three alert sources, and `dq` (read-only)."""
    if "full" not in _STAGES:
        root = tmp_path_factory.mktemp("cases_tiny")
        settings = duck_settings()
        db = load_tiny_duck(tiny_parquet, root / "work.duckdb")
        try:
            db = _snapshot(db, root, "load")
            mod("aml.entity_resolution.runner").run_er(db, settings)
            db = _snapshot(db, root, "er")
            mod("aml.screening.runner").run_screening(db, settings)
            mod("aml.monitoring.runner").run_monitoring(db, settings)
            mod("aml.graph.network.runner").run_network(db, settings)
            db = _snapshot(db, root, "sources")
            mod("aml.dq.runner").run_dq(db, settings)
            db = _snapshot(db, root, "full")
        finally:
            db.close()
    return dict(_STAGES)


@pytest.fixture
def minic(duck: DuckDb) -> DuckDb:
    """MINI-C of the spec."""
    load_minic(duck)
    return duck


@pytest.fixture
def tiny_cases(tiny_stages: dict[str, Path], tmp_path: Path) -> Iterator[DuckDb]:
    """A private writable copy of TINY after ER, screening, monitoring, network and DQ."""
    target = tmp_path / "tiny_cases.duckdb"
    shutil.copy(tiny_stages["full"], target)
    db = DuckDb(target)
    yield db
    db.close()


@pytest.fixture
def cli_db(
    tiny_stages: dict[str, Path],
    tiny_env: Callable[..., dict[str, str]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str], Path]:
    """``cli_db("sources")`` puts that TINY stage in place as the configured DuckDB."""
    from aml.common.config import get_settings

    def use(stage: str) -> Path:
        path = tmp_path / "tiny.duckdb"
        shutil.copy(tiny_stages[stage], path)
        env: dict[str, Any] = tiny_env()
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        return path

    return use
