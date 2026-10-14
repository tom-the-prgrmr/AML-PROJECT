"""AC8 for specs/assistant-answering.md: one audit row per answer or draft, no untrusted text."""

from __future__ import annotations

import json

from aml.common.db import DuckDb

from .an_helpers import (
    ALERT_KEY,
    CASE,
    CY,
    K0,
    LLM,
    N_OK,
    QUESTION,
    R0,
    R4,
    S_AMOUNT,
    S_OK1,
    S_OK2,
    J,
    answering,
    audit8c,
    audit_rows,
    counts,
    mini_n,
    narrative,
)

KEYS = {
    "answer_id", "question", "language", "mode", "retrievers", "notes", "cypher",
    "retrieved_ids", "cited_ids", "model", "prompt_version", "validation", "flagged",
    "refusal_reason", "llm_calls",
}  # fmt: skip


def test_ac8_audit_rows(duck: DuckDb) -> None:
    settings = mini_n(duck)
    ask = answering().answer_question
    before_counts, before_8c, before_all = counts(duck), len(audit8c(duck)), audit_rows(duck)
    r4 = R4()
    a1 = ask(
        duck,
        settings,
        QUESTION,
        case_id=CASE,
        retriever=r4,
        llm=LLM(J(S_OK1, S_AMOUNT)),
        actor="analyst01",
    )
    a2 = ask(duck, settings, QUESTION, case_id=CASE, retriever=R0(), llm=LLM())
    a3 = ask(duck, settings, "Structuring là gì?", retriever=R4(), llm=LLM(J(S_OK2)))
    narrative().draft_narrative(
        duck, settings, CASE, llm=LLM(N_OK), knowledge=K0(), actor="analyst01"
    )

    rows = audit8c(duck)[before_8c:]
    assert audit_rows(duck) == before_all + 4
    assert [r["decision"] for r in rows] == [
        "ANSWERED",
        "INSUFFICIENT_EVIDENCE",
        "ANSWERED",
        "NARRATIVE_DRAFTED",
    ]
    assert r4.calls[0][1]["actor"] == "analyst01"

    first = rows[0]
    assert (first["entity_type"], first["entity_id"]) == ("case", CASE)
    assert (first["version"], first["actor"]) == ("answer/v1", "analyst01")
    assert first["reason"].startswith(
        "answered: 2 sentence(s), 1 supported, 1 flagged; 4 context item(s), 1 cited"
    )
    d = first["details"]
    assert set(d) == KEYS
    assert d["question"] == QUESTION
    assert d["mode"] == "graphrag"
    assert d["retrievers"] == ["case_graph", "knowledge", "text2cypher"]
    assert d["notes"] == []
    assert d["cypher"] == [{"attempt": 1, "status": "EXECUTED", "rule": None, "executed": CY}]
    assert d["retrieved_ids"] == [
        "txn:T01",
        "account:A01",
        "customer:G-C01",
        "chunk:KB-TYP-001#003",
    ]
    assert d["cited_ids"] == ["T01"]
    assert d["prompt_version"] == "answer/v1"
    assert d["validation"] == {
        "sentences": 2,
        "supported": 1,
        "unsupported": 1,
        "issues": {"amount_not_in_evidence": 1},
    }
    assert d["flagged"] == [
        {
            "text": "Tài khoản A01 nhận 395,000,000 VND tiền mặt vào ngày 2026-03-02.",
            "issues": ["amount_not_in_evidence"],
        }
    ]
    assert d["refusal_reason"] is None
    assert "Structuring: repeated cash deposits" not in json.dumps(d, ensure_ascii=False)
    assert "Structuring: repeated cash deposits" not in str(first["details_raw"])

    second = rows[1]["details"]
    assert rows[1]["actor"] == settings.audit.system_actor
    assert second["refusal_reason"] == "no_context"
    assert (second["retrieved_ids"], second["cypher"], second["llm_calls"]) == ([], [], 0)

    assert (rows[2]["entity_type"], rows[2]["entity_id"]) == ("question", a3.answer_id)

    last = rows[3]
    assert (last["entity_type"], last["entity_id"]) == ("case", CASE)
    assert (last["version"], last["actor"]) == ("narrative/v1", "analyst01")
    nd = last["details"]
    assert nd["watermark"] == "DRAFT — requires investigator review"
    assert nd["knowledge"] == "ok"
    assert (nd["validation"]["sentences"], nd["validation"]["supported"]) == (5, 4)
    assert nd["cited_ids"] == ["G-C01", ALERT_KEY, "A01"]
    assert "question" not in nd

    assert [r["details"]["answer_id"] for r in rows[:3]] == [
        a1.answer_id,
        a2.answer_id,
        a3.answer_id,
    ]
    assert counts(duck) == before_counts
