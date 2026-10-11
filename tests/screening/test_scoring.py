"""AC5-AC9 for specs/screening-normalize-score.md: IDF, token matching and the combined score."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.db import DuckDb

from .helpers import mod, norm


def test_ac5_idf_and_rarity_on_base(base_stats_fixture: Any) -> None:
    s = base_stats_fixture
    assert s.n_names == 8
    assert round(s.idf("NGUYEN"), 4) == 0.8109
    assert round(s.idf("THI"), 4) == 1.0986
    assert round(s.idf("AN"), 4) == 1.5041
    assert round(s.idf("BASHIROV"), 4) == 2.1972
    assert s.is_rare("NGUYEN", 0.25) is False
    assert s.is_rare("THI", 0.25) is True
    assert s.is_rare("BASHIROV", 0.02) is True


def test_ac5_doc_freq_counts_names_once(base_stats_fixture: Any) -> None:
    df = base_stats_fixture.doc_freq
    got = (df["NGUYEN"], df["VAN"], df["THI"], df["HOA"], df["TRAN"], df["LONG"])
    assert got == (3, 3, 2, 2, 2, 2)


def test_ac5_empty_stats() -> None:
    s = mod("aml.screening.idf").build_token_stats([])
    assert s.n_names == 0
    assert s.idf("X") == 0.0
    assert s.is_rare("X", 0.02) is True


@pytest.fixture
def tiny_stats(cfg: Any, tiny_parquet: Path, tmp_path: Path) -> Iterator[Any]:
    db = DuckDb(tmp_path / "tiny.duckdb")
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    try:
        yield mod("aml.screening.idf").customer_token_stats(db, cfg)
    finally:
        db.close()


def test_ac6_customer_token_stats_on_tiny(cfg: Any, tiny_stats: Any) -> None:
    s = tiny_stats
    assert s.n_names == 300
    assert len(s.doc_freq) == 85
    assert s.doc_freq["NGUYEN"] == 115
    assert s.doc_freq["THI"] == 72
    assert s.doc_freq["VAN"] == 20
    assert round(s.idf("NGUYEN"), 4) == 0.9535
    assert round(s.idf("VAN"), 4) == 2.6626
    assert round(s.idf("BASHIROV"), 4) == 5.7071
    assert s.is_rare("NGUYEN", cfg.rare_token_max_df_rate) is False


@pytest.mark.parametrize(
    ("a", "b"),
    [("TRA", "TRAN"), ("AN", "ANH"), ("TRAN", "TRANG"), ("NGUYEN", "NGUYEN")],
)
def test_ac7_tokens_match(cfg: Any, a: str, b: str) -> None:
    assert mod("aml.screening.scoring").tokens_match(a, b, cfg) is True


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("HA", "HOA"),
        ("LE", "LY"),
        ("MUHAMMAD", "MOHAMMED"),
        ("HANH", "ANH"),
        ("ZHANG", "CHANG"),
        ("NGUYEN", "NGUYENTHI"),
    ],
)
def test_ac7_tokens_do_not_match(cfg: Any, a: str, b: str) -> None:
    assert mod("aml.screening.scoring").tokens_match(a, b, cfg) is False


def _score(a: str, b: str, stats: Any, cfg: Any) -> Any:
    return mod("aml.screening.scoring").score_names(norm(a, cfg), b, stats, cfg)


@pytest.mark.parametrize(
    ("a", "b"), [("Nguyễn Văn An", "NGUYEN VAN AN"), ("Đỗ Xuân Sơn", "SON DO XUAN")]
)
def test_ac8_identical_names_score_100(cfg: Any, base_stats_fixture: Any, a: str, b: str) -> None:
    r = _score(a, b, base_stats_fixture, cfg)
    got = (r.token_set, r.jaro_winkler, r.fuzzy, r.coverage, r.score)
    assert got == (100.0, 100.0, 100.0, 1.0, 100.0)


def test_ac8_typo_still_scores_high(cfg: Any, base_stats_fixture: Any) -> None:
    r = _score("Trầ Hữu Long", "TRAN HUU LONG", base_stats_fixture, cfg)
    assert r.token_set == 96.0
    assert r.jaro_winkler == 98.46
    assert r.fuzzy == 97.23
    assert r.coverage == 1.0
    assert r.score == 97.23
    assert r.matched == ("TRA", "HUU", "LONG")


def test_ac8_unrelated_names_score_zero(cfg: Any, base_stats_fixture: Any) -> None:
    r = _score("Phạm Quốc Bảo", "MUHAMMAD AL RASHID", base_stats_fixture, cfg)
    assert r.coverage == 0.0
    assert r.score == 0.0
    assert r.matched == ()


@pytest.fixture
def rare_cfg(cfg: Any) -> Any:
    return cfg.model_copy(update={"rare_token_max_df_rate": 0.25})


def test_ac9_common_tokens_only_score_low(rare_cfg: Any, base_stats_fixture: Any) -> None:
    r = _score("Nguyễn Văn", "NGUYEN VAN BASHIROV", base_stats_fixture, rare_cfg)
    assert r.token_set == 100.0
    assert r.fuzzy == 72.72
    assert r.coverage == 0.4247
    assert r.score == 30.88
    assert r.matched == ("NGUYEN", "VAN")
    assert r.common_only is True

    r = _score("Nguyễn Văn An", "NGUYEN VAN", base_stats_fixture, rare_cfg)
    assert r.token_set == 100.0
    assert r.fuzzy == 89.48
    assert r.coverage == 0.5188
    assert r.score == 46.42
    assert r.common_only is True


def test_ac9_near_miss_and_rare_match(rare_cfg: Any, base_stats_fixture: Any) -> None:
    r = _score("Nguyễn Thị Hoa", "NGUYEN THI HA", base_stats_fixture, rare_cfg)
    assert (r.fuzzy, r.coverage, r.score) == (97.08, 0.465, 45.14)

    r = _score("Lê Thị Hoa", "LY THI HOA", base_stats_fixture, rare_cfg)
    assert (r.fuzzy, r.coverage, r.score) == (93.0, 0.5, 46.5)
    assert r.matched == ("THI", "HOA")
    assert r.common_only is False


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Nguyễn Văn", "NGUYEN VAN BASHIROV"),
        ("Nguyễn Văn An", "NGUYEN VAN"),
        ("Nguyễn Thị Hoa", "NGUYEN THI HA"),
        ("Lê Thị Hoa", "LY THI HOA"),
    ],
)
def test_ac9_score_is_symmetric(rare_cfg: Any, base_stats_fixture: Any, a: str, b: str) -> None:
    fwd = _score(a, b, base_stats_fixture, rare_cfg)
    rev = mod("aml.screening.scoring").score_names(
        b, norm(a, rare_cfg), base_stats_fixture, rare_cfg
    )
    assert fwd.score == rev.score


def test_ac9_empty_side_gives_all_zero(rare_cfg: Any, base_stats_fixture: Any) -> None:
    r = mod("aml.screening.scoring").score_names("", "NGUYEN VAN AN", base_stats_fixture, rare_cfg)
    assert (r.token_set, r.jaro_winkler, r.fuzzy, r.coverage, r.score) == (0.0,) * 5
    assert r.matched == ()
    assert r.common_only is False
