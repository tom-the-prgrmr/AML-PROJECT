"""AC3 for specs/neo4j-queries.md: `trace(method="neo4j")` on MINI-T against a real Neo4j."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pandas as pd
import pytest

from tests.graph.helpers import AC2_ROWS, PATH_COLUMNS, rows_of

from .helpers import (
    MINI_T_S11,
    Synced,
    graph_audit,
    load_mini_t,
    mod,
    neo_settings,
    synced_db,
    trace,
)

pytestmark = pytest.mark.neo4j

# (kwargs of trace for account "A" unless "account" is given, expected rows). The spec leaves
# `hours` open for hops=1; the base case of the spec uses 24.
CASES: list[tuple[str, dict[str, Any], int]] = [
    ("A", {"hops": 4, "hours": 24}, 9),
    ("A", {"hops": 4, "hours": 25}, 10),
    ("A", {"hops": 2, "hours": 24}, 3),
    ("A", {"hops": 1, "hours": 24}, 2),
    ("A", {"hops": 6, "hours": 24}, 9),
    ("A", {"hops": 4, "hours": 24, "since": datetime(2026, 3, 1, 10, 0, 0)}, 8),
    ("A", {"hops": 4, "hours": 24, "since": datetime(2026, 3, 1, 10, 0, 1)}, 0),
    ("ZZZ", {"hops": 3, "hours": 24}, 0),
    ("C", {"hops": 3, "hours": 24}, 7),
    ("EXT-000001", {"hops": 2, "hours": 24}, 1),
]


@pytest.fixture(scope="module")
def synced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("nq_trace_mini") / "mini_t.duckdb"
    with synced_db(path, load_mini_t, expect_graph=MINI_T_S11) as env:
        yield env


def _both(env: Synced, account: str, **kw: Any) -> tuple[Any, Any]:
    neo = trace(env.db, env.settings, account, method="neo4j", record_audit=False, **kw)
    raw = trace(env.db, env.settings, account, method="cte_raw", record_audit=False, **kw)
    return neo, raw


def test_ac3_neo4j_trace_rows_and_summary(synced: Synced) -> None:
    result = trace(
        synced.db, synced.settings, "A", method="neo4j", hops=4, hours=24, actor="analyst01"
    )
    paths = result.paths
    assert list(paths.columns) == PATH_COLUMNS
    assert rows_of(paths) == AC2_ROWS
    last = paths[paths["path"] == "A>B>C>D>F"].iloc[0]
    assert pd.Timestamp(last["first_ts"]) == pd.Timestamp("2026-03-01 10:00:00")
    assert pd.Timestamp(last["last_ts"]) == pd.Timestamp("2026-03-02 10:00:00")
    assert result.n_paths == 9
    assert result.n_cycles == 3
    assert result.n_accounts == 6
    assert result.method == "neo4j"
    assert result.backend == "duckdb"
    assert result.query_lines > 0


@pytest.mark.parametrize(("account", "kw", "expected"), CASES, ids=[str(i) for i in range(10)])
def test_ac3_neo4j_equals_cte_raw(
    synced: Synced, account: str, kw: dict[str, Any], expected: int
) -> None:
    neo, raw = _both(synced, account, **kw)
    assert neo.n_paths == expected
    assert list(neo.paths.columns) == PATH_COLUMNS
    pd.testing.assert_frame_equal(neo.paths, raw.paths)


def test_ac3_audit_row_and_record_audit_false(synced: Synced) -> None:
    before = len(graph_audit(synced.db))
    trace(synced.db, synced.settings, "A", method="neo4j", hops=4, hours=24, record_audit=False)
    assert len(graph_audit(synced.db)) == before

    trace(synced.db, synced.settings, "A", method="neo4j", hops=4, hours=24, actor="analyst01")
    audit = graph_audit(synced.db)
    assert len(audit) == before + 1
    row = audit.iloc[-1]
    assert row["decision"] == "TRACED"
    assert row["version"] == "trace/neo4j"
    assert row["entity_id"] == "A"
    assert row["actor"] == "analyst01"
    assert row["details"]["method"] == "neo4j"
    assert row["details"]["backend"] == "duckdb"
    assert row["details"]["paths"] == 9
    assert row["details"]["cycles"] == 3


def test_ac3_max_paths_is_an_error(synced: Synced) -> None:
    small = neo_settings(AML__TRACE__MAX_PATHS="8")
    with pytest.raises(mod("aml.graph.model").TraceError, match="more than 8 paths"):
        trace(synced.db, small, "A", method="neo4j", hops=4, hours=24)


def test_ac3_seconds_exclude_the_connection_and_freshness_check(synced: Synced) -> None:
    """`prepare` runs before the clock starts (Q6): it is called once per trace, not timed."""
    calls: list[str] = []
    neo = mod("aml.graph.trace").METHODS["neo4j"]
    assert neo.prepare is not None
    original = neo.prepare

    def spy(db: Any, settings: Any) -> None:
        calls.append("prepare")
        original(db, settings)

    patched = type(neo)(
        name=neo.name,
        backends=neo.backends,
        exact=neo.exact,
        run=lambda db, s, r: (calls.append("run"), neo.run(db, s, r))[1],
        query_text=neo.query_text,
        uses_filters=neo.uses_filters,
        prepare=spy,
    )
    methods = mod("aml.graph.trace").METHODS
    methods["neo4j"] = patched
    try:
        trace(synced.db, synced.settings, "A", method="neo4j", hops=2, hours=24, record_audit=False)
    finally:
        methods["neo4j"] = neo
    assert calls == ["prepare", "run"]
