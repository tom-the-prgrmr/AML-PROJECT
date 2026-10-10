"""Acceptance tests AC2-AC3 for specs/oracle-schema-core.md (DuckDB-only)."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.db import DuckDb

from .conftest import TABLES, audit_rows


def _txn(txn_id: str, ts: str, src: str | None, dst: str | None, amount: int, channel: str) -> str:
    s = "NULL" if src is None else f"'{src}'"
    d = "NULL" if dst is None else f"'{dst}'"
    return f"('{txn_id}', TIMESTAMP '{ts}', {s}, {d}, {amount}, '{channel}')"


def test_ac2_refresh_acct_edge_daily_aggregates_per_day_and_audits(duck: DuckDb) -> None:
    schema: Any = importlib.import_module("aml.dba.schema")
    edges: Any = importlib.import_module("aml.dba.edges")
    schema.apply_schema(duck)
    rows = [
        _txn("T1", "2026-02-01 09:00:00", "A1", "A2", 100000, "INTERNAL_TRANSFER"),
        _txn("T2", "2026-02-01 23:59:59", "A1", "A2", 50000, "INTERNAL_TRANSFER"),
        _txn("T3", "2026-02-02 00:00:00", "A1", "A2", 70000, "INTERNAL_TRANSFER"),
        _txn("T4", "2026-02-01 10:00:00", None, "A1", 400000, "CASH"),
        _txn("T5", "2026-02-01 11:00:00", "A1", "EXT-X", 30000, "INTERBANK_TRANSFER"),
    ]
    duck.execute(
        "INSERT INTO transactions (txn_id, txn_ts, from_account_id, to_account_id, "
        f"amount_vnd, channel) VALUES {', '.join(rows)}"
    )

    assert edges.refresh_acct_edge_daily(duck) == 3
    assert edges.refresh_acct_edge_daily(duck) == 3

    df = duck.query_df(
        "SELECT src_acct, dst_acct, CAST(day AS VARCHAR) AS day, txn_count, total_amount "
        "FROM acct_edge_daily ORDER BY src_acct, dst_acct, day"
    )
    got = [
        (r.src_acct, r.dst_acct, r.day, int(r.txn_count), int(r.total_amount))
        for r in df.itertuples()
    ]
    assert got == [
        ("A1", "A2", "2026-02-01", 2, 150000),
        ("A1", "A2", "2026-02-02", 1, 70000),
        ("A1", "EXT-X", "2026-02-01", 1, 30000),
    ]

    audit = audit_rows(duck, "module = 'dba' AND decision = 'REFRESHED'")
    assert len(audit) == 2
    for _, row in audit.iterrows():
        assert row["entity_id"] == "acct_edge_daily"
        assert row["details"]["rows"] == 3


def test_ac3_load_parquet_twice_populates_acct_edge_daily(duck: DuckDb, tiny_parquet: Path) -> None:
    import json

    load_mod: Any = importlib.import_module("aml.datagen.load")
    stats: Any = importlib.import_module("aml.dba.stats")
    manifest = json.loads((tiny_parquet / "manifest.json").read_text(encoding="utf-8"))
    txns = pd.read_parquet(tiny_parquet / "transactions.parquet")
    both = txns[txns["from_account_id"].notna() & txns["to_account_id"].notna()]
    want_count = len(both)
    want_amount = int(both["amount_vnd"].sum())
    assert want_count > 0

    for run in (1, 2):
        load_mod.load_parquet(duck, tiny_parquet)
        for t in TABLES:
            n = duck.query_df(f"SELECT COUNT(*) AS n FROM {t}")["n"].iloc[0]
            assert int(n) == manifest["tables"][t], f"{t} run {run}"
        agg = duck.query_df(
            "SELECT COUNT(*) FILTER (WHERE src_acct IS NULL OR dst_acct IS NULL) AS nulls, "
            "CAST(SUM(txn_count) AS BIGINT) AS c, CAST(SUM(total_amount) AS BIGINT) AS a "
            "FROM acct_edge_daily"
        ).iloc[0]
        assert int(agg["nulls"]) == 0, run
        assert int(agg["c"]) == want_count, run
        assert int(agg["a"]) == want_amount, run

    assert stats.gather_stats(duck) == []
