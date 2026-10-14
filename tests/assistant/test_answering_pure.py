"""AC1 and AC2 for specs/assistant-answering.md: constants, facts, citations, parsing, checks."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from aml.common.config import load_settings

from .an_helpers import (
    CHUNK_TEXT,
    EV,
    J_NONE,
    S_AMOUNT,
    S_DATE,
    S_FAKE,
    S_NOCITE,
    S_NOID,
    S_OK1,
    S_OK2,
    S_VERDICT,
    X1,
    X2,
    X3,
    X4,
    J,
    U,
    mod,
)


def facts():  # type: ignore[no-untyped-def]
    return mod("aml.assistant.facts")


def citations():  # type: ignore[no-untyped-def]
    return mod("aml.assistant.citations")


def validation():  # type: ignore[no-untyped-def]
    return mod("aml.assistant.validation")


# ---------------------------------------------------------------- AC1
def test_ac1_config_and_constants() -> None:
    a = load_settings(environ={}).assistant.answering
    assert (a.language, a.mode, a.max_retries) == ("vi", "graphrag", 1)
    assert (a.explain_max_transactions, a.explain_chunks) == (20, 3)
    prompts = mod("aml.assistant.prompts")
    assert prompts.ANSWER_PROMPT_VERSION == "answer/v1"
    assert prompts.NARRATIVE_PROMPT_VERSION == "narrative/v1"
    ans = mod("aml.assistant.answering")
    assert ans.LANGUAGES == ("vi", "en")
    assert ans.REFUSAL == {"vi": "Không đủ bằng chứng.", "en": "Insufficient evidence."}
    assert ans.DECISIONS == ("ANSWERED", "INSUFFICIENT_EVIDENCE", "FAILED", "NARRATIVE_DRAFTED")
    watermark = mod("aml.assistant.narrative").DRAFT_WATERMARK
    assert watermark == "DRAFT — requires investigator review"
    assert len(watermark) == 36
    c = citations()
    assert c.KINDS == ("node", "transaction", "chunk", "alert")
    assert "Evidence" not in vars(c)


@pytest.mark.parametrize("text", ["390,000,000 VND", "390.000.000 đồng", "390 triệu", "390000000"])
def test_ac1_extract_amounts_390m(text: str) -> None:
    assert facts().extract_amounts(text) == {390000000}


@pytest.mark.parametrize("text", ["1,5 tỷ đồng", "1.5 billion VND"])
def test_ac1_extract_amounts_scaled_decimal(text: str) -> None:
    assert facts().extract_amounts(text) == {1500000000}


def test_ac1_extract_amounts_currency_word_makes_a_small_number_an_amount() -> None:
    assert facts().extract_amounts("1,019 VND") == {1019}


@pytest.mark.parametrize(
    "text",
    [
        "1,019",
        "3 giao dịch",
        "T0000000042",
        "C-C01-20260302",
        "2026-03-02 09:00:00",
        "score 100.0",
    ],
)
def test_ac1_extract_amounts_ignores_ids_counts_and_dates(text: str) -> None:
    assert facts().extract_amounts(text) == frozenset()


def test_ac1_extract_numbers() -> None:
    assert facts().extract_numbers("amount_vnd=390000000 txn_count=3") == {390000000, 3}


@pytest.mark.parametrize(
    "text", ["2026-03-02T09:00:00", "ngày 2/3/2026", "02-03-2026", "ngày 2 tháng 3 năm 2026"]
)
def test_ac1_extract_dates(text: str) -> None:
    assert facts().extract_dates(text) == {"2026-03-02"}


def test_ac1_extract_dates_no_calendar_check_and_partial_dates() -> None:
    assert facts().extract_dates("2026-02-30") == {"2026-02-30"}
    assert facts().extract_dates("tháng 3 năm 2026") == frozenset()


def test_ac1_evidence_numbers_and_dates() -> None:
    f = facts()
    assert f.evidence_numbers(X1) >= {390000000}
    assert f.evidence_dates(X1) == {"2026-03-02"}
    assert 400000000 in f.evidence_numbers(X3)  # from the chunk_text of a passage
    memo = dataclasses.replace(
        X1, untrusted=(U("memo", "da chuyen 777,000,000 VND ngay 2026-05-05"),)
    )
    assert 777000000 not in f.evidence_numbers(memo)
    assert "2026-05-05" not in f.evidence_dates(memo)


def test_ac1_to_citation() -> None:
    c = citations()
    assert c.to_citation(X1, 1) == c.Citation(
        1, "transaction", "T01", "transaction T01", ("A01",), ("T01",), None
    )
    assert c.to_citation(X2, 2) == c.Citation(
        2, "node", "A01", "node A01", ("A01", "G-C01"), (), None
    )
    assert c.to_citation(X3, 3) == c.Citation(
        3,
        "chunk",
        "KB-TYP-001#003",
        "chunk KB-TYP-001#003",
        (),
        (),
        CHUNK_TEXT,
    )
    assert c.primary(X4) is None
    with pytest.raises(ValueError):
        c.to_citation(X4, 1)


def test_ac1_parse_model_answer() -> None:
    v = validation()
    expected = (
        "answered",
        (v.Claim("Tài khoản A01 nhận 390,000,000 VND tiền mặt vào ngày 2026-03-02.", ("E1",)),),
    )
    assert v.parse_model_answer(J(S_OK1)) == expected
    assert v.parse_model_answer("```json\n" + J(S_OK1) + "\n```") == expected
    inline = json.dumps(
        {
            "status": "answered",
            "sentences": [
                {"text": "Tài khoản A01 thuộc khách hàng G-C01 [E2, E1].", "cites": ["[E2]"]}
            ],
        },
        ensure_ascii=False,
    )
    _, (claim,) = v.parse_model_answer(inline)
    assert claim.text == "Tài khoản A01 thuộc khách hàng G-C01."
    assert claim.cites == ("E2", "E1")
    merged = json.dumps(
        {
            "status": "answered",
            "sentences": [{"text": "A01 nhận tiền.", "cites": ["txn:T01, account:A01"]}],
        },
        ensure_ascii=False,
    )
    _, (claim,) = v.parse_model_answer(merged)
    assert claim.cites == ("txn:T01", "account:A01")
    assert v.parse_model_answer(J_NONE) == ("insufficient_evidence", ())


def test_ac1_answer_schema_binds_cites_to_the_refs() -> None:
    schema = mod("aml.assistant.prompts").answer_schema(("E1", "E2"))
    cites = schema["properties"]["sentences"]["items"]["properties"]["cites"]
    assert cites == {"type": "array", "minItems": 1, "items": {"enum": ["E1", "E2"]}}


@pytest.mark.parametrize(
    "raw",
    [
        "xin lỗi",
        '{"status": "maybe", "sentences": []}',
        '{"status": "answered", "sentences": "none"}',
    ],
)
def test_ac1_parse_model_answer_rejects(raw: str) -> None:
    v = validation()
    with pytest.raises(v.ModelOutputError):
        v.parse_model_answer(raw)


def test_ac1_no_evidence_module_added_by_8c() -> None:
    """8c reuses 8b's evidence.py; the citations module defines no evidence type of its own."""
    source = Path(mod("aml.assistant.citations").__file__).read_text(encoding="utf-8")
    assert "class Evidence" not in source


