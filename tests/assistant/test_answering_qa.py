"""AC3 and AC4 for specs/assistant-answering.md: `answer_question` on MINI-N, fake retrievers."""

from __future__ import annotations

import re
from typing import Any

import pytest

from aml.assistant.evidence import RetrievalError, RetrievalUnavailableError, RetrieverNote
from aml.assistant.llm import LLMError
from aml.cases.runner import CaseError
from aml.common.config import Settings
from aml.common.db import DuckDb

from .an_helpers import (
    CASE,
    CHUNK_TEXT,
    EV,
    J_NONE,
    LLM,
    NOPE,
    Q1,
    QUESTION,
    R0,
    R4,
    S_AMOUNT,
    S_FAKE,
    S_NOCITE,
    S_NOID,
    S_OK1,
    S_OK2,
    X1,
    X3,
    FakeRetriever,
    J,
    RaisingLLM,
    answering,
    audit8c,
    chats,
    mini_n,
    mod,
)

LINES = [
    "Tài khoản A01 nhận 390,000,000 VND tiền mặt vào ngày 2026-03-02. [1]",
    "[CHƯA KIỂM CHỨNG] Tài khoản A01 nhận 395,000,000 VND tiền mặt vào ngày 2026-03-02. [1]",
    "Đây là dấu hiệu structuring: nộp tiền mặt nhiều lần ngay dưới ngưỡng báo cáo 400 triệu "
    "đồng. [2]",
]
EXT = "Ai là chủ tài khoản EXT-09?"


@pytest.fixture
def mn(duck: DuckDb) -> tuple[DuckDb, Settings]:
    return duck, mini_n(duck)


def _ask(mn: tuple[DuckDb, Settings], question: str = QUESTION, **kw: Any) -> Any:
    db, settings = mn
    kw.setdefault("case_id", CASE)
    return answering().answer_question(db, settings, question, **kw)


# ---------------------------------------------------------------- AC3
def test_ac3_answer_with_cited_and_flagged_sentences(mn: tuple[DuckDb, Settings]) -> None:
    db, settings = mn
    a_mod, c_mod = answering(), mod("aml.assistant.citations")
    fake, r4 = LLM(J(S_OK1, S_AMOUNT, S_OK2)), R4()
    a = _ask(mn, "  " + QUESTION + "  ", retriever=r4, llm=fake)

    ((args, kwargs),) = r4.calls
    assert args == (db, settings, QUESTION)
    assert kwargs["case_id"] == CASE and kwargs["mode"] == "graphrag"
    assert kwargs["llm"] is fake
    (call,) = chats(fake)
    assert call["json_schema"] == mod("aml.assistant.prompts").answer_schema(
        ("E1", "E2", "E3", "E4")
    )

    assert (a.status, a.refused, a.language, a.question) == ("answered", False, "vi", QUESTION)
    assert (a.model, a.prompt_version) == (fake.chat_model, "answer/v1")
    assert a.retrievers == ("case_graph", "knowledge", "text2cypher")
    assert a.retrieval.queries == (Q1,)
    assert a.llm_calls == 1
    assert [s.supported for s in a.sentences] == [True, False, True]
    assert a.sentences[1].issues == ("amount_not_in_evidence",)
    assert [s.citations for s in a.sentences] == [(1,), (1,), (2,)]
    assert a.citations == (
        c_mod.Citation(1, "transaction", "T01", "transaction T01", ("A01",), ("T01",), None),
        c_mod.Citation(2, "chunk", "KB-TYP-001#003", "chunk KB-TYP-001#003", (), (), CHUNK_TEXT),
    )
    cited = {c.id for c in a.citations} | {t for c in a.citations for t in c.txn_ids}
    assert cited == {"T01", "KB-TYP-001#003"}
    assert a.text.split("\n") == LINES
    assert c_mod.split_citations(LINES[0]) == (
        "Tài khoản A01 nhận 390,000,000 VND tiền mặt vào ngày 2026-03-02.",
        (1,),
    )
    assert a_mod.render_answer(a) == (
        a.text + "\n\nNguồn:\n[1] transaction T01\n[2] chunk KB-TYP-001#003"
    )
    assert a.validation == {"sentences": 3, "supported": 2, "unsupported": 1}
    assert len(a.flagged) == 1
    assert a.context == EV
    assert a.context[2] is X3
    assert a.context[2].untrusted[0].field == "chunk_text"
    assert re.fullmatch(r"ans-[0-9a-f]{12}", a.answer_id)
    again = _ask(mn, QUESTION, retriever=R4(), llm=LLM(J(S_OK1, S_AMOUNT, S_OK2)))
    assert again.answer_id == a.answer_id


