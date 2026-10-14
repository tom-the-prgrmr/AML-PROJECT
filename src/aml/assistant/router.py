"""Deterministic router: which retrievers answer a question (pure Python, no model call).

Rules and keywords are constants, so a routing decision can be tested with a plain string and
explained in one sentence. Changing a keyword means changing ``ROUTER_VERSION``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ROUTES = ("txn_lookup", "case_graph", "knowledge", "text2cypher")
ROUTER_VERSION = "router/rules-v1"
DEFAULT_REASON = "knowledge: no rule matched (default)"

# matched on the normalised question (lower case, no diacritics), on word boundaries
KNOWLEDGE_KEYWORDS = (
    "typology", "dau hieu", "red flag", "quy trinh", "sop", "quy dinh", "thong tu", "nghi dinh",
    "luat", "huong dan", "la gi", "the nao", "tai sao", "vi sao", "khop", "buoc tiep theo", "why",
    "what is", "how to", "procedure", "regulation", "match", "next step", "structuring",
    "smurfing", "mule", "round-tripping",
)  # fmt: skip
COUNT_KEYWORDS = (
    "bao nhieu", "dem", "tong", "top", "lon nhat", "nhieu nhat", "liet ke", "trung binh",
    "how many", "count", "total", "largest", "list", "average",
)  # fmt: skip

_EDGE = r"(?<![A-Za-z0-9-])"
_CASE_RE = re.compile(_EDGE + r"C-[A-Za-z0-9]+-\d{8}(?!\d)")
_CUSTOMER_RE = re.compile(_EDGE + r"G-[A-Za-z0-9-]*[A-Za-z0-9]")
_ACCOUNT_RE = re.compile(_EDGE + r"(?:A\d{10}|EXT-\d+)(?![A-Za-z0-9])")
_TXN_RE = re.compile(_EDGE + r"T\d{10}(?![A-Za-z0-9])")


@dataclass(frozen=True)
class RoutePlan:
    routes: tuple[str, ...]  # a subset of ROUTES, always in the order of ROUTES
    reasons: tuple[str, ...]  # one sentence per route: "<route>: <why>"
    case_id: str | None  # the parameter, or a case id found in the question
    customer: str | None  # a golden customer id found in the question
    txn_ids: tuple[str, ...]  # transaction ids in the question, in order, no repeats


def normalise_question(question: str) -> str:
    """Lower case, no Vietnamese diacritics, single spaces."""
    decomposed = unicodedata.normalize("NFD", question.casefold())
    plain = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(plain.replace("đ", "d").split())


def _found(keywords: tuple[str, ...], text: str) -> list[str]:
    return [k for k in keywords if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", text)]


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group() if match else None


def route(
    question: str, *, case_id: str | None = None, text2cypher_enabled: bool = True
) -> RoutePlan:
    """Apply every rule; the result lists the chosen routes in the order of ``ROUTES``."""
    text = normalise_question(question)
    asked_case = _first(_CASE_RE, question)
    customer = _first(_CUSTOMER_RE, question)
    txn_ids = tuple(dict.fromkeys(_TXN_RE.findall(question)))
    effective_case = case_id or asked_case
    reasons: dict[str, str] = {}

    if txn_ids and effective_case is None:
        reasons["txn_lookup"] = f"txn_lookup: transaction id {', '.join(txn_ids)} in the question"
    if case_id:
        reasons["case_graph"] = "case_graph: case_id given"
    elif asked_case:
        reasons["case_graph"] = f"case_graph: case id {asked_case} in the question"
    elif customer:
        reasons["case_graph"] = f"case_graph: customer id {customer} in the question"
    knowledge_hits = _found(KNOWLEDGE_KEYWORDS, text)
    if knowledge_hits:
        reasons["knowledge"] = f"knowledge: keyword '{knowledge_hits[0]}' in the question"
    count_hits = _found(COUNT_KEYWORDS, text)
    if text2cypher_enabled:
        if count_hits:
            reasons["text2cypher"] = f"text2cypher: keyword '{count_hits[0]}' in the question"
        elif "case_graph" not in reasons and _ACCOUNT_RE.search(question):
            account = _first(_ACCOUNT_RE, question)
            reasons["text2cypher"] = f"text2cypher: account id {account} in the question"
    if not reasons:
        reasons["knowledge"] = DEFAULT_REASON

    routes = tuple(r for r in ROUTES if r in reasons)
    return RoutePlan(
        routes=routes,
        reasons=tuple(reasons[r] for r in routes),
        case_id=effective_case,
        customer=customer,
        txn_ids=txn_ids,
    )
