"""AC4 for specs/ml-anomaly.md: `run_anomaly` on MINI-C stores scores, one alert and the audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    MINI_REASON,
    anom_settings,
    features,
    js,
    matrix,
    model,
    query,
    run_anomaly,
    scalar,
)


@dataclass
class Runs:
    db: DuckDb
    settings: Any
    r1: Any
    r2: Any
    before: dict[str, pd.DataFrame]


@pytest.fixture
def runs(minic: DuckDb) -> Runs:
    settings = anom_settings()
    r1 = run_anomaly(minic, settings)
    before = {
        "scores": query(minic, "SELECT * FROM anomaly_scores WHERE run_id = 1 ORDER BY cif, month"),
        "runs": query(minic, "SELECT * FROM anomaly_runs WHERE run_id = 1"),
    }
    return Runs(minic, settings, r1, run_anomaly(minic, settings), before)


def test_ac4_first_run_summary(runs: Runs) -> None:
    r = runs.r1
    assert (r.run_id, r.model_version, r.as_of) == (1, "anomaly/v1/1", date(2026, 6, 30))
    assert (r.samples, r.customers, r.months, r.alerts) == (6, 4, 4, 1)
    assert r.threshold == pytest.approx(0.567938, abs=1e-6)
    assert r.graph_source == "none"
    assert r.data_hash == model().data_hash(matrix(runs.db, runs.settings))
    assert r.seconds >= 0
    assert r.monitoring_run_id >= 1


def test_ac4_scores_table(runs: Runs) -> None:
    df = query(runs.db, "SELECT * FROM anomaly_scores WHERE run_id = 1 ORDER BY cif, month")
    assert len(df) == 6
    assert set(df["model_version"]) == {"anomaly/v1/1"}
    flagged = df[df["alerted"] == 1]
    assert [(r.cif, r.month, r.rank) for r in flagged.itertuples()] == [("C01", "2026-03", 1)]
    top = js(flagged["top_deviations"].iloc[0])
    assert len(top) == 3 and top[0]["feature"] == "txns_per_day"
    assert df[df["alerted"] == 0]["top_deviations"].isna().all()


def test_ac4_run_row(runs: Runs) -> None:
    row = query(runs.db, "SELECT * FROM anomaly_runs WHERE run_id = 1").iloc[0]
    assert row["feature_version"] == "anomaly/v1"
    assert row["kind"] == "isolation_forest"
    assert row["seed"] == 42
    assert js(row["features"]) == list(features().ANOMALY_FEATURES)
    params = js(row["params"])
    assert params["iforest"]["n_estimators"] == 200
    assert params["iforest"]["max_samples"] == 6  # min(256, 6)
    assert params["iforest"]["random_state"] == 42
    assert params["config"]["max_samples"] == 256
    assert "sklearn_version" in params
    assert js(row["metrics"])["max"] == pytest.approx(0.567938, abs=1e-6)
    assert row["monitoring_run_id"] == runs.r1.monitoring_run_id


def test_ac4_the_alert(runs: Runs) -> None:
    db = runs.db
    a = query(
        db, "SELECT * FROM alerts WHERE source = 'ANOMALY' AND rule_version = 'anomaly/v1/1'"
    ).iloc[0]
    assert (a["rule_id"], a["rule_version"], a["subject_type"]) == (
        "ML_ANOMALY",
        "anomaly/v1/1",
        "CUSTOMER",
    )
    assert (a["subject_id"], a["alert_key"]) == ("C01", "ML_ANOMALY|C01|2026-03")
    assert a["window_start"] == pd.Timestamp("2026-03-02 09:00:00")
    assert a["window_end"] == pd.Timestamp("2026-03-07 10:00:00")
    assert (a["txn_count"], a["amount_vnd"]) == (3, 970_000_000)
    details = js(a["details"])
    assert details["model_version"] == "anomaly/v1/1" and details["rank"] == 1
    assert a["reason"] == MINI_REASON
    aid = int(a["alert_id"])
    accounts = query(db, f"SELECT account_id, cif, role FROM alert_accounts WHERE alert_id = {aid}")
    assert [tuple(r) for r in accounts.itertuples(index=False)] == [("A01", "C01", "SUBJECT")]
    evidence = query(db, f"SELECT txn_id FROM alert_evidence WHERE alert_id = {aid}")
    assert set(evidence["txn_id"]) == {"T01", "T02", "T04"}
    mon = query(db, "SELECT * FROM monitoring_runs WHERE rule_version = 'anomaly/v1/1'")
    row = mon.iloc[0]
    assert row["source"] == "ANOMALY"
    assert (row["rule_id"], row["rule_version"], row["alerts"], row["evidence"]) == (
        "ML_ANOMALY",
        "anomaly/v1/1",
        1,
        3,
    )


def test_ac4_audit_rows(runs: Runs) -> None:
    db = runs.db
    alert = query(db, "SELECT * FROM audit_log WHERE decision = 'ALERT' AND version LIKE 'ML_%'")
    assert len(alert) == 2  # one per run
    assert set(alert["version"]) == {"ML_ANOMALY/anomaly/v1/1", "ML_ANOMALY/anomaly/v1/2"}
    done = query(db, "SELECT * FROM audit_log WHERE decision = 'MONITORING_RUN_COMPLETED'")
    assert (done["version"] == "monitoring/anomaly").sum() == 2
    ev = query(db, "SELECT * FROM audit_log WHERE module = 'ml_anomaly' ORDER BY audit_id")
    first = ev.iloc[0]
    assert len(ev) == 2
    assert (first["entity_type"], first["entity_id"], first["decision"]) == (
        "anomaly_run",
        "1",
        "ANOMALY_RUN_COMPLETED",
    )
    assert (first["version"], first["actor"]) == ("anomaly/v1/1", "system")
    assert first["reason"].startswith(
        "scored 6 customer-months of 4 customers (2026-01 to 2026-05)"
    )
    assert "nothing is closed or cleared" in first["reason"]
    details = js(first["details"])
    assert details["run_id"] == 1 and "metrics" in details


def test_ac4_second_run_replaces_the_first_as_current(runs: Runs) -> None:
    db, r2 = runs.db, runs.r2
    assert (r2.run_id, r2.model_version) == (2, "anomaly/v1/2")
    assert r2.data_hash == runs.r1.data_hash
    keys = "cif, month, score, rank, alerted"
    one = query(db, f"SELECT {keys} FROM anomaly_scores WHERE run_id = 1 ORDER BY cif, month")
    two = query(db, f"SELECT {keys} FROM anomaly_scores WHERE run_id = 2 ORDER BY cif, month")
    pd.testing.assert_frame_equal(one, two)
    current = query(db, "SELECT DISTINCT run_id FROM anomaly_scores_current")
    assert list(current["run_id"]) == [2]
    assert scalar(db, "SELECT COUNT(*) FROM anomaly_scores_current") == 6
    cur = query(db, "SELECT * FROM alerts_current WHERE source = 'ANOMALY'")
    assert len(cur) == 1 and cur["rule_version"].iloc[0] == "anomaly/v1/2"
    by_source = query(db, "SELECT source, COUNT(*) AS n FROM alerts_current GROUP BY source")
    assert dict(zip(by_source["source"], by_source["n"], strict=True)) == {
        "RULE": 4,
        "NETWORK": 1,
        "ANOMALY": 1,
    }


def test_ac4_the_first_run_is_left_alone(runs: Runs) -> None:
    db = runs.db
    scores = query(db, "SELECT * FROM anomaly_scores WHERE run_id = 1 ORDER BY cif, month")
    pd.testing.assert_frame_equal(scores, runs.before["scores"])
    pd.testing.assert_frame_equal(
        query(db, "SELECT * FROM anomaly_runs WHERE run_id = 1"), runs.before["runs"]
    )


def test_ac4_actor_is_recorded(minic: DuckDb) -> None:
    run_anomaly(minic, anom_settings(), actor="analyst01")
    row = query(minic, "SELECT actor FROM audit_log WHERE decision = 'ANOMALY_RUN_COMPLETED'")
    assert list(row["actor"]) == ["analyst01"]