def test_ac3_as_dict_and_events(mn: tuple[DuckDb, Settings]) -> None:
    db, settings = mn
    a = _ask(mn, retriever=R4(), llm=LLM(J(S_OK1, S_AMOUNT, S_OK2)))
    d = a.as_dict()
    assert set(d) == {
        "answer_id", "case_id", "question", "language", "status", "sentences", "citations",
        "retrievers", "validation", "model", "prompt_version",
    }  # fmt: skip
    assert all(set(s) == {"text", "supported", "citations"} for s in d["sentences"])
    assert all(
        set(c) == {"n", "kind", "id", "label", "node_ids", "txn_ids", "excerpt"}
        for c in d["citations"]
    )
    events = list(
        answering().answer_events(
            db, settings, QUESTION, case_id=CASE, retriever=R4(), llm=LLM(J(S_OK1))
        )
    )
    assert [name for name, _ in events] == ["start", "final"]
    assert set(events[0][1]) == {"answer_id", "case_id", "language"}
    assert events[1][1]["answer"]["status"] == "answered"


def test_ac3_english(mn: tuple[DuckDb, Settings]) -> None:
    fake = LLM(J(S_OK1, S_AMOUNT, S_OK2))
    a = _ask(mn, retriever=R4(), llm=fake, language="en")
    assert a.language == "en"
    assert a.text.split("\n")[1].startswith("[UNVERIFIED] ")
    assert "Sources:" in answering().render_answer(a).split("\n")
    assert "Answer in English" in chats(fake)[0]["messages"][0]["content"]
    vi = LLM(J(S_OK1))
    _ask(mn, retriever=R4(), llm=vi)
    assert "Answer in Vietnamese" in chats(vi)[0]["messages"][0]["content"]


def test_ac3_bad_input(mn: tuple[DuckDb, Settings]) -> None:
    error = answering().AssistantError
    with pytest.raises(error) as err:
        _ask(mn, retriever=R4(), llm=LLM(J(S_OK1)), language="fr")
    assert "language 'fr' is not available; choose vi or en" in str(err.value)
    for question in ("   ", "x" * 1001):
        r4 = R4()
        with pytest.raises(error) as err:
            _ask(mn, question, retriever=r4, llm=LLM(J(S_OK1)))
        assert "question must be 1 to 1000 characters" in str(err.value)
        assert r4.calls == []


def test_ac3_without_a_case(mn: tuple[DuckDb, Settings]) -> None:
    a = _ask(mn, retriever=R4(), llm=LLM(J(S_OK1)), case_id=None)
    assert a.case_id is None


# ---------------------------------------------------------------- AC4
def test_ac4_no_context_refuses_without_calling_the_model(mn: tuple[DuckDb, Settings]) -> None:
    fake = LLM()
    a = _ask(mn, EXT, retriever=R0(), llm=fake)
    assert (a.status, a.refused, a.refusal_reason) == ("insufficient_evidence", True, "no_context")
    assert a.text == "Không đủ bằng chứng."
    assert (a.sentences, a.citations, a.llm_calls) == ((), (), 0)
    assert chats(fake) == []
    en = _ask(mn, EXT, retriever=R0(), llm=LLM(), language="en")
    assert en.text == "Insufficient evidence."


def test_ac4_model_refusal(mn: tuple[DuckDb, Settings]) -> None:
    a = _ask(mn, EXT, retriever=R4(), llm=LLM(J_NONE))
    assert (a.refusal_reason, a.text) == ("model", "Không đủ bằng chứng.")


def test_ac4_nothing_supported(mn: tuple[DuckDb, Settings]) -> None:
    a = _ask(mn, EXT, retriever=R4(), llm=LLM(J(S_NOCITE, S_FAKE, S_NOID)))
    assert (a.status, a.refusal_reason, a.sentences) == (
        "insufficient_evidence",
        "nothing_supported",
        (),
    )
    assert [s.issues for s in a.discarded] == [
        ("no_citation",),
        ("unknown_citation",),
        ("no_citation",),
    ]
    assert len(a.flagged) == 3
    assert a.validation == {"sentences": 0, "supported": 0, "unsupported": 0}


