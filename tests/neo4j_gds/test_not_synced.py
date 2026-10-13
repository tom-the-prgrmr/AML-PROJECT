"""AC3 (refusal part) for specs/neo4j-gds.md: a graph that was never synced is refused."""

from __future__ import annotations

import pytest

from aml.common.db import DuckDb

from .conftest import Neo
from .helpers import load_mini_g, mod, run_gds, scalar

pytestmark = pytest.mark.neo4j


def test_ac3_wiped_graph_is_refused_and_nothing_is_written(duck: DuckDb, neo: Neo) -> None:
    load_mini_g(duck)
    mod("aml.dba.schema").apply_schema(duck)
    with pytest.raises(mod("aml.graph.neo4j.gds").GdsError, match="graph not synced"):
        run_gds(duck, neo.settings)
    assert int(scalar(duck, "SELECT COUNT(*) FROM gds_runs")) == 0
    assert int(scalar(duck, "SELECT COUNT(*) FROM gds_account_features")) == 0
    assert (
        int(scalar(duck, "SELECT COUNT(*) FROM audit_log WHERE decision = 'GDS_FEATURES_WRITTEN'"))
        == 0
    )
