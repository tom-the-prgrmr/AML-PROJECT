"""Fixtures for the Phase 2c-i tests (specs/oracle-retention.md)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import OracleDb
from tests.datagen.conftest import EnvFactory
from tests.dba.conftest import audit_rows, tiny_env

from .helpers import clean_rt, insert_rt_rows, mod

__all__ = ["audit_rows", "tiny_env"]


@pytest.fixture
def archive_dir(tmp_path: Path) -> Path:
    return tmp_path / "archive"


@pytest.fixture
def rt_settings(tiny_env: EnvFactory, archive_dir: Path) -> Settings:
    env = tiny_env(DB_BACKEND="oracle", AML__RETENTION__ARCHIVE_DIR=str(archive_dir))
    return load_settings(environ={**read_environ(), **env})


@pytest.fixture
def rt_db(rt_settings: Settings) -> Iterator[OracleDb]:
    """Oracle with the schema applied and exactly RT1, RT2, RT3 inserted; cleaned afterwards."""
    with OracleDb(rt_settings) as db:
        mod("aml.dba.schema").apply_schema(db)
        clean_rt(db)
        insert_rt_rows(db)
        try:
            yield db
        finally:
            clean_rt(db)
