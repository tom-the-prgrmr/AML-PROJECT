"""AC9 (a)-(i) for specs/assistant-retrievers.md: `retrieve` with the four retrievers faked."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aml.common.db import DuckDb

from .kn_helpers import mod
from .rt_helpers import (
    CASE_ID,
    SECRETS,
    Fakes,
    audit_count,
    audit_rows,
    duck_settings,
    ev_mod,
    knowledge_mod,
    llm_mod,
    offline_settings,
    retrieve_mod,
    route_mod,
    t2c_mod,
)

WHY = "Vì sao case này khớp structuring?"
LIST = "Liệt kê 5 giao dịch lớn nhất của case"
TXN_QUESTION = "Giao dịch T0000003073 có ghi chú gì?"


@pytest.fixture
def db(duck: DuckDb) -> DuckDb:
    mod("aml.dba.schema").apply_schema(duck)
    return duck


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Fakes:
    return Fakes(monkeypatch)


def _retrieve(db: DuckDb, question: str, **kw: Any) -> Any:
    kw.setdefault("llm", llm_mod().FakeLLM())
    settings = kw.pop("settings", None) or duck_settings()
    return retrieve_mod().retrieve(db, settings, question, **kw)


# ---------------------------------------------------------------- (a) graphrag, case + knowledge
def test_ac9a_case_question_runs_case_graph_then_knowledge(db: DuckDb, fakes: Fakes) -> None:
    r = _retrieve(db, WHY, case_id=CASE_ID, actor="analyst01")
    assert r.mode == "graphrag"
    assert r.routes == ("case_graph", "knowledge")
    assert len(r.reasons) == 2
    assert [e.ref for e in r.evidence] == ["E1", "E2", "E3", "E4"]
    assert [e.retriever for e in r.evidence] == [
        "case_graph",
        "case_graph",
        "vector",
        "graph_expansion",
    ]
    assert r.notes == ()
    assert r.truncated is False
    assert r.context_chars == len(ev_mod().render_evidence(r.evidence))
    assert r.question == WHY
    assert r.case_id == CASE_ID
    assert r.queries == ()


def test_ac9a_arguments_passed_to_the_retrievers(db: DuckDb, fakes: Fakes) -> None:
    _retrieve(db, WHY, case_id=CASE_ID)
    assert fakes.called() == {"case_graph", "knowledge"}
    (case_call,) = fakes.calls["case_graph"]
    assert case_call["case_id"] == CASE_ID
    assert case_call.get("customer") is None
    (knowledge_call,) = fakes.calls["knowledge"]
    assert knowledge_call["expand"] is True
    assert tuple(knowledge_call["seed_typologies"]) == ("structuring",)
    assert knowledge_call["question"] == WHY


def test_ac9a_one_audit_row_without_untrusted_content(db: DuckDb, fakes: Fakes) -> None:
    r = _retrieve(db, WHY, case_id=CASE_ID, actor="analyst01")
    assert any(e.has_untrusted for e in r.evidence)
    (row,) = audit_rows(db)
    assert row["entity_type"] == "retrieval"
    assert row["entity_id"] == CASE_ID
    assert row["decision"] == "RETRIEVED"
    assert row["version"] == "retrieval/v1"
    assert row["actor"] == "analyst01"
    assert row["reason"] == "graphrag: case_graph+knowledge returned 4 evidence item(s)"
    d = row["details"]
    assert d["routes"] == ["case_graph", "knowledge"]
    assert d["router_version"] == "router/rules-v1" == route_mod().ROUTER_VERSION
    assert len(d["evidence"]) == 4
    for item in d["evidence"]:
        assert set(item) == {"ref", "retriever", "source", "citations"}
    assert d["evidence"][0]["citations"] == [f"case:{CASE_ID}", "customer:G-C01"]
    for key in ("question", "mode", "case_id", "reasons", "context_chars", "truncated", "notes"):
        assert key in d
    dumped = json.dumps(d, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in dumped


def test_ac9a_the_default_actor_is_the_system_actor(db: DuckDb, fakes: Fakes) -> None:
    _retrieve(db, WHY, case_id=CASE_ID)
    (row,) = audit_rows(db)
    assert row["actor"] == duck_settings().audit.system_actor


# ---------------------------------------------------------------- (b) vector mode
@pytest.mark.parametrize("question", [WHY, TXN_QUESTION])
def test_ac9b_vector_mode_only_searches_chunks(db: DuckDb, fakes: Fakes, question: str) -> None:
    r = _retrieve(db, question, case_id=CASE_ID, mode="vector")
    assert r.mode == "vector"
    assert r.routes == ("vector",)
    assert r.reasons == ("vector: plain vector mode",)
    assert fakes.called() == {"knowledge"}
    (call,) = fakes.calls["knowledge"]
    assert call["expand"] is False
    assert tuple(call["seed_typologies"]) == ()
    assert r.case_id == CASE_ID
    assert [e.ref for e in r.evidence] == ["E1", "E2"]


def test_ac9b_both_modes_return_the_same_type(db: DuckDb, fakes: Fakes) -> None:
    a = _retrieve(db, WHY, case_id=CASE_ID, mode="vector")
    b = _retrieve(db, WHY, case_id=CASE_ID, mode="graphrag")
    assert type(a) is type(b) is retrieve_mod().Retrieval


# ---------------------------------------------------------------- (c) (d) text2cypher
def test_ac9c_listing_question_runs_case_graph_then_text2cypher(db: DuckDb, fakes: Fakes) -> None:
    r = _retrieve(db, LIST, case_id=CASE_ID, actor="analyst01")
    assert r.routes == ("case_graph", "text2cypher")
    assert [e.ref for e in r.evidence] == ["E1", "E2", "E3"]
    assert r.evidence[2].retriever == "text2cypher"
    assert len(r.queries) == 1
    assert fakes.called() == {"case_graph", "text2cypher"}
    (call,) = fakes.calls["text2cypher"]
    assert call["case_id"] == CASE_ID
    assert call["golden_customer_id"] == "G-C01"
    assert call["actor"] == "analyst01"


def test_ac9d_a_disabled_text2cypher_is_a_note(db: DuckDb, fakes: Fakes) -> None:
    m = retrieve_mod()
    fakes.errors["text2cypher"] = t2c_mod().Text2CypherError("text2cypher is disabled")
    r = _retrieve(db, LIST, case_id=CASE_ID)
    assert len(r.evidence) == 2
    assert r.notes == (m.RetrieverNote("text2cypher", "failed", "text2cypher is disabled"),)
    assert r.queries == ()
    (row,) = audit_rows(db)
    assert row["decision"] == "RETRIEVED"
    assert len(row["details"]["notes"]) == 1


def test_ac9d_no_executed_query_is_a_failed_note(
    db: DuckDb, fakes: Fakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every attempt was rejected: the turn goes on, and the note says why."""
    t2c = t2c_mod()
    rejected = t2c.GeneratedQuery(2, "x", None, "REJECTED", "label", "label X is unknown", 0, 0.0)

    def all_rejected(*args: Any, **kw: Any) -> Any:
        return t2c.Text2CypherResult((), (rejected,))

    monkeypatch.setattr(retrieve_mod(), "text2cypher", all_rejected)
    r = _retrieve(db, LIST, case_id=CASE_ID)
    assert len(r.evidence) == 2
    (note,) = r.notes
    assert (note.retriever, note.status) == ("text2cypher", "failed")
    assert "label X is unknown" in note.message
    assert r.queries == (rejected,)


