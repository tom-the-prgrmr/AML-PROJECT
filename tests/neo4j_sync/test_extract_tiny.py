"""AC4 for specs/neo4j-sync.md: `build_projection` on TINY in DuckDB (no service)."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.db import DuckDb
from aml.dba.edges import refresh_acct_edge_daily

from .helpers import KEYS_11, TINY_S11, mod


def _projection(db: DuckDb) -> Any:
    return mod("aml.graph.neo4j.extract").build_projection(db)


def _shared(frame: pd.DataFrame) -> pd.Series:
    """Customers per key, for keys carried by two or more customers."""
    sizes = frame.groupby("key")["golden_customer_id"].nunique()
    return sizes[sizes >= 2]


def test_ac4_tiny_counts_and_watermark(tiny_er: DuckDb) -> None:
    projection = _projection(tiny_er)
    assert [len(projection.frames[k]) for k in KEYS_11] == list(TINY_S11)
    assert list(projection.frames) == list(KEYS_11)
    assert projection.max_ts == datetime(2026, 6, 30, 21, 53, 57)


def test_ac4_tiny_customers_and_accounts(tiny_er: DuckDb) -> None:
    frames = _projection(tiny_er).frames
    assert int((frames["Customer"]["cif_count"] > 1).sum()) == 22
    external = frames["Account"][frames["Account"]["is_external"].astype(bool)]
    assert len(external) == 782
    assert all(a.startswith("EXT-") for a in external["account_id"])
    owns = frames["OWNS"]
    for golden, account, cif in (
        ("G-CIF00000206", "A8201784530", "CIF00000206"),
        ("G-CIF00000189", "A4937939209", "CIF00000189"),
    ):
        hit = (
            (owns["golden_customer_id"] == golden)
            & (owns["account_id"] == account)
            & (owns["cif"] == cif)
        )
        assert int(hit.sum()) == 1, account


def test_ac4_tiny_shared_attribute_keys(tiny_er: DuckDb) -> None:
    frames = _projection(tiny_er).frames
    devices = _shared(frames["USES_DEVICE"])
    assert len(devices) == 1
    assert int(devices.iloc[0]) == 16
    phones = _shared(frames["HAS_PHONE"])
    assert len(phones) == 1
    assert int(phones.iloc[0]) == 7
    addresses = _shared(frames["LIVES_AT"])
    assert len(addresses) == 2
    assert int(addresses.max()) == 8


def test_ac4_tiny_transfers_and_daily_edges(tiny_er: DuckDb) -> None:
    frames = _projection(tiny_er).frames
    transfers = frames["TRANSFERRED_TO"]
    row = transfers[transfers["txn_id"] == "T0000002197"].iloc[0]
    assert (row["src"], row["dst"], int(row["amount"])) == ("A8201784530", "A3312263346", 456916000)
    assert pd.Timestamp(row["ts"]) == pd.Timestamp("2026-03-22 15:00:00")
    assert row["channel"] == "EBANKING"
    assert int(frames["SENT_TO"]["count"].sum()) == 3651


def test_ac4_tiny_projection_is_independent_of_row_order(
    tiny_er: DuckDb, er_template: Path, tmp_path: Path
) -> None:
    expected = _projection(tiny_er).frames

    target = tmp_path / "shuffled.duckdb"
    shutil.copy(er_template, target)
    shuffled = DuckDb(target)
    try:
        tables = ("customers", "accounts", "transactions")
        data = {t: shuffled.query_df(f"SELECT * FROM {t}") for t in tables}
        for table in reversed(tables):
            shuffled.execute(f"DELETE FROM {table}")
        for table in tables:
            shuffled.insert_df(table, data[table].sample(frac=1, random_state=7))
        refresh_acct_edge_daily(shuffled)
        actual = _projection(shuffled).frames
    finally:
        shuffled.close()

    for name in KEYS_11:
        left, right = expected[name].copy(), actual[name].copy()
        for frame in (left, right):
            if "cifs" in frame:
                frame["cifs"] = frame["cifs"].map(tuple)
        pd.testing.assert_frame_equal(left, right, obj=name)
