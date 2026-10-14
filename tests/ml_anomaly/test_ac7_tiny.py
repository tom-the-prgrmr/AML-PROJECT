"""AC7 for specs/ml-anomaly.md: `run_anomaly` and `evaluate_anomaly` on TINY (seed 42)."""

from __future__ import annotations

import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from aml.common.db import Database, DuckDb
from aml.datagen.activity import TYPOLOGY_KEYS

from .helpers import duck_settings, evaluate, mod, query, run_anomaly

KEY = re.compile(r"^ML_ANOMALY\|[^|]+\|2026-0[1-6]$")


@pytest.fixture
def tiny(tiny_cases: DuckDb) -> SimpleNamespace:
    settings = duck_settings()
    r = run_anomaly(tiny_cases, settings)
    e = evaluate().evaluate_anomaly(tiny_cases, settings)
    return SimpleNamespace(db=tiny_cases, settings=settings, r=r, e=e)


def test_ac7_run_summary(tiny: SimpleNamespace) -> None:
    r = tiny.r
    assert r.samples == 1334
    assert r.customers <= 300
    assert r.alerts == 7 == mod("aml.ml.anomaly.model").alert_count(1334, 0.005)
    assert r.graph_source == "networkx"
    assert r.months == 6


def test_ac7_ranks_and_threshold(tiny: SimpleNamespace) -> None:
    df = query(tiny.db, f"SELECT * FROM anomaly_scores WHERE run_id = {tiny.r.run_id}")
    assert len(df) == 1334
    alerted = df[df["alerted"] == 1].sort_values("rank")
    assert list(alerted["rank"]) == list(range(1, 8))
    assert alerted["score"].is_monotonic_decreasing
    rest = df[df["alerted"] == 0]
    assert (rest["rank"] > 7).all()
    assert (rest["score"] <= tiny.r.threshold).all()
    assert alerted["score"].iloc[-1] == pytest.approx(tiny.r.threshold, abs=1e-9)


def test_ac7_the_seven_alerts(tiny: SimpleNamespace) -> None:
    db, r = tiny.db, tiny.r
    alerts = query(db, "SELECT * FROM alerts_current WHERE source = 'ANOMALY'")
    assert len(alerts) == 7
    for a in alerts.itertuples():
        assert KEY.match(a.alert_key), a.alert_key
        assert f"model anomaly/v1/{r.run_id}" in a.reason
        assert a.txn_count >= 1
        _, cif, month = a.alert_key.split("|")
        assert a.subject_id == cif
        evidence = query(
            db,
            "SELECT t.txn_id, t.txn_ts, o.cif AS from_cif, d.cif AS to_cif "
            "FROM alert_evidence e JOIN transactions t ON t.txn_id = e.txn_id "
            "LEFT JOIN accounts o ON o.account_id = t.from_account_id "
            "LEFT JOIN accounts d ON d.account_id = t.to_account_id "
            f"WHERE e.alert_id = {a.alert_id}",
        )
        assert len(evidence) == a.txn_count
        for row in evidence.itertuples():
            assert cif in (row.from_cif, row.to_cif)
            assert f"{row.txn_ts:%Y-%m}" == month


