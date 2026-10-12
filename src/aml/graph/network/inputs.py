"""Read what the network detections need: customers, account owners and cross-owner transfers.

Every sort is done in Python so the result does not depend on the backend's ORDER BY or on
the physical row order. Column names are lower-cased because Oracle returns upper-case ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd

from aml.common.db import Database
from aml.graph.network.rules import NETWORK_RULES

CUSTOMER_COLUMNS = "cif, phone, device_id, street, ward, district, province"
TRANSFER_COLUMNS = ["txn_id", "txn_ts", "src", "dst", "amt", "sec"]


class NetworkError(RuntimeError):
    """The network detections cannot run (or be evaluated) with the data they were given."""


@dataclass(frozen=True)
class NetworkInputs:
    as_of: date
    cutoff: datetime  # 00:00 of the day after as_of: transfers must be strictly earlier
    customers: pd.DataFrame
    mapping: pd.DataFrame
    accounts: pd.DataFrame  # account_id, cif; sorted by account_id
    owner_of_cif: dict[str, str]  # cif -> golden customer id
    owner: dict[str, str]  # account_id -> golden customer id
    transfers: pd.DataFrame  # TRANSFER_COLUMNS, other-owner transfers sorted by (txn_ts, txn_id)


def rule_version(rule_id: str) -> str:
    return next(r.rule_version for r in NETWORK_RULES if r.rule_id == rule_id)


def fmt_ts(value: datetime | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def midnight(day: date) -> datetime:
    return datetime.combine(day, time.min)


def _query(db: Database, sql: str, hint: str) -> pd.DataFrame:
    try:
        frame = db.query_df(sql)
    except Exception as exc:  # table not created yet: driver-specific error types
        raise NetworkError(f"{hint} ({exc})") from exc
    frame.columns = [str(c).lower() for c in frame.columns]
    return frame


def _read_transfers(db: Database, cutoff: datetime) -> pd.DataFrame:
    frame = _query(
        db,
        "SELECT t.txn_id, t.txn_ts, t.from_account_id AS src, t.to_account_id AS dst, "
        "t.amount_vnd AS amt FROM transactions t "
        "JOIN accounts a ON a.account_id = t.from_account_id "
        "JOIN accounts b ON b.account_id = t.to_account_id "
        f"WHERE t.from_account_id <> t.to_account_id AND t.txn_ts < TIMESTAMP '{fmt_ts(cutoff)}'",
        "transactions is unavailable; run `aml load` first",
    )
    frame["txn_ts"] = pd.to_datetime(frame["txn_ts"]).astype("datetime64[ns]")
    frame["amt"] = frame["amt"].astype("int64")
    frame["sec"] = frame["txn_ts"].astype("datetime64[s]").astype("int64")
    frame = frame.sort_values(["txn_ts", "txn_id"], kind="stable").reset_index(drop=True)
    return frame[TRANSFER_COLUMNS]


def read_inputs(db: Database, as_of: date) -> NetworkInputs:
    """Load everything; raises NetworkError before anything is computed or written."""
    cutoff = midnight(as_of + timedelta(days=1))
    customers = _query(
        db,
        f"SELECT {CUSTOMER_COLUMNS} FROM customers",
        "customers is unavailable; run `aml load` first",
    )
    accounts = _query(
        db, "SELECT account_id, cif FROM accounts", "accounts is unavailable; run `aml load` first"
    )
    if customers.empty or accounts.empty:
        raise NetworkError("customers or accounts is empty; run `aml load` first")
    mapping = _query(
        db,
        "SELECT old_ward, old_district, old_province, new_ward, new_province "
        "FROM admin_unit_mapping",
        "admin_unit_mapping is unavailable; run `aml load` first",
    )
    golden = _query(
        db,
        "SELECT cif, golden_customer_id FROM customer_golden",
        "customer_golden is unavailable; run `aml er` first",
    )
    if golden.empty:
        raise NetworkError("no entity resolution result; run `aml er` first")
    customers = customers.sort_values("cif").reset_index(drop=True)
    accounts = accounts.sort_values("account_id").reset_index(drop=True)
    by_cif = dict(zip(golden["cif"], golden["golden_customer_id"], strict=True))
    owner_of_cif = {c: by_cif.get(c, f"G-{c}") for c in [*customers["cif"], *accounts["cif"]]}
    owner = {
        a: owner_of_cif[c] for a, c in zip(accounts["account_id"], accounts["cif"], strict=True)
    }
    transfers = _read_transfers(db, cutoff)
    keep = [owner[s] != owner[d] for s, d in zip(transfers["src"], transfers["dst"], strict=True)]
    transfers = transfers[pd.Series(keep, index=transfers.index, dtype=bool)].reset_index(drop=True)
    return NetworkInputs(
        as_of, cutoff, customers, mapping, accounts, owner_of_cif, owner, transfers
    )
