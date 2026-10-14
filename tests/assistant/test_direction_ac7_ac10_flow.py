"""AC7-AC10 for specs/assistant-direction-check.md: answer_question, draft_narrative, purity."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aml.common.db import DuckDb

from .an_helpers import CASE, K0, LLM, J, answering, audit8c, mini_n, narrative
from .dir_helpers import DEV, RD, S_DIR1, S_IN, S_SPEC2, mod, validation

CONTRACT_KEYS = {
    "answer_id", "case_id", "question", "language", "status", "sentences", "citations",
    "retrievers", "validation", "model", "prompt_version",
}  # fmt: skip


def test_dir_ac7_qa_flags_the_reversed_sentence(duck: DuckDb) -> None:
    """Given a reversed and a correct sentence, When answered, Then the first is UNVERIFIED."""
    settings = mini_n(duck)
    fake = LLM(J({"text": S_DIR1, "cites": ["E1"]}, {"text": S_IN, "cites": ["E2"]}))
    a = answering().answer_question(
        duck,
        settings,
        "Tài khoản A3154676584 nhận tiền từ những tài khoản nào?",
        case_id=CASE,
        retriever=RD(),
        llm=fake,
    )
    d = a.as_dict()
    assert a.status == "answered"
    assert set(d) == CONTRACT_KEYS
    assert [s["supported"] for s in d["sentences"]] == [False, True]
    assert [s["citations"] for s in d["sentences"]] == [[1], [2]]
    assert d["validation"] == {"sentences": 2, "supported": 1, "unsupported": 1}
    assert a.text.splitlines()[0] == "[CHƯA KIỂM CHỨNG] " + S_DIR1 + " [1]"
    assert a.llm_calls == 1
    row = audit8c(duck)[-1]
    assert row["decision"] == "ANSWERED"
    assert row["reason"] == (
        "answered: 2 sentence(s), 1 supported, 1 flagged; 4 context item(s), 2 cited"
    )
    assert row["details"]["validation"] == {
        "sentences": 2,
        "supported": 1,
        "unsupported": 1,
        "issues": {"direction_mismatch": 1},
    }
    assert row["details"]["flagged"][0]["issues"] == ["direction_mismatch"]


def test_dir_ac8_nothing_supported_refuses(duck: DuckDb) -> None:
    """Given only the speculative reversed sentence, When answered, Then nothing_supported."""
    settings = mini_n(duck)
    fake = LLM(J({"text": S_SPEC2, "cites": ["E2", "E3"]}))
    a = answering().answer_question(
        duck,
        settings,
        "Ai là chủ sở hữu hưởng lợi cuối cùng của số tiền này?",
        case_id=CASE,
        retriever=RD(),
        llm=fake,
    )
    assert a.status == "insufficient_evidence"
    assert a.refusal_reason == "nothing_supported"
    assert a.text == "Không đủ bằng chứng."
    assert a.sentences == ()
    assert a.citations == ()
    assert len(a.discarded) == 1
    assert a.discarded[0].issues == ("direction_mismatch", "speculative")
    assert a.as_dict()["validation"] == {"sentences": 0, "supported": 0, "unsupported": 0}
    assert a.llm_calls == 1
    row = audit8c(duck)[-1]
    assert row["decision"] == "INSUFFICIENT_EVIDENCE"
    assert row["details"]["refusal_reason"] == "nothing_supported"
    assert row["details"]["validation"] == {
        "sentences": 0,
        "supported": 0,
        "unsupported": 0,
        "issues": {"direction_mismatch": 1, "speculative": 1},
    }


def test_dir_ac9_narrative_uses_counterparty_items(duck: DuckDb) -> None:
    """Given E9 (EXT-01 IN) and E10 (EXT-02 OUT), When the timeline says both sent money in."""
    settings = mini_n(duck)
    reply = json.dumps(
        {
            "timeline": [
                {"text": "Khách hàng nhận 500,000,000 VND từ tài khoản EXT-01.", "cites": ["E9"]},
                {"text": "Khách hàng nhận 480,000,000 VND từ tài khoản EXT-02.", "cites": ["E10"]},
            ]
        },
        ensure_ascii=False,
    )
    d = narrative().draft_narrative(duck, settings, CASE, llm=LLM(reply), knowledge=K0())
    timeline = d.sections["timeline"]
    assert [s.supported for s in timeline] == [True, False]
    assert timeline[1].issues == ("direction_mismatch",)
    assert "1 of 2 sentence(s) verified." in d.narrative.markdown
    assert d.llm_calls == 1
    rows = [r for r in audit8c(duck) if r["decision"] == "NARRATIVE_DRAFTED"]
    assert rows[-1]["details"]["validation"] == {
        "sentences": 2,
        "supported": 1,
        "unsupported": 1,
        "issues": {"direction_mismatch": 1},
    }


def test_dir_ac10_check_claims_is_deterministic() -> None:
    """Given the same claims twice, When check_claims runs, Then equal results."""
    v = validation()
    claims = [
        v.Claim(S_DIR1, ("E1",)),
        v.Claim(S_SPEC2, ("E2", "E3")),
        v.Claim(S_IN, ("E2",)),
    ]
    first = v.check_claims(claims, DEV)
    assert first == v.check_claims(claims, DEV)
    assert [c.issues for c in first] == [
        ("direction_mismatch",),
        ("direction_mismatch", "speculative"),
        (),
    ]


def test_dir_ac10_checks_import_no_llm_or_network() -> None:
    """Given facts.py and validation.py, When their imports are read, Then no LLM / HTTP client."""
    banned = re.compile(
        r"^\s*(?:from|import)\s+(?:aml\.assistant\.llm|requests|httpx|ollama)\b", re.MULTILINE
    )
    for name in ("aml.assistant.facts", "aml.assistant.validation"):
        path: Any = mod(name).__file__
        source = Path(path).read_text(encoding="utf-8")
        assert banned.search(source) is None, name
        assert "from .llm" not in source and "from . import llm" not in source, name
