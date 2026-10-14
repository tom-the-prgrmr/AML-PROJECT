"""Helpers for the Phase 8c tests (specs/assistant-answering.md): X1-X4, RET, R4 / R0, K3 / K0, S_*.

Product modules are imported lazily (``mod``) so that a missing module fails the test that needs
it, not the collection of the whole suite. The fake retrievers and knowledge functions write no
audit row, as the spec requires.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aml.assistant.evidence import (
    Evidence,
    RetrieverNote,
    UntrustedField,
    clean_untrusted,
    render_evidence,
)
from aml.assistant.llm import FakeLLM
from aml.assistant.retrieve import Retrieval
from aml.assistant.text2cypher import GeneratedQuery
from aml.common.db import Database
from tests.assistant.kn_helpers import mod
from tests.cases.helpers import duck_settings
from tests.cases.summary_helpers import mini_n, v1

__all__ = ["duck_settings", "mini_n", "mod", "v1"]

CASE = "C-C01-20260302"
NOPE = "C-NOPE-20260101"
QUESTION = "Tài khoản A01 nhận tiền gì?"
ALERT_KEY = "STRUCTURING|A01|2026-03-02T09:00:00"
CHUNK_TEXT = (
    "Structuring: repeated cash deposits just under the reporting threshold of 400,000,000 VND."
)
CHUNK_TITLE = "Chunk KB-TYP-001#003 from document KB-TYP-001 (version 1.0, effective 2026-01-01)"
WATERMARK = "DRAFT — requires investigator review"


def U(field: str, text: str) -> UntrustedField:
    return UntrustedField(field, text, False)


X1 = Evidence(
    "E1",
    "fact",
    "case_graph",
    "records",
    "Transaction T01: 390,000,000 VND from - to A01 on 2026-03-02 09:00:00 via CASH",
    ("txn:T01", "account:A01"),
    {
        "txn_id": "T01",
        "amount": 390000000,
        "ts": "2026-03-02 09:00:00",
        "src": None,
        "dst": "A01",
        "channel": "CASH",
    },
)
X2 = Evidence(
    "E2",
    "fact",
    "case_graph",
    "neo4j",
    "Account A01 (CURRENT, VND) of CIF C01, opened 2025-01-01",
    ("account:A01", "customer:G-C01"),
    {"account_id": "A01", "cif": "C01", "open_date": "2025-01-01"},
)
X3 = Evidence(
    "E3",
    "passage",
    "vector",
    "neo4j",
    CHUNK_TITLE,
    ("chunk:KB-TYP-001#003",),
    {"chunk_id": "KB-TYP-001#003"},
    (U("chunk_text", CHUNK_TEXT),),
    0.9,
)
X4 = Evidence("E4", "fact", "text2cypher", "neo4j", "Query row 1: n=3", (), {"n": 3})
EV = (X1, X2, X3, X4)
CY = "MATCH (a:Account) RETURN count(a) AS n LIMIT 20"
Q1 = GeneratedQuery(1, CY, CY, "EXECUTED", None, "", 1, 0.01)
ROUTES = ("case_graph", "knowledge", "text2cypher")

S_OK1 = {
    "text": "Tài khoản A01 nhận 390,000,000 VND tiền mặt vào ngày 2026-03-02.",
    "cites": ["E1"],
}
S_OK2 = {
    "text": "Đây là dấu hiệu structuring: nộp tiền mặt nhiều lần ngay dưới ngưỡng báo cáo "
    "400 triệu đồng.",
    "cites": ["E3"],
}
S_AMOUNT = {**S_OK1, "text": S_OK1["text"].replace("390,000,000", "395,000,000")}
S_DATE = {**S_OK1, "text": S_OK1["text"].replace("2026-03-02", "2026-03-03")}
S_FAKE = {"text": "Giao dịch T99 chuyển 390,000,000 VND.", "cites": ["T99"]}
S_NOCITE = {"text": "Khách hàng có hành vi đáng ngờ.", "cites": []}
S_NOID = {"text": "Đồ thị có 3 tài khoản.", "cites": ["E4"]}
S_VERDICT = {"text": "Khách hàng này là sạch và không cần báo cáo.", "cites": ["E2"]}
J_NONE = '{"status": "insufficient_evidence", "sentences": []}'
N_OK = json.dumps(
    {
        "subject": [
            {
                "text": "Khách hàng G-C01 có 2 CIF và 2 tài khoản, mức rủi ro KYC HIGH.",
                "cites": ["E2"],
            }
        ],
        "timeline": [
            {
                "text": "Ngày 2026-03-02 có cảnh báo STRUCTURING với số tiền 390,000,000 VND.",
                "cites": ["E3"],
            },
            {"text": "Ngày 2026-03-09 tài khoản A01 nhận 999,000,000 VND.", "cites": ["E3"]},
        ],
        "typologies": [{"text": "Hoạt động khớp typology structuring.", "cites": ["E3"]}],
        "red_flags": [],
        "next_step": [
            {
                "text": "Đề nghị investigator đối chiếu chứng từ nộp tiền mặt của tài khoản A01.",
                "cites": ["E6"],
            }
        ],
    },
    ensure_ascii=False,
)
COUNT_TABLES = (
    "cases",
    "case_alerts",
    "case_dispositions",
    "case_runs",
    "alerts",
    "screening_results",
    "transactions",
)
DECISIONS_SQL = "('ANSWERED', 'INSUFFICIENT_EVIDENCE', 'FAILED', 'NARRATIVE_DRAFTED')"


def J(*sentences: dict[str, Any]) -> str:
    return json.dumps({"status": "answered", "sentences": list(sentences)}, ensure_ascii=False)


def LLM(*replies: str) -> FakeLLM:
    return FakeLLM(replies=list(replies))


def chats(fake: FakeLLM) -> list[dict[str, Any]]:
    return [c for c in fake.calls if c["kind"] == "chat"]


class RaisingLLM(FakeLLM):
    """A client whose ``chat`` raises the given error (and counts the call)."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def chat(self, messages: Any, *, json_schema: Any = None) -> str:
        self.calls.append({"kind": "chat", "messages": list(messages), "json_schema": json_schema})
        raise self.error


