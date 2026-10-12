"""AC1 for specs/entity-resolution.md: config keys, dependency, DDL and the er_* objects."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, sql_file

from .helpers import mod

SCRIPT = "ddl/100_entity_resolution.sql"
OBJECTS = (
    "er_runs",
    "er_model",
    "er_pairs",
    "er_golden",
    "customer_golden",
    "er_cluster_weights",
)
EXPECTED_M = {
    "name": [0.6, 0.25, 0.1, 0.05],
    "dob": [0.97, 0.03],
    "phone": [0.9, 0.1],
    "email": [0.45, 0.55],
    "address": [0.85, 0.1, 0.05],
    "id": [0.98, 0.02],
}


def test_ac1_entity_resolution_config_defaults() -> None:
    cfg = load_settings(environ={}).entity_resolution
    assert cfg.match_threshold == 0.95
    assert cfg.review_threshold == 0.5
    assert tuple(cfg.name_jw_thresholds) == (0.92, 0.8)
    assert cfg.deterministic_recall == 0.9
    assert cfg.u_max_pairs == 1000000
    assert cfg.m_probabilities == EXPECTED_M


def test_ac1_review_threshold_must_not_exceed_match_threshold() -> None:
    with pytest.raises(ValidationError, match="review_threshold must not exceed match_threshold"):
        load_settings(environ={"AML__ENTITY_RESOLUTION__REVIEW_THRESHOLD": "0.99"})


def test_ac1_m_probabilities_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match=r"m_probabilities\.dob must sum to 1\.0"):
        load_settings(environ={"AML__ENTITY_RESOLUTION__M_PROBABILITIES__DOB": "[0.9, 0.2]"})


def test_ac1_splink_5_installed_and_declared() -> None:
    import splink

    assert splink.__version__.startswith("5.")
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    deps = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    assert "splink>=5.0,<6" in [d.replace(" ", "") for d in deps]


def test_ac1_script_registered_and_resolves_per_backend() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    assert SCRIPT in scripts["duckdb"]
    assert SCRIPT in scripts["oracle"]
    assert scripts["oracle"].index(SCRIPT) < scripts["oracle"].index("ddl/050_security_objects.sql")
    assert scripts["duckdb"].index(SCRIPT) < scripts["duckdb"].index("ddl/050_customers_masked.sql")
    for backend in ("duckdb", "oracle"):
        assert sql_file(SCRIPT, backend) == SQL_ROOT / backend / SCRIPT


def test_ac1_apply_schema_twice_creates_empty_objects(duck: DuckDb) -> None:
    apply_schema = mod("aml.dba.schema").apply_schema
    apply_schema(duck)
    apply_schema(duck)
    for name in OBJECTS:
        assert int(duck.query_df(f"SELECT COUNT(*) FROM {name}").iloc[0, 0]) == 0, name
