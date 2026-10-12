"""Fixtures for the Phase 6b-i tests (specs/neo4j-queries.md).

Syncing Neo4j is the slow part, so every [neo4j] module builds its data set once with a
module-scoped fixture (see ``helpers.synced_db``). Modules run one after the other and each
wipes and re-syncs the projection, so no test may rely on what an earlier module left behind.
"""

from __future__ import annotations

import pytest

from aml.common.config import Settings, load_settings
from aml.common.db import DuckDb
from tests.neo4j_sync.conftest import (
    Neo,
    er_template,
    neo,
    tiny_env,
    tiny_er,
    tiny_parquet,
    tiny_settings,
)

from .helpers import OFFLINE_URI, load_mini_t

__all__ = [
    "Neo",
    "er_template",
    "neo",
    "tiny_env",
    "tiny_er",
    "tiny_parquet",
    "tiny_settings",
]


@pytest.fixture
def mini_t(duck: DuckDb) -> DuckDb:
    """MINI-T of the spec (DuckDB)."""
    load_mini_t(duck)
    return duck


@pytest.fixture
def offline() -> Settings:
    """DuckDB settings whose Neo4j URI points at a closed port."""
    return load_settings(environ={"DB_BACKEND": "duckdb", "AML__NEO4J__URI": OFFLINE_URI})
