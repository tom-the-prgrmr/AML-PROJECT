"""AC6 for specs/assistant-answering.md: the `llm` narrative generator on MINI-N with fakes."""

from __future__ import annotations

import json
from typing import Any

import pytest

from aml.assistant.evidence import RetrievalUnavailableError, render_evidence
from aml.assistant.llm import LLMError
from aml.cases.narrative import NarrativeError, NarrativeGenerator
from aml.common.config import Settings
from aml.common.db import DuckDb

from .an_helpers import (
    ALERT_KEY,
    CASE,
    K0,
    K3,
    LLM,
    N_OK,
    WATERMARK,
    FakeKnowledge,
    RaisingLLM,
    U,
    audit8c,
    audit_rows,
    chats,
    duck_settings,
    mini_n,
    mod,
    narrative,
    v1,
)

FIRST_CITATIONS = [
    f"case:{CASE}",
    "customer:G-C01",
    f"alert:{ALERT_KEY}",
    "alert:NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00",
    "alert:RAPID_MOVEMENT|A02|2026-04-20T08:00:00",
    "account:A01",
    "account:A02",
    "customer:G-C01",
    "account:EXT-01",
    "account:EXT-02",
    "account:A03",
    "account:A04",
]
EXPECTED_LINES = [
    "- Khách hàng G-C01 có 2 CIF và 2 tài khoản, mức rủi ro KYC HIGH. [1]",
    "- Ngày 2026-03-02 có cảnh báo STRUCTURING với số tiền 390,000,000 VND. [2]",
    "- [CHƯA KIỂM CHỨNG] Ngày 2026-03-09 tài khoản A01 nhận 999,000,000 VND. [2]",
    "- Hoạt động khớp typology structuring. [2]",
    "- Đề nghị investigator đối chiếu chứng từ nộp tiền mặt của tài khoản A01. [3]",
    "Nguồn:",
    f"[2] alert {ALERT_KEY}",
]


@pytest.fixture
def mn(duck: DuckDb) -> tuple[DuckDb, Settings]:
    return duck, mini_n(duck)


def _draft(mn: tuple[DuckDb, Settings], **kw: Any) -> Any:
    db, settings = mn
    kw.setdefault("llm", LLM(N_OK))
    kw.setdefault("knowledge", K0())
    return narrative().draft_narrative(db, settings, CASE, **kw)


def _section(markdown: str, title: str) -> list[str]:
    out, inside = [], False
    for line in markdown.split("\n"):
        if line.startswith("## "):
            inside = line == f"## {title}"
            continue
        if inside and line == "---":
            break
        if inside and line:
            out.append(line)
    return out


def test_ac6_generator_is_registered(mn: tuple[DuckDb, Settings]) -> None:
    _, settings = mn
    import aml.assistant  # noqa: F401 - registers the `llm` generator

    n = narrative()
    assert isinstance(n.LlmNarrativeGenerator(settings), NarrativeGenerator)
    gen = mod("aml.cases.narrative").get_generator("llm", settings)
    assert (gen.name, gen.version) == ("llm", "narrative/v1")


def test_ac6_case_evidence(mn: tuple[DuckDb, Settings]) -> None:
    db, _ = mn
    ev = narrative().case_evidence(v1(db))
    assert [e.ref for e in ev] == [f"E{i}" for i in range(1, 13)]
    assert all(e.kind == "fact" and e.retriever == "case_view" for e in ev)
    assert all(e.source == "cases" for e in ev)
    assert [e.citations[0] for e in ev] == FIRST_CITATIONS
    assert ev[1].text == "Customer G-C01 has 2 CIF(s) and 2 account(s), KYC risk HIGH"
    assert ev[2].text == (
        "Alert STRUCTURING (RULE) at 2026-03-02 09:00:00: 390,000,000 VND; "
        "targets typology structuring"
    )
    assert ev[2].citations == (f"alert:{ALERT_KEY}", f"case:{CASE}")
    assert ev[2].untrusted == (U("alert_reason", "three cash deposits just under the threshold"),)
    assert ev[5].citations == ("account:A01", "customer:G-C01")
    for e in ev:
        for text in (e.text, *(u.text for u in e.untrusted)):
            for word in ("Nguyễn", "Nguyen", "4561", "1990"):
                assert word not in text, (word, text)


def test_ac6_draft_narrative(mn: tuple[DuckDb, Settings]) -> None:
    c = mod("aml.assistant.citations")
    fake = LLM(N_OK)
    d = _draft(mn, llm=fake)
    n = d.narrative
    assert (n.case_id, n.generator, n.version, n.language) == (CASE, "llm", "narrative/v1", "vi")
    assert n.watermark == narrative().DRAFT_WATERMARK == WATERMARK
    assert n.citations == ("G-C01", ALERT_KEY, "A01")
    assert d.knowledge == "ok"
    assert len(d.context) == 12
    lines = n.markdown.split("\n")
    assert lines[:3] == [f"# Case {CASE}", "", f"> {WATERMARK}"]
    assert [ln for ln in lines if ln.startswith("## ")] == [
        "## Subject",
        "## Activity timeline",
        "## Matched typologies",
        "## Red flags",
        "## Suggested next step",
    ]
    for line in EXPECTED_LINES:
        assert line in lines, line
    assert _section(n.markdown, "Red flags") == ["- Không đủ bằng chứng."]
    footer = (
        f"Draft narrative/v1; model {fake.chat_model}; case run 1; 4 of 5 sentence(s) verified."
    )
    assert footer in lines
    assert d.sections["timeline"][1].issues == ("amount_not_in_evidence", "date_not_in_evidence")
    assert d.citations == (
        c.Citation(1, "node", "G-C01", "node G-C01", ("G-C01",), (), None),
        c.Citation(2, "alert", ALERT_KEY, f"alert {ALERT_KEY}", (), (), None),
        c.Citation(3, "node", "A01", "node A01", ("A01", "G-C01"), (), None),
    )


