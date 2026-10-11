"""AC10 for specs/screening-normalize-score.md: config keys, dependency and the design note."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from aml.common.config import load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_ac10_default_config_values() -> None:
    s = load_settings(environ={}).screening
    assert s.token_set_weight == 0.5
    assert s.jaro_winkler_weight == 0.5
    assert s.token_match_min == 0.90
    assert s.token_length_band == 1
    assert s.rare_token_max_df_rate == 0.02
    assert "TNHH" in s.legal_strong_terms
    assert "CONG TY" in s.legal_weak_terms


def test_ac10_weights_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="must sum to 1"):
        load_settings(environ={"AML__SCREENING__TOKEN_SET_WEIGHT": "0.7"})


def test_ac10_rapidfuzz_is_a_dependency() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert any(d.strip().lower().startswith("rapidfuzz") for d in deps)


def test_ac10_docs_explain_why_not_soundex() -> None:
    path = ROOT / "docs" / "screening.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    for needle in ("Soundex", "Metaphone", "HOANG", "HONG", "HUNG", "HUONG", "H520"):
        assert needle in text, needle
