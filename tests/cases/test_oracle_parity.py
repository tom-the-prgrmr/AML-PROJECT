"""AC10 for specs/case-consolidation.md: Oracle and DuckDB give the same cases on TINY.

The Oracle schema is shared and keeps earlier runs (audit_log cannot be purged), so the
history-dependent numbers (`opened`, audit rows) are checked against what was there before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml.common.config import load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import (
    AS_OF,
    SECTIONS,
    TINY_CASE,
    approx_equal,
    enrichment,
    mod,
    none_if_nan,
    query,
    run_cases,
)


def _build(db: Database, settings: Any, parquet: Path) -> Any:
    mod("aml.datagen.load").load_parquet(db, parquet)
    mod("aml.entity_resolution.runner").run_er(db, settings, as_of=AS_OF)
    mod("aml.screening.runner").run_screening(db, settings, as_of=AS_OF)
    mod("aml.monitoring.runner").run_monitoring(db, settings, as_of=AS_OF)
    mod("aml.graph.network.runner").run_network(db, settings, as_of=AS_OF)
    mod("aml.dq.runner").run_dq(db, settings, as_of=AS_OF)
    return run_cases(db, settings, as_of=AS_OF)


def _case_set(db: Database) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT case_id, golden_customer_id, alerts, sources, status, reason FROM cases_current",
    )
    return {tuple(r) for r in df.itertuples(index=False)}


def _item_set(db: Database) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT item_key, golden_customer_id, case_id, source, rule_id, cif "
        "FROM case_alerts_current",
    )
    return {tuple(none_if_nan(v) for v in r) for r in df.itertuples(index=False)}


def _fields(run: Any) -> tuple[Any, ...]:
    return tuple(
        getattr(run, f) for f in ("items", "alerts", "active", "cases", "opened", "graph_source")
    )


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_tiny(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    schema = mod("aml.dba.schema")
    # pinned: GDS rows left on the shared Oracle by the graph tests would make `auto` pick gds
    pinned = {"AML__CASES__GRAPH_FEATURES": "networkx"}
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **pinned})
    with OracleDb(osettings) as odb:
        schema.apply_schema(odb)
        known = set(
            odb.query_df(
                "SELECT DISTINCT case_id FROM cases WHERE run_id IN (SELECT run_id FROM case_runs)"
            ).iloc[:, 0]
        )
        orun = _build(odb, osettings, tiny_parquet)
        rid = orun.run_id
        ocases = _case_set(odb)
        oitems = _item_set(odb)
        oenrich = {s: enrichment(odb, TINY_CASE, rid)[s] for s in SECTIONS}
        tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
        views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
        n_audit = int(
            odb.query_df(
                "SELECT COUNT(*) FROM audit_log WHERE module = 'cases' "
                "AND decision IN ('CASE_OPENED', 'CASE_REOPENED', 'CASE_RUN_COMPLETED') AND ("
                "(entity_type = 'case' AND JSON_VALUE(details, '$.run_id') = "
                f"'{rid}') OR (entity_type = 'case_run' AND entity_id = '{rid}'))"
            ).iloc[0, 0]
        )
        schema.apply_schema(odb)  # idempotent on a second call

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **pinned})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        drun = _build(ddb, dsettings, tiny_parquet)
        dcases = _case_set(ddb)
        ditems = _item_set(ddb)
        denrich = {s: enrichment(ddb, TINY_CASE, drun.run_id)[s] for s in SECTIONS}

    assert _fields(drun) == (74, 40, 74, 52, 52, "networkx")
    assert _fields(orun)[:4] == _fields(drun)[:4]
    assert orun.graph_source == "networkx"
    assert ocases == dcases
    # a case opens once: on a re-run of the same Oracle schema the 52 are already known
    assert orun.opened == len({c[0] for c in ocases} - known)
    assert oitems == ditems
    for section in SECTIONS:
        assert approx_equal(oenrich[section], denrich[section], 1e-9), section

    assert {"CASE_RUNS", "CASES", "CASE_ALERTS", "CASE_ENRICHMENT", "CASE_DISPOSITIONS"} <= tables
    assert {
        "CASES_CURRENT",
        "CASE_ALERTS_CURRENT",
        "CASE_ENRICHMENT_CURRENT",
        "CASE_DISPOSITIONS_CURRENT",
    } <= views
    # one row per opened case plus CASE_RUN_COMPLETED: 53 on a clean schema, 1 on a re-run
    # (CASE_UPDATED is left out: it depends on what the previous run on this schema held)
    assert n_audit == orun.opened + orun.reopened + 1
    if not known:
        assert (orun.opened, n_audit) == (52, 53)
