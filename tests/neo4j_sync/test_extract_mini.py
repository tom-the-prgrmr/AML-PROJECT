"""AC3 and AC5 for specs/neo4j-sync.md: `build_projection` and friends on MINI-G (DuckDB only)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb

from .helpers import (
    KEYS_11,
    MINI_S11,
    add_late,
    cells,
    col,
    count,
    day,
    graph_audit,
    mod,
    ts,
)


def _extract() -> Any:
    return mod("aml.graph.neo4j.extract")


def _cust_ids(frame: pd.DataFrame, key: str) -> list[str]:
    return sorted(frame.loc[frame["key"] == key, "golden_customer_id"])


def test_ac3_frames_shape_and_counts(mini: DuckDb) -> None:
    ex = _extract()
    projection = ex.build_projection(mini)
    frames = projection.frames
    assert list(frames) == list(ex.NODE_LABELS) + list(ex.REL_TYPES)
    assert list(frames) == list(KEYS_11)
    for name, frame in frames.items():
        assert list(frame.columns) == ex.COLUMNS[name], name
    assert [len(frames[name]) for name in frames] == list(MINI_S11)
    assert projection.er_run_id == 1
    assert projection.max_ts == datetime(2026, 7, 1, 10, 0, 0)


def test_ac3_customer_and_account_frames(mini: DuckDb) -> None:
    frames = _extract().build_projection(mini).frames
    customers = frames["Customer"]
    ids = col(customers, "golden_customer_id")
    assert ids == sorted(ids)
    g06 = customers[customers["golden_customer_id"] == "G-C06"].iloc[0]
    assert list(g06["cifs"]) == ["C06", "C07", "C08"]
    assert int(g06["cif_count"]) == 3
    g19 = customers[customers["golden_customer_id"] == "G-C19"].iloc[0]
    assert list(g19["cifs"]) == ["C19"]

    accounts = frames["Account"]
    assert int((~accounts["is_external"].astype(bool)).sum()) == 23
    external = accounts[accounts["is_external"].astype(bool)]
    assert list(external["account_id"]) == ["EXT-01"]
    ext = external.iloc[0]
    assert pd.isna(ext["cif"]) and pd.isna(ext["account_type"]) and pd.isna(ext["open_date"])
    a01s = accounts[accounts["account_id"] == "A01S"].iloc[0]
    assert a01s["cif"] == "C01"
    assert a01s["account_type"] == "SAVINGS"


def test_ac3_attribute_keys() -> None:
    ex = _extract()
    assert ex.attribute_key("phone", "0901000001") == "1582642d9e86c0cf"
    assert ex.attribute_key("device", "DEV-R") == "9780efe92205e69d"
    addr = "1 LE LOI|PHUONG AN PHU|TP. HO CHI MINH"
    assert ex.attribute_key("address", addr) == "01dabfcfc5ec16dc"


def test_ac3_attribute_relationships(mini: DuckDb) -> None:
    ex = _extract()
    frames = ex.build_projection(mini).frames
    phone_key = ex.attribute_key("phone", "0901000001")
    device_key = ex.attribute_key("device", "DEV-R")
    address_key = ex.attribute_key("address", "1 LE LOI|PHUONG AN PHU|TP. HO CHI MINH")

    phones = frames["HAS_PHONE"]
    assert _cust_ids(phones, phone_key) == ["G-C01", "G-C02"]
    sizes = phones.groupby("key")["golden_customer_id"].apply(sorted)
    big = [v for v in sizes if len(v) == 6]
    assert big == [[f"G-C{n}" for n in range(14, 20)]]

    devices = frames["USES_DEVICE"]
    assert _cust_ids(devices, device_key) == ["G-C01", "G-C03"]
    assert list(devices["golden_customer_id"]).count("G-C06") == 1

    assert _cust_ids(frames["LIVES_AT"], address_key) == ["G-C01", "G-C04"]

    for name in ("USES_DEVICE", "HAS_PHONE", "LIVES_AT"):
        present = set(frames[name]["golden_customer_id"])
        assert present.isdisjoint({"G-C20", "G-C21", "G-C22"}), name


def test_ac3_owns_transfers_and_daily_edges(mini: DuckDb) -> None:
    frames = _extract().build_projection(mini).frames
    owns = frames["OWNS"]
    assert (
        (owns["golden_customer_id"] == "G-C06")
        & (owns["account_id"] == "A07")
        & (owns["cif"] == "C07")
    ).sum() == 1

    transfers = frames["TRANSFERRED_TO"]
    assert sorted(transfers["txn_id"]) == [f"T0{n}" for n in (1, 2, 3, 4, 5, 6, 7, 9)]
    t03 = transfers[transfers["txn_id"] == "T03"].iloc[0]
    assert (t03["src"], t03["dst"], int(t03["amount"])) == ("A01", "EXT-01", 25_000_000)
    assert pd.Timestamp(t03["ts"]) == pd.Timestamp("2026-03-03 10:00:00")
    assert t03["channel"] == "INTERNAL_TRANSFER"

    daily = frames["SENT_TO"]
    rows = {(r.src, r.dst, day(r.day), int(r.count), int(r.total)) for r in daily.itertuples()}
    assert ("A02", "A01", date(2026, 3, 1), 2, 14_000_000) in rows


def test_ac3_no_personal_data_in_any_cell(mini: DuckDb) -> None:
    frames = _extract().build_projection(mini).frames
    for name, frame in frames.items():
        text = [str(v) for v in cells(frame)]
        for secret in ("0901000001", "DEV-R", "1 Lê Lợi", "Khach C01"):
            assert not any(secret in t for t in text), (name, secret)


def test_ac3_to_rows_and_batches(mini: DuckDb) -> None:
    ex = _extract()
    frames = ex.build_projection(mini).frames
    first = ex.to_rows(frames["TRANSFERRED_TO"])[0]
    assert type(first["ts"]) is datetime
    assert type(first["amount"]) is int
    assert type(ex.to_rows(frames["SENT_TO"])[0]["day"]) is date
    account_rows = ex.to_rows(frames["Account"])
    assert any(r["cif"] is None for r in account_rows)  # EXT-01: null cells are plain None
    assert [len(b) for b in ex.batches(account_rows, 10)] == [10, 10, 4]


def test_ac3_build_projection_is_read_only(mini: DuckDb) -> None:
    _extract().build_projection(mini)
    assert count(mini, "transactions") == 9
    assert len(graph_audit(mini)) == 0


def test_ac5_plan_since() -> None:
    plan = _extract_sync().plan_since
    wm = datetime(2026, 7, 1, 10, 0, 0)
    assert plan(None, 60, full=False) is None
    assert plan(wm, 60, full=False) == datetime(2026, 7, 1, 9, 0, 0)
    assert plan(wm, 0, full=False) == wm
    assert plan(wm, 60, full=True) is None


def _extract_sync() -> Any:
    return mod("aml.graph.neo4j.sync")


def test_ac5_incremental_window_after_late_arrivals(mini: DuckDb) -> None:
    ex = _extract()
    add_late(mini)
    projection = ex.build_projection(mini, since=datetime(2026, 7, 1, 9, 0, 0))
    frames = projection.frames
    assert sorted(frames["TRANSFERRED_TO"]["txn_id"]) == ["T06", "T10", "T12"]  # T11 is before
    daily = {
        (r.src, r.dst, day(r.day), int(r.count), int(r.total))
        for r in frames["SENT_TO"].itertuples()
    }
    assert daily == {
        ("A03", "A02", date(2026, 7, 1), 2, 3_000_000),
        ("A04", "A01", date(2026, 7, 1), 1, 7_000_000),
        ("A05", "EXT-02", date(2026, 7, 2), 1, 3_000_000),
    }
    accounts = frames["Account"]
    assert len(accounts) == 24
    assert "EXT-02" in set(accounts["account_id"])
    assert "EXT-01" not in set(accounts["account_id"])
    assert int((~accounts["is_external"].astype(bool)).sum()) == 23
    counts = [len(frames[n]) for n in ("Customer", "Device", "Phone", "Address")]
    assert counts == [20, 14, 10, 14]
    assert [len(frames[n]) for n in ("OWNS", "USES_DEVICE", "HAS_PHONE", "LIVES_AT")] == [
        23,
        17,
        17,
        17,
    ]
    assert projection.max_ts == datetime(2026, 7, 2, 10, 0, 0)


def test_ac5_since_boundary_is_inclusive(mini: DuckDb) -> None:
    add_late(mini)
    frames = _extract().build_projection(mini, since=ts("2026-07-01 10:00:00")).frames
    assert sorted(frames["TRANSFERRED_TO"]["txn_id"]) == ["T06", "T12"]


def test_ac5_missing_load(duck: DuckDb) -> None:
    ex = _extract()
    mod("aml.dba.schema").apply_schema(duck)
    with pytest.raises(ex.SyncError, match="run `aml load` first"):
        ex.build_projection(duck)


def test_ac5_missing_er_run(mini: DuckDb) -> None:
    ex = _extract()
    mini.execute("DELETE FROM er_runs")
    with pytest.raises(ex.SyncError, match="run `aml er` first"):
        ex.build_projection(mini)


def test_ac5_open_source_duckdb_is_identity(mini: DuckDb) -> None:
    ex = _extract()
    settings = load_settings(environ={"DB_BACKEND": "duckdb"})
    assert ex.open_source(mini, settings) is mini


def test_ac5_open_source_oracle_without_password_never_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ex = _extract()
    settings = load_settings(environ={"DB_BACKEND": "oracle"})

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("oracledb.connect must not be called")

    import oracledb

    monkeypatch.setattr(oracledb, "connect", boom)
    fake = SimpleNamespace(backend="oracle")
    with pytest.raises(ex.SyncError, match="ORACLE_DEMO_PASSWORD"):
        ex.open_source(fake, settings)
