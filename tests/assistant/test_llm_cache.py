"""AC4 for specs/assistant-knowledge.md: `cache_key` and `CachedLLM`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from .kn_helpers import files_in, llm

KEY_FAKE = "7ee83fc4aec3838bb495d8fef8bb94fa139c28a676351ff74b90afb4170d02d0"
KEY_BGE = "b2850245cf64148915830adeda440e06792283b039ce044af12738d9553b9d48"
M = [{"role": "user", "content": "u"}]


def _json_files(directory: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in files_in(directory)]


def _embed_calls(inner: Any) -> list[dict[str, Any]]:
    return [c for c in inner.calls if c["kind"] == "embed"]


def _chat_calls(inner: Any) -> list[dict[str, Any]]:
    return [c for c in inner.calls if c["kind"] == "chat"]


def test_ac4_cache_key_values() -> None:
    cache_key = llm().cache_key
    assert cache_key("embed", "fake-embed", {"text": "xin chào"}) == KEY_FAKE
    assert cache_key("embed", "bge-m3", {"text": "xin chào"}) == KEY_BGE


def test_ac4_wrapper_mirrors_the_inner_client(tmp_path: Path) -> None:
    c = llm().CachedLLM(llm().FakeLLM(dim=8), tmp_path)
    assert (c.chat_model, c.embed_model, c.seed, c.num_ctx) == ("fake-chat", "fake-embed", 0, 4096)


def test_ac4_embed_writes_one_file_per_text(tmp_path: Path) -> None:
    m = llm()
    c = m.CachedLLM(m.FakeLLM(dim=8), tmp_path)
    assert c.embed(["xin chào", "b"]) == [m.fake_embedding("xin chào", 8), m.fake_embedding("b", 8)]
    assert (c.misses, c.hits) == (2, 0)
    assert len(files_in(tmp_path / "embed")) == 2
    entry = json.loads((tmp_path / "embed" / f"{KEY_FAKE}.json").read_text(encoding="utf-8"))
    assert entry["kind"] == "embed"
    assert entry["model"] == "fake-embed"
    assert entry["payload"] == {"text": "xin chào"}
    assert entry["response"] == m.fake_embedding("xin chào", 8)


def test_ac4_embed_sends_only_missing_texts_once_in_order(tmp_path: Path) -> None:
    m = llm()
    inner = m.FakeLLM(dim=8)
    c = m.CachedLLM(inner, tmp_path)
    c.embed(["xin chào", "b"])
    out = c.embed(["b", "c", "xin chào", "c"])
    assert out == [m.fake_embedding(t, 8) for t in ("b", "c", "xin chào", "c")]
    assert _embed_calls(inner)[-1]["texts"] == ["c"]
    assert (c.hits, c.misses) == (2, 3)


def test_ac4_a_new_wrapper_reuses_the_files(tmp_path: Path) -> None:
    m = llm()
    m.CachedLLM(m.FakeLLM(dim=8), tmp_path).embed(["xin chào", "b", "c"])
    inner = m.FakeLLM(dim=8)
    out = m.CachedLLM(inner, tmp_path).embed(["xin chào", "b", "c"])
    assert out == [m.fake_embedding(t, 8) for t in ("xin chào", "b", "c")]
    assert inner.calls == []


def test_ac4_another_embed_model_is_a_miss(tmp_path: Path) -> None:
    m = llm()
    m.CachedLLM(m.FakeLLM(dim=8), tmp_path).embed(["xin chào"])
    other = m.FakeLLM(dim=8, embed_model="other")
    m.CachedLLM(other, tmp_path).embed(["xin chào"])
    assert len(other.calls) == 1


def test_ac4_chat_is_cached_by_messages_schema_seed_and_num_ctx(tmp_path: Path) -> None:
    m = llm()
    inner = m.FakeLLM(replies=["r1", "r2"])
    c2 = m.CachedLLM(inner, tmp_path)
    assert c2.chat(M) == "r1"
    assert c2.chat(M) == "r1"
    assert len(_chat_calls(inner)) == 1
    assert c2.chat(M, json_schema={"type": "object"}) == "r2"
    entries = _json_files(tmp_path / "chat")
    assert len(entries) == 2
    for entry in entries:
        assert entry["payload"]["num_ctx"] == 4096
        assert entry["payload"]["temperature"] == 0

    assert m.CachedLLM(m.FakeLLM(seed=7, replies=["r3"]), tmp_path).chat(M) == "r3"
    assert m.CachedLLM(m.FakeLLM(num_ctx=8192, replies=["r4"]), tmp_path).chat(M) == "r4"
    entries = _json_files(tmp_path / "chat")
    assert sum(e["payload"]["num_ctx"] == 8192 for e in entries) == 1


def test_ac4_corrupt_cache_file_is_a_miss_and_is_overwritten(tmp_path: Path) -> None:
    m = llm()
    c = m.CachedLLM(m.FakeLLM(dim=8), tmp_path)
    c.embed(["xin chào"])
    path = tmp_path / "embed" / f"{KEY_FAKE}.json"
    path.write_text("not json", encoding="utf-8")
    misses = c.misses
    assert c.embed(["xin chào"]) == [m.fake_embedding("xin chào", 8)]
    assert c.misses == misses + 1
    assert "response" in json.loads(path.read_text(encoding="utf-8"))


def test_ac4_inner_errors_are_not_cached_and_no_temp_files_remain(tmp_path: Path) -> None:
    m = llm()
    c = m.CachedLLM(m.FakeLLM(dim=8, replies=["r"]), tmp_path)
    c.embed(["xin chào", "b"])
    c.chat(M)
    before = len(files_in(tmp_path / "embed"))
    with pytest.raises(m.LLMError):
        c.embed([" "])
    assert len(files_in(tmp_path / "embed")) == before
    for sub in ("embed", "chat"):
        assert all(p.name.endswith(".json") for p in files_in(tmp_path / sub))
