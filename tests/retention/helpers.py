"""Helpers for the Phase 2c-i tests (specs/oracle-retention.md): RT* data, partitions, audit ids."""

from __future__ import annotations

import importlib
import json
from typing import Any

from aml.common.db import Database

AS_OF_ISO = "2026-06-30"
RT_ROWS = (
    ("RT1", "2019-03-15 10:00:00"),
    ("RT2", "2019-04-15 10:00:00"),
    ("RT3", "2026-02-15 10:00:00"),
)


def mod(name: str) -> Any:
    return importlib.import_module(name)


def scalar(db: Database, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def count_txn(db: Database, txn_id: str) -> int:
    return int(scalar(db, f"SELECT COUNT(*) FROM transactions WHERE txn_id = '{txn_id}'"))


def partition_highs(db: Database, table: str = "TRANSACTIONS") -> dict[str, str]:
    """``partition_name -> high_value`` (ISO text from ``high_value_json``)."""
    df = db.query_df(
        "SELECT partition_name, high_value_json FROM user_tab_partitions "
        f"WHERE table_name = '{table}'"
    )
    out: dict[str, str] = {}
    for name, raw in zip(df.iloc[:, 0], df.iloc[:, 1], strict=True):
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        out[str(name)] = str(parsed["high_value"])
    return out


def max_audit_id(db: Database) -> int:
    return int(scalar(db, "SELECT NVL(MAX(audit_id), 0) FROM audit_log"))


def insert_rt_rows(db: Database) -> None:
    for tid, ts in RT_ROWS:
        db.execute(
            "INSERT INTO transactions (txn_id, txn_ts, from_account_id, to_account_id, "
            f"amount_vnd, channel) VALUES ('{tid}', TIMESTAMP '{ts}', 'A1', 'A2', 100000, "
            "'INTERNAL_TRANSFER')"
        )


def clean_rt(db: Database) -> None:
    """Remove RT* rows and every stray pre-2026 partition (keeps the anchor partition)."""
    db.execute("DELETE FROM transactions WHERE txn_id IN ('RT1', 'RT2', 'RT3')")
    for name, high in partition_highs(db).items():
        if name != "P_BEFORE_2000" and high[:10] <= "2026-01-01":
            db.execute(f"ALTER TABLE transactions DROP PARTITION {name} UPDATE GLOBAL INDEXES")
