"""AC9 (j) for specs/assistant-retrievers.md: `aml rag retrieve` on TINY, with Neo4j offline."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.helpers import cli, count
from tests.datagen.conftest import tiny_env, tiny_parquet

from .rt_helpers import OFFLINE, mod

__all__ = ["tiny_env", "tiny_parquet"]


@pytest.fixture
def loaded(
    tiny_env: Callable[..., dict[str, str]],
    tiny_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """`tiny_env` after `aml load`, with Neo4j unreachable; returns the DuckDB path."""
    for key, value in {**tiny_env(), **OFFLINE}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    result = cli("load", "--src", str(tiny_parquet))
    assert result.exit_code == 0, result.output
    return tmp_path / "tiny.duckdb"


def _audit_rows(path: Path) -> int:
    with DuckDb(path) as db:
        return count(db, "audit_log")


def test_ac9j_rag_help_lists_retrieve(loaded: Path) -> None:
    result = cli("rag", "--help")
    assert result.exit_code == 0, result.output
    assert "retrieve" in result.stdout


def test_ac9j_errors_have_exit_codes_and_write_no_audit(loaded: Path) -> None:
    before = _audit_rows(loaded)

    vector = cli("rag", "retrieve", "Structuring là gì?", "--mode", "vector")
    assert vector.exit_code == 1, vector.output
    assert "neo4j not available" in vector.stderr
    assert "Traceback" not in vector.stderr

    hybrid = cli("rag", "retrieve", "x", "--mode", "hybrid")
    assert hybrid.exit_code == 2, hybrid.output
    assert "unknown mode" in hybrid.stderr

    empty = cli("rag", "retrieve", "")
    assert empty.exit_code == 2, empty.output
    assert "question is empty" in empty.stderr

    assert _audit_rows(loaded) == before


def test_ac9j_an_unknown_case_exits_with_1(loaded: Path) -> None:
    result = cli("rag", "retrieve", "x", "--case", "C-NOPE-20260101")
    assert result.exit_code == 1, result.output
    assert "unknown case_id" in result.stderr


def test_ac9j_a_transaction_question_prints_wrapped_evidence_without_neo4j(loaded: Path) -> None:
    """The output format of the spec: a header line, a blank line, then `render_evidence`."""
    with DuckDb(loaded) as db:
        row = db.query_df(
            "SELECT txn_id, memo FROM transactions WHERE memo IS NOT NULL AND txn_id LIKE 'T%' "
            "ORDER BY txn_id LIMIT 1"
        ).iloc[0]
    txn_id = str(row["txn_id"])
    before = _audit_rows(loaded)
    result = cli("rag", "retrieve", f"Giao dịch {txn_id} có ghi chú gì?")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].startswith("mode=graphrag routes=txn_lookup evidence=1 notes=0 seconds=")
    assert lines[1] == ""
    assert lines[2].startswith(f"[E1] Transaction {txn_id}: ")
    assert lines[3].startswith(f"cite: txn:{txn_id}")
    assert lines[4].startswith('<untrusted field="memo" ref="E1">')
    assert lines[4].endswith("</untrusted>")
    assert _audit_rows(loaded) == before + 1

    missing = cli("rag", "retrieve", "Giao dịch T9999999999 đi đâu?")
    assert missing.exit_code == 0, missing.output
    out = missing.stdout.splitlines()
    assert out[0].startswith("mode=graphrag routes=txn_lookup evidence=0 notes=1 seconds=")
    assert out[1] == "note: txn_lookup skipped: no transaction found for: T9999999999"


def test_ac9j_a_graph_error_exits_with_1_without_a_traceback(
    loaded: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review 8b: a server timeout from the case graph is a clean error, not a traceback."""
    from aml.graph.neo4j.client import QueryTimeoutError

    def slow(*args: object, **kw: object) -> None:
        raise QueryTimeoutError("query exceeded 60 s")

    monkeypatch.setattr(mod("aml.assistant.retrieve"), "case_graph", slow)
    before = _audit_rows(loaded)
    result = cli("rag", "retrieve", "Tóm tắt hoạt động", "--case", "C-CIF00000001-20260101")
    assert result.exit_code == 1, result.output
    assert "query exceeded 60 s" in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert _audit_rows(loaded) == before
