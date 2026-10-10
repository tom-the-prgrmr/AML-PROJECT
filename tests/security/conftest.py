"""Fixtures for the Phase 2b tests. Oracle fixtures skip when a secret is missing."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from aml.common.config import Settings
from aml.common.db import OracleDb
from tests.datagen.conftest import tiny_env, tiny_parquet

from .helpers import base_env, mod, owner_settings

__all__ = ["tiny_env", "tiny_parquet"]


@pytest.fixture(scope="module")
def oracle_settings() -> Settings:
    env = base_env()
    for name in ("ORACLE_SYS_PASSWORD", "ORACLE_DEMO_PASSWORD"):
        if not env.get(name):
            pytest.skip(f"{name} is not set in .env")
    return owner_settings()


@pytest.fixture(scope="module")
def secured(oracle_settings: Settings, tiny_parquet: Path) -> Iterator[Settings]:
    """TINY loaded into Oracle, then roles/grants/policies (re)applied."""
    with OracleDb(oracle_settings) as db:
        mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    mod("aml.dba.security").apply_security(oracle_settings)
    yield oracle_settings
