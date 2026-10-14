"""Helpers for the Phase 8a tests (specs/assistant-knowledge.md): MINI-K, settings, module access.

Product modules are imported lazily (``mod``) so that a missing module fails the test that needs
it, not the collection of the whole suite.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from aml.common.config import Settings
from aml.common.db import Database
from tests.cases.helpers import duck_settings
from tests.neo4j_sync.helpers import neo_settings

__all__ = ["duck_settings", "neo_settings"]

OFFLINE_URI = "bolt://127.0.0.1:1"
OFFLINE_OLLAMA = "http://127.0.0.1:1"
USER_MSG = [{"role": "user", "content": "u"}]


def mod(name: str) -> Any:
    return importlib.import_module(name)


def llm() -> Any:
    return mod("aml.assistant.llm")


def kmodel() -> Any:
    return mod("aml.assistant.knowledge.model")


def kdocs() -> Any:
    return mod("aml.assistant.knowledge.docs")


def kmatches() -> Any:
    return mod("aml.assistant.knowledge.matches")


def kbuild() -> Any:
    return mod("aml.assistant.knowledge.build")


# ---------------------------------------------------------------- MINI-K
KB_A = """---
doc_number: KB-TYP-901
title: Structuring thử nghiệm
doc_type: TYPOLOGY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Typology, id: structuring, name: Chia nhỏ giao dịch}
  - {label: RedFlag, id: RF-901, name: Nộp tiền mặt sát ngưỡng}
relations:
  - {from: structuring, type: HAS_RED_FLAG, to: RF-901}
  - {from: structuring, type: INVESTIGATED_BY, to: PROC-901}
---
# Structuring thử nghiệm

Đoạn mở đầu.

## Mô tả {structuring}

Khách hàng chia nhỏ tiền mặt.

## Dấu hiệu {RF-901 structuring}

Nộp tiền nhiều lần dưới ngưỡng.
"""

KB_B = """---
doc_number: KB-SOP-901
title: SOP thử nghiệm
doc_type: SOP
version: "2.1"
effective_date: 2026-02-01
language: vi
defines:
  - {label: Procedure, id: PROC-901, name: Xác minh nguồn tiền}
  - {label: Regulation, id: REG-901, name: Quy định thử nghiệm}
relations:
  - {from: PROC-901, type: REQUIRED_BY, to: REG-901}
---
# SOP thử nghiệm

## Bước 1 {PROC-901}

Yêu cầu chứng từ nguồn tiền.

## Căn cứ {REG-901}

Theo quy định nội bộ.
"""

KB_C = """---
doc_number: KB-RFC-901
title: Checklist thử nghiệm
doc_type: CHECKLIST
version: "1.0"
effective_date: 2026-01-01
language: vi
---
## Kiểm tra {RF-901}

Đối chiếu sao kê.
"""


def write_file(directory: Path, name: str, text: str) -> Path:
    """Write UTF-8 with LF line endings on every platform (the sha256 is over the bytes)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(text.encode("utf-8"))
    return path


def write_mini_k(directory: Path, *, with_c: bool = False) -> Path:
    write_file(directory, "kb-a.md", KB_A)
    write_file(directory, "kb-b.md", KB_B)
    if with_c:
        write_file(directory, "kb-c.md", KB_C)
    return directory


def replace_once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, (old, text.count(old))
    return text.replace(old, new)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def k_env(mini_k: Path, cache: Path, **extra: str) -> dict[str, str]:
    return {
        "AML__ASSISTANT__KNOWLEDGE__DIR": str(mini_k),
        "AML__ASSISTANT__EMBEDDING__DIMENSIONS": "64",
        "AML__ASSISTANT__CACHE__DIR": str(cache),
        "AML__ASSISTANT__PROVIDER": "fake",
        **extra,
    }


def k_settings(mini_k: Path, cache: Path, **extra: str) -> Settings:
    """``k_settings`` of the spec (DuckDB, fake provider, 64 dimensions)."""
    return duck_settings(**k_env(mini_k, cache, **extra))


def k_neo_settings(mini_k: Path, cache: Path, **extra: str) -> Settings:
    """Same, plus the credentials from ``.env`` so that a real Neo4j can be reached."""
    return neo_settings(**k_env(mini_k, cache, **extra))


# ---------------------------------------------------------------- audit rows
def assistant_audit(db: Database) -> list[dict[str, Any]]:
    df = db.query_df(
        "SELECT entity_type, entity_id, decision, reason, version, details "
        "FROM audit_log WHERE module = 'assistant' ORDER BY audit_id"
    )
    df.columns = [c.lower() for c in df.columns]
    rows = df.to_dict("records")
    for row in rows:
        if isinstance(row["details"], str):
            row["details"] = json.loads(row["details"])
    return rows


def files_in(directory: Path) -> list[Path]:
    return sorted(directory.iterdir()) if directory.exists() else []


# ---------------------------------------------------------------- a local Ollama look-alike
@contextmanager
def serve(status: int, body: Mapping[str, Any] | str) -> Iterator[str]:
    """A local HTTP server answering every POST with ``status`` and ``body`` (JSON or text)."""
    payload = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


Recorder = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


def recording_transport(
    chat: Mapping[str, Any] | None = None, vector: list[float] | None = None
) -> tuple[Recorder, list[tuple[str, Mapping[str, Any]]]]:
    """A transport that records (path, body) and answers like the spec's ``t`` of AC3."""
    seen: list[tuple[str, Mapping[str, Any]]] = []
    answer = chat if chat is not None else {"message": {"content": "xin chào"}}
    vec = vector if vector is not None else [0.1, 0.2]

    def transport(path: str, body: Mapping[str, Any]) -> Mapping[str, Any]:
        seen.append((path, body))
        if path == "/api/chat":
            return answer
        return {"embeddings": [vec] * len(body["input"])}

    return transport, seen
