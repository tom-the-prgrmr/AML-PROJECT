"""AC1-AC3 for specs/oracle-retention.md (no Oracle needed)."""

from __future__ import annotations

import re
from datetime import date, datetime

import pytest

from aml.common.config import load_settings
from aml.common.db import SQL_ROOT, DuckDb, split_oracle_script, sql_file

from .helpers import mod


def test_ac1_retention_cutoff_values() -> None:
    cutoff = mod("aml.dba.retention").retention_cutoff
    assert cutoff(date(2026, 6, 30), 60) == datetime(2021, 6, 1, 0, 0)
    assert cutoff(date(2026, 1, 1), 60) == datetime(2021, 1, 1, 0, 0)
    assert cutoff(date(2026, 3, 31), 61) == datetime(2021, 2, 1, 0, 0)


def test_ac1_retention_cutoff_rejects_below_legal_minimum() -> None:
    retention = mod("aml.dba.retention")
    assert retention.LEGAL_MIN_MONTHS == 60
    with pytest.raises(retention.RetentionError, match="legal minimum of 60 months"):
        retention.retention_cutoff(date(2026, 6, 30), 59)


def test_ac2_config_defaults() -> None:
    settings = load_settings(environ={})
    assert settings.retention.transactions_months == 60
    assert settings.retention.archive_dir == "data/archive"


def test_ac2_purge_rejects_low_retention_before_touching_db(duck: DuckDb) -> None:
    retention = mod("aml.dba.retention")
    mod("aml.dba.schema").apply_schema(duck)
    settings = load_settings(environ={"AML__RETENTION__TRANSACTIONS_MONTHS": "59"})
    assert settings.retention.transactions_months == 59
    with pytest.raises(retention.RetentionError, match="legal minimum of 60 months"):
        retention.purge_transactions(duck, settings, dry_run=True)
    n = duck.query_df(
        "SELECT COUNT(*) AS n FROM audit_log WHERE module = 'dba' "
        "AND (decision LIKE 'RETENTION%' OR decision = 'PARTITION_DROPPED')"
    )["n"].iloc[0]
    assert int(n) == 0


def test_ac3_audit_log_partitioning_script_registered_and_well_formed() -> None:
    scripts = mod("aml.dba.schema").SCHEMA_SCRIPTS
    name = "ddl/070_audit_log_partitioning.sql"
    oracle = scripts["oracle"]
    assert name in oracle
    assert oracle.index(name) > oracle.index("ddl/040_acct_edge_daily.sql")
    resolved = sql_file(name, "oracle")
    assert resolved.parent.parent == SQL_ROOT / "oracle"
    statements = split_oracle_script(resolved.read_text(encoding="utf-8"))
    assert len(statements) >= 1
    for stmt in statements:
        body = "\n".join(ln for ln in stmt.splitlines() if not ln.strip().startswith("--")).strip()
        assert not re.match(r"(?i)(CREATE|ALTER|DROP)\b", body), "bare DDL"


def test_ac3_duckdb_has_no_audit_log_partitioning_and_apply_schema_is_idempotent(
    duck: DuckDb,
) -> None:
    schema = mod("aml.dba.schema")
    assert not any("audit_log_partitioning" in s for s in schema.SCHEMA_SCRIPTS["duckdb"])
    schema.apply_schema(duck)
    schema.apply_schema(duck)
