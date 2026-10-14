"""Reading the model's JSON and checking every sentence against the evidence it cites (pure).

The checks are deterministic and run on every sentence, in this order:

1. ``no_citation``            -- nothing cited, or only items without an id (a Text2Cypher row)
2. ``unknown_citation``       -- a cite that is not a handle or an id of this turn (one made-up id
                                 spoils the sentence)
3. ``amount_not_in_evidence`` -- an amount the cited items do not hold (exact match, no tolerance),
                                 or an amount that cannot be read
   ``date_not_in_evidence``   -- a date the cited items do not hold
   ``direction_mismatch``     -- the sentence gives an account a side of a transfer
                                 (src / dst) that no cited item holds; an account
                                 of no cited transaction is ignored
4. ``speculative``            -- the sentence hedges ("may be", "có thể là")
   ``verdict_language``       -- the sentence clears, closes, approves or whitelists

Counts and relations are still not checked; the direction of a transfer is checked only by the
word lists of `facts.account_roles` (specs/assistant-direction-check.md). 8e measures the rest.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aml.assistant.evidence import Evidence, parse_citation
from aml.assistant.facts import (
    account_roles,
    evidence_dates,
    evidence_numbers,
    extract_amounts,
    extract_dates,
    has_unreadable_amount,
    is_speculative,
    is_verdict,
)

ISSUES = (
    "no_citation",
    "unknown_citation",
    "amount_not_in_evidence",
    "date_not_in_evidence",
    "direction_mismatch",
    "speculative",
    "verdict_language",
)
STATUSES = ("answered", "insufficient_evidence")
_INLINE = re.compile(r"\[\s*(E\d+(?:\s*,\s*E\d+)*)\s*\]")
_BLANKS = re.compile(r"\s+")
_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_NUMBER_MARKER = re.compile(r"\[\s*(\d+)\s*\]")  # "[2]": what a citation looks like to a reader


class ModelOutputError(ValueError):
    """The model's reply is not the JSON the schema asks for."""


@dataclass(frozen=True)
class Claim:
    text: str
    cites: tuple[str, ...]


@dataclass(frozen=True)
class Checked:
    text: str
    supported: bool  # == (issues == ())
    issues: tuple[str, ...]  # in the order of ISSUES
    refs: tuple[str, ...]  # resolved refs, in the order cited


# ---------------------------------------------------------------- parsing
def _load(raw: str) -> dict[str, Any]:
    """The object between the first ``{`` and the last ``}`` (a ```json fence is ignored)."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ModelOutputError("the reply holds no JSON object")
    try:
        value = json.loads(raw[start : end + 1])
    except ValueError as exc:
        raise ModelOutputError(f"the reply is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ModelOutputError("the reply is not a JSON object")
    return value


def _cites(value: Any) -> list[str]:
    """Split merged entries ("txn:T01, account:A01"), strip ``[]``; repeats are removed later."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    out = []
    for item in items:
        for part in str(item).split(","):
            cleaned = part.strip().strip("[]").strip()
            if cleaned:
                out.append(cleaned)
    return out


def _printable(text: str) -> str:
    """Control and format characters (C0, C1, ESC, bidi overrides) become a space."""
    return "".join(" " if unicodedata.category(ch) in ("Cc", "Cf") else ch for ch in text)


def _claim(item: Any, *, markers: bool) -> Claim | None:
    if not isinstance(item, dict) or not isinstance(item.get("text"), str):
        raise ModelOutputError("every sentence must be an object with a text string")
    cites = _cites(item.get("cites"))
    text = _printable(item["text"])
    for match in _INLINE.finditer(text):  # "[E3]" or "[E3, E4]" written into the sentence
        cites += [c.strip() for c in match.group(1).split(",")]
    text = _INLINE.sub(" ", text)
    if markers:  # a "[2]" of the model would read as a citation it never made: "(2)"
        text = _NUMBER_MARKER.sub(r"(\1)", text)
    text = _BEFORE_PUNCT.sub(r"\1", _BLANKS.sub(" ", text)).strip()
    if not text:
        return None
    return Claim(text, tuple(dict.fromkeys(cites)))


