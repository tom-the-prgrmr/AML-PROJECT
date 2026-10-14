"""AC2 for specs/screening-ml.md: the pure `match_features`."""

from __future__ import annotations

import math
from datetime import date

import pytest

from .helpers import C, E, F, identifiers, mod

NAME = "NGUYEN VAN AN"


def test_ac2_exact_match() -> None:
    f = F(NAME, NAME, C(), E(1971))
    assert list(f) == list(mod("aml.screening.ml.features").FEATURES)
    assert len(f) == 19
    want = {
        "token_set": 100.0, "jaro_winkler": 100.0, "fuzzy_score": 100.0, "coverage": 1.0,
        "name_score": 100.0, "matched_tokens": 3, "token_count_gap": 0, "rare_matched": 1,
        "max_matched_idf": 1.504077, "common_only": 0, "dob_known": 1, "dob_gap_years": 0,
        "dob_within_tolerance": 1, "nationality_match": 1, "nationality_mismatch": 0,
        "gender_mismatch": 0, "id_match": 0, "alias_match": 0, "sanctions_list": 0,
    }  # fmt: skip
    assert f == pytest.approx(want, abs=1e-9)
    assert all(type(v) is float and math.isfinite(v) for v in f.values())


def test_ac2_partial_names() -> None:
    f = F(NAME, "NGUYEN VAN", C(), E(1971))
    assert f["name_score"] == pytest.approx(46.42)
    assert f["coverage"] == pytest.approx(0.5188)
    assert f["matched_tokens"] == 2
    assert f["token_count_gap"] == 1
    assert f["rare_matched"] == 0
    assert f["max_matched_idf"] == pytest.approx(0.81093)
    assert f["common_only"] == 1
    g = F("TRAN VAN LONG", "TRAN HUU LONG", C(), E(1971))
    assert g["fuzzy_score"] == pytest.approx(74.88)
    assert g["name_score"] == pytest.approx(44.45)
    assert g["rare_matched"] == 2
    assert g["max_matched_idf"] == pytest.approx(1.098612)


@pytest.mark.parametrize(
    ("year", "known", "gap", "within"),
    [(1973, 1, 2, 0), (2031, 1, 50, 0), (None, 0, 0, 0), (1971, 1, 0, 1)],
)
def test_ac2_birth_year(year: int | None, known: int, gap: int, within: int) -> None:
    f = F(NAME, NAME, C(), E(year))
    assert (f["dob_known"], f["dob_gap_years"], f["dob_within_tolerance"]) == (known, gap, within)


def test_ac2_customer_born_after_as_of_is_unknown() -> None:
    future = identifiers(dob=date(2033, 1, 20), dob_year=2033, nationality="VN")
    assert F(NAME, NAME, future, E(1971))["dob_known"] == 0


def test_ac2_nationality() -> None:
    f = F(NAME, NAME, C(), E(1971, "RU"))
    assert (f["nationality_match"], f["nationality_mismatch"]) == (0, 1)
    g = F(NAME, NAME, C(nationality=None), E(1971))
    assert (g["nationality_match"], g["nationality_mismatch"]) == (0, 0)


def test_ac2_gender_and_id() -> None:
    assert F(NAME, NAME, C(gender="M"), E(1971, gender="F"))["gender_mismatch"] == 1
    assert F(NAME, NAME, C(gender="M"), E(1971, gender=None))["gender_mismatch"] == 0
    same = F(NAME, NAME, C(id_number="B1234567"), E(1971, id_number="b-1234567"))
    other = F(NAME, NAME, C(id_number="B1234567"), E(1971, id_number="C7654321"))
    assert (same["id_match"], other["id_match"]) == (1, 0)


def test_ac2_alias_and_list_type() -> None:
    assert F(NAME, NAME, C(), E(1971), name_type="AKA")["alias_match"] == 1
    assert F(NAME, NAME, C(), E(1971), list_type="SANCTIONS")["sanctions_list"] == 1
    assert F(NAME, NAME, C(), E(1971), list_type=None)["sanctions_list"] == 0
