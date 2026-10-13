"""AC1 for specs/case-consolidation.md: config, DDL 160, SQL files, no role grants."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, split_oracle_script, sql_file
from aml.dba.schema import SCHEMA_SCRIPTS, apply_schema

from .helpers import count, mod

DDL = "ddl/160_cases.sql"
OBJECTS = (
    "case_runs",
    "cases",
    "case_alerts",
    "case_enrichment",
    "case_dispositions",
    "cases_current",
    "case_alerts_current",
    "case_enrichment_current",
    "case_dispositions_current",
)
SQL_FILES = ("cases/items.sql", "cases/txn_summary.sql", "cases/counterparties.sql")


def test_ac1_default_cases_config() -> None:
    c = load_settings(environ={}).cases
    assert c.window_days == 90
    assert c.txn_summary_days == 90
    assert c.top_counterparties == 5
    assert c.graph_features == "auto"


def test_ac1_invalid_window_days_is_rejected() -> None:
    with pytest.raises(ValidationError, match=re.escape("window_days must be >= 1")):
        load_settings(environ={"AML__CASES__WINDOW_DAYS": "0"})


def test_ac1_unknown_graph_features_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_settings(environ={"AML__CASES__GRAPH_FEATURES": "neo4j"})


def test_ac1_ddl_160_is_registered_for_both_backends() -> None:
    duckdb = SCHEMA_SCRIPTS["duckdb"]
    assert DDL in duckdb
    assert duckdb.index(DDL) > duckdb.index("ddl/150_gds.sql")
    assert duckdb.index(DDL) < duckdb.index("ddl/050_customers_masked.sql")
    oracle = SCHEMA_SCRIPTS["oracle"]
    assert DDL in oracle
    assert oracle.index(DDL) > oracle.index("ddl/150_gds.sql")
    assert oracle.index(DDL) < oracle.index("ddl/050_security_objects.sql")
    for backend in ("duckdb", "oracle"):
        assert sql_file(DDL, backend) == SQL_ROOT / backend / "ddl" / "160_cases.sql"
        assert sql_file(DDL, backend).exists()


def test_ac1_apply_schema_twice_creates_empty_tables_and_views(duck: DuckDb) -> None:
    apply_schema(duck)
    apply_schema(duck)  # idempotent
    for name in OBJECTS:
        assert count(duck, name) == 0, name


@pytest.mark.parametrize("name", SQL_FILES)
def test_ac1_sql_files_resolve_per_backend(name: str) -> None:
    assert sql_file(name, "duckdb") == SQL_ROOT / "duckdb" / name
    assert sql_file(name, "oracle") == SQL_ROOT / "oracle" / name
    oracle_text = sql_file(name, "oracle").read_text(encoding="utf-8")
    assert len(split_oracle_script(oracle_text)) == 1


def test_ac1_role_grants_do_not_mention_case_tables() -> None:
    grants = mod("aml.dba.security").ROLE_GRANTS
    for role, pairs in grants.items():
        for _privilege, table in pairs:
            assert not table.lower().startswith("case"), (role, table)
