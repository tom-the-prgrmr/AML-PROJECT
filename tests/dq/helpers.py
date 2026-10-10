"""Helpers for the Phase 2c-ii tests: module access, settings and the hand-built MINI data set."""

from __future__ import annotations

import importlib
import json
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database

ALL_RULES = (
    "KYC_OCCUPATION_MISSING",
    "KYC_NATIONALITY_MISSING",
    "KYC_ID_FORMAT",
    "KYC_DOB_FUTURE",
    "KYC_CCCD_DOB_MISMATCH",
    "TXN_DUPLICATE",
    "TXN_VALUE_INVALID",
    "TXN_ACCOUNT_UNKNOWN",
    "TXN_BEFORE_ACCOUNT_OPEN",
    "TXN_FEED_STALE",
)


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings() -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb"})


def by_rule(run: Any) -> dict[str, Any]:
    return {r.rule_id: r for r in run.results}


def lower_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    return df


def parse_json_list(value: Any) -> list[str]:
    parsed = json.loads(value) if isinstance(value, str) else value
    return [str(x) for x in parsed]


_CUSTOMERS = (
    "('C1','M',DATE '1990-05-20','VN','Teacher','CCCD','001090123456')",
    "('C2','F',DATE '2026-07-01',NULL,NULL,'CMND','12345678')",
    "('C3','M',DATE '2026-06-30','US','Engineer','PASSPORT','B1234567')",
    "('C4','M',DATE '1990-05-20','VN','Teacher','CCCD','001190123456')",
    "('C5','M',DATE '1990-05-20','VN','Teacher','CCCD','00109012345X')",
    "('C6','M',DATE '1990-05-20','VN','Teacher','CCCD','001085123456')",
)

_TXNS = (
    ("T1", "'A1'", "'A2'", "2026-02-01 09:00:00", 100000, "INTERNAL_TRANSFER"),
    ("T2", "'A1'", "'A2'", "2026-02-01 09:00:00", 100000, "INTERNAL_TRANSFER"),
    ("T3", "'A1'", "'A2'", "2026-02-01 09:00:00", 100000, "INTERNAL_TRANSFER"),
    ("T4", "NULL", "'A1'", "2026-01-05 10:00:00", 500000, "CASH"),
    ("T5", "'A1'", "'EXT-X'", "2026-03-01 09:00:00", 200000, "INTERBANK_TRANSFER"),
    ("T6", "'A9'", "'A2'", "2026-03-02 09:00:00", 300000, "EBANKING"),
    ("T7", "'A1'", "'A2'", "2026-06-30 12:00:00", 0, "WIRE"),
    ("T8", "NULL", "'A2'", "2026-02-01 09:00:00", 100000, "CASH"),
    ("T9", "NULL", "'A2'", "2026-02-01 09:00:00", 100000, "CASH"),
)


def load_mini(db: Database) -> None:
    """Apply the schema and insert the MINI data set of the spec (9 txns, 6 customers)."""
    mod("aml.dba.schema").apply_schema(db)
    db.execute(
        "INSERT INTO customers (cif, gender, dob, nationality, occupation, id_type, id_number) "
        "VALUES " + ",".join(_CUSTOMERS)
    )
    db.execute(
        "INSERT INTO accounts (account_id, cif, open_date) VALUES "
        "('A1','C1',DATE '2026-01-10'),('A2','C1',DATE '2025-01-01')"
    )
    for tid, frm, to, ts, amt, ch in _TXNS:
        insert_txn(db, tid, frm, to, ts, amt, ch)


def insert_txn(
    db: Database, tid: str, frm: str, to: str, ts: str, amount: int, channel: str
) -> None:
    db.execute(
        "INSERT INTO transactions (txn_id, from_account_id, to_account_id, txn_ts, "
        f"amount_vnd, channel) VALUES ('{tid}', {frm}, {to}, TIMESTAMP '{ts}', {amount}, "
        f"'{channel}')"
    )
