"""Review follow-ups for specs/neo4j-gds.md (no service needed): backtick quoting cannot get a
name past the guard, and a half-written GDS run never blocks the next one."""

from __future__ import annotations

import pandas as pd
import pytest

from aml.common.config import load_settings
from aml.common.db import DuckDb
from aml.dba.schema import apply_schema
from aml.graph.neo4j.features import GDS_FEATURE_COLUMNS
from aml.graph.neo4j.gds_record import next_run_id
from aml.graph.neo4j.guard import WriteBlockedError, assert_read_only

SETTINGS = load_settings(environ={})
READ = SETTINGS.neo4j.read_procedures
GDS = SETTINGS.gds.procedures

PROJECT_AS_FUNCTION = (
    "MATCH (a:Account)-[:SENT_TO]->(b:Account) "
    "WITH {name}('g', a, b) AS g RETURN g.graphName, g.nodeCount"
)


@pytest.mark.parametrize(
    "name",
    [
        "gds.`graph`.project",
        "`gds`.`graph`.`project`",
        "gds.graph.`project`",
        "`gds`.graph.project",
    ],
)
def test_backticks_do_not_hide_gds_graph_project(name: str) -> None:
    query = PROJECT_AS_FUNCTION.format(name=name)
    with pytest.raises(WriteBlockedError, match=r"procedure gds\.graph\.project is not allowed"):
        assert_read_only(query, allowed_procedures=READ)
    assert_read_only(query, allowed_procedures=GDS)  # the GDS path itself may project


@pytest.mark.parametrize(
    "query",
    [
        "CALL `gds.graph.project`('g', 'Account', 'SENT_TO')",
        "CALL `apoc.cypher.doIt`('CREATE (n)', {})",
        "CALL `db`.labels()",
    ],
)
def test_a_quoted_procedure_name_is_refused_not_read_as_a_subquery(query: str) -> None:
    with pytest.raises(WriteBlockedError, match="procedure"):
        assert_read_only(query, allowed_procedures=[*READ, *GDS])


def test_backtick_labels_and_scoped_subqueries_still_pass() -> None:
    assert_read_only("MATCH (n:`CREATE`) RETURN count(n)", allowed_procedures=READ)
    assert_read_only(
        "MATCH (a:Account) CALL (a) { MATCH (a)<-[:OWNS]-(c) RETURN count(c) AS n } RETURN n",
        allowed_procedures=READ,
    )


def test_next_run_id_skips_a_half_written_run(duck: DuckDb) -> None:
    apply_schema(duck)
    assert next_run_id(duck) == 1
    orphan = {column: [0] for column in GDS_FEATURE_COLUMNS}
    orphan.update(run_id=[3], account_id=["A1"], wcc_id=[None], louvain_id=[None])
    orphan["shared_cluster_id"] = [None]
    duck.insert_df("gds_account_features", pd.DataFrame(orphan))
    assert next_run_id(duck) == 4
