"""AC8 for specs/screening-tiers-eval.md: evaluation against the exact and fuzzy baselines."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from aml.common.config import Settings
from aml.common.db import DuckDb

from .helpers import mod
from .helpers_3b import EVAL_TINY, assert_eval, duck_settings, load_tiny_duck, results_row


@pytest.fixture
def tiny(tiny_parquet: Path, tmp_path: Path) -> Iterator[tuple[DuckDb, Settings]]:
    db = load_tiny_duck(tiny_parquet, tmp_path / "tiny.duckdb")
    yield db, duck_settings()
    db.close()


def test_ac8_tiny_evaluation_table(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    mod("aml.screening.runner").run_screening(db, settings)
    assert_eval(mod("aml.screening.evaluate").evaluate(db, settings), EVAL_TINY)


def test_ac8_typo_and_namesake_make_baselines_worse(tiny: tuple[DuckDb, Settings]) -> None:
    db, settings = tiny
    runner, evaluate = mod("aml.screening.runner"), mod("aml.screening.evaluate")
    runner.run_screening(db, settings)
    db.execute("UPDATE customers SET full_name = 'Huỳn Xuân Sơn' WHERE cif = 'CIF00000104'")
    db.execute(
        "INSERT INTO customers (cif, full_name, gender, dob, nationality) "
        "VALUES ('CIF90000001', 'Bùi Thanh Ngọc Chi', 'F', DATE '1990-01-01', 'VN')"
    )
    runner.run_screening(db, settings)
    df = evaluate.evaluate(db, settings)
    assert_eval(
        df,
        {
            "exact": (5, 4, 1, 1, 0.8, 0.8, 98.04),
            "fuzzy": (56, 5, 51, 0, 0.0893, 1.0, 0.0),
            "two_tier_alert": (5, 5, 0, 0, 1.0, 1.0, 100.0),
            "two_tier": (5, 5, 0, 0, 1.0, 1.0, 100.0),
        },
    )
    typo = results_row(db, "CIF00000104", "WL000158", "screening_current")
    assert typo["decision"] == "ALERT"
    assert round(float(typo["name_score"]), 2) == 97.44
    namesake = results_row(db, "CIF90000001", "WL000199", "screening_current")
    assert namesake["decision"] == "AUTO_CLEARED"
    assert round(float(namesake["name_score"]), 2) == 100.0
    assert namesake["reason"].startswith("DOB mismatch > 5y")
