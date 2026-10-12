"""AC7 for specs/network-detections.md: `run_network` stores alerts via `record_run` (DuckDB)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    AS_OF,
    HUB_TINY,
    RULE_IDS,
    SHR_TINY,
    count,
    duck_settings,
    js,
    load_tiny_duck,
    mod,
    network_error,
    query,
    run_monitoring,
    run_network,
    scalar,
    ts,
)

CLUSTER_ALERT_KEY = f"NET_SHARED_ATTRIBUTE|{SHR_TINY}"


def _tuples(db: DuckDb, run_id: int) -> set[tuple[Any, ...]]:
    df = query(
        db,
        f"SELECT alert_key, reason, txn_count, amount_vnd FROM alerts WHERE run_id = {run_id}",
    )
    return {(r.alert_key, r.reason, int(r.txn_count), int(r.amount_vnd)) for r in df.itertuples()}


def _evidence_pairs(db: DuckDb, run_id: int) -> set[tuple[str, str]]:
    df = query(
        db,
        "SELECT a.alert_key, e.txn_id FROM alerts a JOIN alert_evidence e "
        f"ON e.alert_id = a.alert_id WHERE a.run_id = {run_id}",
    )
    return {(r.alert_key, r.txn_id) for r in df.itertuples()}


def _alert_rows(db: DuckDb, run_id: int) -> pd.DataFrame:
    return query(db, f"SELECT * FROM alerts WHERE run_id = {run_id} ORDER BY alert_id")


def _assert_run(run: Any, run_id: int) -> None:
    assert run.run_id == run_id
    assert run.as_of == AS_OF
    assert run.alerts == 4
    assert run.evidence == 67
    assert run.by_rule == {"NET_SHARED_ATTRIBUTE": 1, "NET_CYCLE": 2, "NET_HUB": 1}
    assert list(run.by_rule) == list(RULE_IDS)
    assert run.accounts == 532
    assert run.active_accounts == 298
    assert run.cycle_search_steps == 12


# ----------------------------------------------------------------------------- first run
def test_ac7_first_run_summary(tiny_er: DuckDb) -> None:
    _assert_run(run_network(tiny_er, duck_settings()), 1)


def test_ac7_first_run_alerts_table(tiny_er: DuckDb) -> None:
    run_network(tiny_er, duck_settings())
    alerts = query(tiny_er, "SELECT * FROM alerts ORDER BY alert_id")
    assert list(alerts["alert_id"]) == [1, 2, 3, 4]
    assert set(alerts["run_id"]) == {1}
    assert set(alerts["source"]) == {"NETWORK"}
    assert list(alerts["rule_id"]) == ["NET_SHARED_ATTRIBUTE", "NET_CYCLE", "NET_CYCLE", "NET_HUB"]
    assert list(alerts["subject_type"]) == [
        "ACCOUNT_GROUP",
        "ACCOUNT_GROUP",
        "ACCOUNT_GROUP",
        "ACCOUNT",
    ]
    assert [int(v) for v in alerts["txn_count"]] == [28, 4, 4, 31]


def test_ac7_first_run_alert_accounts_and_evidence(tiny_er: DuckDb) -> None:
    run_network(tiny_er, duck_settings())
    accounts = query(tiny_er, "SELECT * FROM alert_accounts")
    assert len(accounts) == 62
    assert accounts["role"].value_counts().to_dict() == {
        "MEMBER": 53,
        "HOP": 6,
        "ORIGIN": 2,
        "SUBJECT": 1,
    }
    assert accounts["account_id"].nunique() == 61
    hub = accounts[(accounts["alert_id"] == 4) & (accounts["account_id"] == HUB_TINY)]
    assert list(hub["cif"]) == ["CIF00000189"]
    origin = accounts[(accounts["alert_id"] == 2) & (accounts["role"] == "ORIGIN")]
    assert list(origin["account_id"]) == ["A8201784530"]
    assert list(origin["cif"]) == ["CIF00000206"]

    evidence = query(tiny_er, "SELECT * FROM alert_evidence")
    assert len(evidence) == 67
    assert evidence["txn_id"].nunique() == 39


def test_ac7_first_run_monitoring_runs_rows(tiny_er: DuckDb) -> None:
    settings = duck_settings()
    run_network(tiny_er, settings)
    runs = query(tiny_er, "SELECT * FROM monitoring_runs ORDER BY rule_id")
    assert list(runs["rule_id"]) == sorted(RULE_IDS)
    assert set(runs["run_id"]) == {1}
    assert set(runs["source"]) == {"NETWORK"}
    assert {pd.Timestamp(v).date() for v in runs["as_of"]} == {date(2026, 6, 30)}
    got = {r.rule_id: (int(r.alerts), int(r.evidence)) for r in runs.itertuples()}
    assert got == {"NET_SHARED_ATTRIBUTE": (1, 28), "NET_CYCLE": (2, 8), "NET_HUB": (1, 31)}
    cycle = runs[runs["rule_id"] == "NET_CYCLE"].iloc[0]
    expected = mod("aml.graph.network.rules").network_rule_params("NET_CYCLE", settings)
    assert js(cycle["params"]) == expected


def test_ac7_first_run_features_table(tiny_er: DuckDb) -> None:
    run_network(tiny_er, duck_settings())
    assert count(tiny_er, "nx_account_features", "WHERE run_id = 1") == 532
    assert count(tiny_er, "nx_account_features") == 532
    row = query(tiny_er, f"SELECT * FROM nx_account_features WHERE account_id = '{HUB_TINY}'").iloc[
        0
    ]
    assert int(row["in_degree"]) == 31
    assert int(row["out_degree"]) == 3
    assert int(row["in_vnd"]) == 2_930_380_000
    assert int(row["out_vnd"]) == 2_851_894_000
    assert round(float(row["pagerank_ratio"]), 2) == 6.77
    assert row["shared_cluster_id"] == SHR_TINY
    assert int(row["is_hub"]) == 1


def test_ac7_first_run_audit_trail_is_written_by_record_run(tiny_er: DuckDb) -> None:
    run_network(tiny_er, duck_settings())
    audit = query(
        tiny_er,
        "SELECT entity_type, entity_id, decision, reason, version, details FROM audit_log "
        "WHERE module = 'monitoring' ORDER BY audit_id",
    )
    assert len(audit) == 5
    assert list(audit["decision"]).count("ALERT") == 4
    assert list(audit["decision"]).count("MONITORING_RUN_COMPLETED") == 1
    alert2 = audit[(audit["decision"] == "ALERT") & (audit["entity_id"] == "2")].iloc[0]
    assert alert2["version"] == "NET_CYCLE/v1"
    stored = scalar(tiny_er, "SELECT reason FROM alerts WHERE alert_id = 2")
    assert alert2["reason"] == stored
    done = audit[audit["decision"] == "MONITORING_RUN_COMPLETED"].iloc[0]
    assert done["entity_id"] == "1"
    details = js(done["details"])
    assert details["source"] == "NETWORK"
    assert details["alerts"] == 4


# ----------------------------------------------------------------------------- re-runs
def test_ac7_second_run_after_monitoring_is_a_new_run_with_same_content(tiny_er: DuckDb) -> None:
    settings = duck_settings()
    first = run_network(tiny_er, settings)
    snapshot = _alert_rows(tiny_er, 1)
    mon = run_monitoring(tiny_er, settings)
    assert (mon.run_id, mon.alerts) == (2, 31)
    third = run_network(tiny_er, settings)
    _assert_run(first, 1)
    _assert_run(third, 3)

    ids = list(
        query(tiny_er, "SELECT alert_id FROM alerts WHERE run_id = 3 ORDER BY alert_id")["alert_id"]
    )
    assert ids == [36, 37, 38, 39]
    assert _tuples(tiny_er, 1) == _tuples(tiny_er, 3)
    assert _evidence_pairs(tiny_er, 1) == _evidence_pairs(tiny_er, 3)
    pd.testing.assert_frame_equal(_alert_rows(tiny_er, 1), snapshot)  # append-only

    assert count(tiny_er, "alerts_current") == 35
    assert count(tiny_er, "alerts_current", "WHERE source = 'RULE'") == 31
    assert count(tiny_er, "alerts_current", "WHERE source = 'NETWORK' AND run_id = 3") == 4
    assert count(tiny_er, "nx_account_features") == 1064
    assert count(tiny_er, "nx_account_features_current") == 532
    assert set(query(tiny_er, "SELECT run_id FROM nx_account_features_current")["run_id"]) == {3}


def test_ac7_run_before_the_ring_is_active_keeps_an_empty_cluster_alert(tiny_er: DuckDb) -> None:
    settings = duck_settings()
    run_network(tiny_er, settings)
    run_monitoring(tiny_er, settings)
    run_network(tiny_er, settings)
    run = run_network(tiny_er, settings, as_of=date(2026, 3, 26))
    assert run.run_id == 4
    assert run.alerts == 1
    assert run.evidence == 0
    assert run.by_rule == {"NET_SHARED_ATTRIBUTE": 1, "NET_CYCLE": 0, "NET_HUB": 0}

    alert = _alert_rows(tiny_er, 4)
    assert len(alert) == 1
    row = alert.iloc[0]
    assert row["alert_key"] == CLUSTER_ALERT_KEY
    assert int(row["txn_count"]) == 0
    assert int(row["amount_vnd"]) == 0
    assert pd.Timestamp(row["window_start"]) == pd.Timestamp(row["window_end"])
    assert pd.Timestamp(row["window_start"]) == ts("2026-03-26 00:00:00")
    assert row["reason"].endswith("no transfers between members")
    alert_id = int(row["alert_id"])
    assert count(tiny_er, "alert_accounts", f"WHERE alert_id = {alert_id}") == 53
    assert count(tiny_er, "alert_evidence", f"WHERE alert_id = {alert_id}") == 0

    runs = query(tiny_er, "SELECT alerts FROM monitoring_runs WHERE run_id = 4")
    assert len(runs) == 3
    assert sorted(int(v) for v in runs["alerts"]) == [0, 0, 1]
    assert count(tiny_er, "alerts_current") == 32
    assert count(tiny_er, "alerts_current", "WHERE source = 'RULE'") == 31
    assert count(tiny_er, "alerts_current", "WHERE source = 'NETWORK'") == 1


# ----------------------------------------------------------------------------- errors
def _assert_nothing_written(db: DuckDb) -> None:
    for table in ("alerts", "monitoring_runs", "nx_account_features"):
        assert count(db, table) == 0, table
    assert count(db, "audit_log", "WHERE module = 'monitoring'") == 0


def test_ac7_without_load_raises_and_writes_nothing(duck: DuckDb) -> None:
    mod("aml.dba.schema").apply_schema(duck)
    with pytest.raises(network_error(), match="run `aml load` first"):
        run_network(duck, duck_settings())
    _assert_nothing_written(duck)


def test_ac7_without_er_raises_and_writes_nothing(tiny_parquet: Path, tmp_path: Path) -> None:
    db = load_tiny_duck(tiny_parquet, tmp_path / "loaded.duckdb")
    try:
        with pytest.raises(network_error(), match="run `aml er` first"):
            run_network(db, duck_settings())
        _assert_nothing_written(db)
    finally:
        db.close()
