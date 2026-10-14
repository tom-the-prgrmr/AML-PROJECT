"""AC1 for specs/assistant-knowledge.md: config, interfaces, constants, get_llm, wiring."""

from __future__ import annotations

import re
import socket
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from aml.common.config import PROJECT_ROOT, load_settings
from tests.neo4j_sync.helpers import READ_PROCEDURES

from .kn_helpers import OFFLINE_OLLAMA, kmodel, llm, mod

LLM_SOURCE = PROJECT_ROOT / "src" / "aml" / "assistant" / "llm.py"


def test_ac1_assistant_config_defaults() -> None:
    s = load_settings(environ={})
    a = s.assistant
    assert a.provider == "ollama"
    assert a.request_timeout_seconds == 300
    assert a.num_ctx == 4096
    assert a.keep_alive_chat == "5m"
    assert a.keep_alive_embed == "5m"
    assert a.cache.enabled is True
    assert a.cache.dir == "data/llm_cache"
    assert a.embedding.dimensions == 1024
    assert a.embedding.batch_size == 16
    assert a.knowledge.dir == "docs/knowledge"
    assert a.knowledge.chunk_max_chars == 1200
    assert a.vector_procedures == ["db.index.vector.queryNodes"]
    assert s.ollama.llm_model == "qwen2.5:3b-instruct"
    assert s.ollama.embed_model == "bge-m3"


def test_ac1_read_procedures_of_6a_are_unchanged() -> None:
    s = load_settings(environ={})
    assert s.neo4j.read_procedures == READ_PROCEDURES
    assert len(s.neo4j.read_procedures) == 7
    assert "db.index.vector.queryNodes" not in s.neo4j.read_procedures


@pytest.mark.parametrize(
    "env",
    [
        {"AML__ASSISTANT__PROVIDER": "openai"},
        {"AML__ASSISTANT__EMBEDDING__DIMENSIONS": "0"},
        {"AML__ASSISTANT__EMBEDDING__DIMENSIONS": "4097"},
        {"AML__ASSISTANT__EMBEDDING__BATCH_SIZE": "0"},
        {"AML__ASSISTANT__KNOWLEDGE__CHUNK_MAX_CHARS": "199"},
        {"AML__ASSISTANT__NUM_CTX": "511"},
        {"AML__ASSISTANT__REQUEST_TIMEOUT_SECONDS": "0"},
    ],
)
def test_ac1_invalid_assistant_config_is_rejected(env: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        load_settings(environ=env)


def test_ac1_assistant_config_bounds_are_inclusive() -> None:
    s = load_settings(
        environ={
            "AML__ASSISTANT__EMBEDDING__DIMENSIONS": "4096",
            "AML__ASSISTANT__EMBEDDING__BATCH_SIZE": "256",
            "AML__ASSISTANT__KNOWLEDGE__CHUNK_MAX_CHARS": "200",
            "AML__ASSISTANT__NUM_CTX": "512",
        }
    )
    assert s.assistant.embedding.dimensions == 4096
    assert s.assistant.embedding.batch_size == 256
    assert s.assistant.knowledge.chunk_max_chars == 200
    assert s.assistant.num_ctx == 512


def test_ac1_protocol_is_runtime_checkable(tmp_path: Path) -> None:
    m = llm()
    assert isinstance(m.FakeLLM(), m.LLMClient)
    assert isinstance(m.OllamaClient("http://x", "a", "b", seed=1), m.LLMClient)
    assert isinstance(m.CachedLLM(m.FakeLLM(), tmp_path), m.LLMClient)
    assert not isinstance(object(), m.LLMClient)


def test_ac1_constants() -> None:
    assert llm().TEMPERATURE == 0
    k = kmodel()
    assert k.VECTOR_INDEX == "chunk_embedding"
    assert k.KNOWLEDGE_VERSION == "knowledge/v1"
    assert re.fullmatch(k.CHUNK_ID_PATTERN, "KB-TYP-001#003")
    assert not re.fullmatch(k.CHUNK_ID_PATTERN, "KB-TYP-001")
    assert not re.fullmatch(k.CHUNK_ID_PATTERN, "kb-typ-001#3")


def test_ac1_get_llm_builds_clients_without_touching_the_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = load_settings(environ={"AML__OLLAMA__HOST": OFFLINE_OLLAMA})
    cached = load_settings(
        environ={
            "AML__OLLAMA__HOST": OFFLINE_OLLAMA,
            "AML__ASSISTANT__CACHE__DIR": str(tmp_path / "cache"),
        }
    )
    s2 = load_settings(
        environ={
            "AML__OLLAMA__HOST": OFFLINE_OLLAMA,
            "AML__ASSISTANT__PROVIDER": "fake",
            "AML__ASSISTANT__EMBEDDING__DIMENSIONS": "64",
        }
    )

    def no_network(self: Any, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("get_llm must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    get_llm = llm().get_llm
    plain = get_llm(s, cached=False)
    wrapped = get_llm(cached)
    fake = get_llm(s2, cached=False)
    monkeypatch.undo()

    assert type(plain).__name__ == "OllamaClient"
    assert plain.chat_model == "qwen2.5:3b-instruct"
    assert plain.embed_model == "bge-m3"
    assert plain.seed == 42
    assert plain.num_ctx == 4096
    assert type(wrapped).__name__ == "CachedLLM"
    assert type(fake).__name__ == "FakeLLM"
    assert len(fake.embed(["a"])[0]) == 64


def test_ac1_llm_source_has_no_hosted_provider_and_no_neo4j() -> None:
    text = LLM_SOURCE.read_text(encoding="utf-8")
    lowered = text.lower()
    for word in ("openai", "anthropic", "googleapis", "api_key"):
        assert word not in lowered, word
    assert not re.search(r"^\s*(import|from)\s+neo4j", text, flags=re.MULTILINE)


def test_ac1_write_prefixes_include_knowledge() -> None:
    client = mod("aml.graph.neo4j.client")
    assert tuple(client.WRITE_PREFIXES) == ("schema.cypher", "sync/", "knowledge/")


def test_ac1_makefile_and_tasks_run_rag_build() -> None:
    assert "$(AML) rag build" in (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    assert '"rag", "build"' in (PROJECT_ROOT / "tasks.ps1").read_text(encoding="utf-8")