# ---------------------------------------------------------------- (e) knowledge not available
def test_ac9e_a_model_failure_in_knowledge_is_a_note(db: DuckDb, fakes: Fakes) -> None:
    fakes.errors["knowledge"] = llm_mod().LLMError("ollama not available")
    r = _retrieve(db, WHY, case_id=CASE_ID)
    assert len(r.evidence) == 2
    assert (r.notes[0].retriever, r.notes[0].status) == ("knowledge", "unavailable")
    assert r.notes[0].message == "ollama not available"


def test_ac9e_a_missing_index_is_a_note(db: DuckDb, fakes: Fakes) -> None:
    message = "knowledge layer not built: run aml rag build"
    fakes.errors["knowledge"] = knowledge_mod().KnowledgeNotBuiltError(message)
    r = _retrieve(db, WHY, case_id=CASE_ID)
    assert len(r.evidence) == 2
    assert (r.notes[0].retriever, r.notes[0].status) == ("knowledge", "unavailable")
    assert r.notes[0].message == message


# ---------------------------------------------------------------- (f) (g) (h) errors and audit
def test_ac9f_neo4j_down_is_raised_and_not_audited(db: DuckDb, fakes: Fakes) -> None:
    error = ev_mod().RetrievalUnavailableError("neo4j not available")
    fakes.errors["case_graph"] = error
    with pytest.raises(ev_mod().RetrievalUnavailableError) as caught:
        _retrieve(db, WHY, case_id=CASE_ID)
    assert caught.value is error
    assert audit_count(db) == 0


def test_ac9g_bad_input_touches_nothing(db: DuckDb, fakes: Fakes) -> None:
    m = retrieve_mod()
    with pytest.raises(ev_mod().RetrievalError, match="question is empty"):
        m.retrieve(db, duck_settings(), "  ")
    with pytest.raises(ev_mod().RetrievalError) as caught:
        m.retrieve(db, duck_settings(), "x", mode="hybrid")
    assert "unknown mode 'hybrid'; choose one of: graphrag, vector" in str(caught.value)
    assert fakes.called() == set()
    assert audit_count(db) == 0


def test_ac9h_audit_can_be_switched_off(db: DuckDb, fakes: Fakes) -> None:
    r = _retrieve(db, WHY, case_id=CASE_ID, record_audit=False)
    assert len(r.evidence) == 4
    assert audit_count(db) == 0


# ---------------------------------------------------------------- (i) nothing faked, Neo4j off
def test_ac9i_knowledge_route_without_neo4j_is_raised(db: DuckDb) -> None:
    with pytest.raises(ev_mod().RetrievalUnavailableError, match="neo4j not available"):
        _retrieve(db, "Structuring là gì?", settings=offline_settings())
    assert audit_count(db) == 0


def test_ac9i_an_unknown_case_is_a_case_error(db: DuckDb) -> None:
    with pytest.raises(mod("aml.cases.runner").CaseError, match="unknown case_id"):
        _retrieve(db, "x", case_id="C-NOPE-20260101", settings=offline_settings())
    assert audit_count(db) == 0
