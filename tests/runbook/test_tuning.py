"""AC6-AC9 for specs/dba-runbook-tuning.md: run_tuning and the `aml tune-demo` command."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from typer.testing import CliRunner

from aml.common.config import Settings, get_settings, load_settings, read_environ
from aml.common.db import DuckDb, OracleDb
from tests.datagen.conftest import EnvFactory

from .conftest import audit_rows
from .helpers import GRANT_SCRIPT, mod

SKIP_NO_V = f"no access to V$ views: apply {GRANT_SCRIPT} as SYS (see dba/RUNBOOK.md)"


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _oracle_env(tiny_env: EnvFactory) -> dict[str, str]:
    return {**read_environ(), **tiny_env(DB_BACKEND="oracle")}


def _invoke(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, ["tune-demo", *args])


def test_ac7_run_tuning_on_duckdb_is_oracle_only(duck: DuckDb, tiny_settings: Settings) -> None:
    with pytest.raises(NotImplementedError, match="Oracle only"):
        mod("aml.dba.tuning").run_tuning(duck, tiny_settings)


def test_ac7_tune_demo_cli_on_duckdb_exits_2_without_file(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env(DB_BACKEND="duckdb"))
    out = tmp_path / "t.txt"
    result = _invoke("--out", str(out))
    assert result.exit_code == 2, result.output
    assert "Oracle only" in result.output
    assert not out.exists()


class _FakeOracle:
    """Pretends to be an Oracle Database; records every write so tests can assert none happened."""

    backend = "oracle"

    def __init__(self) -> None:
        self.writes: list[str] = []

    def __enter__(self) -> _FakeOracle:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def close(self) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.writes.append(sql)

    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        self.writes.append(table)
        return len(df)

    def query_df(self, sql: str, params: Any = None) -> pd.DataFrame:
        return pd.DataFrame({"n": [0]})

    def run_script(self, path: Path) -> int:
        self.writes.append(str(path))
        return 0


def test_ac8_tune_demo_without_v_access_exits_1_naming_grant_script(
    tiny_env: EnvFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_env(monkeypatch, tiny_env(DB_BACKEND="oracle"))
    fake = _FakeOracle()
    tuning = mod("aml.dba.tuning")
    cli = mod("aml.cli")
    monkeypatch.setattr(tuning, "has_cursor_stats_access", lambda db: False)
    monkeypatch.setattr(cli, "has_cursor_stats_access", lambda db: False, raising=False)
    monkeypatch.setattr(cli, "get_db", lambda *a, **k: fake)
    out = tmp_path / "t.txt"
    result = _invoke("--out", str(out))
    assert result.exit_code == 1, result.output
    assert GRANT_SCRIPT in result.output
    assert not out.exists()
    assert fake.writes == []  # no audit_log row (or anything else) written


def _tiny_oracle(tiny_env: EnvFactory, tiny_parquet: Path) -> tuple[Settings, OracleDb]:
    settings = load_settings(environ=_oracle_env(tiny_env))
    db = OracleDb(settings)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return settings, db


@pytest.mark.oracle
def test_ac6_run_tuning_shows_pruning_and_fewer_buffer_gets(
    tiny_env: EnvFactory, tiny_parquet: Path
) -> None:
    tuning = mod("aml.dba.tuning")  # imported outside the skip: a missing module must FAIL
    settings, db = _tiny_oracle(tiny_env, tiny_parquet)
    with db:
        if not tuning.has_cursor_stats_access(db):
            pytest.skip(SKIP_NO_V)
        results = tuning.run_tuning(db, settings, runs=3)
        steps = tuning.tuning_steps(settings)
        frames = [
            db.query_df(s.sql).sort_values("from_account_id").reset_index(drop=True) for s in steps
        ]

    assert [r.step.name for r in results] == ["before", "after"]
    before, after = results
    assert "PARTITION RANGE ALL" in before.plan
    assert "PARTITION RANGE SINGLE" in after.plan
    assert "PARTITION RANGE ALL" not in after.plan
    for r in results:
        assert "A-Rows" in r.plan and "Buffers" in r.plan
        assert len(r.elapsed_ms) == 3
        assert all(t > 0 for t in r.elapsed_ms)
    assert before.plan_hash_value != after.plan_hash_value
    assert after.buffer_gets < before.buffer_gets
    assert before.rows == after.rows >= 1
    pd.testing.assert_frame_equal(frames[0], frames[1])


def _block(text: str, name: str) -> str:
    m = re.search(rf"^== {name} ==\s*$(.*?)(?=^== |^summary:|\Z)", text, re.M | re.S)
    assert m, f"no '== {name} ==' block"
    return m.group(1)


def _single(block: str, key: str, pattern: str) -> str:
    found = re.findall(rf"^{key}: *({pattern})\s*$", block, re.M)
    assert len(found) == 1, f"expected exactly one '{key}:' line, got {found}"
    return found[0]


@pytest.mark.oracle
def test_ac9_tune_demo_writes_evidence_and_audits(
    tiny_env: EnvFactory,
    tiny_parquet: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tuning = mod("aml.dba.tuning")  # imported outside the skip: a missing module must FAIL
    settings, db = _tiny_oracle(tiny_env, tiny_parquet)
    with db:
        if not tuning.has_cursor_stats_access(db):
            pytest.skip(SKIP_NO_V)
        last_id = int(db.query_df("SELECT NVL(MAX(audit_id), 0) AS m FROM audit_log").iloc[0, 0])

    _set_env(monkeypatch, _oracle_env(tiny_env))
    out = tmp_path / "t.txt"
    result = _invoke("--out", str(out), "--runs", "3")
    assert result.exit_code == 0, result.output

    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("# aml tune-demo")
    assert re.search(r"^transactions_rows: 5100\s*$", text, re.M)
    assert re.search(r"^runs: 3\s*$", text, re.M)
    assert re.search(r"^oracle_version: \S.*$", text, re.M)
    assert len(re.findall(r"^== (?:before|after) ==\s*$", text, re.M)) == 2

    hashes: dict[str, int] = {}
    gets: dict[str, str] = {}
    medians: dict[str, str] = {}
    for name in ("before", "after"):
        block = _block(text, name)
        assert "SELECT" in block.upper()
        hashes[name] = int(_single(block, "plan_hash_value", r"\d+"))
        gets[name] = _single(block, "buffer_gets", r"\d+")
        times = _single(block, "elapsed_ms", r"[^\n]*?\d[^\n]*").replace(",", " ").split()
        assert len(times) == 3 and all(float(t) > 0 for t in times)
        medians[name] = _single(block, "elapsed_ms_median", r"[\d.]+")
        _single(block, "rows", r"\d+")
        assert "A-Rows" in block

    assert lines[-1].strip() == (
        f"summary: buffer_gets {gets['before']} -> {gets['after']}, "
        f"elapsed_ms_median {medians['before']} -> {medians['after']}"
    )

    with OracleDb(settings) as db2:
        rows = audit_rows(
            db2,
            f"audit_id > {last_id} AND module = 'dba' AND entity_type = 'query' "
            "AND entity_id = 'outflow_30d' AND decision = 'TUNING_CAPTURED'",
        )
    assert len(rows) == 1
    details = rows.iloc[0]["details"]
    assert details["path"] == str(out)
    assert int(details["before"]["plan_hash_value"]) == hashes["before"]
    assert int(details["after"]["plan_hash_value"]) == hashes["after"]
