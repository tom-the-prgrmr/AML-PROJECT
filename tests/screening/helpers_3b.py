"""Helpers for the Phase 3b tests (specs/screening-tiers-eval.md): NameScore/Identifiers
builders, TINY loading and the expected evaluation rows."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings
from aml.common.db import Database, DuckDb

from .helpers import mod

AS_OF = date(2026, 6, 30)

TRUE_PAIRS = frozenset(
    {
        ("CIF00000032", "WL000084"),
        ("CIF00000041", "WL000199"),
        ("CIF00000057", "WL000013"),
        ("CIF00000069", "WL000117"),
        ("CIF00000104", "WL000158"),
    }
)

EVAL_METHODS = ("exact", "fuzzy", "two_tier_alert", "two_tier")
EVAL_COLUMNS = ("flagged", "tp", "fp", "fn", "precision", "recall", "fp_reduction_pct")

# (flagged, tp, fp, fn, precision, recall, fp_reduction_pct) per method, AC8 first part
EVAL_TINY = {
    "exact": (5, 5, 0, 0, 1.0, 1.0, 100.0),
    "fuzzy": (55, 5, 50, 0, 0.0909, 1.0, 0.0),
    "two_tier_alert": (5, 5, 0, 0, 1.0, 1.0, 100.0),
    "two_tier": (5, 5, 0, 0, 1.0, 1.0, 100.0),
}


def N(fuzzy: float, score: float, common_only: bool = False) -> Any:
    """The spec's N(fuzzy, score, common_only) NameScore."""
    return mod("aml.screening.scoring").NameScore(
        token_set=fuzzy,
        jaro_winkler=fuzzy,
        fuzzy=fuzzy,
        coverage=round(score / fuzzy, 4),
        score=score,
        matched=("X",),
        common_only=common_only,
    )


def ident(**kw: Any) -> Any:
    return mod("aml.screening.decision").Identifiers(**kw)


def cust(**kw: Any) -> Any:
    """The spec's C, with optional overrides."""
    base: dict[str, Any] = {"dob": date(1971, 2, 15), "dob_year": 1971, "nationality": "VN"}
    return ident(**{**base, **kw})


def entry(year: int | None, **kw: Any) -> Any:
    """The spec's E(year), with optional overrides."""
    base: dict[str, Any] = {"dob_year": year, "nationality": "VN"}
    return ident(**{**base, **kw})


def decide(name: Any, customer: Any, ent: Any, cfg: Any) -> Any:
    return mod("aml.screening.decision").decide(name, customer, ent, cfg, as_of=AS_OF)


def duck_settings() -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb"})


def load_tiny_duck(tiny_parquet: Path, path: Path) -> DuckDb:
    db = DuckDb(path)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return db


def lower_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    return df


def query(db: Database, sql: str) -> pd.DataFrame:
    return lower_cols(db.query_df(sql))


def results_row(db: Database, cif: str, entry_id: str, view: str = "screening_results") -> Any:
    df = query(db, f"SELECT * FROM {view} WHERE cif = '{cif}' AND entry_id = '{entry_id}'")
    assert len(df) == 1, (cif, entry_id, len(df))
    return df.iloc[0]


def eval_row(df: pd.DataFrame, method: str) -> tuple[Any, ...]:
    row = df[df["method"] == method]
    assert len(row) == 1, method
    return tuple(row.iloc[0][c] for c in EVAL_COLUMNS)


def assert_eval(df: pd.DataFrame, expected: dict[str, tuple[Any, ...]]) -> None:
    assert list(df["method"]) == list(EVAL_METHODS)
    assert list(df.columns)[: 1 + len(EVAL_COLUMNS)] == ["method", *EVAL_COLUMNS]
    for method in EVAL_METHODS:
        got, want = eval_row(df, method), expected[method]
        for col, g, w in zip(EVAL_COLUMNS, got, want, strict=True):
            if isinstance(w, float):
                assert not (isinstance(g, float) and math.isnan(g)), (method, col)
                assert g == pytest.approx(w, abs=1e-9), (method, col, g, w)
            else:
                assert g == w, (method, col, g, w)
