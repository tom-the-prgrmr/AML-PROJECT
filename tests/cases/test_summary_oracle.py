"""AC6 for specs/case-summary.md: Oracle and DuckDB write the same summary on TINY.

The Oracle schema is shared and keeps its history (case runs, audit rows), so nothing
history-dependent is pinned. The only run-dependent text of a summary is its footer (`case run N`):
it is checked against the run id that `run_cases` returned, and the rest of the markdown is
compared character by character. `AML__CASES__GRAPH_FEATURES=networkx` keeps GDS rows that other
tests left on the Oracle schema out of the comparison. The test writes no disposition, good-guy row
or model, so there is nothing to clean up: the only rows it adds are one more case run and its audit
rows, which every Oracle test of `tests/cases` adds too.

`apply_security` is not called: `customers_masked` is created by `apply_schema` on Oracle (script
050_security_objects.sql), which `run_cases` and the loader need anyway.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb

from .helpers import AS_OF, mod, run_cases
from .summary_helpers import PINNED, WATERMARK, strip_footer, summarize

CASES = ("C-CIF00000189-20260413", "C-CIF00000104-20260416", "C-CIF00000041-20260630")


def _build(db: Database, settings: Settings, parquet: Path) -> Any:
    mod("aml.datagen.load").load_parquet(db, parquet)
    mod("aml.entity_resolution.runner").run_er(db, settings, as_of=AS_OF)
    mod("aml.screening.runner").run_screening(db, settings, as_of=AS_OF)
    mod("aml.monitoring.runner").run_monitoring(db, settings, as_of=AS_OF)
    mod("aml.graph.network.runner").run_network(db, settings, as_of=AS_OF)
    mod("aml.dq.runner").run_dq(db, settings, as_of=AS_OF)
    return run_cases(db, settings, as_of=AS_OF)


def _summaries(db: Database, settings: Settings) -> dict[str, Any]:
    return {case_id: summarize(db, settings, case_id) for case_id in CASES}


@pytest.mark.oracle
def test_ac6_oracle_and_duckdb_write_the_same_summary(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    schema = mod("aml.dba.schema")
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **PINNED})
    with OracleDb(osettings) as odb:
        schema.apply_schema(odb)
        orun = _build(odb, osettings, tiny_parquet)
        oracle = _summaries(odb, osettings)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **PINNED})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        drun = _build(ddb, dsettings, tiny_parquet)
        duck = _summaries(ddb, dsettings)

    for case_id in CASES:
        o, d = oracle[case_id], duck[case_id]
        assert d.markdown.splitlines()[0] == f"# Case {case_id}"  # not an empty comparison
        assert d.citations, case_id
        assert strip_footer(o.markdown) == strip_footer(d.markdown), case_id
        assert o.citations == d.citations, case_id
        assert WATERMARK in o.markdown, case_id
        assert o.markdown.splitlines()[-1] == (
            f"Template summary/v1; case run {orun.run_id}; no LLM was used."
        )
        assert d.markdown.splitlines()[-1] == (
            f"Template summary/v1; case run {drun.run_id}; no LLM was used."
        )
    top = duck[CASES[0]].markdown.splitlines()
    assert any(ln.startswith("- Alerts: 5 (3 RULE, 2 NETWORK, 0 SCREENING)") for ln in top)
