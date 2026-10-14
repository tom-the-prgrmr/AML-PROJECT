"""AC11 for specs/assistant-retrievers.md: transaction lookup and the context budget of `retrieve`.

Nothing here needs Neo4j: the lookup reads the system of record only (the `fit_context` part of
AC11 is in test_retrieval_evidence.py).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from aml.common.db import DuckDb

from .kn_helpers import mod
from .rt_helpers import (
    CASE_ID,
    INJ,
    Fakes,
    add_two_transactions,
    audit_rows,
    duck_settings,
    ev_mod,
    filler,
    llm_mod,
    memo_lines,
    offline_settings,
    retrieve_mod,
    txn_mod,
)

HOSTILE_ID = "x' OR '1'='1"
ASKED = ["T0000000001", "T0000000002", "T0000000009", "T0000000001", HOSTILE_ID]
QUESTION_1 = "Giao dịch T0000000001 có ghi chú gì?"
QUESTION_9 = "Giao dịch T0000000009 có ghi chú gì?"


@pytest.fixture
def db(duck: DuckDb) -> DuckDb:
    mod("aml.dba.schema").apply_schema(duck)
    add_two_transactions(duck)
    return duck


def test_ac11_transaction_facts_in_the_order_asked(db: DuckDb) -> None:
    ev = txn_mod().transaction_facts(db, duck_settings(), ASKED)
    assert len(ev) == 2
    assert [e.ref for e in ev] == ["E1", "E2"]
    assert {(e.kind, e.retriever, e.source) for e in ev} == {("fact", "txn_lookup", "records")}
    first, second = ev
    assert first.text == (
        "Transaction T0000000001: 5,000,000 VND from A01 to A20 on 2026-03-03 11:00:00 "
        "via INTERNAL_TRANSFER"
    )
    assert first.citations == ("txn:T0000000001", "account:A01", "account:A20")
    assert first.data == {
        "txn_id": "T0000000001",
        "src": "A01",
        "dst": "A20",
        "amount": 5_000_000,
        "ts": datetime(2026, 3, 3, 11, 0, 0),
        "channel": "INTERNAL_TRANSFER",
    }
    assert type(first.data["amount"]) is int
    assert type(first.data["ts"]) is datetime
    assert first.untrusted == (ev_mod().UntrustedField("memo", INJ, False),)
    assert "ignore previous" not in first.text
    assert second.text == (
        "Transaction T0000000002: 9,000,000 VND from A02 to - on 2026-03-06 09:00:00 via CASH"
    )
    assert second.citations == ("txn:T0000000002", "account:A02")
    assert second.untrusted == ()


def test_ac11_an_unsafe_id_never_reaches_the_sql(
    db: DuckDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = db.query_df

    def spy(sql: str, params: Any = None) -> Any:
        seen.append(sql)
        return real(sql, params)

    monkeypatch.setattr(db, "query_df", spy)
    txn_mod().transaction_facts(db, duck_settings(), ASKED)
    assert len(seen) == 1
    assert "'1'" not in seen[0]
    assert " OR " not in seen[0].upper().split("WHERE", 1)[1]
    seen.clear()
    assert txn_mod().transaction_facts(db, duck_settings(), [HOSTILE_ID]) == []
    assert seen == []


def test_ac11_memos_can_be_switched_off(db: DuckDb) -> None:
    settings = duck_settings(AML__ASSISTANT__RETRIEVAL__INCLUDE_MEMOS="false")
    ev = txn_mod().transaction_facts(db, settings, ASKED)
    assert ev[0].untrusted == ()


def test_ac11_no_ids_no_facts(db: DuckDb) -> None:
    assert txn_mod().transaction_facts(db, duck_settings(), []) == []


def test_ac11_retrieve_looks_a_transaction_up_without_neo4j(db: DuckDb) -> None:
    e = ev_mod()
    r = retrieve_mod().retrieve(db, offline_settings(), QUESTION_1, llm=llm_mod().FakeLLM())
    assert r.routes == ("txn_lookup",)
    assert [x.ref for x in r.evidence] == ["E1"]
    assert r.evidence[0].untrusted == (e.UntrustedField("memo", INJ, False),)
    assert r.notes == ()
    assert memo_lines(e.render_evidence(r.evidence), "E1") == [
        f'<untrusted field="memo" ref="E1">{INJ}</untrusted>'
    ]


def test_ac11_retrieve_notes_a_transaction_that_does_not_exist(db: DuckDb) -> None:
    m = retrieve_mod()
    r = m.retrieve(db, offline_settings(), QUESTION_9, llm=llm_mod().FakeLLM())
    assert r.evidence == ()
    assert r.notes == (
        m.RetrieverNote("txn_lookup", "skipped", "no transaction found for: T0000000009"),
    )


def test_ac11_vector_mode_does_not_look_transactions_up(db: DuckDb) -> None:
    with pytest.raises(ev_mod().RetrievalUnavailableError):
        retrieve_mod().retrieve(
            db, offline_settings(), QUESTION_1, mode="vector", llm=llm_mod().FakeLLM()
        )


def test_ac11_retrieve_cuts_the_evidence_to_the_context_budget(
    db: DuckDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    m = retrieve_mod()
    fakes = Fakes(monkeypatch)
    fakes.case_evidence = [filler(f"E{i}") for i in range(1, 31)]
    settings = duck_settings(AML__ASSISTANT__RETRIEVAL__MAX_CONTEXT_CHARS="1000")
    r = m.retrieve(
        db,
        settings,
        "Tóm tắt hoạt động của khách hàng",
        case_id=CASE_ID,
        llm=llm_mod().FakeLLM(),
    )
    assert len(r.evidence) == 8
    assert [x.ref for x in r.evidence] == [f"E{i}" for i in range(1, 9)]
    assert r.context_chars <= 1000
    assert r.context_chars == len(ev_mod().render_evidence(r.evidence))
    assert r.truncated is True
    assert r.notes == (
        m.RetrieverNote(
            "case_graph", "truncated", "kept 8 of 30 evidence item(s): context budget 1000 chars"
        ),
    )
    (row,) = audit_rows(db, "retrieval")
    assert row["decision"] == "RETRIEVED"
    assert row["details"]["truncated"] is True
    assert len(row["details"]["evidence"]) == 8


def test_ac11_the_budget_holds_when_each_group_numbers_its_own_refs() -> None:
    """Every retriever numbers from E1, and a renumbered ref can be longer than the original."""
    e = ev_mod()
    first = [filler(f"E{i}") for i in range(1, 10)]
    second = [filler("E1", "vector"), filler("E2", "vector")]
    for budget in range(1100, 1400):
        kept, _ = e.fit_context([("case_graph", first), ("knowledge", second)], budget)
        assert len(e.render_evidence(kept)) <= budget, budget
