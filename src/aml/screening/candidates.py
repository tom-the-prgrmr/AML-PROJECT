"""Tier 1 blocking: which (customer name, list name) pairs are worth scoring.

Scoring every customer name against every list name is |C| x |W|. Instead, an inverted index
maps each customer token to the customer names containing it; a list token is compared only with
customer tokens of the same first letter and similar length. A pair is a candidate when it shares
a matching token and either the match involves a rare token, or one name is fully covered by the
other (so names made only of common tokens, such as ``NGUYEN VAN``, still get scored and cleared
with a reason).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from aml.common.config import ScreeningConfig
from aml.screening.idf import TokenStats
from aml.screening.scoring import tokens_match


def candidate_name_pairs(
    customer_norms: Iterable[str],
    list_norms: Iterable[str],
    stats: TokenStats,
    cfg: ScreeningConfig,
) -> set[tuple[str, str]]:
    """Return ``(customer name, list name)`` candidates; both sides normalised, de-duplicated."""
    customers = {n: frozenset(n.split()) for n in set(customer_norms) if n.split()}
    listed = {n: frozenset(n.split()) for n in set(list_norms) if n.split()}

    postings: dict[str, set[str]] = defaultdict(set)  # customer token -> customer names
    for name, tokens in customers.items():
        for t in tokens:
            postings[t].add(name)
    vocab_by_letter: dict[str, list[str]] = defaultdict(list)
    for t in postings:
        vocab_by_letter[t[0]].append(t)

    matches: dict[str, frozenset[str]] = {}  # list token -> matching customer tokens (cached)

    def matching(w: str) -> frozenset[str]:
        if w not in matches:
            matches[w] = frozenset(
                u
                for u in vocab_by_letter.get(w[0], ())
                if abs(len(u) - len(w)) <= cfg.token_length_band and tokens_match(u, w, cfg)
            )
        return matches[w]

    def names_with(tokens: Iterable[str]) -> set[str]:
        found: set[str] = set()
        for u in tokens:
            found |= postings[u]
        return found

    pairs: set[tuple[str, str]] = set()
    for list_name, w_tokens in listed.items():
        per_token = [matching(w) for w in w_tokens]
        matched_vocab = frozenset().union(*per_token)
        if not matched_vocab:
            continue
        # (a) a rare customer token matches
        keep = names_with(u for u in matched_vocab if stats.is_rare(u, cfg.rare_token_max_df_rate))
        # (b) every list token has a matching token in the customer name
        if all(per_token):
            covered = names_with(per_token[0])
            for m in per_token[1:]:
                covered &= names_with(m)
            keep |= covered
        # (c) every customer token has a matching token in the list name
        for name in names_with(matched_vocab) - keep:
            if customers[name] <= matched_vocab:
                keep.add(name)
        pairs.update((name, list_name) for name in keep)
    return pairs
