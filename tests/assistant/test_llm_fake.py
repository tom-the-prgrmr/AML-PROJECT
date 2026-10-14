"""AC2 for specs/assistant-knowledge.md: `fake_embedding` and `FakeLLM`."""

from __future__ import annotations

import re

import pytest

from .kn_helpers import llm

HELLO = [{"role": "user", "content": "xin chào"}]
BYE = [{"role": "user", "content": "tạm biệt"}]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_ac2_fake_embedding_shape_and_normalisation() -> None:
    fake_embedding = llm().fake_embedding
    repeated = fake_embedding("a a", 8)
    assert len(repeated) == 8
    assert [x for x in repeated if x != 0] == [1.0]
    assert fake_embedding("!!!", 4) == [1.0, 0.0, 0.0, 0.0]
    assert fake_embedding("Rửa Tiền", 16) == fake_embedding("rửa tiền", 16)
    vec = fake_embedding("nộp tiền mặt sát ngưỡng", 1024)
    assert abs(sum(x * x for x in vec) - 1.0) <= 1e-9


def test_ac2_fake_embedding_shared_words_mean_high_cosine() -> None:
    fake_embedding = llm().fake_embedding
    base = fake_embedding("nộp tiền mặt sát ngưỡng", 1024)
    assert _dot(base, fake_embedding("nộp tiền mặt", 1024)) > 0.7
    assert _dot(base, fake_embedding("chuyển khoản vòng tròn", 1024)) < 0.2


def test_ac2_fake_llm_embed() -> None:
    m = llm()
    f = m.FakeLLM(dim=8)
    assert f.embed([]) == []
    assert f.embed(["x", "y"]) == [m.fake_embedding("x", 8), m.fake_embedding("y", 8)]
    with pytest.raises(m.LLMError, match="cannot embed an empty text"):
        f.embed(["x", "  "])


def test_ac2_fake_llm_default_attributes() -> None:
    f = llm().FakeLLM()
    assert f.chat_model == "fake-chat"
    assert f.embed_model == "fake-embed"
    assert f.seed == 0
    assert f.num_ctx == 4096


def test_ac2_fake_llm_default_chat_is_deterministic() -> None:
    m = llm()
    first = m.FakeLLM().chat(HELLO)
    second = m.FakeLLM().chat(HELLO)
    assert first == second
    assert m.FakeLLM().chat(HELLO).startswith("FAKE-")
    assert re.fullmatch(r"FAKE-[0-9a-f]{12}", first)
    assert m.FakeLLM().chat(BYE) != first
    assert m.FakeLLM().chat(HELLO, json_schema={"type": "object"}) == "{}"


def test_ac2_fake_llm_scripted_replies_run_out() -> None:
    m = llm()
    f = m.FakeLLM(replies=["a", "b"])
    assert f.chat(HELLO) == "a"
    assert f.chat(HELLO) == "b"
    with pytest.raises(m.LLMError, match="no scripted reply left"):
        f.chat(HELLO)


def test_ac2_fake_llm_responder() -> None:
    f = llm().FakeLLM(responder=lambda m, js: m[-1]["content"].upper())
    assert f.chat(HELLO) == "XIN CHÀO"


def test_ac2_fake_llm_records_calls() -> None:
    f = llm().FakeLLM(dim=8)
    f.chat(HELLO)
    f.embed(["x"])
    assert len(f.calls) == 2
    assert f.calls[0]["kind"] == "chat"
    assert f.calls[0]["messages"][0]["content"] == "xin chào"
    assert f.calls[1] == {"kind": "embed", "texts": ["x"]}
