"""Helpers for the Phase 5b tests (specs/fund-flow-trace.md): lazy imports, MINI, TINY."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database, DuckDb
from aml.dba.edges import refresh_acct_edge_daily
from aml.dba.schema import apply_schema

PATH_COLUMNS = [
    "hop",
    "path",
    "account_id",
    "step_path",
    "first_ts",
    "last_ts",
    "amount_vnd",
    "is_cycle",
]
SHOWN = ["hop", "path", "step_path", "amount_vnd", "is_cycle"]

# (txn_id, txn_ts, from, to, amount_vnd)
MINI_ROWS: list[tuple[Any, ...]] = [
    ("M01", "2026-03-01 08:00:00", "A", "A", 5_000_000),
    ("M02", "2026-03-01 09:00:00", "B", "E", 50_000_000),
    ("M03", "2026-03-01 10:00:00", "A", "B", 100_000_000),
    ("M04", "2026-03-01 10:00:00", "B", "H", 30_000_000),
    ("M05", "2026-03-01 11:00:00", "A", None, 7_000_000),
    ("M06", "2026-03-01 12:00:00", "B", "C", 90_000_000),
    ("M07", "2026-03-01 13:00:00", "C", "B", 10_000_000),
    ("M08", "2026-03-01 15:00:00", "C", "A", 80_000_000),
    ("M09", "2026-03-01 16:00:00", "C", "EXT-000001", 20_000_000),
    ("M10", "2026-03-01 17:00:00", "EXT-000001", "K", 15_000_000),
    ("M11", "2026-03-02 09:00:00", "C", "D", 70_000_000),
    ("M12", "2026-03-02 10:00:00", "D", "F", 60_000_000),
    ("M13", "2026-03-02 10:00:01", "D", "G", 40_000_000),
    ("M14", "2026-03-01 07:00:00", None, "A", 300_000_000),
]

# AC2: (hop, path, step_path, amount_vnd, is_cycle) of trace(A, cte_raw, hops=4, hours=24)
AC2_ROWS: list[tuple[Any, ...]] = [
    (1, "A>A", "M01", 5_000_000, True),
    (1, "A>B", "M03", 100_000_000, False),
    (2, "A>B>C", "M03>M06", 90_000_000, False),
    (3, "A>B>C>A", "M03>M06>M08", 80_000_000, True),
    (3, "A>B>C>B", "M03>M06>M07", 10_000_000, True),
    (3, "A>B>C>D", "M03>M06>M11", 70_000_000, False),
    (3, "A>B>C>EXT-000001", "M03>M06>M09", 20_000_000, False),
    (4, "A>B>C>D>F", "M03>M06>M11>M12", 60_000_000, False),
    (4, "A>B>C>EXT-000001>K", "M03>M06>M09>M10", 15_000_000, False),
]
AC2_PATHS = [r[1] for r in AC2_ROWS]

# TINY accounts of the spec
RND = "A8201784530"
RND_CYCLE = "A8201784530>A3312263346>A9950029109>A1070944972>A8201784530"
RAP = "A4879560749"
MULE = "A2582841008"
HUB = "A1037369383"
PAYROLL = "A3906301972"


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings(**env: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def trace(db: Database, settings: Settings, account: str, **kw: Any) -> Any:
    return mod("aml.graph.trace").trace(db, settings, account, **kw)


def query(db: Database, sql: str) -> pd.DataFrame:
    df = db.query_df(sql)
    df.columns = [c.lower() for c in df.columns]
    return df


def scalar(db: Database, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def js(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def rows_of(paths: pd.DataFrame) -> list[tuple[Any, ...]]:
    """(hop, path, step_path, amount_vnd, is_cycle) as plain Python tuples."""
    return [
        (int(r[0]), r[1], r[2], int(r[3]), bool(r[4])) for r in paths[SHOWN].itertuples(index=False)
    ]


def path_set(result: Any) -> set[str]:
    return set(result.paths["path"])


def by_hop(result: Any) -> dict[int, int]:
    return {int(k): int(v) for k, v in result.paths.groupby("hop").size().items()}


def graph_audit(db: Database) -> pd.DataFrame:
    df = query(
        db,
        "SELECT entity_type, entity_id, decision, reason, version, actor, details "
        "FROM audit_log WHERE module = 'graph' ORDER BY audit_id",
    )
    df["details"] = [js(d) for d in df["details"]]
    return df


def mini_frame() -> pd.DataFrame:
    df = pd.DataFrame(
        MINI_ROWS, columns=["txn_id", "txn_ts", "from_account_id", "to_account_id", "amount_vnd"]
    )
    df["txn_ts"] = pd.to_datetime(df["txn_ts"])
    df["channel"] = [
        "CASH" if f is None or t is None else "INTERNAL_TRANSFER"
        for f, t in zip(df["from_account_id"], df["to_account_id"], strict=True)
    ]
    return df


def load_mini(db: Database) -> None:
    """Apply the schema, insert the 14 MINI transactions and rebuild acct_edge_daily."""
    apply_schema(db)
    db.insert_df("transactions", mini_frame())
    refresh_acct_edge_daily(db)


def load_tiny_duck(tiny_parquet: Path, path: Path) -> DuckDb:
    db = DuckDb(path)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return db
