"""AC3 for specs/screening-ml.md: stored features of TINY-S."""

from __future__ import annotations

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import mod, query, scalar, settings_with


def _write(db: DuckDb) -> int:
    return int(mod("aml.screening.ml.features").write_features(db, settings_with()))


def test_ac3_write_is_idempotent_and_read_has_the_shape(tiny_s: DuckDb) -> None:
    features = mod("aml.screening.ml.features")
    assert _write(tiny_s) == 55
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_features") == 1045
    assert _write(tiny_s) == 0
    assert scalar(tiny_s, "SELECT COUNT(*) FROM screening_ml_features") == 1045
    X = features.read_features(tiny_s)
    assert X.shape == (55, 19)
    assert list(X.columns) == list(features.FEATURES)
    assert list(X.index.names) == ["result_run_id", "cif", "entry_id"]
    assert X.index.is_monotonic_increasing


def test_ac3_values_follow_screening_current(tiny_s: DuckDb) -> None:
    _write(tiny_s)
    X = mod("aml.screening.ml.features").read_features(tiny_s).reset_index()
    cur = query(tiny_s, "SELECT * FROM screening_current")
    both = X.merge(cur, on=["cif", "entry_id"], suffixes=("", "_sc"))
    assert len(both) == 55
    for col in ("token_set", "jaro_winkler", "fuzzy_score", "coverage", "name_score"):
        assert both[col].to_numpy() == pytest.approx(both[f"{col}_sc"].to_numpy(), abs=1e-9)
    gap = both["dob_gap_years_sc"].where(both["dob_gap_years_sc"].notna(), 0).clip(upper=50)
    assert both["dob_gap_years"].to_numpy() == pytest.approx(gap.to_numpy(), abs=1e-9)
    assert (both["gender_mismatch"] == 0).all()
    assert (both["id_match"] == 0).all()


def _row(db: DuckDb, cif: str, entry: str) -> pd.Series:
    X = mod("aml.screening.ml.features").read_features(db).reset_index()
    return X[(X["cif"] == cif) & (X["entry_id"] == entry)].iloc[0]


def test_ac3_known_rows(tiny_s: DuckDb) -> None:
    _write(tiny_s)
    a = _row(tiny_s, "CIF00000214", "WL000099")
    assert a["name_score"] == pytest.approx(78.09)
    assert (a["dob_known"], a["dob_gap_years"], a["dob_within_tolerance"]) == (1, 38, 0)
    assert (a["token_count_gap"], a["nationality_match"], a["sanctions_list"]) == (1, 1, 1)
    b = _row(tiny_s, "CIF00000104", "WL000158")
    assert (b["name_score"], b["dob_known"], b["alias_match"]) == (100.0, 0, 0)
    c = _row(tiny_s, "CIF00000032", "WL000084")
    assert (c["alias_match"], c["dob_known"], c["dob_within_tolerance"]) == (1, 1, 1)
    assert c["sanctions_list"] == 0


def test_ac3_without_screening_fails(tiny_loaded: DuckDb) -> None:
    error = mod("aml.screening.ml.model").ScreeningMlError
    with pytest.raises(error, match="run `aml screen` first"):
        _write(tiny_loaded)
    assert scalar(tiny_loaded, "SELECT COUNT(*) FROM screening_ml_features") == 0
