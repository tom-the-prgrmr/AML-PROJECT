"""AC6 for specs/ml-anomaly.md: an ANOMALY alert is a fourth source of the case run."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.cases.summary_template import render_summary
from aml.common.db import DuckDb
from aml.dba.schema import apply_schema
from tests.cases.helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    MINI_CASES,
    cases_current,
    duck_settings,
    js,
    load_case,
    load_minic,
    mod,
    query,
    run_cases,
    ts,
)

from .helpers import anom_settings, run_anomaly

AS_OF = date(2026, 6, 30)
REASON_A = (
    "4 alert(s) (2 RULE, 1 NETWORK, 0 SCREENING, 1 ANOMALY) on G-C01 between "
    "2026-03-02 09:00:00 and 2026-04-20 12:00:00; window of 90 days from the first alert"
)


@pytest.fixture
def built(minic: DuckDb) -> tuple[DuckDb, Any]:
    settings = anom_settings()
    run_anomaly(minic, settings)
    return minic, run_cases(minic, settings)


def test_ac6_run_counts_and_case_ids(built: tuple[DuckDb, Any]) -> None:
    db, run = built
    assert (run.items, run.alerts, run.cases) == (10, 8, 5)
    assert set(cases_current(db)) == set(MINI_CASES)


def test_ac6_the_case_of_the_anomaly_customer(built: tuple[DuckDb, Any]) -> None:
    db, _ = built
    row = cases_current(db)[CASE_C01_A]
    assert (row.alerts, row.rule_alerts, row.network_alerts, row.screening_alerts) == (4, 2, 1, 0)
    assert row.sources == "ANOMALY+NETWORK+RULE"
    assert row.reason == REASON_A


def test_ac6_other_cases_keep_their_reason_without_the_word_anomaly(
    built: tuple[DuckDb, Any], tmp_path: Path
) -> None:
    db, _ = built
    plain = DuckDb(tmp_path / "plain.duckdb")
    try:
        load_minic(plain)
        run_cases(plain, duck_settings())
        want = {c: r.reason for c, r in cases_current(plain).items()}
    finally:
        plain.close()
    got = cases_current(db)
    for case_id in (CASE_C01_B, CASE_C03, CASE_C04, CASE_C05):
        assert got[case_id].reason == want[case_id], case_id
        assert "ANOMALY" not in got[case_id].reason


def test_ac6_the_anomaly_item(built: tuple[DuckDb, Any]) -> None:
    db, _ = built
    df = query(db, "SELECT * FROM case_alerts_current WHERE item_key = 'ML_ANOMALY|C01|2026-03'")
    assert len(df) == 1
    row = df.iloc[0]
    assert (row["source"], row["rule_id"], row["cif"]) == ("ANOMALY", "ML_ANOMALY", "C01")
    assert (row["case_id"], row["status"]) == (CASE_C01_A, "ACTIVE")
    assert js(row["details"]) == {"subject_type": "CUSTOMER", "roles": ["SUBJECT"]}
    assert pd.Timestamp(row["event_ts"]) == ts("2026-03-02 09:00:00")


def test_ac6_summary_alert_line_counts_the_anomaly_item(built: tuple[DuckDb, Any]) -> None:
    db, _ = built
    lines = render_summary(load_case(db, CASE_C01_A)).splitlines()
    assert any(
        ln.startswith("- Alerts: 4 (2 RULE, 1 NETWORK, 0 SCREENING, 1 ANOMALY)") for ln in lines
    )
    other = render_summary(load_case(db, CASE_C04)).splitlines()
    assert any(ln.startswith("- Alerts: 1 (0 RULE, 1 NETWORK, 0 SCREENING)") for ln in other)
    assert not any("ANOMALY" in ln for ln in other if ln.startswith("- Alerts:"))


def test_ac6_the_transaction_window_of_the_case_is_unchanged(built: tuple[DuckDb, Any]) -> None:
    db, _ = built
    txn = query(
        db,
        "SELECT content FROM case_enrichment_current "
        f"WHERE case_id = '{CASE_C01_A}' AND section = 'txn_summary'",
    )
    content = js(txn["content"].iloc[0])
    assert (content["window_start"], content["window_end"]) == ("2026-01-21", "2026-04-20")


def test_ac6_an_anomaly_alert_can_move_the_window_of_a_customer(
    built: tuple[DuckDb, Any],
) -> None:
    db, _ = built
    rec = mod("aml.monitoring.recording")
    moved = rec.AlertRecord(
        rule_id="ML_ANOMALY",
        rule_version="anomaly/v1/9",
        subject_type="CUSTOMER",
        subject_id="C01",
        accounts=(("A01", "SUBJECT"),),
        window_start=ts("2026-01-15 09:00:00"),
        window_end=ts("2026-01-15 09:00:00"),
        txn_ids=("T08",),
        amount_vnd=10_000_000,
        reason="x",
        details={},
        alert_key="ML_ANOMALY|C01|2026-01",
    )
    run = rec.RuleRun("ML_ANOMALY", "anomaly/v1/9", {})
    rec.record_run(db, as_of=AS_OF, source="ANOMALY", rules=[run], alerts=[moved])
    run_cases(db, anom_settings())
    current = cases_current(db)
    g_c01 = {c for c, r in current.items() if r.golden_customer_id == "G-C01"}
    assert g_c01 == {"C-C01-20260115", "C-C01-20260420"}
    items = query(db, "SELECT case_id, rule_id FROM case_alerts_current")
    by_case = {c: set(g["rule_id"]) for c, g in items.groupby("case_id")}
    assert by_case["C-C01-20260115"] == {"ML_ANOMALY", "STRUCTURING", "NET_CYCLE"}
    assert by_case["C-C01-20260420"] == {"RAPID_MOVEMENT", "FAN_OUT", "SCREENING_ALERT"}
    assert CASE_C01_A not in current
    assert "C-C01-20260531" not in current


def test_ac6_cases_table_gets_no_anomaly_column(duck: DuckDb) -> None:
    apply_schema(duck)  # the anomaly source adds no column to cases
    columns = set(
        query(
            duck,
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'cases'",
        )["column_name"]
    )
    assert "anomaly_alerts" not in columns
