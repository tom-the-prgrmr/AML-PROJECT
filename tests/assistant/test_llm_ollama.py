"""AC3 for specs/assistant-knowledge.md: `OllamaClient` (recording transport, local server)."""

from __future__ import annotations

from typing import Any

import pytest

from aml.common.db import ServiceUnavailableError

from .kn_helpers import OFFLINE_OLLAMA, USER_MSG, llm, recording_transport, serve

SYS_USER = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
CHAT_BODY = {
    "model": "qwen2.5:3b-instruct",
    "messages": SYS_USER,
    "stream": False,
    "truncate": False,
    "options": {"temperature": 0, "seed": 42, "num_ctx": 4096},
    "keep_alive": "5m",
}
SCHEMA = {"type": "object", "properties": {"category": {"type": "string"}}}
CONTEXT_ERROR = (
    "request (5255 tokens) exceeds the available context size (4096 tokens), "
    "try increasing it; type exceed_context_size_error"
)


def _client(transport: Any = None, **kw: Any) -> Any:
    return llm().OllamaClient(
        "http://ollama.test",
        "qwen2.5:3b-instruct",
        "bge-m3",
        seed=42,
        batch_size=2,
        transport=transport,
        **kw,
    )


def test_ac3_chat_sends_the_exact_body() -> None:
    transport, seen = recording_transport()
    assert _client(transport).chat(SYS_USER) == "xin chào"
    assert len(seen) == 1
    path, body = seen[0]
    assert path == "/api/chat"
    assert dict(body) == CHAT_BODY


def test_ac3_num_ctx_is_sent_in_options() -> None:
    transport, seen = recording_transport()
    _client(transport, num_ctx=8192).chat(SYS_USER)
    assert seen[0][1]["options"]["num_ctx"] == 8192


def test_ac3_json_schema_goes_to_format_and_content_must_parse() -> None:
    m = llm()
    transport, seen = recording_transport()
    with pytest.raises(m.LLMError, match="not valid JSON"):
        _client(transport).chat(SYS_USER, json_schema=SCHEMA)
    assert dict(seen[0][1]) == {**CHAT_BODY, "format": SCHEMA}

    ok, _ = recording_transport(chat={"message": {"content": '{"category": "salary"}'}})
    assert _client(ok).chat(SYS_USER, json_schema=SCHEMA) == '{"category": "salary"}'


def test_ac3_embed_is_split_into_batches() -> None:
    transport, seen = recording_transport()
    assert _client(transport).embed(["a", "b", "c"]) == [[0.1, 0.2]] * 3
    assert [p for p, _ in seen] == ["/api/embed", "/api/embed"]
    assert dict(seen[0][1]) == {
        "model": "bge-m3",
        "input": ["a", "b"],
        "truncate": False,
        "keep_alive": "5m",
    }
    assert dict(seen[1][1]) == {
        "model": "bge-m3",
        "input": ["c"],
        "truncate": False,
        "keep_alive": "5m",
    }


def test_ac3_embed_empty_list_and_empty_text_make_no_call() -> None:
    transport, seen = recording_transport()
    client = _client(transport)
    assert client.embed([]) == []
    with pytest.raises(llm().LLMError, match="cannot embed an empty text"):
        client.embed(["a", ""])
    assert seen == []


def test_ac3_bad_response_shapes_are_unexpected() -> None:
    m = llm()
    with pytest.raises(m.LLMError, match="unexpected Ollama response"):
        _client(lambda path, body: {"embeddings": [[0.1, 0.2]]}).embed(["a", "b"])
    with pytest.raises(m.LLMError, match="unexpected Ollama response"):
        _client(lambda path, body: {}).chat(SYS_USER)


def test_ac3_unreachable_host_raises_service_unavailable() -> None:
    client = llm().OllamaClient(OFFLINE_OLLAMA, "m", "e", seed=1, timeout=2)
    with pytest.raises(ServiceUnavailableError, match=f"cannot reach Ollama at {OFFLINE_OLLAMA}"):
        client.chat(USER_MSG)
    with pytest.raises(ServiceUnavailableError, match=f"cannot reach Ollama at {OFFLINE_OLLAMA}"):
        client.embed(["a"])


def _over_http(host: str, **kw: Any) -> Any:
    return llm().OllamaClient(host, kw.pop("chat_model", "m"), "bge-m3", seed=1, **kw)


def test_ac3_http_404_means_model_not_available() -> None:
    with serve(404, {"error": "model not found"}) as host:
        with pytest.raises(llm().LLMError) as embed_err:
            _over_http(host).embed(["a"])
        with pytest.raises(llm().LLMError) as chat_err:
            _over_http(host, chat_model="qwen-x").chat(USER_MSG)
    assert "model 'bge-m3' is not available on Ollama" in str(embed_err.value)
    assert "ollama pull bge-m3" in str(embed_err.value)
    assert "model 'qwen-x' is not available on Ollama" in str(chat_err.value)
    assert "ollama pull qwen-x" in str(chat_err.value)


def test_ac3_http_400_context_errors_name_the_context_window() -> None:
    m = llm()
    with serve(400, {"error": CONTEXT_ERROR}) as host, pytest.raises(m.LLMError) as chat_err:
        _over_http(host).chat(USER_MSG)
    assert "prompt exceeds the context window" in str(chat_err.value)
    assert "5255" in str(chat_err.value)

    too_long = {"error": "the input length exceeds the context length"}
    with serve(400, too_long) as host, pytest.raises(m.LLMError) as embed_err:
        _over_http(host).embed(["a"])
    assert "prompt exceeds the context window" in str(embed_err.value)


def test_ac3_other_http_errors_report_the_status_code() -> None:
    m = llm()
    with serve(400, {"error": "bad request"}) as host, pytest.raises(m.LLMError) as bad:
        _over_http(host).embed(["a"])
    assert "Ollama returned HTTP 400" in str(bad.value)
    assert "context window" not in str(bad.value)

    with (
        serve(500, {"error": "boom"}) as host,
        pytest.raises(m.LLMError, match="Ollama returned HTTP 500"),
    ):
        _over_http(host).embed(["a"])
