"""Group alert items into cases: one case per golden customer per rolling window (pure pandas)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd


def case_id_for(golden_customer_id: str, window_start: datetime) -> str:
    """``G-CIF00000189`` + 2026-04-13 -> ``C-CIF00000189-20260413``."""
    return f"C-{golden_customer_id.removeprefix('G-')}-{window_start:%Y%m%d}"


def assign_cases(items: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Add ``case_id`` and ``window_start`` to every item; the row count never changes.

    Per golden customer the items are ordered by (``event_ts``, ``item_key``). The first item
    opens a case; each next item joins it while ``event_ts < window_start + window_days`` (the
    window is half-open and anchored on the first alert, it does not slide). The result is
    sorted the same way, so it does not depend on the order of the input.
    """
    if items.empty:
        return items.assign(case_id=pd.Series(dtype=object), window_start=pd.Series(dtype=object))

    ordered = items.sort_values(
        ["golden_customer_id", "event_ts", "item_key"], kind="stable"
    ).reset_index(drop=True)
    span = timedelta(days=window_days)
    starts: list[pd.Timestamp] = []
    anchor_customer: str | None = None
    anchor: pd.Timestamp | None = None
    for customer, when in zip(ordered["golden_customer_id"], ordered["event_ts"], strict=True):
        if customer != anchor_customer or anchor is None or when >= anchor + span:
            anchor_customer, anchor = customer, pd.Timestamp(when)
        starts.append(anchor)
    ordered["window_start"] = pd.Series(starts, dtype="datetime64[ns]")
    ordered["case_id"] = [
        case_id_for(g, w.to_pydatetime())
        for g, w in zip(ordered["golden_customer_id"], ordered["window_start"], strict=True)
    ]
    return ordered
