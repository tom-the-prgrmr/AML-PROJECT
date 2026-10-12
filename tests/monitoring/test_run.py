"""AC7-AC8 for specs/monitoring-rules.md: `run_monitoring` / `record_run` on TINY (DuckDB)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings
from aml.common.db import Database, DuckDb

from .helpers import (
    AS_OF,
    RULE_IDS,
    TINY_BY_RULE,
    TINY_RUNS_ROWS,
    duck_settings,
    js,
    load_tiny_duck,
    mod,
    query,
    run_monitoring,
    scalar,
)

ALERT_1_KEY = "STRUCTURING|A6457424962|2026-02-10T09:52:00"
ALERT_1_REASON = (
    "8 cash deposits of 360,000,000 to 399,999,999 VND (just under the 400,000,000 VND "
    "reporting threshold) totalling 3,023,290,000 VND at 3 branch(es) between "
    "2026-02-10 09:52:00 and 2026-02-15 16:38:00"
)
ALERT_7_REASON = (
    "received 1,172,011,000 VND and sent out 1,146,596,000 VND (98%) between "
    "2026-02-22 16:10:24 and 2026-02-23 10:24:53"
)
ALERT_14_REASON = (
    "received 2,930,380,000 VND from 31 new senders in 31 transactions between "
    "2026-04-13 09:28:12 and 2026-04-17 23:16:36 (at least 8 within 7 days)"
)


@pytest.fixture(scope="module")
def once(
    tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[DuckDb, Settings, Any]]:
    """TINY with exactly one run_monitoring (read-only for the tests of this module)."""
    db = load_tiny_duck(tiny_parquet, tmp_path_factory.mktemp("mon_once") / "tiny.duckdb")
    settings = duck_settings()
    run = run_monitoring(db, settings)
    yield db, settings, run
    db.close()


@pytest.fixture
def tiny(tiny_parquet: Path, tmp_path: Path) -> Iterator[tuple[DuckDb, Settings]]:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    yield db, duck_settings()
    db.close()


def _evidence_of(db: Database, scenario_id: str) -> set[str]:
    df = query(
        db,
        "SELECT entity_id FROM ground_truth WHERE entity_type = 'transaction' "
        f"AND role = 'evidence' AND scenario_id = '{scenario_id}'",
    )
    return set(df["entity_id"])


def _alert_evidence(db: Database, alert_id: int) -> set[str]:
    return set(
        query(db, f"SELECT txn_id FROM alert_evidence WHERE alert_id = {alert_id}")["txn_id"]
    )


def _alerts(db: Database) -> pd.DataFrame:
    return query(db, "SELECT * FROM alerts ORDER BY alert_id")


def _audit(db: Database) -> pd.DataFrame:
    df = query(
        db,
        "SELECT entity_type, entity_id, decision, reason, version, details FROM audit_log "
        "WHERE module = 'monitoring' ORDER BY audit_id",
    )
    df["details"] = [js(d) for d in df["details"]]
    return df


def _tuples(db: Database, run_id: int) -> set[tuple[Any, ...]]:
    df = query(
        db,
        f"SELECT alert_key, reason, txn_count, amount_vnd FROM alerts WHERE run_id = {run_id}",
    )
    return {(r.alert_key, r.reason, int(r.txn_count), int(r.amount_vnd)) for r in df.itertuples()}


def _evidence_pairs(db: Database, run_id: int) -> set[tuple[str, str]]:
    df = query(
        db,
        "SELECT a.alert_key, e.txn_id FROM alerts a JOIN alert_evidence e "
        f"ON e.alert_id = a.alert_id WHERE a.run_id = {run_id}",
    )
    return {(r.alert_key, r.txn_id) for r in df.itertuples()}


# ----------------------------------------------------------------------------- AC7
def test_ac7_run_summary(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, run = once
    assert run.run_id == 1
    assert run.as_of == AS_OF
    assert run.alerts == 31
    assert run.evidence == 323
    assert run.by_rule == TINY_BY_RULE
    assert list(run.by_rule) == list(RULE_IDS)
    assert scalar(db, "SELECT COUNT(*) FROM txn_legs") == 6137


def test_ac7_alerts_table(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    df = _alerts(db)
    assert len(df) == 31
    assert list(df["alert_id"]) == list(range(1, 32))
    assert set(df["run_id"]) == {1}
    assert set(df["source"]) == {"RULE"}
    assert set(df["subject_type"]) == {"ACCOUNT"}
    assert set(df["rule_version"]) == {"v1"}
    assert df["subject_id"].nunique() == 20
    order = {r: i for i, r in enumerate(RULE_IDS)}
    keys = [(order[r.rule_id], r.subject_id, pd.Timestamp(r.window_start)) for r in df.itertuples()]
    assert keys == sorted(keys)

    a1 = df.iloc[0]
    assert (a1["rule_id"], a1["subject_id"], a1["alert_key"]) == (
        "STRUCTURING",
        "A6457424962",
        ALERT_1_KEY,
    )
    assert pd.Timestamp(a1["window_start"]) == pd.Timestamp("2026-02-10 09:52:00")
    assert pd.Timestamp(a1["window_end"]) == pd.Timestamp("2026-02-15 16:38:00")
    assert (int(a1["txn_count"]), int(a1["amount_vnd"])) == (8, 3023290000)
    assert js(a1["details"]) == {"deposits": 8, "total_vnd": 3023290000, "branches": 3}
    assert a1["reason"] == ALERT_1_REASON

    a7 = df[df["alert_id"] == 7].iloc[0]
    assert (a7["rule_id"], a7["subject_id"], int(a7["txn_count"])) == (
        "RAPID_MOVEMENT",
        "A9586661327",
        3,
    )
    assert a7["reason"] == ALERT_7_REASON

    a14 = df[df["alert_id"] == 14].iloc[0]
    assert (a14["rule_id"], a14["subject_id"], int(a14["txn_count"])) == (
        "FAN_IN",
        "A4937939209",
        31,
    )
    assert a14["reason"] == ALERT_14_REASON


def test_ac7_alert_accounts(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    df = query(db, "SELECT * FROM alert_accounts")
    assert len(df) == 31
    assert set(df["role"]) == {"SUBJECT"}
    row = df[df["alert_id"] == 1].iloc[0]
    assert (row["account_id"], row["cif"]) == ("A6457424962", "CIF00000043")


def test_ac7_alert_evidence_matches_ground_truth(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    assert scalar(db, "SELECT COUNT(*) FROM alert_evidence") == 323
    assert scalar(db, "SELECT COUNT(DISTINCT txn_id) FROM alert_evidence") == 144
    assert _alert_evidence(db, 1) == _evidence_of(db, "GT-STR-0001")
    assert _alert_evidence(db, 2) == _evidence_of(db, "GT-STR-0002")
    assert _alert_evidence(db, 4) == _evidence_of(db, "GT-RAP-0001")
    assert _alert_evidence(db, 7) == _evidence_of(db, "GT-RAP-0002")

    suspicious = query(
        db,
        "SELECT DISTINCT entity_id FROM ground_truth WHERE entity_type = 'transaction' "
        "AND role = 'evidence' AND is_suspicious",
    )
    flagged = set(query(db, "SELECT DISTINCT txn_id FROM alert_evidence")["txn_id"])
    assert flagged <= set(suspicious["entity_id"])
    mule = _evidence_of(db, "GT-MULE-0001")
    assert len(mule) == 118
    assert mule <= flagged


def test_ac7_monitoring_runs(once: tuple[DuckDb, Settings, Any]) -> None:
    db, settings, _ = once
    df = query(db, "SELECT * FROM monitoring_runs")
    assert len(df) == 6
    assert set(df["run_id"]) == {1}
    assert set(df["source"]) == {"RULE"}
    assert {str(a)[:10] for a in df["as_of"]} == {"2026-06-30"}
    by_rule = {r.rule_id: r for r in df.itertuples()}
    assert set(by_rule) == set(RULE_IDS)
    for rule_id, (alerts, evidence) in TINY_RUNS_ROWS.items():
        assert (int(by_rule[rule_id].alerts), int(by_rule[rule_id].evidence)) == (
            alerts,
            evidence,
        ), rule_id
    rule_params = mod("aml.monitoring.rules").rule_params
    assert js(by_rule["STRUCTURING"].params) == rule_params("STRUCTURING", settings)


def test_ac7_alerts_current(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    df = query(db, "SELECT alert_id, run_id FROM alerts_current")
    assert len(df) == 31
    assert set(df["run_id"]) == {1}
    assert set(df["alert_id"]) == set(range(1, 32))


def test_ac7_audit_log(once: tuple[DuckDb, Settings, Any]) -> None:
    db, _, _ = once
    df = _audit(db)
    assert len(df) == 32
    alerts = df[df["entity_type"] == "alert"]
    assert len(alerts) == 31
    assert set(alerts["decision"]) == {"ALERT"}
    first = alerts[alerts["entity_id"] == "1"].iloc[0]
    assert first["version"] == "STRUCTURING/v1"
    assert first["reason"] == ALERT_1_REASON
    assert first["details"]["run_id"] == 1
    assert first["details"]["alert_key"] == ALERT_1_KEY
    summary = df[df["entity_type"] == "monitoring_run"]
    assert len(summary) == 1
    row = summary.iloc[0]
    assert (row["entity_id"], row["decision"]) == ("1", "MONITORING_RUN_COMPLETED")
    assert row["details"]["alerts"] == 31
    assert row["details"]["evidence"] == 323
    assert row["details"]["by_rule"]["DORMANT_REACTIVATION"] == 13


# ----------------------------------------------------------------------------- AC8
def test_ac8_second_run_is_a_full_new_snapshot(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    first = run_monitoring(db, settings)
    audit_before = len(_audit(db))
    first_rows = query(db, "SELECT * FROM alerts WHERE run_id = 1 ORDER BY alert_id")
    second = run_monitoring(db, settings)

    assert second.run_id == 2
    assert (second.alerts, second.evidence, second.by_rule) == (
        first.alerts,
        first.evidence,
        first.by_rule,
    )
    df = _alerts(db)
    assert len(df) == 62
    assert list(df[df["run_id"] == 2]["alert_id"]) == list(range(32, 63))
    again = query(db, "SELECT * FROM alerts WHERE run_id = 1 ORDER BY alert_id")
    pd.testing.assert_frame_equal(first_rows, again)
    assert _tuples(db, 1) == _tuples(db, 2)
    assert _evidence_pairs(db, 1) == _evidence_pairs(db, 2)
    current = query(db, "SELECT alert_id, run_id FROM alerts_current")
    assert len(current) == 31
    assert set(current["run_id"]) == {2}
    assert len(_audit(db)) - audit_before == 32


def test_ac8_as_of_and_record_run_for_network_alerts(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    run_monitoring(db, settings)
    run_monitoring(db, settings)
    keys_run1 = {k for k, *_ in _tuples(db, 1)}

    third = run_monitoring(db, settings, as_of=date(2026, 3, 31))
    assert third.run_id == 3
    assert (third.alerts, third.evidence) == (6, 26)
    assert third.by_rule == {
        "STRUCTURING": 2,
        "RAPID_MOVEMENT": 4,
        "HIGH_VELOCITY": 0,
        "FAN_IN": 0,
        "FAN_OUT": 0,
        "DORMANT_REACTIVATION": 0,
    }
    runs = query(db, "SELECT * FROM monitoring_runs WHERE run_id = 3")
    assert len(runs) == 6
    assert sorted(int(a) for a in runs["alerts"]) == [0, 0, 0, 0, 2, 4]
    current = query(db, "SELECT alert_key, rule_id, subject_id FROM alerts_current")
    assert len(current) == 6
    rapid = current[current["rule_id"] == "RAPID_MOVEMENT"]
    assert set(rapid["subject_id"]) == {
        "A1070944972",
        "A1425071026",
        "A4750305205",
        "A9586661327",
    }
    assert set(current["alert_key"]) <= keys_run1

    recording = mod("aml.monitoring.recording")
    audit_before = len(_audit(db))
    run_id = recording.record_run(
        db,
        as_of=date(2026, 6, 30),
        source="NETWORK",
        rules=[recording.RuleRun("NET_TEST", "v0", {"k": 1})],
        alerts=[
            recording.AlertRecord(
                rule_id="NET_TEST",
                rule_version="v0",
                subject_type="ACCOUNT_GROUP",
                subject_id="GRP-A1070944972",
                accounts=(("A1070944972", "MEMBER"), ("A1425071026", "MEMBER")),
                window_start=datetime(2026, 3, 1),
                window_end=datetime(2026, 3, 2),
                txn_ids=("T0000000528",),
                amount_vnd=1,
                reason="test group",
                details={"size": 2},
                alert_key="NET_TEST|GRP-A1070944972|2026-03-01T00:00:00",
            )
        ],
    )
    assert run_id == 4
    row = query(db, "SELECT * FROM alerts WHERE alert_id = 69").iloc[0]
    assert row["source"] == "NETWORK"
    members = query(db, "SELECT account_id, cif FROM alert_accounts WHERE alert_id = 69")
    assert sorted(zip(members["account_id"], members["cif"], strict=True)) == [
        ("A1070944972", "CIF00000070"),
        ("A1425071026", "CIF00000169"),
    ]
    assert scalar(db, "SELECT COUNT(*) FROM alert_evidence WHERE alert_id = 69") == 1
    current = query(db, "SELECT source FROM alerts_current")
    assert len(current) == 7
    assert sorted(current["source"]) == ["NETWORK"] + ["RULE"] * 6
    assert len(_audit(db)) - audit_before == 2


def test_ac8_without_data_raises_and_writes_nothing(duck: DuckDb) -> None:
    mod("aml.dba.schema").apply_schema(duck)
    error = mod("aml.monitoring.runner").MonitoringError
    with pytest.raises(error, match="run `aml load` first"):
        run_monitoring(duck, duck_settings())
    assert scalar(duck, "SELECT COUNT(*) FROM monitoring_runs") == 0
    assert scalar(duck, "SELECT COUNT(*) FROM alerts") == 0
    assert scalar(duck, "SELECT COUNT(*) FROM audit_log WHERE module = 'monitoring'") == 0
