"""AC1 for specs/screening-tiers-eval.md: config keys, DDL and the screening tables/view."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, sql_file

from .helpers import mod

SCRIPT = "ddl/080_screening.sql"


def test_ac1_new_screening_config_defaults() -> None:
    cfg = load_settings(environ={}).screening
    assert cfg.alert_threshold == 90
    assert cfg.review_threshold == 75
    assert cfg.dob_tolerance_years == 1
    assert cfg.dob_clear_years == 5
    assert cfg.dob_gap_discount == 15
    assert cfg.nationality_mismatch_discount == 15
    assert cfg.gender_mismatch_discount == 15


def test_ac1_review_threshold_must_not_exceed_alert_threshold() -> None:
    with pytest.raises(ValidationError, match="review_threshold must not exceed alert_threshold"):
        load_settings(environ={"AML__SCREENING__REVIEW_THRESHOLD": "95"})


def test_ac1_script_registered_and_resolves_per_backend() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    assert SCRIPT in scripts["duckdb"]
    assert SCRIPT in scripts["oracle"]
    assert scripts["oracle"].index(SCRIPT) < scripts["oracle"].index("ddl/050_security_objects.sql")
    assert scripts["duckdb"].index(SCRIPT) < scripts["duckdb"].index("ddl/050_customers_masked.sql")
    for backend in ("duckdb", "oracle"):
        assert sql_file(SCRIPT, backend) == SQL_ROOT / backend / SCRIPT


def test_ac1_apply_schema_twice_creates_empty_tables_and_view(duck: DuckDb) -> None:
    apply_schema = mod("aml.dba.schema").apply_schema
    apply_schema(duck)
    apply_schema(duck)
    for name in ("screening_runs", "screening_results", "screening_current"):
        assert int(duck.query_df(f"SELECT COUNT(*) FROM {name}").iloc[0, 0]) == 0, name