def _independent_coverage(db: Database, e: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    """Recompute the sets behind each coverage row with plain Python loops."""
    rule_accounts = set(
        query(
            db,
            "SELECT DISTINCT aa.account_id FROM alerts_current a "
            "JOIN alert_accounts aa ON aa.alert_id = a.alert_id "
            "WHERE a.source IN ('RULE', 'NETWORK')",
        )["account_id"]
    )
    flagged = [
        (r.cif, r.month)
        for r in query(
            db, "SELECT cif, month FROM anomaly_scores_current WHERE alerted = 1"
        ).itertuples()
    ]
    truth = query(
        db,
        "SELECT g.scenario_id, g.typology, g.entity_id, g.start_ts, g.end_ts, a.cif "
        "FROM ground_truth g JOIN accounts a ON a.account_id = g.entity_id "
        "WHERE g.entity_type = 'account'",
    )
    out: dict[str, dict[str, set[str]]] = {}
    for typology in TYPOLOGY_KEYS:
        mine = truth[truth["typology"] == typology]
        sets: dict[str, set[str]] = {
            "scenarios": set(mine["scenario_id"]),
            "rules": set(),
            "anomaly": set(),
            "accounts": set(mine["entity_id"]),
            "accounts_rules": set(),
            "accounts_anomaly": set(),
        }
        for row in mine.itertuples():
            if row.entity_id in rule_accounts:
                sets["rules"].add(row.scenario_id)
                sets["accounts_rules"].add(row.entity_id)
            for cif, month in flagged:
                first = datetime.strptime(month, "%Y-%m")
                after = datetime(first.year + (first.month == 12), first.month % 12 + 1, 1)
                if cif == row.cif and first <= row.end_ts and after > row.start_ts:
                    sets["anomaly"].add(row.scenario_id)
                    sets["accounts_anomaly"].add(row.entity_id)
        out[typology] = sets
    return out


def test_ac7_coverage_columns_and_order(tiny: SimpleNamespace) -> None:
    coverage = tiny.e["coverage"]
    assert [row["typology"] for row in coverage] == list(TYPOLOGY_KEYS)
    assert all(list(row) == evaluate().COVERAGE_COLUMNS for row in coverage)
    frame = evaluate().anomaly_coverage(tiny.db)
    assert list(frame.columns) == evaluate().COVERAGE_COLUMNS
    assert len(frame) == 6


def test_ac7_the_rules_already_catch_every_suspicious_scenario(tiny: SimpleNamespace) -> None:
    for row in tiny.e["coverage"]:
        if row["is_suspicious"]:
            assert row["flagged_rules"] == row["scenarios"], row["typology"]
            assert row["new_by_anomaly"] == 0, row["typology"]
    assert tiny.e["suspicious"]["new_by_anomaly"] == 0


def test_ac7_coverage_arithmetic_matches_an_independent_computation(tiny: SimpleNamespace) -> None:
    mine = _independent_coverage(tiny.db, tiny.e)
    for row in tiny.e["coverage"]:
        s = mine[row["typology"]]
        assert row["scenarios"] == len(s["scenarios"])
        assert row["flagged_rules"] == len(s["rules"])
        assert row["flagged_anomaly"] == len(s["anomaly"])
        assert row["flagged_any"] == len(s["rules"] | s["anomaly"])
        assert row["new_by_anomaly"] == len(s["anomaly"] - s["rules"])
        assert row["new_by_anomaly"] == row["flagged_any"] - row["flagged_rules"]
        assert row["accounts"] == len(s["accounts"])
        assert row["accounts_rules"] == len(s["accounts_rules"])
        assert row["accounts_anomaly"] == len(s["accounts_anomaly"])
        both = len(s["accounts_anomaly"] & s["accounts_rules"])
        assert row["accounts_new"] == row["accounts_anomaly"] - both


def test_ac7_summary_blocks(tiny: SimpleNamespace) -> None:
    e = tiny.e
    assert e["model_version"] == tiny.r.model_version
    assert sum(e["alerts_by_kind"].values()) == 7
    assert set(e["alerts_by_kind"]) == {"suspicious", "benign", "scenario_other_month", "none"}
    assert e["samples"] == 1334 and e["alerts"] == 7
    assert e["suspicious"]["scenarios"] == sum(
        r["scenarios"] for r in e["coverage"] if r["is_suspicious"]
    )
    assert e["benign"]["scenarios"] == sum(
        r["scenarios"] for r in e["coverage"] if not r["is_suspicious"]
    )
    assert 0 <= e["alerts_on_rule_alerted_customers"] <= 7


def test_ac7_anomaly_items_reach_the_cases_and_their_labels(tiny: SimpleNamespace) -> None:
    db = tiny.db
    mod("aml.cases.runner").run_cases(db, tiny.settings)
    items = query(db, "SELECT * FROM case_alerts_current WHERE source = 'ANOMALY'")
    assert len(items) == 7
    expected = set(
        query(
            db,
            "SELECT DISTINCT ca.case_id FROM case_alerts_current ca "
            "JOIN alert_accounts aa ON CAST(aa.alert_id AS VARCHAR) = ca.alert_ref "
            "LEFT JOIN customer_golden g ON g.cif = aa.cif "
            "JOIN ground_truth gt ON gt.entity_type = 'account' AND gt.entity_id = aa.account_id "
            "WHERE ca.source = 'ANOMALY' AND gt.is_suspicious "
            "AND COALESCE(g.golden_customer_id, 'G-' || aa.cif) = ca.golden_customer_id",
        )["case_id"]
    )
    assert expected, "the fixture must hold a case worth checking"
    labels = mod("aml.cases.labels").truth_labels(db)
    for case_id in expected:
        assert labels[case_id].disposition == "SUSPICIOUS", case_id


def test_ac7_a_second_run_gives_the_same_scores(tiny: SimpleNamespace) -> None:
    second = run_anomaly(tiny.db, tiny.settings)
    assert second.data_hash == tiny.r.data_hash
    keys = "cif, month, score, rank, alerted"
    one = query(
        tiny.db,
        f"SELECT {keys} FROM anomaly_scores WHERE run_id = {tiny.r.run_id} ORDER BY cif, month",
    )
    two = query(
        tiny.db,
        f"SELECT {keys} FROM anomaly_scores WHERE run_id = {second.run_id} ORDER BY cif, month",
    )
    assert len(one) == len(two) == 1334
    pd.testing.assert_frame_equal(one, two)
