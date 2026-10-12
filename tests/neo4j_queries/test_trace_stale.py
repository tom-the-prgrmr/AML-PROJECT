"""AC3 (stale graph part) for specs/neo4j-queries.md: refusal when Neo4j lags the source."""

from __future__ import annotations

import pandas as pd
import pytest

from aml.common.db import DuckDb
from aml.dba.edges import refresh_acct_edge_daily
from tests.network.helpers import add_txns

from .conftest import Neo
from .helpers import MINI_T_S11, mod, run_sync, trace

pytestmark = pytest.mark.neo4j


def test_ac3_unsynced_graph_is_refused(mini_t: DuckDb, neo: Neo) -> None:
    unavailable = mod("aml.graph.model").TraceUnavailableError
    with pytest.raises(unavailable, match="graph not synced"):
        trace(mini_t, neo.settings, "A", method="neo4j")


def test_ac3_out_of_sync_graph_is_refused_until_synced(mini_t: DuckDb, neo: Neo) -> None:
    unavailable = mod("aml.graph.model").TraceUnavailableError
    assert run_sync(mini_t, neo.settings, full=True).graph == MINI_T_S11

    add_txns(mini_t, [("M15", "2026-03-03 09:00:00", "K", "A", 1_000_000)])
    refresh_acct_edge_daily(mini_t)

    kw = {"hops": 4, "hours": 24, "record_audit": False}
    with pytest.raises(unavailable, match=r"graph is out of sync \(12 of 13 transfers\)"):
        trace(mini_t, neo.settings, "A", method="neo4j", **kw)
    raw = trace(mini_t, neo.settings, "A", method="cte_raw", **kw)  # SQL methods are unaffected

    run_sync(mini_t, neo.settings)
    again = trace(mini_t, neo.settings, "A", method="neo4j", **kw)
    pd.testing.assert_frame_equal(again.paths, raw.paths)
