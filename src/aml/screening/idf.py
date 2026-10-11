"""Token statistics over the customer base: IDF weights and token rarity.

A token such as ``NGUYEN`` (about a third of customers) says little; a token seen nowhere in the
customer base gets the largest IDF, so a watchlist-only token is the strongest evidence.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from aml.common.config import ScreeningConfig
from aml.common.db import Database
from aml.screening.normalize import normalize_name


@dataclass(frozen=True)
class TokenStats:
    n_names: int  # number of non-empty normalised names
    doc_freq: Mapping[str, int]  # token -> number of names containing it (once per name)

    def idf(self, token: str) -> float:
        return math.log((self.n_names + 1) / (self.doc_freq.get(token, 0) + 1))

    def is_rare(self, token: str, max_df_rate: float) -> bool:
        if self.n_names == 0:
            return True
        return self.doc_freq.get(token, 0) / self.n_names <= max_df_rate


def build_token_stats(normalized_names: Iterable[str]) -> TokenStats:
    """Count, per token, the names that contain it; empty names are ignored."""
    counts: Counter[str] = Counter()
    n_names = 0
    for name in normalized_names:
        tokens = set(name.split())
        if not tokens:
            continue
        n_names += 1
        counts.update(tokens)
    return TokenStats(n_names=n_names, doc_freq=dict(counts))


def customer_token_stats(db: Database, cfg: ScreeningConfig) -> TokenStats:
    """Token statistics over ``customers.full_name`` (by position: Oracle upper-cases)."""
    df = db.query_df("SELECT full_name FROM customers")
    return build_token_stats(normalize_name(v, cfg) for v in df.iloc[:, 0])
