"""AC8 for specs/case-consolidation.md: `run_cases` on TINY (seed 42)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    TINY_CASE,
    cases_current,
    duck_settings,
    enrichment,
    query,
    run_cases,
    ts,
)


@pytest.fixture
def tiny_run(tiny_cases: DuckDb) -> tuple[DuckDb, Any]:
    return tiny_cases, run_cases(tiny_cases, duck_settings())


def test_ac8_run_summary(tiny_run: tuple[DuckDb, Any]) -> None:
    _, run = tiny_run
    assert run.items == 74
    assert run.alerts == 40
    assert run.active == 74
    assert run.cases == 52
    assert run.opened == 52
    assert run.graph_source == "networkx"


def test_ac8_case_distribution(tiny_run: tuple[DuckDb, Any]) -> None:
    db, _ = tiny_run
    df = query(db, "SELECT * FROM cases_current")
    assert len(df) == 52
    assert df["golden_customer_id"].nunique() == 52
    assert df["sources"].value_counts().to_dict() == {
        "NETWORK": 27,
        "RULE": 11,
        "NETWORK+RULE": 9,
        "SCREENING": 4,
        "NETWORK+SCREENING": 1,
    }
    assert df["alerts"].value_counts().to_dict() == {1: 38, 2: 9, 3: 3, 4: 1, 5: 1}
    assert int(df["alerts"].sum()) == 74


def test_ac8_case_alerts_by_source_and_referential_integrity(
    tiny_run: tuple[DuckDb, Any],
) -> None:
    db, _ = tiny_run
    df = query(db, "SELECT source, COUNT(*) AS n FROM case_alerts_current GROUP BY source")
    assert dict(zip(df["source"], df["n"], strict=True)) == {
        "RULE": 31,
        "NETWORK": 38,
        "SCREENING": 5,
    }
    orphans = query(
        db,
        "SELECT COUNT(*) AS n FROM case_alerts_current a "
        "WHERE a.case_id NOT IN (SELECT case_id FROM cases_current)",
    )
    assert int(orphans.iloc[0]["n"]) == 0


def test_ac8_collector_case(tiny_run: tuple[DuckDb, Any]) -> None:
    db, _ = tiny_run
    row = cases_current(db)[TINY_CASE]
    assert row.alerts == 5
    assert pd.Timestamp(row.first_alert_ts) == ts("2026-04-13 09:28:12")
    assert pd.Timestamp(row.last_alert_ts) == ts("2026-04-18 10:04:12")
    rules = query(db, f"SELECT rule_id FROM case_alerts_current WHERE case_id = '{TINY_CASE}'")
    assert sorted(rules["rule_id"]) == sorted(
        ["FAN_IN", "NET_HUB", "HIGH_VELOCITY", "NET_SHARED_ATTRIBUTE", "RAPID_MOVEMENT"]
    )


def test_ac8_collector_txn_summary(tiny_run: tuple[DuckDb, Any]) -> None:
    db, _ = tiny_run
    t = enrichment(db, TINY_CASE)["txn_summary"]
    want = {
        "window_start": "2026-01-19",
        "window_end": "2026-04-18",
        "txn_count": 34,
        "in_count": 31,
        "out_count": 3,
        "in_vnd": 2_930_380_000,
        "out_vnd": 2_851_894_000,
        "cash_in_vnd": 0,
        "counterparties": 34,
        "max_txn_vnd": 1_019_225_000,
        "active_days": 5,
    }
    for key, value in want.items():
        assert t[key] == value, key


def test_ac8_collector_network(tiny_run: tuple[DuckDb, Any]) -> None:
    db, _ = tiny_run
    net = enrichment(db, TINY_CASE)["network"]
    f = net["features"]
    assert (f["in_degree"], f["out_degree"]) == (31, 3)
    assert f["pagerank_ratio"] == pytest.approx(6.7651, abs=1e-4)
    assert f["shared_cluster_id"] == "SHARED-CIF00000002"
    assert f["shared_cluster_size"] == 29
    assert f["is_hub"] == 1
    assert len(net["shared_alert_cases"]) == 28


def test_ac8_screening_plus_network_case(tiny_run: tuple[DuckDb, Any]) -> None:
    db, _ = tiny_run
    row = cases_current(db)["C-CIF00000104-20260416"]
    assert row.sources == "NETWORK+SCREENING"
    assert row.alerts == 2


def test_ac8_window_30_days_splits_one_customer(tiny_cases: DuckDb) -> None:
    run = run_cases(tiny_cases, duck_settings(AML__CASES__WINDOW_DAYS="30"))
    assert run.cases == 53
    got = cases_current(tiny_cases)
    mine = sorted(c for c, r in got.items() if r.golden_customer_id == "G-CIF00000104")
    assert mine == ["C-CIF00000104-20260416", "C-CIF00000104-20260630"]
