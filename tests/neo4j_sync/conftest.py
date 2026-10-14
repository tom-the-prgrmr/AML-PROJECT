"""Fixtures for the Phase 6a tests (specs/neo4j-sync.md)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb
from tests.network.conftest import er_template, tiny_env, tiny_er, tiny_parquet, tiny_settings

from .helpers import client, load_mini_g, neo_settings

__all__ = ["er_template", "tiny_env", "tiny_er", "tiny_parquet", "tiny_settings"]


@pytest.fixture
def mini(duck: DuckDb) -> DuckDb:
    """MINI-G of the spec (DuckDB)."""
    load_mini_g(duck)
    return duck


class Neo:
    """A driver plus the settings it was opened with, on a wiped projection."""

    def __init__(self, driver: Any, settings: Settings) -> None:
        self.driver = driver
        self.settings = settings


@pytest.fixture
def neo() -> Iterator[Neo]:
    """[neo4j] a driver on the dev Neo4j after `sync/wipe.cypher` (spec Q21)."""
    settings = neo_settings()
    driver = client().open_driver(settings)
    try:
        client().run_write_file(driver, settings, "knowledge/wipe.cypher")
        client().run_write_file(driver, settings, "sync/wipe.cypher")
        yield Neo(driver, settings)
    finally:
        driver.close()
