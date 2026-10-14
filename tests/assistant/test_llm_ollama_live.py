"""AC11 for specs/assistant-knowledge.md: `get_llm` against the real local Ollama."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from aml.common.config import Settings, load_settings

from .kn_helpers import files_in, llm

pytestmark = pytest.mark.ollama

TEXTS = ["xin chào", "nộp tiền mặt nhiều lần dưới ngưỡng báo cáo"]
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}
QUESTION = [
    {"role": "user", "content": "Trả lời đúng một từ: thủ đô của Việt Nam là gì?"},
]
LONG_PROMPT = (
    "SECRET=ALPHA. "
    + "Đây là một câu đệm dài không có ý nghĩa gì. " * 400
    + " Câu hỏi: giá trị SECRET ở đầu văn bản là gì?"
)


def _settings(cache: Path, **extra: str) -> Settings:
    return load_settings(environ={"AML__ASSISTANT__CACHE__DIR": str(cache), **extra})


def test_ac11_embeddings_chat_cache_and_context_limit(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    client = llm().get_llm(_settings(cache))

    vectors = client.embed(TEXTS)
    assert len(vectors) == 2
    for vector in vectors:
        assert len(vector) == 1024
        assert all(isinstance(x, float) for x in vector)
        assert all(math.isfinite(x) for x in vector)
        assert sum(x * x for x in vector) > 0
    assert client.misses == 2
    assert client.embed(TEXTS) == vectors
    assert client.hits == 2
    assert client.misses == 2

    out = client.chat(QUESTION, json_schema=SCHEMA)
    parsed = json.loads(out)
    assert isinstance(parsed, dict)
    assert isinstance(parsed["answer"], str)
    assert client.chat(QUESTION, json_schema=SCHEMA) == out
    assert client.hits == 3

    assert len(files_in(cache / "embed")) == 2
    assert len(files_in(cache / "chat")) == 1

    with pytest.raises(llm().LLMError, match="prompt exceeds the context window"):
        client.chat([{"role": "user", "content": LONG_PROMPT}])
    assert len(files_in(cache / "chat")) == 1

    with pytest.raises(llm().LLMError, match="prompt exceeds the context window"):
        client.embed(["x " * 20000])
    assert len(files_in(cache / "embed")) == 2


def test_ac11_missing_embedding_model_is_reported(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "cache", AML__OLLAMA__EMBED_MODEL="khong-co-mo-hinh-nay")
    client = llm().get_llm(settings)
    with pytest.raises(
        llm().LLMError, match="model 'khong-co-mo-hinh-nay' is not available on Ollama"
    ):
        client.embed(["a"])
