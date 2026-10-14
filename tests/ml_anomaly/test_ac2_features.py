"""AC2 for specs/ml-anomaly.md: `build_samples` on LEGS-M (the 11 legs of MINI-C)."""

from __future__ import annotations

import inspect
import math
from datetime import date

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import anom_settings, build, features, read_legs, settings_with

TOL = 1e-6


def _row(s: pd.DataFrame, cif: str, month: str) -> pd.Series:
    part = s[(s["cif"] == cif) & (s["month"] == month)]
    assert len(part) == 1, (cif, month)
    return part.iloc[0]


@pytest.fixture
def samples(minic: DuckDb) -> pd.DataFrame:
    return build(minic, anom_settings())


def test_ac2_rows_and_columns(samples: pd.DataFrame) -> None:
    f = features()
    assert list(zip(samples["cif"], samples["month"], strict=True)) == [
        ("C01", "2026-01"),
        ("C01", "2026-03"),
        ("C01", "2026-05"),
        ("C02", "2026-04"),
        ("C03", "2026-03"),
        ("C04", "2026-03"),
    ]
    assert list(samples.columns) == [*f.SAMPLE_COLUMNS, *f.ANOMALY_FEATURES]
    assert samples[list(f.ANOMALY_FEATURES)].map(math.isfinite).all().all()


def test_ac2_c01_march_sample_columns_and_features(samples: pd.DataFrame) -> None:
    r = _row(samples, "C01", "2026-03")
    assert r["window_start"] == pd.Timestamp("2026-03-01 00:00:00")
    assert r["window_end"] == pd.Timestamp("2026-04-01 00:00:00")
    assert r["first_ts"] == pd.Timestamp("2026-03-02 09:00:00")
    assert r["last_ts"] == pd.Timestamp("2026-03-07 10:00:00")
    assert r["txn_count"] == 3
    assert r["amount_vnd"] == 970_000_000
    assert list(r["accounts"]) == ["A01"]
    assert r["txns_per_day"] == pytest.approx(3 / 31, abs=TOL)
    assert r["max_txns_day"] == 1
    assert r["amount_log"] == pytest.approx(math.log10(1 + 970_000_000), abs=TOL)
    assert r["cash_ratio"] == pytest.approx(390 / 970, abs=TOL)
    assert r["counterparties"] == 2  # the NULL counterparty of the cash deposit does not count
    assert r["night_ratio"] == 0
    assert r["pass_through"] == pytest.approx(300 / 670, abs=TOL)
    expected_amount = math.log10((1 + 970_000_000 / 31) / (1 + 10_000_000 / 59))
    assert r["amount_dev"] == pytest.approx(expected_amount, abs=TOL)
    assert r["amount_dev"] == pytest.approx(2.266260, abs=TOL)
    assert r["txn_dev"] == pytest.approx(math.log10((1 + 3 / 31) / (1 + 1 / 59)), abs=TOL)
    assert r["txn_dev"] == pytest.approx(0.032818, abs=TOL)
    # baseline 2026-01-01 -> 2026-03-01 (59 days) only holds EXT-01
    assert r["new_counterparty_ratio"] == 1.0


def test_ac2_first_month_has_no_baseline(samples: pd.DataFrame) -> None:
    r = _row(samples, "C01", "2026-01")
    assert (r["amount_dev"], r["txn_dev"], r["new_counterparty_ratio"]) == (0, 0, 0)


def test_ac2_baseline_of_90_days_excludes_the_january_leg(samples: pd.DataFrame) -> None:
    r = _row(samples, "C01", "2026-05")
    # baseline 2026-01-31 -> 2026-05-01 (90 days): T08 of 2026-01-15 is outside it
    assert r["amount_dev"] == pytest.approx(
        math.log10((1 + 50_000_000 / 31) / (1 + 970_000_000 / 90)), abs=TOL
    )
    assert r["amount_dev"] == pytest.approx(-0.824921, abs=TOL)
    assert r["txn_dev"] == pytest.approx(-0.000452, abs=TOL)


def test_ac2_pass_through_money_in_and_out_of_one_day(samples: pd.DataFrame) -> None:
    r = _row(samples, "C02", "2026-04")
    assert r["window_end"] == pd.Timestamp("2026-05-01 00:00:00")
    assert r["max_txns_day"] == 2
    assert r["txns_per_day"] == pytest.approx(2 / 30, abs=TOL)
    assert r["pass_through"] == pytest.approx(0.96, abs=TOL)
    assert r["amount_dev"] == pytest.approx(math.log10(1 + 980_000_000 / 30), abs=TOL)
    assert r["amount_dev"] == pytest.approx(7.514105, abs=TOL)


def test_ac2_empty_graph_gives_zero_graph_columns(samples: pd.DataFrame) -> None:
    graph_columns = list(features().GRAPH_FEATURES)
    assert (samples[graph_columns] == 0.0).all().all()


