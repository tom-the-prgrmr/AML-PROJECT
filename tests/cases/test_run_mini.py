"""AC3 for specs/case-consolidation.md: `run_cases` on MINI-C."""

from __future__ import annotations

from datetime import date

import pandas as pd

from aml.common.db import DuckDb

from .helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    N1_KEY,
    cases_current,
    count,
    duck_settings,
    js,
    query,
    run_cases,
    ts,
)

EXPECTED_CASES = {
    CASE_C01_A: ("G-C01", 3, 2, 1, 0, "NETWORK+RULE"),
    CASE_C01_B: ("G-C01", 2, 1, 0, 1, "RULE+SCREENING"),
    CASE_C03: ("G-C03", 2, 1, 1, 0, "NETWORK+RULE"),
    CASE_C04: ("G-C04", 1, 0, 1, 0, "NETWORK"),
    CASE_C05: ("G-C05", 1, 0, 0, 1, "SCREENING"),
}


def test_ac3_run_summary(minic: DuckDb) -> None:
    run = run_cases(minic, duck_settings())
    assert run.run_id == 1
    assert run.as_of == date(2026, 6, 30)
    assert (run.items, run.alerts, run.suppressed, run.active) == (9, 7, 0, 9)
    assert (run.cases, run.opened, run.reopened, run.closed) == (5, 5, 0, 0)


def test_ac3_cases_current_rows(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    got = cases_current(minic)
    assert set(got) == set(EXPECTED_CASES)
    for case_id, want in EXPECTED_CASES.items():
        row = got[case_id]
        have = (
            row.golden_customer_id,
            row.alerts,
            row.rule_alerts,
            row.network_alerts,
            row.screening_alerts,
            row.sources,
        )
        assert have == want, case_id
        assert row.status == "OPEN", case_id


def test_ac3_case_reason_and_timestamps(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    row = cases_current(minic)[CASE_C01_A]
    assert pd.Timestamp(row.first_alert_ts) == ts("2026-03-02 09:00:00")
    assert pd.Timestamp(row.last_alert_ts) == ts("2026-04-20 12:00:00")
    assert row.reason == (
        "3 alert(s) (2 RULE, 1 NETWORK, 0 SCREENING) on G-C01 between "
        "2026-03-02 09:00:00 and 2026-04-20 12:00:00; window of 90 days from the first alert"
    )


def test_ac3_case_alerts_current(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    df = query(minic, "SELECT * FROM case_alerts_current")
    assert len(df) == 9
    assert set(df["status"]) == {"ACTIVE"}
    assert set(df["retriggered"]) == {0}
    assert df["suppression_rule"].isna().all()
    assert df["suppression_reason"].isna().all()
    assert "C06" not in set(df["cif"])  # the AUTO_CLEARED pair is not an item

    n1 = df[df["item_key"] == N1_KEY]
    assert sorted(n1["golden_customer_id"]) == ["G-C01", "G-C03", "G-C04"]
    n1_c03 = n1[n1["golden_customer_id"] == "G-C03"].iloc[0]
    assert js(n1_c03["details"]) == {"subject_type": "ACCOUNT_GROUP", "roles": ["HOP"]}


def test_ac3_screening_item_row(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    df = query(minic, "SELECT * FROM case_alerts_current WHERE item_key = 'SCREENING|C02|WL1'")
    assert len(df) == 1
    row = df.iloc[0]
    assert row["golden_customer_id"] == "G-C01"
    assert row["alert_ref"] == "C02:WL1"
    assert row["source"] == "SCREENING"
    assert row["rule_id"] == "SCREENING_ALERT"
    assert row["cif"] == "C02"
    assert row["entry_id"] == "WL1"
    assert pd.Timestamp(row["event_ts"]) == ts("2026-06-30 00:00:00")
    assert row["case_id"] == CASE_C01_B
    assert js(row["details"]) == {
        "decision": "ALERT",
        "list_type": "SANCTIONS",
        "final_score": 100.0,
    }


def test_ac3_rule_alert_on_second_cif_goes_to_the_golden_customer(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    df = query(minic, "SELECT * FROM case_alerts_current WHERE rule_id = 'RAPID_MOVEMENT'")
    assert len(df) == 1  # R2 sits on A02, owned by C02
    assert df.iloc[0]["golden_customer_id"] == "G-C01"
    assert df.iloc[0]["case_id"] == CASE_C01_A
    assert df.iloc[0]["cif"] == "C02"


def test_ac3_as_of_cutoff_drops_later_items(minic: DuckDb) -> None:
    settings = duck_settings()
    run_cases(minic, settings)
    run = run_cases(minic, settings, as_of=date(2026, 5, 30))
    assert (run.run_id, run.items, run.cases) == (2, 6, 3)


def test_ac3_window_365_merges_into_four_cases(minic: DuckDb) -> None:
    run = run_cases(minic, duck_settings(AML__CASES__WINDOW_DAYS="365"))
    assert run.cases == 4
    assert cases_current(minic)[CASE_C01_A].alerts == 5


def test_ac3_source_tables_are_not_modified(minic: DuckDb) -> None:
    before = (count(minic, "alerts"), count(minic, "screening_results"))
    run_cases(minic, duck_settings())
    assert (count(minic, "alerts"), count(minic, "screening_results")) == before


def test_ac3_run_row(minic: DuckDb) -> None:
    run_cases(minic, duck_settings())
    assert count(minic, "case_runs") == 1
    row = query(minic, "SELECT * FROM case_runs").iloc[0]
    assert (row["items"], row["alerts"], row["cases"], row["window_days"]) == (9, 7, 5, 90)
    assert row["version"] == "cases/v1"
    assert len(row["config_hash"]) == 16
