"""Alert items: one (alert, golden customer) pair per row, from all three alert sources."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database

ITEM_COLUMNS = [
    "item_key",
    "golden_customer_id",
    "source",
    "rule_id",
    "alert_ref",
    "cif",
    "entry_id",
    "event_ts",
    "end_ts",
    "amount_vnd",
    "txn_count",
    "reason",
    "details",
]

SOURCE_SCREENING = "SCREENING"


def sql_statement(db: Database, name: str) -> str:
    """The single statement of a `.sql` file, without the Oracle `/` or a trailing `;`."""
    lines = db.sql_file(name).read_text(encoding="utf-8").strip().splitlines()
    if lines and lines[-1].strip() == "/":
        lines = lines[:-1]
    return "\n".join(lines).strip().rstrip(";")


def _screening_items(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=ITEM_COLUMNS)
    items = raw.rename(columns={"alert_key": "item_key"})
    items["details"] = [
        json.dumps({"decision": d, "list_type": lt, "final_score": float(fs)}, ensure_ascii=False)
        for d, lt, fs in zip(raw["decision"], raw["list_type"], raw["final_score"], strict=True)
    ]
    return items[ITEM_COLUMNS]


def _alert_items(raw: pd.DataFrame) -> pd.DataFrame:
    """Merge the account rows of one alert that belong to one golden customer into one item."""
    if raw.empty:
        return pd.DataFrame(columns=ITEM_COLUMNS)
    grouped = raw.groupby(["alert_key", "golden_customer_id"], sort=True).agg(
        # Every column but `cif` and `roles` is identical across the account rows of one alert,
        # so "min" just picks that value; `cif` takes the smallest CIF of the golden customer.
        source=("source", "min"),
        rule_id=("rule_id", "min"),
        alert_ref=("alert_ref", "min"),
        cif=("cif", "min"),
        event_ts=("event_ts", "min"),
        end_ts=("end_ts", "min"),
        amount_vnd=("amount_vnd", "min"),
        txn_count=("txn_count", "min"),
        reason=("reason", "min"),
        subject_type=("subject_type", "min"),
        roles=("role", lambda s: sorted({r for r in s if isinstance(r, str)})),
    )
    items = grouped.reset_index().rename(columns={"alert_key": "item_key"})
    items["entry_id"] = pd.Series([None] * len(items), dtype=object)
    items["details"] = [
        json.dumps({"subject_type": st, "roles": roles}, ensure_ascii=False)
        for st, roles in zip(items["subject_type"], items["roles"], strict=True)
    ]
    return items[ITEM_COLUMNS]


def collect_items(db: Database, settings: Settings, *, as_of: date) -> pd.DataFrame:
    """All items with ``event_ts`` before 00:00 of ``as_of + 1``; writes nothing.

    Sorted by (golden_customer_id, event_ts, item_key). ``settings`` is part of the interface
    (later specs filter by configuration) and is not read here.
    """
    del settings
    raw = db.query_df(sql_statement(db, "cases/items.sql"))
    raw.columns = [str(c).lower() for c in raw.columns]
    is_screening = raw["source"] == SOURCE_SCREENING
    items = pd.concat(
        [_screening_items(raw[is_screening].copy()), _alert_items(raw[~is_screening].copy())],
        ignore_index=True,
    )
    items["event_ts"] = pd.to_datetime(items["event_ts"]).astype("datetime64[ns]")
    items["end_ts"] = pd.to_datetime(items["end_ts"]).astype("datetime64[ns]")
    # Oracle returns NUMBER as int or float; DuckDB guesses object columns badly on VND totals.
    for column in ("amount_vnd", "txn_count"):
        items[column] = pd.to_numeric(items[column]).astype("int64")
    items["entry_id"] = items["entry_id"].astype(object).where(items["entry_id"].notna(), None)
    cutoff = datetime.combine(as_of + timedelta(days=1), time.min)
    items = items[items["event_ts"] < cutoff]
    return items.sort_values(["golden_customer_id", "event_ts", "item_key"]).reset_index(drop=True)
