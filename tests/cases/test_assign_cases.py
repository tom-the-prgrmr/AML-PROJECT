"""AC2 for specs/case-consolidation.md: the pure functions `assign_cases` and `case_id_for`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .helpers import mod, ts

G1, G3 = "G-C01", "G-C03"
ROWS = [
    (G1, "k1", "2026-03-02 09:00:00"),
    (G1, "k2", "2026-03-05 10:00:00"),
    (G1, "k3", "2026-05-31 08:59:59"),
    (G1, "k4", "2026-05-31 09:00:00"),
    (G1, "k5", "2026-06-30 00:00:00"),
    (G3, "k2", "2026-03-05 10:00:00"),
    (G3, "k9", "2026-03-05 10:00:00"),
]


def _items() -> pd.DataFrame:
    columns = mod("aml.cases.items").ITEM_COLUMNS
    rows = [
        {
            **dict.fromkeys(columns),
            "golden_customer_id": golden,
            "item_key": key,
            "source": "RULE",
            "event_ts": ts(when),
            "end_ts": ts(when),
            "amount_vnd": 0,
            "txn_count": 0,
        }
        for golden, key, when in reversed(ROWS)  # fed in reverse order
    ]
    return pd.DataFrame(rows, columns=columns)


def _assign(window_days: int) -> dict[tuple[str, str], Any]:
    out = mod("aml.cases.consolidate").assign_cases(_items(), window_days)
    assert len(out) == 7
    return {(r.golden_customer_id, r.item_key): r for r in out.itertuples()}


def test_ac2_window_90_days_is_half_open_and_anchored_on_first_alert() -> None:
    got = _assign(90)
    for key in ("k1", "k2", "k3"):
        assert got[G1, key].case_id == "C-C01-20260302", key
        assert pd.Timestamp(got[G1, key].window_start) == ts("2026-03-02 09:00:00")
    for key in ("k4", "k5"):  # k4 is exactly window_start + 90 days
        assert got[G1, key].case_id == "C-C01-20260531", key
        assert pd.Timestamp(got[G1, key].window_start) == ts("2026-05-31 09:00:00")
    assert got[G3, "k2"].case_id == "C-C03-20260305"
    assert got[G3, "k9"].case_id == "C-C03-20260305"


def test_ac2_window_91_days_moves_the_boundary() -> None:
    got = _assign(91)
    assert got[G1, "k4"].case_id == "C-C01-20260302"
    assert got[G1, "k5"].case_id == "C-C01-20260630"


def test_ac2_window_365_days_gives_one_case() -> None:
    got = _assign(365)
    assert {got[G1, k].case_id for k in ("k1", "k2", "k3", "k4", "k5")} == {"C-C01-20260302"}


def test_ac2_window_1_day_splits_all_but_the_one_second_pair() -> None:
    got = _assign(1)
    # k3 and k4 are one second apart, so they share a case even with a 1-day window
    assert got[G1, "k3"].case_id == got[G1, "k4"].case_id == "C-C01-20260531"
    assert len({got[G1, k].case_id for k in ("k1", "k2", "k3", "k4", "k5")}) == 4


def test_ac2_empty_frame_gets_case_columns() -> None:
    columns = mod("aml.cases.items").ITEM_COLUMNS
    out = mod("aml.cases.consolidate").assign_cases(pd.DataFrame(columns=columns), 90)
    assert out.empty
    assert "case_id" in out.columns
    assert "window_start" in out.columns


def test_ac2_case_id_for() -> None:
    case_id_for = mod("aml.cases.consolidate").case_id_for
    assert (
        case_id_for("G-CIF00000189", datetime(2026, 4, 13, 9, 28, 12)) == "C-CIF00000189-20260413"
    )
