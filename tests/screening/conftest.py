"""Fixtures for the Phase 3a tests (specs/screening-normalize-score.md)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.dba.conftest import tiny_env, tiny_parquet, tiny_settings

from .helpers import base_stats, screening_cfg

__all__ = ["base_stats_fixture", "cfg", "tiny_env", "tiny_parquet", "tiny_settings"]


@pytest.fixture
def cfg() -> Any:
    """``settings.screening`` of the default config.yaml."""
    return screening_cfg()


@pytest.fixture
def base_stats_fixture(cfg: Any) -> Any:
    return base_stats(cfg)
