"""AC10 for specs/assistant-knowledge.md: `aml rag build|status` without Neo4j or Ollama."""

from __future__ import annotations

from pathlib import Path

import pytest

from aml.common.config import get_settings
from aml.common.db import DuckDb
from tests.cases.helpers import cli, count, duck_settings, load_minic, run_cases

from .kn_helpers import (
    KB_A,
    OFFLINE_OLLAMA,
    OFFLINE_URI,
    k_env,
    replace_once,
    write_file,
    write_mini_k,
)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """MINI-C (after `run_cases`) in a temp DuckDB, MINI-K, fake provider, Neo4j offline."""
    db_path = tmp_path / "rag.duckdb"
    with DuckDb(db_path) as db:
        load_minic(db)
        run_cases(db, duck_settings())
    mini_k = write_mini_k(tmp_path / "kb")
    values = {
        "DB_BACKEND": "duckdb",
        "AML__DB__DUCKDB_PATH": str(db_path),
        "AML__NEO4J__URI": OFFLINE_URI,
        **k_env(mini_k, tmp_path / "cache"),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return tmp_path


def _assistant_rows(root: Path) -> int:
    with DuckDb(root / "rag.duckdb") as db:
        return count(db, "audit_log", "WHERE module = 'assistant'")


def test_ac10_rag_help_lists_both_commands(env: Path) -> None:
    result = cli("rag", "--help")
    assert result.exit_code == 0, result.output
    assert "build" in result.stdout
    assert "status" in result.stdout


def test_ac10_dry_run_counts_without_any_service(env: Path) -> None:
    result = cli("rag", "build", "--dry-run")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert (
        "dry_run documents=2 chunks=5 typologies=1 red_flags=1 procedures=1 regulations=1 "
        "relations=3 mentions=5"
    ) in lines


def test_ac10_build_without_neo4j_fails_cleanly(env: Path) -> None:
    result = cli("rag", "build")
    assert result.exit_code == 1, result.output
    assert "neo4j not available" in result.stderr
    assert "Traceback" not in result.stderr
    assert _assistant_rows(env) == 0


def test_ac10_status_without_neo4j_fails_cleanly(env: Path) -> None:
    result = cli("rag", "status")
    assert result.exit_code == 1, result.output
    assert "neo4j not available" in result.stderr


def test_ac10_build_with_ollama_down_and_cold_cache_fails_cleanly(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AML__ASSISTANT__PROVIDER", "ollama")
    monkeypatch.setenv("AML__OLLAMA__HOST", OFFLINE_OLLAMA)
    get_settings.cache_clear()
    result = cli("rag", "build")
    assert result.exit_code == 1, result.output
    assert "ollama not available" in result.stderr
    assert f"cannot reach Ollama at {OFFLINE_OLLAMA}" in result.stderr
    assert _assistant_rows(env) == 0


def test_ac10_invalid_corpus_names_the_file(env: Path) -> None:
    broken = replace_once(KB_A, "effective_date: 2026-01-01\n", "")
    write_file(env / "kb", "kb-a.md", broken)
    result = cli("rag", "build")
    assert result.exit_code == 1, result.output
    assert "kb-a.md" in result.stderr
    assert "missing metadata 'effective_date'" in result.stderr


def test_ac10_dry_run_with_full_is_a_usage_error(env: Path) -> None:
    result = cli("rag", "build", "--dry-run", "--full")
    assert result.exit_code == 2, result.output
    # a usage error raised by the command itself, not "rag/build/--dry-run does not exist"
    for missing in ("No such option", "No such command", "unexpected extra argument"):
        assert missing not in result.output, result.output
    assert "dry_run" not in result.stdout
