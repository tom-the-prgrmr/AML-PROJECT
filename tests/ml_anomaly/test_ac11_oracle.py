"""AC11 for specs/ml-anomaly.md: Oracle and DuckDB score TINY the same way.

The Oracle schema is shared and keeps its history (`audit_log` cannot be purged), so this test is
written to be re-run: ids come from the returned runs, nothing depends on history, and
`GRAPH_FEATURES` is pinned to networkx on both backends (GDS rows left by other tests would make
`auto` pick them on Oracle). Like `test_prio_oracle.py` it removes, in `finally`, the rows it wrote
(by the ids it was given): a run left behind would put ANOMALY items into the cases of
`test_oracle_parity.py` and the anomaly columns into the models of the prioritization tests. Only
its audit rows stay.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb
from tests.cases.helpers import mod, query

from .helpers import evaluate, run_anomaly

AS_OF = date(2026, 6, 30)
PINNED = {"AML__CASES__GRAPH_FEATURES": "networkx"}


def _build(db: Database, settings: Settings, parquet: Path) -> None:
    mod("aml.datagen.load").load_parquet(db, parquet)
    mod("aml.entity_resolution.runner").run_er(db, settings, as_of=AS_OF)
    mod("aml.screening.runner").run_screening(db, settings, as_of=AS_OF)
    mod("aml.monitoring.runner").run_monitoring(db, settings, as_of=AS_OF)
    mod("aml.graph.network.runner").run_network(db, settings, as_of=AS_OF)
    mod("aml.dq.runner").run_dq(db, settings, as_of=AS_OF)


def _max(db: Database, table: str) -> int:
    return int(db.query_df(f"SELECT COALESCE(MAX(run_id), 0) FROM {table}").iloc[0, 0])


def _forget(db: Database, monitoring_floor: int, anomaly_floor: int) -> None:
    """Remove the anomaly rows written after the floors (also those of a run that died half way)."""
    alerts = f"SELECT alert_id FROM alerts WHERE source = 'ANOMALY' AND run_id > {monitoring_floor}"
    for sql in (
        f"DELETE FROM alert_evidence WHERE alert_id IN ({alerts})",
        f"DELETE FROM alert_accounts WHERE alert_id IN ({alerts})",
        f"DELETE FROM alerts WHERE source = 'ANOMALY' AND run_id > {monitoring_floor}",
        f"DELETE FROM monitoring_runs WHERE rule_id = 'ML_ANOMALY' AND run_id > {monitoring_floor}",
        f"DELETE FROM anomaly_scores WHERE run_id > {anomaly_floor}",
        f"DELETE FROM anomaly_runs WHERE run_id > {anomaly_floor}",
    ):
        db.execute(sql)


def _observe(
    db: Database, settings: Settings, parquet: Path, *, forget: bool = False
) -> SimpleNamespace:
    _build(db, settings, parquet)
    monitoring_floor = max(_max(db, "monitoring_runs"), _max(db, "alerts"))
    anomaly_floor = max(_max(db, "anomaly_runs"), _max(db, "anomaly_scores"))
    try:
        run = run_anomaly(db, settings, as_of=AS_OF)
        scores = query(
            db,
            "SELECT cif, month, score, rank, alerted FROM anomaly_scores "
            f"WHERE run_id = {run.run_id} ORDER BY cif, month",
        )
        alerts = query(
            db,
            "SELECT alert_key, txn_count, amount_vnd, reason FROM alerts "
            f"WHERE run_id = {run.monitoring_run_id} AND source = 'ANOMALY' ORDER BY alert_key",
        )
        evaluation = evaluate().evaluate_anomaly(db, settings, run_id=run.run_id)
    finally:
        if forget:
            _forget(db, monitoring_floor, anomaly_floor)
    # the reason names the model version, whose run number depends on the history of the schema
    alerts["reason"] = alerts["reason"].str.replace(run.model_version, "<version>", regex=False)
    return SimpleNamespace(run=run, scores=scores, alerts=alerts, evaluation=evaluation)


@pytest.mark.oracle
def test_ac11_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    schema = mod("aml.dba.schema")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **PINNED})
    with OracleDb(osettings) as odb:
        schema.apply_schema(odb)
        oracle = _observe(odb, osettings, tiny_parquet, forget=True)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        width = odb.query_df(
            "SELECT char_length FROM user_tab_columns "
            "WHERE table_name = 'CASE_MODELS' AND column_name = 'FEATURE_VERSION'"
        ).iloc[0, 0]
        schema.apply_schema(odb)  # a second call must not raise (ALTER ... MODIFY is idempotent)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **PINNED})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        duck = _observe(ddb, dsettings, tiny_parquet)

    o, d = oracle.run, duck.run
    for name in ("samples", "customers", "months", "alerts", "graph_source", "data_hash"):
        assert getattr(o, name) == getattr(d, name), name
    assert (d.samples, d.alerts, d.graph_source) == (1334, 7, "networkx")
    assert abs(o.threshold - d.threshold) <= 1e-6

    keys = ["cif", "month", "rank", "alerted"]
    left, right = oracle.scores, duck.scores
    assert len(left) == len(right) == 1334
    pd.testing.assert_frame_equal(
        left[keys].astype("int64", errors="ignore"),
        right[keys].astype("int64", errors="ignore"),
        check_dtype=False,
    )
    assert (left["score"] - right["score"]).abs().max() <= 1e-6

    assert len(oracle.alerts) == len(duck.alerts) == 7
    assert oracle.alerts["reason"].str.contains("model <version>;").all()
    pd.testing.assert_frame_equal(oracle.alerts, duck.alerts, check_dtype=False)

    for part in ("coverage", "suspicious", "benign", "alerts_by_kind"):
        assert oracle.evaluation[part] == duck.evaluation[part], part

    assert {"ANOMALY_RUNS", "ANOMALY_SCORES", "CASE_ANOMALY_FEATURES"} <= tables
    assert "ANOMALY_SCORES_CURRENT" in views
    assert int(width) == 60
