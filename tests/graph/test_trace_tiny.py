"""AC5, AC6 for specs/fund-flow-trace.md: `trace` on TINY (DuckDB)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import (
    HUB,
    MULE,
    PAYROLL,
    RAP,
    RND,
    RND_CYCLE,
    by_hop,
    duck_settings,
    load_tiny_duck,
    path_set,
    trace,
)


@pytest.fixture(scope="module")
def tiny(
    tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[DuckDb, Settings]]:
    db = load_tiny_duck(tiny_parquet, tmp_path_factory.mktemp("trace_tiny") / "tiny.duckdb")
    yield db, duck_settings()
    db.close()


def _raw(tiny: tuple[DuckDb, Settings], account: str, hops: int, hours: int, **kw: Any) -> Any:
    db, settings = tiny
    return trace(db, settings, account, method="cte_raw", hops=hops, hours=hours, **kw)


def _edge(tiny: tuple[DuckDb, Settings], account: str, hops: int, hours: int, **kw: Any) -> Any:
    db, settings = tiny
    return trace(db, settings, account, method="cte_edge", hops=hops, hours=hours, **kw)


# ----------------------------------------------------------------------------- AC5
def test_ac5_round_tripping_cycle(tiny: tuple[DuckDb, Settings]) -> None:
    result = _raw(tiny, RND, 4, 168)
    paths = result.paths
    assert list(paths["path"]) == [
        "A8201784530>A3312263346",
        "A8201784530>A3312263346>A9950029109",
        "A8201784530>A3312263346>A9950029109>A1070944972",
        RND_CYCLE,
    ]
    assert [bool(x) for x in paths["is_cycle"]] == [False, False, False, True]
    last = paths.iloc[-1]
    assert last["step_path"] == "T0000002197>T0000002246>T0000002299>T0000002327"
    assert int(last["amount_vnd"]) == 399_475_000
    assert pd.Timestamp(last["last_ts"]) == pd.Timestamp("2026-03-27 00:11:51")


def test_ac5_round_tripping_shorter_windows(tiny: tuple[DuckDb, Settings]) -> None:
    short_window = _raw(tiny, RND, 4, 72)
    assert short_window.n_paths == 2
    assert short_window.n_cycles == 0
    few_hops = _raw(tiny, RND, 3, 168)
    assert few_hops.n_paths == 3
    assert few_hops.n_cycles == 0


def test_ac5_rapid_movement(tiny: tuple[DuckDb, Settings]) -> None:
    paths = _raw(tiny, RAP, 2, 24).paths
    assert len(paths) == 4
    hop1 = paths[paths["hop"] == 1]
    assert list(hop1["account_id"]) == ["A1425071026"]
    assert int(hop1.iloc[0]["amount_vnd"]) == 525_932_000
    hop2 = paths[paths["hop"] == 2]
    assert sorted(hop2["account_id"]) == ["A4383611454", "A8857496274", "A9439686600"]


def test_ac5_mule_ring(tiny: tuple[DuckDb, Settings]) -> None:
    result = _raw(tiny, MULE, 4, 168)
    assert result.n_paths == 104
    assert by_hop(result) == {1: 21, 2: 23, 3: 60}
    assert result.n_cycles == 0
    assert result.n_accounts == 24
    hop3 = set(result.paths.loc[result.paths["hop"] == 3, "account_id"])
    assert {"A5212040158", "A5340314117", "A9706971063"} <= hop3


def test_ac5_hub_with_cycles(tiny: tuple[DuckDb, Settings]) -> None:
    result = _raw(tiny, HUB, 6, 168)
    assert result.n_paths == 41
    assert result.n_cycles == 4


def test_ac5_payroll_and_since(tiny: tuple[DuckDb, Settings]) -> None:
    assert _raw(tiny, PAYROLL, 2, 24).n_paths == 120
    assert _raw(tiny, PAYROLL, 2, 24, since=datetime(2026, 6, 1)).n_paths == 20


def test_ac5_deterministic(tiny: tuple[DuckDb, Settings]) -> None:
    cases = [
        (RND, 4, 168),
        (RND, 4, 72),
        (RAP, 2, 24),
        (MULE, 4, 168),
        (HUB, 6, 168),
        (PAYROLL, 2, 24),
    ]
    for account, hops, hours in cases:
        first = _raw(tiny, account, hops, hours).paths
        second = _raw(tiny, account, hops, hours).paths
        pd.testing.assert_frame_equal(first, second)


# ----------------------------------------------------------------------------- AC6
@pytest.mark.parametrize(
    ("account", "hops", "hours"),
    [
        (RND, 4, 168),
        (RAP, 2, 24),
        (MULE, 4, 168),
        (HUB, 6, 168),
        (HUB, 2, 24),
    ],
)
def test_ac6_edge_paths_are_a_superset_of_raw(
    tiny: tuple[DuckDb, Settings], account: str, hops: int, hours: int
) -> None:
    raw = _raw(tiny, account, hops, hours)
    edge = _edge(tiny, account, hops, hours, min_amount_vnd=0, top_k=0)
    assert path_set(raw) <= path_set(edge)


def test_ac6_edge_vs_raw_hub_counts(tiny: tuple[DuckDb, Settings]) -> None:
    raw = _raw(tiny, HUB, 2, 24)
    edge = _edge(tiny, HUB, 2, 24, min_amount_vnd=0, top_k=0)
    assert raw.n_paths == 33
    assert len(path_set(raw)) == 10
    assert edge.n_paths == 36
    assert len(path_set(edge)) == 12
    assert path_set(edge) - path_set(raw) == {
        "A1037369383>A1129199111>A1037369383",
        "A1037369383>A7341585768>A1037369383",
    }


def test_ac6_edge_vs_raw_mule_row_counts(tiny: tuple[DuckDb, Settings]) -> None:
    assert _raw(tiny, MULE, 2, 24).n_paths == 23
    assert _edge(tiny, MULE, 2, 24, min_amount_vnd=0, top_k=0).n_paths == 24


def test_ac6_edge_uses_config_defaults(tiny: tuple[DuckDb, Settings]) -> None:
    result = _edge(tiny, MULE, 4, 168)
    assert result.request.min_amount_vnd == 10_000_000
    assert result.request.top_k == 5
    assert result.n_paths == 25
    assert by_hop(result) == {1: 5, 2: 5, 3: 15}
    assert result.n_accounts == 9
    assert _edge(tiny, PAYROLL, 2, 24).n_paths == 5
