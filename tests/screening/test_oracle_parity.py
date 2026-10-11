"""AC10 for specs/screening-tiers-eval.md: Oracle and DuckDB give the same screening results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml.common.config import load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import mod
from .helpers_3b import AS_OF, EVAL_TINY, assert_eval, query

COUNTS = ("alerts", "reviews", "auto_cleared", "recorded", "candidate_pairs")


def _current(db: Database) -> list[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT cif, entry_id, matched_name, decision, reason, name_score, final_score "
        "FROM screening_current",
    )
    rows = [
        (r.cif, r.entry_id, r.matched_name, r.decision, r.reason,
         round(float(r.name_score), 2), round(float(r.final_score), 2))
        for r in df.itertuples()
    ]  # fmt: skip
    return sorted(rows)


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    load = mod("aml.datagen.load")
    runner, evaluate = mod("aml.screening.runner"), mod("aml.screening.evaluate")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle")})
    with OracleDb(osettings) as odb:
        load.load_parquet(odb, tiny_parquet)
        orun = runner.run_screening(odb, osettings, as_of=AS_OF)
        ocur = _current(odb)
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        rid = orun.run_id
        n_audit = int(
            odb.query_df(
                "SELECT COUNT(*) FROM audit_log WHERE module = 'screening' AND ("
                "(entity_type = 'screening_match' AND JSON_VALUE(details, '$.run_id') = "
                f"'{rid}') OR (entity_type = 'screening_run' AND entity_id = '{rid}'))"
            ).iloc[0, 0]
        )
        oeval = evaluate.evaluate(odb, osettings)
    assert {"SCREENING_RUNS", "SCREENING_RESULTS"} <= tables
    assert "SCREENING_CURRENT" in views
    assert n_audit == orun.recorded + 1
    assert_eval(oeval, EVAL_TINY)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb"})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        load.load_parquet(ddb, tiny_parquet)
        drun = runner.run_screening(ddb, dsettings, as_of=AS_OF)
        dcur = _current(ddb)

    for field in COUNTS:
        assert getattr(orun, field) == getattr(drun, field), field
    assert ocur == dcur
