"""Shared fixtures for the 1c tests (specs/datagen-watchlist-output.md): the TINY profile."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings, load_settings

TABLES = [
    "customers",
    "customer_person",
    "admin_unit_mapping",
    "accounts",
    "transactions",
    "ground_truth",
    "dq_labels",
    "watchlist",
    "watchlist_alias",
]

EnvFactory = Callable[..., dict[str, str]]


@pytest.fixture
def tiny_env(tmp_path: Path) -> EnvFactory:
    """Build the TINY env-override dict (300 customers, 5000 txns, 6 months, 200 entries)."""

    def make(
        seed: int = 42, profile: str = "small", out_name: str = "parquet", **extra: str
    ) -> dict[str, str]:
        env = {
            "DB_BACKEND": "duckdb",
            "AML__SEED": str(seed),
            "AML__DATA__PROFILE": profile,
            "AML__DATA__OUTPUT_DIR": str(tmp_path / out_name),
            "AML__DB__DUCKDB_PATH": str(tmp_path / "tiny.duckdb"),
            "AML__DATA__INJECTION_MEMOS": "6",
            "AML__DATA__WATCHLIST__ENTRIES": "200",
            "AML__DATA__WATCHLIST__TRUE_HITS": "5",
            "AML__DATA__WATCHLIST__TRAPS": "6",
        }
        for name in ("SMALL", "DENSE", "LARGE"):
            env[f"AML__DATA__PROFILES__{name}__CUSTOMERS"] = "300"
            env[f"AML__DATA__PROFILES__{name}__TRANSACTIONS"] = "5000"
            env[f"AML__DATA__PROFILES__{name}__MONTHS"] = "6"
            env[f"AML__DATA__PROFILES__{name}__TYPOLOGY_SCALE"] = "1"
        # dense keeps 50-100 counterparties: 300 accounts x >=50 needs >=7500 two-sided txns
        env["AML__DATA__PROFILES__DENSE__TRANSACTIONS"] = "20000"
        for typology, count in {
            "STRUCTURING": 2,
            "RAPID_MOVEMENT": 2,
            "MULE_RING": 1,
            "ROUND_TRIPPING": 2,
            "BENIGN_PAYROLL": 1,
            "BENIGN_MERCHANT": 1,
        }.items():
            env[f"AML__DATA__TYPOLOGIES__{typology}"] = str(count)
        env.update(extra)
        return env

    return make


@pytest.fixture
def tiny_settings(tiny_env: EnvFactory) -> Settings:
    return load_settings(environ=tiny_env())


@pytest.fixture(scope="module")
def tiny_parquet(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A Parquet directory produced by ``run_pipeline`` on TINY (read-only for tests)."""
    root = tmp_path_factory.mktemp("tiny_pq")
    env = {
        "DB_BACKEND": "duckdb",
        "AML__SEED": "42",
        "AML__DATA__INJECTION_MEMOS": "6",
        "AML__DATA__WATCHLIST__ENTRIES": "200",
        "AML__DATA__WATCHLIST__TRUE_HITS": "5",
        "AML__DATA__WATCHLIST__TRAPS": "6",
        "AML__DATA__PROFILES__SMALL__CUSTOMERS": "300",
        "AML__DATA__PROFILES__SMALL__TRANSACTIONS": "5000",
        "AML__DATA__PROFILES__SMALL__MONTHS": "6",
        "AML__DATA__TYPOLOGIES__STRUCTURING": "2",
        "AML__DATA__TYPOLOGIES__RAPID_MOVEMENT": "2",
        "AML__DATA__TYPOLOGIES__MULE_RING": "1",
        "AML__DATA__TYPOLOGIES__ROUND_TRIPPING": "2",
        "AML__DATA__TYPOLOGIES__BENIGN_PAYROLL": "1",
        "AML__DATA__TYPOLOGIES__BENIGN_MERCHANT": "1",
    }
    settings = load_settings(environ=env)
    pipeline: Any = importlib.import_module("aml.datagen.pipeline")
    out = root / "pq"
    pipeline.run_pipeline(settings, out)
    return out
