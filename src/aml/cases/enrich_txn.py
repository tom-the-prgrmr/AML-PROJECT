"""Transaction side of the case enrichment: summary over a window, top counterparties, txn ids."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from aml.cases.items import sql_statement
from aml.cases.values import in_filter, lower_columns, plain, whole
from aml.common.db import Database

_TOTALS = (
    "txn_count", "in_count", "out_count", "in_vnd", "out_vnd", "cash_in_vnd", "cash_out_vnd",
    "counterparties", "max_txn_vnd", "active_days",
)  # fmt: skip


@dataclass(frozen=True)
class TxnActivity:
    summary: dict[str, Any]  # the ``txn_summary`` block
    counterparties: list[dict[str, Any]]  # top counterparties for the ``network`` block
    txn_ids: frozenset[str]  # every transaction of the customer in the window (for DQ counts)


def _run(db: Database, name: str, cifs: list[str], start: date, end: date) -> pd.DataFrame:
    """Run a `cases/*.sql` file for the CIFs over [start, end]; placeholders are typed values."""
    sql = (
        sql_statement(db, name)
        .replace("{cif_filter}", in_filter("l.cif", cifs))
        .replace("{window_start}", f"DATE '{start.isoformat()}'")
        .replace("{window_end_next}", f"DATE '{(end + timedelta(days=1)).isoformat()}'")
    )
    return lower_columns(db.query_df(sql))


def _summary(df: pd.DataFrame, start: date, end: date) -> dict[str, Any]:
    flag = df["is_total"].astype(int) if not df.empty else pd.Series(dtype=int)
    total = df[flag == 1]
    row = total.iloc[0] if not total.empty else None  # no legs: zeros
    summary: dict[str, Any] = {"window_start": start.isoformat(), "window_end": end.isoformat()}
    for key in _TOTALS:
        summary[key] = 0 if row is None else whole(row[key])
    by_channel = {}
    for item in df[flag == 0].itertuples():
        by_channel[plain(item.channel) or "UNKNOWN"] = {
            "count": whole(item.txn_count),
            "vnd": whole(item.vnd),
        }
    summary["by_channel"] = dict(sorted(by_channel.items()))
    return summary


def _top_counterparties(legs: pd.DataFrame, own: str, top_n: int) -> list[dict[str, Any]]:
    """Largest counterparties by VND, leaving out accounts of the same golden customer."""
    named = legs[legs["counterparty_id"].notna()].copy()  # cash legs have no counterparty
    if named.empty:
        return []
    named["amount_vnd"] = pd.to_numeric(named["amount_vnd"], errors="coerce").fillna(0)
    grouped = (
        named.groupby(["counterparty_id", "direction"], sort=True)
        .agg(
            txns=("txn_id", "nunique"),
            vnd=("amount_vnd", "sum"),
            golden=("golden_customer_id", "first"),
        )
        .reset_index()
    )
    grouped = grouped[~(grouped["golden"] == own)]
    ranked = grouped.sort_values(
        ["vnd", "counterparty_id", "direction"], ascending=[False, True, True]
    ).head(top_n)
    return [
        {
            "account_id": str(r.counterparty_id),
            "golden_customer_id": plain(r.golden),
            "direction": str(r.direction),
            "txns": whole(r.txns),
            "vnd": whole(r.vnd),
        }
        for r in ranked.itertuples()
    ]


def txn_activity(
    db: Database,
    cifs: list[str],
    golden_customer_id: str,
    last_alert_ts: pd.Timestamp,
    *,
    days: int,
    top_n: int,
) -> TxnActivity:
    """Activity of the CIFs in the ``days`` days that end on the day of the last alert."""
    end = pd.Timestamp(last_alert_ts).date()
    start = end - timedelta(days=days - 1)
    summary = _summary(_run(db, "cases/txn_summary.sql", cifs, start, end), start, end)
    legs = _run(db, "cases/counterparties.sql", cifs, start, end)
    return TxnActivity(
        summary=summary,
        counterparties=_top_counterparties(legs, golden_customer_id, top_n),
        txn_ids=frozenset(str(t) for t in legs["txn_id"]),
    )
