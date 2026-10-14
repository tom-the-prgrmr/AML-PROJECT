"""AC5 of specs/ui-mock-pages.md: POST .../narrative and GET .../typologies (fakes for 8c / 8b)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aml.assistant.evidence import RetrievalUnavailableError
from aml.assistant.llm import OllamaUnavailableError
from tests.assistant.an_helpers import K3, LLM, N_OK, FakeKnowledge, RaisingLLM, chats

from .helpers import api_settings, audit_rows, mod
from .insight_helpers import C1, C5, NOPE, V1, data_of, fakes
from .live_helpers import assert_error, audit_total

NARR = f"{V1}/cases/{C1}/narrative"
TYPO = f"{V1}/cases/{C1}/typologies"
NARRATIVE_KEYS = {
    "case_id",
    "generator",
    "version",
    "language",
    "watermark",
    "markdown",
    "citations",
}
T01 = {
    "txn_id": "T01",
    "txn_ts": "2026-03-02T09:00:00",
    "from_account_id": None,
    "to_account_id": "A01",
    "amount_vnd": 390000000,
    "channel": "CASH",
}


def _draft(client: Any, monkeypatch: pytest.MonkeyPatch, **kw: Any) -> Any:
    fakes(monkeypatch, **{"llm": LLM(N_OK), "knowledge": K3(), **kw})
    return client(user="analyst01").post(NARR, json={})


# ---------------------------------------------------------------- narrative
def test_ac5_narrative_envelope_and_shape(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = _draft(client, monkeypatch)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "live"
    assert body["feature"] == "assistant"
    assert body["meta"] == {"pii": "masked", "knowledge": "ok"}
    data = body["data"]
    assert set(data) == {"narrative", "citations"}
    narr = data["narrative"]
    assert set(narr) == NARRATIVE_KEYS
    assert narr["case_id"] == C1
    assert narr["generator"] == "llm"
    assert narr["version"] == "narrative/v1"
    assert narr["language"] == "vi"
    assert narr["watermark"] == mod("aml.assistant.narrative").DRAFT_WATERMARK
    assert narr["watermark"] == "DRAFT — requires investigator review"


def test_ac5_narrative_citations(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _draft(client, monkeypatch).json()["data"]
    narr, cites = data["narrative"], data["citations"]
    assert narr["citations"] == ["G-C01", "STRUCTURING|A01|2026-03-02T09:00:00", "A01"]
    assert narr["citations"] == [c["id"] for c in cites]
    assert [c["kind"] for c in cites] == ["node", "alert", "node"]
    assert cites[1]["node_ids"] == []
    assert cites[2]["node_ids"] == ["A01", "G-C01"]


def test_ac5_narrative_markdown(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    md = _draft(client, monkeypatch).json()["data"]["narrative"]["markdown"]
    assert md.startswith("# Case C-C01-20260302\n\n> DRAFT — requires investigator review\n")
    headings = [line for line in md.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Subject",
        "## Activity timeline",
        "## Matched typologies",
        "## Red flags",
        "## Suggested next step",
    ]
    assert "- [CHƯA KIỂM CHỨNG] Ngày 2026-03-09 tài khoản A01 nhận 999,000,000 VND. [2]" in md
    assert "Draft narrative/v1; model fake-chat; case run 1; 4 of 5 sentence(s) verified." in md


def test_ac5_narrative_writes_one_audit_row(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = audit_total(api_mini)
    _draft(client, monkeypatch)
    assert audit_total(api_mini) == before + 1
    (row,) = audit_rows(api_mini, "decision = 'NARRATIVE_DRAFTED'")
    assert row["actor"] == "analyst01"


@pytest.mark.parametrize(
    ("case_id", "body", "status"),
    [
        (C1, {"language": "fr"}, 422),
        (C1, {"disposition": "SUSPICIOUS"}, 422),
        (NOPE, {}, 404),
    ],
)
def test_ac5_narrative_bad_input_writes_nothing(
    api_mini: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    body: dict[str, Any],
    status: int,
) -> None:
    fakes(monkeypatch, llm=LLM(N_OK), knowledge=K3())
    before = audit_total(api_mini)
    r = client(user="analyst01").post(f"{V1}/cases/{case_id}/narrative", json=body)
    assert_error(r, status, "not_found" if status == 404 else "invalid_request")
    assert audit_total(api_mini) == before


def test_ac5_narrative_broken_model_is_502_without_audit(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = audit_total(api_mini)
    r = _draft(client, monkeypatch, llm=LLM("x", "y"))
    assert r.status_code == 502, r.text
    assert r.json()["error"]["code"] == "model_error"
    assert (
        r.json()["error"]["message"]
        == "narrative model output is not valid JSON after 2 attempt(s)"
    )
    assert audit_total(api_mini) == before


def test_ac5_narrative_ollama_down_is_503(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = _draft(client, monkeypatch, llm=RaisingLLM(OllamaUnavailableError("x")))
    assert r.status_code == 503, r.text
    assert r.json() == {"error": {"code": "unavailable", "message": "service unavailable"}}


def test_ac5_narrative_knowledge_down_still_200(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    down = FakeKnowledge(error=RetrievalUnavailableError("x"))
    r = _draft(client, monkeypatch, knowledge=down)
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["knowledge"] == "unavailable"


# ---------------------------------------------------------------- typologies
def _expected_typologies(db: Any) -> dict[str, Any]:
    explain = mod("aml.assistant.explainer").explain_typology
    x = explain(db, api_settings(), C1, llm=LLM(), knowledge=K3())
    return json.loads(json.dumps(x.as_dict()))


def test_ac5_typologies_envelope_and_equality(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM(), knowledge=K3())
    r = client(user="analyst01").get(TYPO)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feature"] == "assistant"
    assert body["meta"] == {"pii": "masked", "knowledge": "ok"}
    assert body["data"] == _expected_typologies(api_mini)


def test_ac5_typologies_measured_values(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM(), knowledge=K3())
    typologies = data_of(client(user="analyst01").get(TYPO))["typologies"]
    assert [t["typology"] for t in typologies] == [
        "rapid_movement",
        "round_tripping",
        "structuring",
    ]
    assert [t["rule_ids"] for t in typologies] == [
        ["RAPID_MOVEMENT"],
        ["NET_CYCLE"],
        ["STRUCTURING"],
    ]
    assert [[x["txn_id"] for x in t["transactions"]] for t in typologies] == [
        ["T05", "T06"],
        ["T02", "T03", "T04"],
        ["T01"],
    ]
    assert typologies[2]["transactions"][0] == T01
    t05 = next(c for c in typologies[0]["citations"] if c["id"] == "T05")
    assert t05["node_ids"] == ["EXT-01", "A02"]
    for t in typologies:
        assert [c["chunk_id"] for c in t["chunks"]] == ["KB-TYP-001#003"]


def test_ac5_typologies_never_chat_and_never_audit(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm, _, _ = fakes(monkeypatch, llm=LLM(), knowledge=K3())
    before = audit_total(api_mini)
    assert client(user="analyst01").get(TYPO).status_code == 200
    assert chats(llm) == []
    assert audit_total(api_mini) == before


def test_ac5_typologies_screening_only_case_is_empty_and_unknown_is_404(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM(), knowledge=K3())
    c = client(user="analyst01")
    r = c.get(f"{V1}/cases/{C5}/typologies")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["typologies"] == []
    assert_error(c.get(f"{V1}/cases/{NOPE}/typologies"), 404, "not_found", "unknown case_id")


def test_ac5_typologies_knowledge_down_gives_empty_chunks(
    api_mini: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakes(monkeypatch, llm=LLM(), knowledge=FakeKnowledge(error=RetrievalUnavailableError("x")))
    r = client(user="analyst01").get(TYPO)
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["knowledge"] == "unavailable"
    typologies = r.json()["data"]["typologies"]
    assert typologies
    assert all(t["chunks"] == [] for t in typologies)
