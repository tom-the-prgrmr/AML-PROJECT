"""AC7 for specs/assistant-answering.md: the typology explainer on MINI-N (no chat, no audit)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aml.assistant.evidence import RetrievalUnavailableError
from aml.cases.runner import CaseError
from aml.common.config import Settings
from aml.common.db import DuckDb

from .an_helpers import (
    CASE,
    CHUNK_TEXT,
    CHUNK_TITLE,
    K3,
    LLM,
    NOPE,
    FakeKnowledge,
    answering,
    audit_rows,
    chats,
    counts,
    duck_settings,
    explainer,
    mini_n,
    source_of,
)

T01 = {
    "txn_id": "T01",
    "txn_ts": "2026-03-02T09:00:00",
    "from_account_id": None,
    "to_account_id": "A01",
    "amount_vnd": 390000000,
    "channel": "CASH",
}
T06 = {
    "txn_id": "T06",
    "txn_ts": "2026-04-20T12:00:00",
    "from_account_id": "A02",
    "to_account_id": "EXT-02",
    "amount_vnd": 480000000,
    "channel": "EBANKING",
}
DEFINITION = "STRUCTURING v1: Repeated cash deposits just under the large-cash reporting threshold"


@pytest.fixture
def mn(duck: DuckDb) -> tuple[DuckDb, Settings]:
    return duck, mini_n(duck)


def _explain(mn: tuple[DuckDb, Settings], case_id: str = CASE, **kw: Any) -> Any:
    db, settings = mn
    kw.setdefault("llm", LLM())
    kw.setdefault("knowledge", K3())
    return explainer().explain_typology(db, kw.pop("settings", settings), case_id, **kw)


def _by_name(x: Any) -> dict[str, Any]:
    return {t.typology: t for t in x.typologies}


def test_ac7_three_typologies(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = (audit_rows(db), counts(db))
    fake, k3 = LLM(), K3()
    x = _explain(mn, llm=fake, knowledge=k3)
    assert [t.typology for t in x.typologies] == ["rapid_movement", "round_tripping", "structuring"]
    assert x.knowledge == "ok"
    assert [kw["seed_typologies"] for _, kw in k3.calls] == [
        ("rapid_movement",),
        ("round_tripping",),
        ("structuring",),
    ]
    assert all(kw["expand"] is True for _, kw in k3.calls)
    t = _by_name(x)
    s = t["structuring"]
    assert s.rule_ids == ("STRUCTURING",)
    assert s.definition == DEFINITION
    assert s.transactions == (T01,)
    assert s.transactions_total == 1
    assert s.chunks == (
        {"chunk_id": "KB-TYP-001#003", "title": CHUNK_TITLE, "excerpt": CHUNK_TEXT},
    )
    assert [(c.n, c.kind, c.id) for c in s.citations] == [
        (1, "transaction", "T01"),
        (2, "chunk", "KB-TYP-001#003"),
    ]
    rapid = t["rapid_movement"]
    assert [r["txn_id"] for r in rapid.transactions] == ["T05", "T06"]
    assert rapid.transactions[1] == T06
    cycle = t["round_tripping"]
    assert cycle.rule_ids == ("NET_CYCLE",)
    assert [r["txn_id"] for r in cycle.transactions] == ["T02", "T03", "T04"]
    for typ in x.typologies:
        for row in typ.transactions:
            assert "memo" not in row and "counterparty_name" not in row
    assert set(x.as_dict()) == {"case_id", "typologies"}
    for item in x.as_dict()["typologies"]:
        assert set(item) == {
            "typology", "rule_ids", "definition", "transactions", "chunks", "citations",
        }  # fmt: skip
    assert chats(fake) == []
    assert (audit_rows(db), counts(db)) == before


def test_ac7_rule_parameters_in_the_definition(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    params = {
        "window_days": 14,
        "band_low_vnd": 360000000,
        "min_deposits": 3,
        "large_cash_vnd": 400000000,
    }
    db.execute(
        "UPDATE monitoring_runs SET params = ? WHERE rule_id = 'STRUCTURING'", [json.dumps(params)]
    )
    s = _by_name(_explain(mn))["structuring"]
    assert s.definition == (
        DEFINITION + " (band_low_vnd=360000000, large_cash_vnd=400000000, min_deposits=3, "
        "window_days=14)"
    )


def test_ac7_one_typology(mn: tuple[DuckDb, Settings]) -> None:
    assert len(_explain(mn, typology="structuring").typologies) == 1
    assert _explain(mn, typology="mule_ring").typologies == ()
    with pytest.raises(answering().AssistantError) as err:
        _explain(mn, typology="smurfing")
    assert "unknown typology 'smurfing'" in str(err.value)
    assert "mule_ring, rapid_movement, round_tripping, structuring" in str(err.value)


def test_ac7_transaction_limit(mn: tuple[DuckDb, Settings]) -> None:
    capped = duck_settings(AML__ASSISTANT__ANSWERING__EXPLAIN_MAX_TRANSACTIONS="2")
    cycle = _by_name(_explain(mn, settings=capped))["round_tripping"]
    assert [r["txn_id"] for r in cycle.transactions] == ["T02", "T03"]
    assert cycle.transactions_total == 3


def test_ac7_knowledge_unavailable(mn: tuple[DuckDb, Settings]) -> None:
    down = FakeKnowledge(error=RetrievalUnavailableError("neo4j not available: down"))
    x = _explain(mn, knowledge=down)
    assert x.knowledge == "unavailable"
    assert all(t.chunks == () for t in x.typologies)
    t = _by_name(x)
    assert [r["txn_id"] for r in t["rapid_movement"].transactions] == ["T05", "T06"]
    assert t["structuring"].transactions == (T01,)
    assert len(t["round_tripping"].transactions) == 3


def test_ac7_screening_only_case_and_unknown_case(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    before = (audit_rows(db), counts(db))
    assert _explain(mn, "C-C05-20260630").typologies == ()
    with pytest.raises(CaseError) as err:
        _explain(mn, NOPE)
    assert "unknown case_id" in str(err.value)
    assert (audit_rows(db), counts(db)) == before


def test_ac7_the_explainer_never_chats() -> None:
    assert "chat(" not in source_of("aml.assistant.explainer")
