"""AC4 of specs/ui-mock-pages.md: POST /api/v1/assistant/chat (plain JSON, fakes for 8c / 8b)."""

from __future__ import annotations

from typing import Any

import pytest

from aml.assistant.evidence import RetrievalUnavailableError
from aml.assistant.llm import OllamaUnavailableError
from tests.assistant.an_helpers import (
    LLM,
    R0,
    R4,
    S_AMOUNT,
    S_OK1,
    S_OK2,
    FakeRetriever,
    J,
    RaisingLLM,
)

from .helpers import audit_rows, count
from .insight_helpers import C1, NOPE, V1, Q, fakes
from .live_helpers import assert_error, audit_total

URL = f"{V1}/assistant/chat"
BODY = {"case_id": C1, "question": Q}
CITATIONS = [
    {
        "n": 1,
        "kind": "transaction",
        "id": "T01",
        "label": "transaction T01",
        "node_ids": ["A01"],
        "txn_ids": ["T01"],
        "excerpt": None,
    },
    {
        "n": 2,
        "kind": "chunk",
        "id": "KB-TYP-001#003",
        "label": "chunk KB-TYP-001#003",
        "node_ids": [],
        "txn_ids": [],
        "excerpt": (
            "Structuring: repeated cash deposits just under the reporting threshold of "
            "400,000,000 VND."
        ),
    },
]
UNTOUCHED = ("case_dispositions", "cases", "case_runs")


def _llm() -> Any:
    return LLM(J(S_OK1, S_AMOUNT, S_OK2))


def _decisions(db: Any, decision: str) -> list[dict[str, Any]]:
    return audit_rows(db, f"module = 'assistant' AND decision = '{decision}'")


def test_ac4_answer_envelope_and_data(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=_llm(), retriever=R4())
    r = client(user="analyst01").post(URL, json=BODY)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "assistant"
    assert body["meta"] == {"pii": "masked"}
    data = body["data"]
    assert data["answer_id"] == "ans-9504e4efe5dd"
    assert data["case_id"] == C1
    assert data["question"] == "Tài khoản A01 nhận tiền gì?"
    assert data["language"] == "vi"
    assert data["status"] == "answered"
    assert [s["supported"] for s in data["sentences"]] == [True, False, True]
    assert [s["citations"] for s in data["sentences"]] == [[1], [1], [2]]
    assert data["citations"] == CITATIONS
    assert data["retrievers"] == ["case_graph", "knowledge", "text2cypher"]
    assert data["validation"] == {"sentences": 3, "supported": 2, "unsupported": 1}
    assert data["model"] == "fake-chat"
    assert data["prompt_version"] == "answer/v1"


def test_ac4_retriever_called_once_with_case_and_actor(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    retriever = R4()
    fakes(monkeypatch, llm=_llm(), retriever=retriever)
    client(user="analyst01").post(URL, json=BODY)
    assert len(retriever.calls) == 1
    _, kwargs = retriever.calls[0]
    assert kwargs["case_id"] == C1
    assert kwargs["actor"] == "analyst01"


def test_ac4_exactly_one_audit_row_with_request_actor(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=_llm(), retriever=R4())
    before = audit_total(api_mini)
    client(user="analyst01").post(URL, json=BODY)
    assert audit_total(api_mini) == before + 1
    (row,) = _decisions(api_mini, "ANSWERED")
    assert row["module"] == "assistant"
    assert row["entity_type"] == "case"
    assert row["entity_id"] == C1
    assert row["actor"] == "analyst01"
    assert row["details"]["answer_id"] == "ans-9504e4efe5dd"


def test_ac4_supervisor_is_the_audit_actor(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=_llm(), retriever=R4())
    r = client(user="supervisor01").post(URL, json=BODY)
    assert r.status_code == 200, r.text
    (row,) = _decisions(api_mini, "ANSWERED")
    assert row["actor"] == "supervisor01"


def test_ac4_insufficient_evidence(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(
        monkeypatch, llm=LLM('{"status": "insufficient_evidence", "sentences": []}'), retriever=R0()
    )
    r = client(user="analyst01").post(
        URL, json={"case_id": C1, "question": "Ai là người hưởng lợi?"}
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["answer_id"] == "ans-10ef7b070a8a"
    assert data["status"] == "insufficient_evidence"
    assert data["sentences"] == []
    assert data["citations"] == []
    assert len(_decisions(api_mini, "INSUFFICIENT_EVIDENCE")) == 1


def _bad_bodies() -> list[dict[str, Any]]:
    return [
        {"case_id": C1, "question": "   "},
        {"case_id": C1},
        {"case_id": C1, "question": "x" * 1001},
        {"case_id": C1, "question": Q, "language": "fr"},
        {"question": Q},
        {"case_id": C1, "question": Q, "actor": "boss"},
    ]


def test_ac4_bad_bodies_are_422_and_touch_nothing(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    retriever = R4()
    fakes(monkeypatch, llm=_llm(), retriever=retriever)
    c = client(user="analyst01")
    before = audit_total(api_mini)
    for body in _bad_bodies():
        assert_error(c.post(URL, json=body), 422, "invalid_request")
    assert retriever.calls == []
    assert audit_total(api_mini) == before


def test_ac4_unknown_case_is_404_and_touches_nothing(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    retriever = R4()
    fakes(monkeypatch, llm=_llm(), retriever=retriever)
    before = audit_total(api_mini)
    r = client(user="analyst01").post(URL, json={"case_id": NOPE, "question": Q})
    assert_error(r, 404, "not_found", "unknown case_id")
    assert retriever.calls == []
    assert audit_total(api_mini) == before


def test_ac4_broken_model_output_is_502_model_error(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM("nope", "nope again"), retriever=R4())
    before = audit_total(api_mini)
    r = client(user="analyst01").post(URL, json=BODY)
    assert r.status_code == 502, r.text
    assert r.json() == {
        "error": {
            "code": "model_error",
            "message": "model output is not valid JSON after 2 attempt(s)",
        }
    }
    assert audit_total(api_mini) == before + 1
    assert len(_decisions(api_mini, "FAILED")) == 1


@pytest.mark.parametrize(
    "kind",
    ["ollama", "neo4j"],
)
def test_ac4_service_down_is_503_and_not_audited(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    if kind == "ollama":
        fakes(
            monkeypatch,
            llm=RaisingLLM(OllamaUnavailableError("cannot reach Ollama")),
            retriever=R4(),
        )
    else:
        down = FakeRetriever(error=RetrievalUnavailableError("neo4j not available: x"))
        fakes(monkeypatch, llm=_llm(), retriever=down)
    before = audit_total(api_mini)
    r = client(user="analyst01").post(URL, json=BODY)
    assert r.status_code == 503, r.text
    assert r.json() == {"error": {"code": "unavailable", "message": "service unavailable"}}
    assert audit_total(api_mini) == before


def test_ac4_chat_never_touches_case_decisions(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = {t: count(api_mini, t) for t in UNTOUCHED}
    c = client(user="analyst01")
    fakes(monkeypatch, llm=_llm(), retriever=R4())
    assert c.post(URL, json=BODY).status_code == 200
    fakes(monkeypatch, llm=LLM("nope", "nope again"), retriever=R4())
    assert c.post(URL, json=BODY).status_code == 502
    fakes(monkeypatch, llm=RaisingLLM(OllamaUnavailableError("x")), retriever=R4())
    assert c.post(URL, json=BODY).status_code == 503
    assert {t: count(api_mini, t) for t in UNTOUCHED} == before