def test_ac2_as_of_in_the_middle_of_a_month_drops_later_legs(minic: DuckDb) -> None:
    s = build(minic, anom_settings(), as_of=date(2026, 5, 15))
    assert len(s) == 5
    assert ("C01", "2026-05") not in set(zip(s["cif"], s["month"], strict=True))


def test_ac2_the_month_of_as_of_is_cut_at_the_end_of_as_of(minic: DuckDb) -> None:
    s = build(minic, anom_settings(), as_of=date(2026, 4, 25))
    r = _row(s, "C02", "2026-04")
    assert r["window_end"] == pd.Timestamp("2026-04-26 00:00:00")
    assert r["txns_per_day"] == pytest.approx(2 / 25, abs=TOL)


def test_ac2_min_baseline_days_decides_when_a_baseline_counts(minic: DuckDb) -> None:
    s = build(minic, settings_with(AML__ML__ANOMALY__MIN_BASELINE_DAYS="60"))
    r = _row(s, "C01", "2026-03")  # 59 days < 60
    assert (r["amount_dev"], r["txn_dev"], r["new_counterparty_ratio"]) == (0, 0, 0)


def test_ac2_night_hours_come_from_the_config(minic: DuckDb) -> None:
    s = build(minic, settings_with(AML__ML__ANOMALY__NIGHT_START_HOUR="9"))
    assert _row(s, "C01", "2026-03")["night_ratio"] == 1.0  # hours >= 9 or < 6


def test_ac2_graph_features_are_the_max_over_the_accounts_of_a_customer(minic: DuckDb) -> None:
    graph = pd.DataFrame(
        [
            {
                "account_id": "A01",
                "in_degree": 3,
                "out_degree": 1,
                "pagerank_ratio": 2.5,
                "shared_cluster_size": 0,
            },
            {
                "account_id": "A02",
                "in_degree": 7,
                "out_degree": 0,
                "pagerank_ratio": 0.5,
                "shared_cluster_size": 4,
            },
        ]
    )
    columns = list(features().GRAPH_FEATURES)
    for frame in (graph, graph.set_index("account_id")):  # the loader gives the indexed form
        s = build(minic, anom_settings(), frame)
        for _, r in s[s["cif"] == "C01"].iterrows():
            assert list(r[columns]) == [3, 1, 2.5, 0]
        assert list(_row(s, "C02", "2026-04")[columns]) == [7, 0, 0.5, 4]
        assert (s[s["cif"].isin(["C03", "C04"])][columns] == 0).all().all()


def test_ac2_empty_legs_give_an_empty_frame_with_all_columns() -> None:
    f = features()
    empty = pd.DataFrame(columns=list(f.LEG_COLUMNS))
    out = f.build_samples(
        empty,
        pd.DataFrame(),
        as_of=date(2026, 6, 30),
        start_date=date(2026, 1, 1),
        cfg=anom_settings().ml.anomaly,
    )
    assert out.empty
    assert list(out.columns) == [*f.SAMPLE_COLUMNS, *f.ANOMALY_FEATURES]


def test_ac2_build_samples_is_pure(minic: DuckDb) -> None:
    legs = read_legs(minic)
    before = legs.copy(deep=True)
    f = features()
    f.build_samples(
        legs,
        pd.DataFrame(),
        as_of=date(2026, 6, 30),
        start_date=date(2026, 1, 1),
        cfg=anom_settings().ml.anomaly,
    )
    pd.testing.assert_frame_equal(legs, before)  # the input is not touched
    source = inspect.getsource(f)
    assert "aml.common.db" not in source
    assert "Database" not in source


def test_ac2_graph_snapshot_is_shared_by_every_month_of_a_customer() -> None:
    f = features()
    rows = [
        ("C09", "A1", "T1", "2026-01-10 09:00:00", "IN", 100, "EXT-1", "CASH"),
        ("C09", "A2", "T2", "2026-03-10 09:00:00", "OUT", 100, "EXT-2", "EBANKING"),
    ]
    legs = pd.DataFrame(rows, columns=list(f.LEG_COLUMNS))
    graph = pd.DataFrame(
        [{"account_id": "A2", "in_degree": 9, "out_degree": 2, "pagerank_ratio": 1.5}]
    )
    out = f.build_samples(
        legs,
        graph,
        as_of=date(2026, 6, 30),
        start_date=date(2026, 1, 1),
        cfg=anom_settings().ml.anomaly,
    )
    january = out[out["month"] == "2026-01"].iloc[0]  # A1 only has legs in January
    assert [january[c] for c in ("in_degree", "out_degree", "pagerank_ratio")] == [9, 2, 1.5]
    assert january["shared_cluster_size"] == 0  # a column the graph lacks gives 0