def RET(
    evidence: Sequence[Evidence],
    queries: Sequence[GeneratedQuery] = (),
    *,
    question: str = QUESTION,
    case_id: str | None = None,
    mode: str = "graphrag",
    notes: Sequence[RetrieverNote] = (),
) -> Retrieval:
    return Retrieval(
        question=question,
        case_id=case_id,
        mode=mode,
        routes=ROUTES,
        reasons=(),
        evidence=tuple(evidence),
        context_chars=len(render_evidence(evidence)),
        truncated=False,
        notes=tuple(notes),
        queries=tuple(queries),
        seconds=0.0,
    )


class FakeRetriever:
    """Returns ``RET(evidence, queries)`` (or raises ``error``) and records every call."""

    def __init__(
        self,
        evidence: Sequence[Evidence] = (),
        queries: Sequence[GeneratedQuery] = (),
        *,
        notes: Sequence[RetrieverNote] = (),
        error: Exception | None = None,
    ) -> None:
        self.evidence, self.queries, self.notes, self.error = evidence, queries, notes, error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Retrieval:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return RET(
            self.evidence,
            self.queries,
            question=args[2],
            case_id=kwargs.get("case_id"),
            mode=kwargs.get("mode", "graphrag"),
            notes=self.notes,
        )


def R4() -> FakeRetriever:
    return FakeRetriever(EV, (Q1,))


def R0() -> FakeRetriever:
    return FakeRetriever(())


class FakeKnowledge:
    """``knowledge(settings, question, *, llm, expand, seed_typologies)`` of 8b, scripted."""

    def __init__(self, items: Sequence[Evidence] = (), error: Exception | None = None) -> None:
        self.items, self.error = list(items), error
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> list[Evidence]:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return list(self.items)


def K3() -> FakeKnowledge:
    return FakeKnowledge([X3])


def K0() -> FakeKnowledge:
    return FakeKnowledge([])


def counts(db: Database) -> dict[str, int]:
    return {t: int(db.query_df(f"SELECT COUNT(*) FROM {t}").iloc[0, 0]) for t in COUNT_TABLES}


def audit_rows(db: Database) -> int:
    return int(db.query_df("SELECT COUNT(*) FROM audit_log").iloc[0, 0])


def audit8c(db: Database) -> list[dict[str, Any]]:
    df = db.query_df(
        "SELECT entity_type, entity_id, decision, reason, version, actor, details FROM audit_log "
        f"WHERE module = 'assistant' AND decision IN {DECISIONS_SQL} ORDER BY audit_id"
    )
    df.columns = [str(c).lower() for c in df.columns]
    rows = df.to_dict("records")
    for row in rows:
        raw = row["details"]
        row["details_raw"] = raw
        row["details"] = json.loads(raw) if isinstance(raw, str) else raw
    return rows


def injection_evidence(db: Database) -> list[Evidence]:
    """INJ of AC5: one Evidence per prompt-injection transaction of TINY, by txn_id."""
    df = db.query_df(
        "SELECT t.txn_id, t.txn_ts, t.from_account_id, t.to_account_id, t.amount_vnd, t.channel, "
        "t.memo FROM ground_truth g JOIN transactions t ON t.txn_id = g.entity_id "
        "WHERE g.typology = 'prompt_injection' AND g.entity_type = 'transaction' ORDER BY t.txn_id"
    )
    df.columns = [str(c).lower() for c in df.columns]
    out = []
    for i, r in enumerate(df.itertuples(), start=1):
        src = r.from_account_id if isinstance(r.from_account_id, str) else "-"
        dst = r.to_account_id if isinstance(r.to_account_id, str) else "-"
        text = (
            f"Transaction {r.txn_id}: {int(r.amount_vnd):,} VND from {src} to {dst} "
            f"on {r.txn_ts:%Y-%m-%d %H:%M:%S} via {r.channel}"
        )
        cleaned = clean_untrusted(r.memo, 300)
        assert cleaned is not None
        out.append(
            Evidence(
                f"E{i}",
                "fact",
                "case_graph",
                "records",
                text,
                (f"txn:{r.txn_id}",),
                {"txn_id": r.txn_id, "amount_vnd": int(r.amount_vnd)},
                (U("memo", cleaned[0]),),
            )
        )
    return out


def answering() -> Any:
    return mod("aml.assistant.answering")


def narrative() -> Any:
    return mod("aml.assistant.narrative")


def explainer() -> Any:
    return mod("aml.assistant.explainer")


def source_of(module_name: str) -> str:
    path = mod(module_name).__file__
    assert path is not None
    return Path(path).read_text(encoding="utf-8")


Factory = Callable[..., Any]