def parse_claims(items: Any, *, markers: bool = True) -> tuple[Claim, ...]:
    """Claims of a list of ``{text, cites}`` objects; empty sentences are dropped.

    ``markers`` turns a bracketed number of the model into ``(n)``. The narrative passes False:
    its markdown escapes the brackets instead (``\\[9\\]``).
    """
    if not isinstance(items, list):
        raise ModelOutputError("sentences must be a list")
    claims = (_claim(item, markers=markers) for item in items)
    return tuple(c for c in claims if c is not None)


def parse_model_answer(raw: str) -> tuple[str, tuple[Claim, ...]]:
    """(status, claims) of a Q&A reply; ``insufficient_evidence`` has no claim."""
    value = _load(raw)
    status = value.get("status")
    if status not in STATUSES:
        raise ModelOutputError(f"unknown status {status!r}")
    if status == "insufficient_evidence":
        return status, ()
    return status, parse_claims(value.get("sentences"))


def parse_model_sections(raw: str, keys: Sequence[str]) -> dict[str, tuple[Claim, ...]]:
    """Claims per section of a narrative reply; a missing section is empty."""
    value = _load(raw)
    return {key: parse_claims(value.get(key, []), markers=False) for key in keys}


# ---------------------------------------------------------------- checking
def _first(evidence: Evidence) -> tuple[str, str] | None:
    """(full citation, bare id) of the item's first citation."""
    if not evidence.citations:
        return None
    return evidence.citations[0], parse_citation(evidence.citations[0])[1]


def resolve(cite: str, evidence: Sequence[Evidence]) -> list[Evidence]:
    """The items a cite points to: its ref, or every item whose FIRST citation is ``kind:id`` or
    the bare ``id``. Empty when the cite is unknown."""
    by_ref = [e for e in evidence if e.ref == cite]
    if by_ref:
        return by_ref
    return [e for e in evidence if (first := _first(e)) is not None and cite in first]


def transfer_sides(evidence: Evidence) -> frozenset[tuple[str, str]]:
    """The (account, "src" | "dst") pairs an item holds: a transaction's two sides (a missing
    side of a cash deposit gives none), or the
    counterparty of a narrative item (IN: it sent; OUT: it received). Any other item holds none."""
    data = evidence.data
    kinds = [parse_citation(c)[0] for c in evidence.citations[:1]]
    if kinds == ["txn"] and "src" in data and "dst" in data:
        return frozenset(
            (data[key], role)
            for key, role in (("src", "src"), ("dst", "dst"))
            if isinstance(data[key], str) and data[key]
        )
    account = data.get("account_id")
    if (
        evidence.retriever == "case_view"
        and kinds == ["account"]
        and data.get("direction") in ("IN", "OUT")
        and isinstance(account, str)
    ):
        return frozenset({(account, "src" if data["direction"] == "IN" else "dst")})
    return frozenset()


def _direction_mismatch(text: str, items: Sequence[Evidence]) -> bool:
    sides = frozenset().union(*(transfer_sides(e) for e in items))
    roles = account_roles(text, {account for account, _ in sides})
    return any((account, r) not in sides for account, rs in roles.items() for r in rs)


def check_claim(claim: Claim, evidence: Sequence[Evidence]) -> Checked:
    resolved: dict[str, Evidence] = {}
    unknown = False
    for cite in claim.cites:
        found = resolve(cite, evidence)
        unknown = unknown or not found
        resolved.update((e.ref, e) for e in found)
    items = list(resolved.values())
    issues = set()
    if not claim.cites or (items and not any(e.citations for e in items)):
        issues.add("no_citation")
    if unknown:
        issues.add("unknown_citation")
    if items:
        numbers = frozenset().union(*(evidence_numbers(e) for e in items))
        unreadable = has_unreadable_amount(claim.text)  # looks like money, cannot be read
        if unreadable or not extract_amounts(claim.text) <= numbers:
            issues.add("amount_not_in_evidence")
        dates = frozenset().union(*(evidence_dates(e) for e in items))
        if not extract_dates(claim.text) <= dates:
            issues.add("date_not_in_evidence")
        if _direction_mismatch(claim.text, items):
            issues.add("direction_mismatch")
    if is_speculative(claim.text):
        issues.add("speculative")
    if is_verdict(claim.text):
        issues.add("verdict_language")
    ordered = tuple(i for i in ISSUES if i in issues)
    return Checked(claim.text, not ordered, ordered, tuple(resolved))


def check_claims(claims: Sequence[Claim], evidence: Sequence[Evidence]) -> tuple[Checked, ...]:
    return tuple(check_claim(c, evidence) for c in claims)
