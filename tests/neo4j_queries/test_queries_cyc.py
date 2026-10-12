"""AC5 (cycles part) for specs/neo4j-queries.md: `run_query("cycles")` on MINI-CYC."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

import pytest

from aml.dba.edges import refresh_acct_edge_daily
from tests.network.helpers import load_cyc

from .helpers import Synced, graph_audit, mod, neo_settings, query, rows, synced_db

pytestmark = pytest.mark.neo4j

COLUMNS = ["length", "path", "step_path", "first_vnd", "last_vnd"]
BASE = [
    (3, "B1>B2>B3", "Y01>Y02>Y03", 100_000_000, 90_000_000),
    (3, "B1>B2>B3", "Y01>Y02D>Y03", 100_000_000, 90_000_000),
    (3, "B2>B3>B1", "Y11>Y12>Y13", 80_000_000, 80_000_000),
]


def _load(db: Any) -> None:
    load_cyc(db)
    refresh_acct_edge_daily(db)


@pytest.fixture(scope="module")
def synced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("nq_cyc") / "cyc.duckdb"
    with synced_db(path, _load) as env:
        yield env


def test_ac5_cycles_rows_and_order(synced: Synced) -> None:
    result = query(synced.db, synced.settings, "cycles", actor="analyst01")
    assert list(result.rows.columns) == mod("aml.graph.neo4j.queries").QUERY_COLUMNS["cycles"]
    assert rows(result, COLUMNS) == BASE
    first = result.rows.iloc[0]
    assert isinstance(first["first_ts"], datetime)
    assert first["first_ts"] == datetime(2026, 3, 1, 10, 0, 0)
    assert first["last_ts"] == datetime(2026, 3, 3, 10, 0, 0)
    assert result.n_rows == 3
    assert result.query_lines > 0
    assert result.name == "cycles"


def test_ac5_cycles_exclude_the_non_cycles(synced: Synced) -> None:
    result = query(synced.db, synced.settings, "cycles", record_audit=False)
    # wrong chronology, two hops, same owner, same second, via EXT-
    assert not any(p[0] in "DFGLM" for p in result.rows["path"])


@pytest.mark.parametrize(
    ("env", "extra_path", "length"),
    [
        ({"AML__NETWORK__CYCLES__WINDOW_HOURS": "169"}, "E1>E2>E3", 3),
        ({"AML__NETWORK__CYCLES__MIN_AMOUNT_RATIO": "0.69"}, "H1>H2>H3", 3),
        ({"AML__NETWORK__CYCLES__MIN_AMOUNT_VND": "49999000"}, "I1>I2>I3", 3),
        ({"AML__NETWORK__CYCLES__MAX_LENGTH": "6"}, "J1>J2>J3>J4>J5>J6", 6),
    ],
    ids=["window", "ratio", "min_amount", "max_length"],
)
def test_ac5_cycles_thresholds_come_from_config(
    synced: Synced, env: dict[str, str], extra_path: str, length: int
) -> None:
    result = query(synced.db, neo_settings(**env), "cycles", record_audit=False)
    assert result.n_rows == 4
    extra = result.rows[result.rows["path"] == extra_path]
    assert len(extra) == 1
    assert int(extra.iloc[0]["length"]) == length


def test_ac5_cycles_min_length_4_finds_none(synced: Synced) -> None:
    settings = neo_settings(AML__NETWORK__CYCLES__MIN_LENGTH="4")
    assert query(synced.db, settings, "cycles", record_audit=False).n_rows == 0


def test_ac5_cycles_filters_and_cutoff(synced: Synced) -> None:
    s = synced.settings
    assert query(synced.db, s, "cycles", account="B2", record_audit=False).n_rows == 3
    assert query(synced.db, s, "cycles", account="G1", record_audit=False).n_rows == 0
    early = query(synced.db, s, "cycles", as_of=date(2026, 3, 2), record_audit=False)
    assert early.n_rows == 0  # Y03 is after the cutoff


def test_ac5_cycles_audit_row(synced: Synced) -> None:
    before = len(graph_audit(synced.db))
    query(synced.db, synced.settings, "cycles", record_audit=False)
    assert len(graph_audit(synced.db)) == before

    query(synced.db, synced.settings, "cycles", actor="analyst01")
    audit = graph_audit(synced.db)
    assert len(audit) == before + 1
    row = audit.iloc[-1]
    assert row["entity_type"] == "graph_query"
    assert row["entity_id"] == "cycles"
    assert row["decision"] == "QUERIED"
    assert row["version"] == "query/v1"
    assert row["actor"] == "analyst01"
    assert row["reason"] == "cycles on the Neo4j projection: 3 row(s)"
    assert row["details"]["rows"] == 3
    assert row["details"]["name"] == "cycles"
    assert row["details"]["params"]["window_hours"] == 168


def test_ac5_max_rows_is_an_error_without_audit(synced: Synced) -> None:
    before = len(graph_audit(synced.db))
    small = neo_settings(AML__GRAPH_QUERIES__MAX_ROWS="2")
    with pytest.raises(mod("aml.graph.neo4j.queries").QueryError, match="more than 2 rows"):
        query(synced.db, small, "cycles")
    assert len(graph_audit(synced.db)) == before
