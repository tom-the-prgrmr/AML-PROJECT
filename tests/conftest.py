"""Shared fixtures. Tests marked ``oracle`` / ``neo4j`` / ``ollama`` skip with a clear
message when the service is not running, so ``pytest`` is always green in DuckDB-only mode."""

from __future__ import annotations

from pathlib import Path

import pytest

from aml.common.db import DuckDb
from aml.common.services import neo4j_status, ollama_status, oracle_status

_CHECKS = {"oracle": oracle_status, "neo4j": neo4j_status, "ollama": ollama_status}
_status_cache: dict[str, tuple[bool, str]] = {}


def pytest_runtest_setup(item: pytest.Item) -> None:
    for marker, check in _CHECKS.items():
        if item.get_closest_marker(marker):
            if marker not in _status_cache:
                st = check()
                _status_cache[marker] = (st.up, st.detail)
            up, detail = _status_cache[marker]
            if not up:
                pytest.skip(f"{marker} not available: {detail}")


@pytest.fixture
def duck(tmp_path: Path) -> DuckDb:
    db = DuckDb(tmp_path / "test.duckdb")
    yield db
    db.close()
