"""AC3 for specs/ml-anomaly.md: `fit_score`, `rank_scores`, `alert_count`, `top_deviations`,
`data_hash` on the 14 features of the six MINI-C customer-months."""

from __future__ import annotations

import re

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import C01_03, MINI_RANKED, MINI_SCORES, anom_settings, matrix, model

TOL = 1e-6


@pytest.fixture
def X(minic: DuckDb) -> pd.DataFrame:
    return matrix(minic, anom_settings())


def test_ac3_same_seed_gives_the_same_scores(X: pd.DataFrame) -> None:
    cfg = anom_settings().ml.anomaly
    first = model().fit_score(X, cfg, seed=42)
    second = model().fit_score(X, cfg, seed=42)
    assert first.equals(second)
    assert list(first.index) == list(X.index)


def test_ac3_scores_match_the_prototype(X: pd.DataFrame) -> None:
    scores = model().fit_score(X, anom_settings().ml.anomaly, seed=42)
    assert {k: v for k, v in scores.items()} == pytest.approx(MINI_SCORES, abs=TOL)
    assert ((scores > 0) & (scores <= 1)).all()
    assert all(abs(v * 1e6 - round(v * 1e6)) < 1e-6 for v in scores)  # 6 decimals exactly


def test_ac3_another_seed_gives_other_scores(X: pd.DataFrame) -> None:
    cfg = anom_settings().ml.anomaly
    assert not model().fit_score(X, cfg, seed=7).equals(model().fit_score(X, cfg, seed=42))


def test_ac3_rank_scores(X: pd.DataFrame) -> None:
    scores = model().fit_score(X, anom_settings().ml.anomaly, seed=42)
    rank = model().rank_scores(scores)
    assert list(rank.sort_values().index) == MINI_RANKED
    assert sorted(rank) == [1, 2, 3, 4, 5, 6]


def test_ac3_rank_ties_go_to_the_smaller_cif_then_the_earlier_month() -> None:
    index = pd.MultiIndex.from_tuples(
        [("C02", "2026-01"), ("C01", "2026-02"), ("C01", "2026-01"), ("C03", "2026-01")],
        names=["cif", "month"],
    )
    rank = model().rank_scores(pd.Series([0.5, 0.5, 0.5, 0.9], index=index))
    assert list(rank.sort_values().index) == [
        ("C03", "2026-01"),
        ("C01", "2026-01"),
        ("C01", "2026-02"),
        ("C02", "2026-01"),
    ]


@pytest.mark.parametrize(
    ("n", "fraction", "expected"),
    [
        (6, 0.005, 1),
        (6, 0.5, 3),
        (1334, 0.005, 7),
        (27589, 0.005, 138),
        (200, 0.005, 1),
        (0, 0.005, 0),
    ],
)
def test_ac3_alert_count(n: int, fraction: float, expected: int) -> None:
    assert model().alert_count(n, fraction) == expected


def test_ac3_top_deviations_of_the_c01_march_sample(X: pd.DataFrame) -> None:
    top = model().top_deviations(X, C01_03, 3)
    assert [d["feature"] for d in top] == ["txns_per_day", "cash_ratio", "amount_dev"]
    assert [d["z"] for d in top] == pytest.approx([1.25, 0.4021, -0.3725], abs=1e-4)
    assert all(set(d) == {"feature", "value", "median", "z"} for d in top)
    assert top[1]["median"] == 0  # IQR 0: z is the plain difference


def test_ac3_data_hash(X: pd.DataFrame) -> None:
    h = model().data_hash(X)
    assert re.fullmatch(r"[0-9a-f]{16}", h)
    assert model().data_hash(X) == h
    changed = X.copy()
    changed.iloc[0, 0] += 1e-6
    assert model().data_hash(changed) != h


def test_ac3_fewer_than_two_rows_raise(X: pd.DataFrame) -> None:
    cfg = anom_settings().ml.anomaly
    with pytest.raises(ValueError):
        model().fit_score(X.iloc[:1], cfg, seed=42)
    with pytest.raises(ValueError):
        model().fit_score(X.iloc[:0], cfg, seed=42)
