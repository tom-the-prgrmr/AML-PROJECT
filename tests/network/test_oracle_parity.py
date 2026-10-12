"""AC10 for specs/network-detections.md: Oracle and DuckDB give the same network alerts."""

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
    mod,
    none_if_nan,
    query,
    run_er,
    run_network,
)


def _alert_set(db: Database, run_id: int) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT alert_key, subject_id, reason, txn_count, amount_vnd, window_start, window_end "
        f"FROM alerts WHERE run_id = {run_id}",
    )
    return {
        (
            r.alert_key,
            r.subject_id,
            r.reason,
            int(r.txn_count),
            int(r.amount_vnd),
            pd.Timestamp(r.window_start),
            pd.Timestamp(r.window_end),
        )
        for r in df.itertuples()
    }


def _account_set(db: Database, run_id: int) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT a.alert_key, c.account_id, c.role, c.cif FROM alerts a JOIN alert_accounts c "
        f"ON c.alert_id = a.alert_id WHERE a.run_id = {run_id}",
    )
    return {(r.alert_key, r.account_id, r.role, none_if_nan(r.cif)) for r in df.itertuples()}


def _evidence_set(db: Database, run_id: int) -> set[tuple[str, str]]:
    df = query(
        db,
        "SELECT a.alert_key, e.txn_id FROM alerts a JOIN alert_evidence e "
        f"ON e.alert_id = a.alert_id WHERE a.run_id = {run_id}",
    )
    return {(r.alert_key, r.txn_id) for r in df.itertuples()}


def _feature_set(db: Database, run_id: int) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT account_id, in_degree, out_degree, in_vnd, out_vnd, pagerank_ratio, cycle_alerts, "
        f"shared_cluster_id, shared_cluster_size, is_hub FROM nx_account_features "
        f"WHERE run_id = {run_id}",
    )
    return {
        (
            r.account_id,
            int(r.in_degree),
            int(r.out_degree),
            int(r.in_vnd),
            int(r.out_vnd),
            round(float(r.pagerank_ratio), 2),
            int(r.cycle_alerts),
            none_if_nan(r.shared_cluster_id),
            int(r.shared_cluster_size),
            int(r.is_hub),
        )
        for r in df.itertuples()
    }


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    schema = mod("aml.dba.schema")
    evaluate = mod("aml.graph.network.evaluate")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    with OracleDb(osettings) as odb:
        load.load_parquet(odb, tiny_parquet)
        run_er(odb, osettings)
        orun = run_network(odb, osettings, as_of=AS_OF)
        rid = orun.run_id
        oalerts = _alert_set(odb, rid)
        oaccounts = _account_set(odb, rid)
        oevidence = _evidence_set(odb, rid)
        ofeatures = _feature_set(odb, rid)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        n_current = int(
            odb.query_df(
                f"SELECT COUNT(*) FROM nx_account_features_current WHERE run_id = {rid}"
            ).iloc[0, 0]
        )
        n_view = int(odb.query_df("SELECT COUNT(*) FROM nx_account_features_current").iloc[0, 0])
        n_audit = int(
            odb.query_df(
                "SELECT COUNT(*) FROM audit_log WHERE module = 'monitoring' AND ("
                "(entity_type = 'alert' AND JSON_VALUE(details, '$.run_id') = "
                f"'{rid}') OR (entity_type = 'monitoring_run' AND entity_id = '{rid}'))"
            ).iloc[0, 0]
        )
        oeval = evaluate.evaluate_network(odb)
        schema.apply_schema(odb)  # idempotent on a second call

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb"})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        run_er(ddb, dsettings)
        drun = run_network(ddb, dsettings, as_of=AS_OF)
        dalerts = _alert_set(ddb, drun.run_id)
        daccounts = _account_set(ddb, drun.run_id)
        devidence = _evidence_set(ddb, drun.run_id)
        dfeatures = _feature_set(ddb, drun.run_id)

    assert "NX_ACCOUNT_FEATURES" in tables
    assert "NX_ACCOUNT_FEATURES_CURRENT" in views
    assert n_current == n_view == 532
    assert n_audit == 5

    for run in (orun, drun):
        assert (run.alerts, run.evidence, run.accounts) == (4, 67, 532)
        assert (run.active_accounts, run.cycle_search_steps) == (298, 12)
        assert [run.by_rule[r] for r in RULE_IDS] == [1, 2, 1]
    assert orun.by_rule == drun.by_rule
    assert oalerts == dalerts
    assert oaccounts == daccounts
    assert oevidence == devidence
    assert ofeatures == dfeatures

    oeval.columns = [c.lower() for c in oeval.columns]
    assert list(oeval["rule_id"]) == list(RULE_IDS)
    for row in oeval.itertuples():
        expected = EVAL_EXPECTED[row.rule_id]
        for column, want in zip(EVAL_VALUE_COLUMNS, expected, strict=True):
            assert none_if_nan(getattr(row, column)) == pytest.approx(want), (row.rule_id, column)
