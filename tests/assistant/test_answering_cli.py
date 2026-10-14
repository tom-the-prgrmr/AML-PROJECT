"""AC9 for specs/assistant-answering.md: `aml rag ask|narrative|explain` on MINI-N with fakes."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from aml.assistant.evidence import RetrievalError, RetrievalUnavailableError
from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.helpers import cli, count

from .an_helpers import (
    CASE,
    J_NONE,
    K3,
    LLM,
    N_OK,
    NOPE,
    QUESTION,
    R4,
    S_OK1,
    FakeKnowledge,
    FakeRetriever,
    J,
    answering,
    mini_n,
    narrative,
)

Setup = Callable[..., FakeRetriever]


@pytest.fixture
def mini_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """MINI-N written to a file that the CLI uses as its configured DuckDB."""
    path = tmp_path / "mini.duckdb"
    with DuckDb(path) as db:
        mini_n(db)
    monkeypatch.setenv("DB_BACKEND", "duckdb")
    monkeypatch.setenv("AML__DB__DUCKDB_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def fakes(mini_db: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    """``fakes(*replies, retriever=..., knowledge=...)`` installs the defaults of the assistant."""

    def install(
        *replies: str, retriever: FakeRetriever | None = None, knowledge: Any = None
    ) -> FakeRetriever:
        r = retriever or R4()
        fake = LLM(*replies)
        monkeypatch.setattr(answering(), "default_llm", lambda settings: fake)
        monkeypatch.setattr(answering(), "default_retriever", lambda settings: r)
        k = knowledge or K3()
        monkeypatch.setattr(narrative(), "default_knowledge", lambda settings: k)
        return r

    return install


def _dispositions(path: Path) -> int:
    with DuckDb(path) as db:
        return count(db, "case_dispositions")


def test_ac9_ask(fakes: Setup, mini_db: Path) -> None:
    before = _dispositions(mini_db)
    fakes(J(S_OK1))
    result = cli("rag", "ask", QUESTION, "--case", CASE)
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "Tài khoản A01 nhận 390,000,000 VND tiền mặt vào ngày 2026-03-02. [1]",
        "",
        "Nguồn:",
        "[1] transaction T01",
    ]
    assert "status=answered supported=1 unsupported=0" in result.stderr

    fakes(J(S_OK1))
    en = cli("rag", "ask", QUESTION, "--case", CASE, "--lang", "en")
    assert en.exit_code == 0, en.output
    assert "Sources:" in en.stdout.splitlines()

    fakes(J(S_OK1))
    as_json = cli("rag", "ask", QUESTION, "--case", CASE, "--json")
    assert as_json.exit_code == 0, as_json.output
    d = json.loads(as_json.stdout)
    assert d["status"] == "answered"
    assert len(d) == 11

    fakes(J_NONE)
    refused = cli("rag", "ask", QUESTION, "--case", CASE)
    assert refused.exit_code == 0, refused.output
    assert refused.stdout.splitlines() == ["Không đủ bằng chứng."]

    r = fakes(J(S_OK1))
    vector = cli("rag", "ask", QUESTION, "--case", CASE, "--mode", "vector")
    assert vector.exit_code == 0, vector.output
    assert r.calls[0][1]["mode"] == "vector"

    fakes(J(S_OK1))
    assert cli("rag", "ask", QUESTION, "--lang", "fr").exit_code == 2

    fakes()
    nope = cli("rag", "ask", QUESTION, "--case", NOPE)
    assert nope.exit_code == 0, nope.output
    assert nope.stdout.splitlines() == ["Không đủ bằng chứng."]
    assert "status=insufficient_evidence" in nope.stderr
    assert "refusal=unknown_case" in nope.stderr
    assert _dispositions(mini_db) == before


def test_ac9_ask_errors(fakes: Setup) -> None:
    fakes("xin lỗi", "xin lỗi")
    broken = cli("rag", "ask", QUESTION, "--case", CASE)
    assert broken.exit_code == 1, broken.output
    assert "model output is not valid JSON" in broken.stderr

    bad = RetrievalError("unknown mode 'xyz'; choose one of: graphrag, vector")
    fakes(retriever=FakeRetriever(error=bad))
    mode = cli("rag", "ask", QUESTION, "--mode", "xyz")
    assert mode.exit_code == 2, mode.output
    assert "unknown mode" in mode.stderr

    down = RetrievalUnavailableError("neo4j not available: down")
    fakes(retriever=FakeRetriever(error=down))
    off = cli("rag", "ask", QUESTION)
    assert off.exit_code == 1, off.output
    assert "neo4j not available" in off.stderr


def test_ac9_narrative(fakes: Setup, tmp_path: Path, mini_db: Path) -> None:
    before = _dispositions(mini_db)
    fakes()
    for command in ("narrative", "explain"):
        unknown = cli("rag", command, NOPE)
        assert unknown.exit_code == 1, unknown.output
        assert "unknown case_id" in unknown.stderr

    fakes(N_OK)
    printed = cli("rag", "narrative", CASE)
    assert printed.exit_code == 0, printed.output
    lines = printed.stdout.splitlines()
    assert lines[0] == f"# Case {CASE}"
    assert "> DRAFT — requires investigator review" in lines

    fakes(N_OK)
    target = tmp_path / "n.md"
    written = cli("rag", "narrative", CASE, "--out", str(target))
    assert written.exit_code == 0, written.output
    assert "wrote" in written.stdout
    assert target.read_text(encoding="utf-8") == printed.stdout
    assert _dispositions(mini_db) == before


def test_ac9_explain(fakes: Setup, mini_db: Path) -> None:
    before = _dispositions(mini_db)
    fakes()
    result = cli("rag", "explain", CASE)
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    for line in (
        f"case={CASE} typologies=3 knowledge=ok",
        "typology=structuring rules=STRUCTURING transactions=1 chunks=1",
        "  definition: STRUCTURING v1: Repeated cash deposits just under the large-cash "
        "reporting threshold",
        "  T01 2026-03-02 09:00:00 - -> A01 390000000 CASH",
        "  T06 2026-04-20 12:00:00 A02 -> EXT-02 480000000 EBANKING",
        "  chunk KB-TYP-001#003",
    ):
        assert line in lines, line

    smurf = cli("rag", "explain", CASE, "--typology", "smurfing")
    assert smurf.exit_code == 2, smurf.output
    assert "unknown typology" in smurf.stderr

    down = FakeKnowledge(error=RetrievalUnavailableError("neo4j not available: down"))
    fakes(knowledge=down)
    offline = cli("rag", "explain", CASE)
    assert offline.exit_code == 0, offline.output
    assert offline.stdout.splitlines()[0] == f"case={CASE} typologies=3 knowledge=unavailable"
    assert _dispositions(mini_db) == before


def test_ac9_no_write_commands(mini_db: Path) -> None:
    import typer.main

    from aml.cli import app

    result = cli("rag", "--help")
    assert result.exit_code == 0, result.output
    group: Any = typer.main.get_command(app)
    names = set(group.commands["rag"].commands)
    assert {"ask", "narrative", "explain"} <= names
    for name in ("dispose", "close", "clear", "file"):
        assert name not in names, name
