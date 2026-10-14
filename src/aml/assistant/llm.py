"""Local LLM access: an Ollama client, a deterministic fake, and an on-disk cache.

Only the Ollama host from ``settings.ollama`` is ever contacted; there is no hosted provider.
Every chat call uses temperature 0 and a fixed seed, so a response is reproducible and cacheable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, runtime_checkable

from aml.common.config import Settings
from aml.common.db import ServiceUnavailableError

TEMPERATURE = 0
CONTEXT_MARKERS = ("exceed_context_size_error", "exceeds the context length")


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(RuntimeError):
    """The model call failed for a reason the caller can report."""


class OllamaUnavailableError(ServiceUnavailableError):
    """Ollama cannot be reached; lets the CLI tell it apart from a Neo4j outage."""


@runtime_checkable
class LLMClient(Protocol):
    chat_model: str
    embed_model: str
    seed: int
    num_ctx: int

    def chat(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str: ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


Transport = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class _HttpStatus(Exception):
    """Internal: the default transport got a non-2xx answer."""

    def __init__(self, code: int, body: str) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code
        self.body = body


def _check_texts(texts: Sequence[str]) -> None:
    if any(not t.strip() for t in texts):
        raise LLMError("cannot embed an empty text")


# ------------------------------------------------------------------ Ollama
class OllamaClient:
    def __init__(
        self,
        host: str,
        chat_model: str,
        embed_model: str,
        *,
        seed: int,
        num_ctx: int = 4096,
        timeout: float = 300.0,
        keep_alive_chat: str = "5m",
        keep_alive_embed: str = "5m",
        batch_size: int = 16,
        transport: Transport | None = None,
    ) -> None:
        self.host = host
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.seed = seed
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.keep_alive_chat = keep_alive_chat
        self.keep_alive_embed = keep_alive_embed
        self.batch_size = batch_size
        self._transport: Transport = transport or self._http_post

    def chat(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str:
        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "stream": False,
            "truncate": False,  # reject over-long prompts instead of cutting them silently
            "options": {"temperature": TEMPERATURE, "seed": self.seed, "num_ctx": self.num_ctx},
            "keep_alive": self.keep_alive_chat,
        }
        if json_schema is not None:
            body["format"] = json_schema
        response = self._call("/api/chat", body, self.chat_model)
        message = response.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, str):
            raise LLMError("unexpected Ollama response: no message content")
        if json_schema is not None:
            try:
                json.loads(content)
            except ValueError as exc:
                raise LLMError(f"model reply is not valid JSON: {exc}") from exc
        return content

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        _check_texts(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            body = {
                "model": self.embed_model,
                "input": batch,
                "truncate": False,
                "keep_alive": self.keep_alive_embed,
            }
            embeddings = self._call("/api/embed", body, self.embed_model).get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise LLMError("unexpected Ollama response: wrong number of embeddings")
            vectors.extend([float(x) for x in v] for v in embeddings)
        if len({len(v) for v in vectors}) > 1:
            raise LLMError("unexpected Ollama response: embeddings differ in length")
        return vectors

    def _call(self, path: str, body: Mapping[str, Any], model: str) -> Mapping[str, Any]:
        try:
            return self._transport(path, body)
        except _HttpStatus as err:
            raise _http_error(err, model) from None

    def _http_post(self, path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        request = urllib.request.Request(
            self.host.rstrip("/") + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise _HttpStatus(err.code, err.read().decode("utf-8", errors="replace")) from None
        except (urllib.error.URLError, OSError) as err:
            raise OllamaUnavailableError(f"cannot reach Ollama at {self.host}: {err}") from err
        except ValueError as err:
            raise LLMError(f"unexpected Ollama response: not JSON ({err})") from err
        if not isinstance(payload, dict):
            raise LLMError("unexpected Ollama response: not a JSON object")
        return payload


def _http_error(err: _HttpStatus, model: str) -> LLMError:
    if err.code == 404:
        return LLMError(f"model '{model}' is not available on Ollama: run `ollama pull {model}`")
    if err.code == 400 and any(marker in err.body for marker in CONTEXT_MARKERS):
        return LLMError(f"prompt exceeds the context window: {_ollama_message(err.body)}")
    return LLMError(f"Ollama returned HTTP {err.code}: {_ollama_message(err.body)}")


def _ollama_message(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"]
    return body.strip()


# ------------------------------------------------------------------ fake
def fake_embedding(text: str, dim: int) -> list[float]:
    """Bag-of-words hash embedding: texts sharing words have a high cosine."""
    vector = [0.0] * dim
    for token in re.findall(r"\w+", text.casefold()):
        slot = int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big") % dim
        vector[slot] += 1.0
    norm = sum(x * x for x in vector) ** 0.5
    if norm == 0:
        vector[0] = 1.0
        return vector
    return [x / norm for x in vector]


class FakeLLM:
    """Deterministic stand-in: no network, no clock, no randomness."""

    def __init__(
        self,
        *,
        dim: int = 1024,
        replies: Sequence[str] | None = None,
        responder: Callable[[Sequence[ChatMessage], Mapping[str, Any] | None], str] | None = None,
        chat_model: str = "fake-chat",
        embed_model: str = "fake-embed",
        seed: int = 0,
        num_ctx: int = 4096,
    ) -> None:
        self.dim = dim
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.seed = seed
        self.num_ctx = num_ctx
        self._replies = list(replies) if replies is not None else None
        self._responder = responder
        self.calls: list[dict[str, Any]] = []

    def chat(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str:
        self.calls.append({"kind": "chat", "messages": list(messages), "json_schema": json_schema})
        if self._responder is not None:
            return self._responder(messages, json_schema)
        if self._replies is not None:
            if not self._replies:
                raise LLMError("no scripted reply left")
            return self._replies.pop(0)
        if json_schema is not None:
            return "{}"
        canonical = json.dumps(
            list(messages), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return "FAKE-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        _check_texts(texts)
        if not texts:
            return []
        self.calls.append({"kind": "embed", "texts": list(texts)})
        return [fake_embedding(t, self.dim) for t in texts]


# ------------------------------------------------------------------ cache
def cache_key(kind: str, model: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"kind": kind, "model": model, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CachedLLM:
    """Wraps any client; one JSON file per chat call or per embedded text."""

    def __init__(self, inner: LLMClient, cache_dir: Path) -> None:
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.chat_model = inner.chat_model
        self.embed_model = inner.embed_model
        self.seed = inner.seed
        self.num_ctx = inner.num_ctx
        self.hits = 0
        self.misses = 0

    def chat(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str:
        payload = {
            "messages": [dict(m) for m in messages],
            "json_schema": dict(json_schema) if json_schema is not None else None,
            "seed": self.seed,
            "temperature": TEMPERATURE,
            "num_ctx": self.num_ctx,
        }
        key = cache_key("chat", self.chat_model, payload)
        cached = self._read("chat", key)
        if isinstance(cached, str):
            self.hits += 1
            return cached
        self.misses += 1
        reply = self.inner.chat(messages, json_schema=json_schema)
        self._write("chat", key, self.chat_model, payload, reply)
        return reply

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        keys = [cache_key("embed", self.embed_model, {"text": t}) for t in texts]
        found: dict[str, list[float]] = {}
        missing: dict[str, str] = {}  # key -> text, in first-seen order
        for key, text in zip(keys, texts, strict=True):
            cached = self._read("embed", key)
            if isinstance(cached, list):
                found[key] = cached
                self.hits += 1
            elif key not in missing:  # a repeated text is one miss, one inner call
                self.misses += 1
                missing[key] = text
        if missing:
            vectors = self.inner.embed(list(missing.values()))
            if len(vectors) != len(missing):
                raise LLMError("unexpected embed result: wrong number of vectors")
            for (key, text), vector in zip(missing.items(), vectors, strict=True):
                self._write("embed", key, self.embed_model, {"text": text}, vector)
                found[key] = vector
        return [found[k] for k in keys]

    def _path(self, kind: str, key: str) -> Path:
        return self.cache_dir / kind / f"{key}.json"

    def _read(self, kind: str, key: str) -> Any:
        try:
            entry = json.loads(self._path(kind, key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return entry.get("response") if isinstance(entry, dict) else None

    def _write(
        self, kind: str, key: str, model: str, payload: Mapping[str, Any], response: Any
    ) -> None:
        target = self._path(kind, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = {"key": key, "kind": kind, "model": model, "payload": payload, "response": response}
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(entry, handle, ensure_ascii=False)
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# ------------------------------------------------------------------ factory
def get_llm(settings: Settings, *, cached: bool | None = None) -> LLMClient:
    """Build the configured client. Opens no connection."""
    a = settings.assistant
    client: LLMClient
    if a.provider == "fake":
        client = FakeLLM(dim=a.embedding.dimensions, seed=settings.seed, num_ctx=a.num_ctx)
    else:
        client = OllamaClient(
            settings.ollama.host,
            settings.ollama.llm_model,
            settings.ollama.embed_model,
            seed=settings.seed,
            num_ctx=a.num_ctx,
            timeout=a.request_timeout_seconds,
            keep_alive_chat=a.keep_alive_chat,
            keep_alive_embed=a.keep_alive_embed,
            batch_size=a.embedding.batch_size,
        )
    if a.cache.enabled if cached is None else cached:
        return CachedLLM(client, settings.path(a.cache.dir))
    return client