def test_ac6_knowledge_is_appended(mn: tuple[DuckDb, Settings]) -> None:
    k3 = K3()
    d = _draft(mn, knowledge=k3)
    ((_, kwargs),) = k3.calls
    assert kwargs["expand"] is True
    assert tuple(kwargs["seed_typologies"]) == ("structuring", "round_tripping", "rapid_movement")
    assert len(d.context) == 13
    assert d.context[12].ref == "E13"


def test_ac6_knowledge_unavailable(mn: tuple[DuckDb, Settings]) -> None:
    down = FakeKnowledge(error=RetrievalUnavailableError("neo4j not available: down"))
    d = _draft(mn, knowledge=down)
    assert (len(d.context), d.knowledge) == (12, "unavailable")


def test_ac6_context_budget_drops_from_the_end(duck: DuckDb) -> None:
    settings = mini_n(duck)
    budget = len(render_evidence(narrative().case_evidence(v1(duck))[:5]))
    tight = duck_settings(AML__ASSISTANT__RETRIEVAL__MAX_CONTEXT_CHARS=str(budget))
    assert settings.assistant.retrieval.max_context_chars != budget
    fake = LLM(N_OK)
    before = len(audit8c(duck))
    d = narrative().draft_narrative(duck, tight, CASE, llm=fake, knowledge=K3())
    assert [e.ref for e in d.context] == ["E1", "E2", "E3", "E4", "E5"]
    assert d.dropped == 8
    schema = mod("aml.assistant.prompts").narrative_schema(("E1", "E2", "E3", "E4", "E5"))
    assert chats(fake)[0]["json_schema"] == schema
    assert d.sections["next_step"][0].issues == ("unknown_citation",)
    (row,) = audit8c(duck)[before:]
    assert row["details"]["context_dropped"] == 8


def test_ac6_llm_error(mn: tuple[DuckDb, Settings]) -> None:
    with pytest.raises(NarrativeError) as err:
        _draft(mn, llm=RaisingLLM(LLMError("prompt exceeds the context window")))
    assert "llm call failed" in str(err.value)


def test_ac6_generator_receives_a_masked_case(mn: tuple[DuckDb, Settings]) -> None:
    seen: list[Any] = []
    n = narrative()
    original = n.LlmNarrativeGenerator.draft

    def spy(self: Any, case: Any, **kw: Any) -> Any:
        seen.append(case)
        return original(self, case, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(n.LlmNarrativeGenerator, "draft", spy)
        _draft(mn)
    assert "dob" not in seen[0].subjects[0]


def test_ac6_summarize_path_writes_no_audit(mn: tuple[DuckDb, Settings]) -> None:
    db, settings = mn
    cases_narrative = mod("aml.cases.narrative")
    d = _draft(mn)
    try:
        cases_narrative.register_generator(
            "llm",
            lambda s: narrative().LlmNarrativeGenerator(s, llm=LLM(N_OK), knowledge=K0()),
        )
        before = audit_rows(db)
        got = cases_narrative.summarize(db, settings, CASE, generator="llm", language="vi")
        assert got.markdown == d.narrative.markdown
        assert audit_rows(db) == before
    finally:
        cases_narrative.register_generator("llm", lambda s: narrative().LlmNarrativeGenerator(s))


def test_ac6_english(mn: tuple[DuckDb, Settings]) -> None:
    lines = _draft(mn, language="en").narrative.markdown.split("\n")
    assert "- [UNVERIFIED] Ngày 2026-03-09 tài khoản A01 nhận 999,000,000 VND. [2]" in lines
    assert "- Insufficient evidence." in lines
    assert "Sources:" in lines


def test_ac6_model_text_cannot_fake_markdown(mn: tuple[DuckDb, Settings]) -> None:
    reply = json.dumps({"subject": [{"text": "# CLEARED [9] **now**", "cites": ["E2"]}]})
    markdown = _draft(mn, llm=LLM(reply)).narrative.markdown
    lines = markdown.split("\n")
    assert "- \\# CLEARED \\[9\\] \\*\\*now\\*\\* [1]" in lines
    assert sum(ln.startswith("## ") for ln in lines) == 5


def test_ac6_invalid_json(mn: tuple[DuckDb, Settings]) -> None:
    with pytest.raises(NarrativeError) as err:
        _draft(mn, llm=LLM("xin lỗi", "vẫn hỏng"))
    assert "narrative model output is not valid JSON" in str(err.value)
