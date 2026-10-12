"""AC10 for specs/monitoring-rules.md: Oracle and DuckDB give the same alerts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import (
    AS_OF,
    EVAL_EXPECTED,
    EVAL_VALUE_COLUMNS,
    RULE_IDS,
    TINY_BY_RULE,
    mod,
    none_if_nan,
    query,
    run_monitoring,
)


def _alert_set(db: Database, run_id: int) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT alert_key, reason, txn_count, amount_vnd, window_start, window_end FROM alerts "
        f"WHERE run_id = {run_id}",
    )
    return {
        (
            r.alert_key,
            r.reason,
            int(r.txn_count),
            int(r.amount_vnd),
            pd.Timestamp(r.window_start),
            pd.Timestamp(r.window_end),
        )
        for r in df.itertuples()
    }


def _evidence_set(db: Database, run_id: int) -> set[tuple[str, str]]:
    df = query(
        db,
        "SELECT a.alert_key, e.txn_id FROM alerts a JOIN alert_evidence e "
        f"ON e.alert_id = a.alert_id WHERE a.run_id = {run_id}",
    )
    return {(r.alert_key, r.txn_id) for r in df.itertuples()}


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    schema = mod("aml.dba.schema")
    evaluate = mod("aml.monitoring.evaluate")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    with OracleDb(osettings) as odb:
        load.load_parquet(odb, tiny_parquet)
        orun = run_monitoring(odb, osettings, as_of=AS_OF)
        rid = orun.run_id
        oalerts = _alert_set(odb, rid)
        oevidence = _evidence_set(odb, rid)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        n_legs = int(odb.query_df("SELECT COUNT(*) FROM txn_legs").iloc[0, 0])
        n_current = int(
            odb.query_df(
                f"SELECT COUNT(*) FROM alerts_current WHERE source = 'RULE' AND run_id = {rid}"
            ).iloc[0, 0]
        )
        n_audit = int(
            odb.query_df(
                "SELECT COUNT(*) FROM audit_log WHERE module = 'monitoring' AND ("
                "(entity_type = 'alert' AND JSON_VALUE(details, '$.run_id') = "
                f"'{rid}') OR (entity_type = 'monitoring_run' AND entity_id = '{rid}'))"
            ).iloc[0, 0]
        )
        oeval = evaluate.evaluate_rules(odb)
        schema.apply_schema(odb)  # idempotent on a second call

    assert {"MONITORING_RUNS", "ALERTS", "ALERT_ACCOUNTS", "ALERT_EVIDENCE"} <= tables
    assert {"TXN_LEGS", "ALERTS_CURRENT"} <= views
    assert n_legs == 6137
    assert n_current == 31
    assert n_audit == 32
    oeval.columns = [c.lower() for c in oeval.columns]
    assert list(oeval["rule_id"]) == list(RULE_IDS)
    for row in oeval.itertuples():
        expected = EVAL_EXPECTED[row.rule_id]
        for col, want in zip(EVAL_VALUE_COLUMNS, expected, strict=True):
            got = none_if_nan(getattr(row, col))
            if want is None:
                assert got is None, (row.rule_id, col, got)
            else:
                assert got == pytest.approx(want), (row.rule_id, col, got)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb"})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        drun = run_monitoring(ddb, dsettings, as_of=AS_OF)
        dalerts = _alert_set(ddb, drun.run_id)
        devidence = _evidence_set(ddb, drun.run_id)

    assert (orun.alerts, orun.evidence) == (31, 323)
    assert [orun.by_rule[r] for r in RULE_IDS] == [TINY_BY_RULE[r] for r in RULE_IDS]
    assert (orun.alerts, orun.evidence, orun.by_rule) == (drun.alerts, drun.evidence, drun.by_rule)
    assert oalerts == dalerts
    assert oevidence == devidence
