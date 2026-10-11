"""Name normalisation: customer names (accented) and watchlist names (plain Latin) meet here.

All functions are pure. ``normalize_name`` strips diacritics, upper-cases, keeps letters only
and drops legal-entity terms (see ``ScreeningConfig``); ``name_key`` makes it order-free.
"""

from __future__ import annotations

import re
import unicodedata

from aml.common.config import ScreeningConfig

_NON_LATIN = re.compile(r"[^A-Z]+")
_D_STROKE = str.maketrans({"đ": "d", "Đ": "D"})


def strip_diacritics(text: str) -> str:
    """Remove combining marks (NFD) and map the Vietnamese d-stroke; case is preserved."""
    decomposed = unicodedata.normalize("NFD", text.translate(_D_STROKE))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _terms(raw_terms: list[str]) -> list[list[str]]:
    """Config terms as token lists, longest phrase first."""
    terms = [t.upper().split() for t in raw_terms if t.strip()]
    return sorted(terms, key=len, reverse=True)


def _drop_terms(tokens: list[str], terms: list[list[str]]) -> list[str]:
    """Remove every occurrence of a term, matched on token boundaries (longest first)."""
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        for term in terms:
            if tokens[i : i + len(term)] == term:
                i += len(term)
                break
        else:
            kept.append(tokens[i])
            i += 1
    return kept


def normalize_name(raw: str | None, cfg: ScreeningConfig) -> str:
    """Normalise a raw name; anything that is not a usable string gives ``""``."""
    if not isinstance(raw, str):
        return ""
    tokens = _NON_LATIN.sub(" ", strip_diacritics(raw).upper()).split()
    kept = _drop_terms(tokens, _terms(cfg.legal_strong_terms))
    if len(kept) < len(tokens):  # weak terms only count when a strong term was present
        kept = _drop_terms(kept, _terms(cfg.legal_weak_terms))
    return " ".join(kept or tokens)


def name_key(normalized: str) -> str:
    """Order-free key: tokens sorted ascending, repeated tokens kept."""
    return " ".join(sorted(normalized.split()))