# ---------------------------------------------------------------- AC2
def _check(text: str, cites: tuple[str, ...]):  # type: ignore[no-untyped-def]
    v = validation()
    (checked,) = v.check_claims([v.Claim(text, cites)], EV)
    return checked


def _of(sentence: dict[str, object]):  # type: ignore[no-untyped-def]
    return _check(str(sentence["text"]), tuple(sentence["cites"]))  # type: ignore[arg-type]


def test_ac2_supported_sentences() -> None:
    ok1 = _of(S_OK1)
    assert (ok1.supported, ok1.issues, ok1.refs) == (True, (), ("E1",))
    assert _of(S_OK2).supported is True  # 400 triệu đồng is in the chunk_text of E3


def test_ac2_wrong_amount_and_date() -> None:
    amount = _of(S_AMOUNT)
    assert (amount.supported, amount.issues) == (False, ("amount_not_in_evidence",))
    assert _of(S_DATE).issues == ("date_not_in_evidence",)
    wrong_item = _check(str(S_OK1["text"]), ("E2",))
    assert wrong_item.issues == ("amount_not_in_evidence", "date_not_in_evidence")


def test_ac2_unknown_citations() -> None:
    fake = _of(S_FAKE)
    assert (fake.issues, fake.refs) == (("unknown_citation",), ())
    partly = _check(str(S_OK1["text"]), ("E1", "E9"))
    assert (partly.issues, partly.refs) == (("unknown_citation",), ("E1",))


def test_ac2_citations_by_id() -> None:
    for cites in (("T01",), ("txn:T01",)):
        checked = _check(str(S_OK1["text"]), cites)
        assert (checked.supported, checked.refs) == (True, ("E1",))
    a01 = _check(str(S_OK1["text"]), ("A01",))  # only the FIRST citation of an item counts
    assert a01.refs == ("E2",)
    assert a01.issues == ("amount_not_in_evidence", "date_not_in_evidence")


def test_ac2_missing_citation_and_verdict() -> None:
    assert _of(S_NOCITE).issues == ("no_citation",)
    noid = _of(S_NOID)
    assert (noid.issues, noid.refs) == (("no_citation",), ("E4",))
    assert _of(S_VERDICT).issues == ("verdict_language",)


def test_ac2_is_verdict() -> None:
    f = facts()
    for phrase in mod("aml.datagen.memos").INJECTION_PHRASES:
        assert f.is_verdict(phrase), phrase
    for text in (
        "Tài khoản A01 nhận 390,000,000 VND tiền mặt vào ngày 2026-03-02.",
        "Giao dịch T05 có memo chứa chỉ dẫn gửi tới mô hình.",
        "Case đang ở trạng thái CLOSED với disposition FALSE_POSITIVE.",
    ):
        assert not f.is_verdict(text), text


def test_ac2_check_claims_is_deterministic() -> None:
    v = validation()
    claims = [v.Claim(str(s["text"]), tuple(s["cites"])) for s in (S_OK1, S_FAKE, S_VERDICT)]  # type: ignore[arg-type]
    assert v.check_claims(claims, EV) == v.check_claims(claims, EV)