def test_ac4_retry_once_then_answer(mn: tuple[DuckDb, Settings]) -> None:
    fake = LLM("xin lỗi", J(S_OK1))
    a = _ask(mn, EXT, retriever=R4(), llm=fake)
    assert (a.status, a.llm_calls) == ("answered", 2)
    second = chats(fake)[1]["messages"]
    assert len(second) == 3
    assert second[-1] == {"role": "user", "content": mod("aml.assistant.prompts").RETRY_MESSAGE}


def test_ac4_invalid_json_twice_fails_with_an_audit_row(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = len(audit8c(db))
    fake = LLM("xin lỗi", "vẫn hỏng")
    with pytest.raises(answering().AssistantError) as err:
        _ask(mn, EXT, retriever=R4(), llm=fake)
    assert "model output is not valid JSON after 2 attempt(s)" in str(err.value)
    assert len(chats(fake)) == 2
    rows = audit8c(db)[before:]
    assert [r["decision"] for r in rows] == ["FAILED"]


def test_ac4_no_retry_when_configured(duck: DuckDb) -> None:
    settings = mini_n(duck, AML__ASSISTANT__ANSWERING__MAX_RETRIES="0")
    fake = LLM("xin lỗi")
    with pytest.raises(answering().AssistantError) as err:
        answering().answer_question(duck, settings, EXT, case_id=CASE, retriever=R4(), llm=fake)
    assert "after 1 attempt(s)" in str(err.value)
    assert len(chats(fake)) == 1


def test_ac4_retrieval_errors_pass_through(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = len(audit8c(db))
    fake = LLM()
    down = RetrievalUnavailableError("neo4j not available: down")
    with pytest.raises(RetrievalUnavailableError) as err:
        _ask(mn, EXT, retriever=FakeRetriever(error=down), llm=fake)
    assert err.value is down
    assert chats(fake) == []
    assert len(audit8c(db)) == before
    bad = RetrievalError("unknown mode 'xyz'; choose one of: graphrag, vector")
    with pytest.raises(RetrievalError) as err:
        _ask(mn, EXT, retriever=FakeRetriever(error=bad), llm=fake)
    assert err.value is bad


@pytest.mark.parametrize("mode", ["graphrag", "vector"])
def test_ac4_unknown_case_is_a_refusal(mn: tuple[DuckDb, Settings], mode: str) -> None:
    db, _ = mn
    before = len(audit8c(db))
    r4, fake = R4(), LLM()
    a = _ask(mn, EXT, case_id=NOPE, mode=mode, retriever=r4, llm=fake)
    assert (a.status, a.refusal_reason) == ("insufficient_evidence", "unknown_case")
    assert (a.text, a.llm_calls) == ("Không đủ bằng chứng.", 0)
    assert r4.calls == []
    (row,) = audit8c(db)[before:]
    assert (row["decision"], row["entity_type"], row["entity_id"]) == (
        "INSUFFICIENT_EVIDENCE",
        "case",
        NOPE,
    )
    assert row["details"]["refusal_reason"] == "unknown_case"


def test_ac4_case_error_from_the_retriever_is_a_refusal(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = len(audit8c(db))
    fake = LLM()
    gone = FakeRetriever(error=CaseError(f"unknown case_id {CASE}"))
    a = _ask(mn, EXT, retriever=gone, llm=fake)
    assert a.refusal_reason == "unknown_case"
    assert len(audit8c(db)) == before + 1
    assert chats(fake) == []


def test_ac4_llm_error_is_not_retried(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = len(audit8c(db))
    broken = RaisingLLM(LLMError("prompt exceeds the context window"))
    with pytest.raises(answering().AssistantError) as err:
        _ask(mn, EXT, retriever=R4(), llm=broken)
    assert "llm call failed: prompt exceeds the context window" in str(err.value)
    assert len(chats(broken)) == 1
    (row,) = audit8c(db)[before:]
    assert row["decision"] == "FAILED"
    assert "prompt exceeds the context window" in row["reason"]


def test_ac4_retriever_notes_reach_the_audit_row(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = len(audit8c(db))
    noted = FakeRetriever((X1,), notes=(RetrieverNote("text2cypher", "failed", "no query"),))
    a = _ask(mn, EXT, retriever=noted, llm=LLM(J(S_OK1)))
    assert a.status == "answered"
    (row,) = audit8c(db)[before:]
    assert row["details"]["notes"] == [{"retriever": "text2cypher", "status": "failed"}]
