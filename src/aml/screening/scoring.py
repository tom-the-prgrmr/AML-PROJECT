"""Combined name score: fuzzy similarity multiplied by IDF-weighted token coverage.

``token_set_ratio`` returns 100 whenever one name is a subset of the other, so the fuzzy part
alone would rate ``NGUYEN VAN`` against ``NGUYEN VAN BASHIROV`` as a perfect match. Coverage
weights each token by its rarity and takes the worse side, which pulls such pairs down.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from aml.common.config import ScreeningConfig
from aml.screening.idf import TokenStats
from aml.screening.normalize import name_key


def tokens_match(a: str, b: str, cfg: ScreeningConfig) -> bool:
    """Same token, or same first letter, close length and Jaro-Winkler >= ``token_match_min``."""
    if a == b:
        return True
    return (
        bool(a)
        and bool(b)
        and a[0] == b[0]
        and abs(len(a) - len(b)) <= cfg.token_length_band
        and JaroWinkler.similarity(a, b) >= cfg.token_match_min
    )


@dataclass(frozen=True)
class NameScore:
    token_set: float  # rapidfuzz token_set_ratio, 0..100
    jaro_winkler: float  # 100 * Jaro-Winkler on the order-free keys
    fuzzy: float  # weighted blend of the two
    coverage: float  # IDF-weighted token coverage, 0..1 (worse of the two sides)
    score: float  # round(fuzzy * coverage, 2)
    matched: tuple[str, ...]  # customer tokens with a matching list token, in original order
    common_only: bool  # matched is non-empty and none of the matched tokens is rare


def _coverage(
    tokens: list[str], others: list[str], stats: TokenStats, cfg: ScreeningConfig
) -> tuple[float, tuple[str, ...]]:
    total = sum(stats.idf(t) for t in tokens)
    hits = tuple(t for t in tokens if any(tokens_match(t, o, cfg) for o in others))
    if total <= 0:
        return 0.0, hits
    return sum(stats.idf(t) for t in hits) / total, hits


def score_names(
    customer_norm: str, list_norm: str, stats: TokenStats, cfg: ScreeningConfig
) -> NameScore:
    """Score two normalised names (customer side first)."""
    cust, lst = customer_norm.split(), list_norm.split()
    if not cust or not lst:
        return NameScore(0.0, 0.0, 0.0, 0.0, 0.0, (), False)
    token_set = round(fuzz.token_set_ratio(customer_norm, list_norm), 2)
    jw = round(100 * JaroWinkler.similarity(name_key(customer_norm), name_key(list_norm)), 2)
    fuzzy = round(cfg.token_set_weight * token_set + cfg.jaro_winkler_weight * jw, 2)
    cov_c, matched = _coverage(cust, lst, stats, cfg)
    cov_w, _ = _coverage(lst, cust, stats, cfg)
    coverage = round(min(cov_c, cov_w), 4)
    common_only = bool(matched) and not any(
        stats.is_rare(t, cfg.rare_token_max_df_rate) for t in matched
    )
    return NameScore(
        token_set, jw, fuzzy, coverage, round(fuzzy * coverage, 2), matched, common_only
    )
