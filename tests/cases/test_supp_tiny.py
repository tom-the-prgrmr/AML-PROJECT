"""AC7 for specs/case-suppression.md: suppression on TINY (DuckDb, deterministic)."""

from __future__ import annotations

import re
from typing import Any

from aml.common.db import DuckDb

from .helpers import audit_cases, cases_current, count, duck_settings, mod, query, run_cases
from .supp_helpers import GG_CASE, GG_KEY, day, dispose, good_guys, item, item_set


def _cleared(db: DuckDb) -> tuple[Any, Any]:
    """Run 1, run 2 (no disposition yet), the clearance, run 3."""
    settings = duck_settings()
    run_cases(db, settings)
    run2 = run_cases(db, settings)
    dispose(db, settings, GG_CASE, reason="test clearance")
    return run2, run_cases(db, settings)


def test_ac7_second_run_without_dispositions_suppresses_nothing(tiny_cases: DuckDb) -> None:
    run2, _ = _cleared(tiny_cases)
    assert (run2.suppressed, run2.lifted, run2.cases) == (0, 0, 52)
    assert run2.suppressed_by_rule == {"GOOD_GUY": 0, "HIBERNATION": 0}
    rows = audit_cases(tiny_cases, "decision = 'SUPPRESSED'")
    assert all(d["run_id"] == 3 for d in rows["details"])  # none from runs 1 and 2


def test_ac7_good_guy_row_carries_the_screening_fingerprints(tiny_cases: DuckDb) -> None:
    _cleared(tiny_cases)
    df = good_guys(tiny_cases)
    assert len(df) == 1
    row = df.iloc[0]
    assert (row["cif"], row["entry_id"]) == ("CIF00000041", "WL000199")
    state = mod("aml.screening.state").read_state(tiny_cases)
    assert row["customer_fingerprint"] == state["customer"]["CIF00000041"]
    assert row["entry_fingerprint"] == state["watchlist_entry"]["WL000199"]
    for column in ("customer_fingerprint", "entry_fingerprint"):
        assert re.fullmatch(r"[0-9a-f]{64}", row[column]), column
    assert day(row["expires_on"]).isoformat() == "2027-06-30"


def test_ac7_third_run_numbers(tiny_cases: DuckDb) -> None:
    _, run3 = _cleared(tiny_cases)
    assert (run3.items, run3.suppressed, run3.active, run3.cases) == (74, 1, 73, 51)
    assert run3.suppressed_by_rule == {"GOOD_GUY": 1, "HIBERNATION": 0}
    assert GG_CASE not in cases_current(tiny_cases)
    row = item(tiny_cases, GG_KEY)
    assert (row["status"], row["suppression_rule"]) == ("SUPPRESSED", "GOOD_GUY")


def test_ac7_the_other_screening_items_stay_active(tiny_cases: DuckDb) -> None:
    assert _cleared(tiny_cases)[1].suppressed == 1
    df = query(
        tiny_cases,
        "SELECT item_key, status FROM case_alerts_current WHERE source = 'SCREENING' "
        f"AND item_key <> '{GG_KEY}'",
    )
    assert len(df) == 4
    assert set(df["status"]) == {"ACTIVE"}


def test_ac7_a_further_run_gives_the_same_result(tiny_cases: DuckDb) -> None:
    _, run3 = _cleared(tiny_cases)
    items3 = item_set(tiny_cases)
    run4 = run_cases(tiny_cases, duck_settings())
    assert (run4.suppressed, run4.cases) == (run3.suppressed, run3.cases)
    assert item_set(tiny_cases) == items3
    assert count(tiny_cases, "good_guy_list") == 1
