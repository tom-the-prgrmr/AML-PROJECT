"""AC5 (fan-in / fan-out and timeout part) for specs/neo4j-queries.md: MINI-HUB."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pandas as pd
import pytest

from aml.dba.edges import refresh_acct_edge_daily
from tests.network.helpers import load_hub

from .helpers import Synced, client, mod, neo_settings, query, rows, synced_db

pytestmark = pytest.mark.neo4j

COLUMNS = ["account_id", "counterparties", "transfers", "total_vnd"]
BASE = [
    ("P0", 11, 12, 720_000_000),
    ("W0", 10, 10, 200_000_000),
    ("L0", 9, 9, 180_000_000),
    ("R0", 9, 9, 180_000_000),
]


def _load(db: object) -> None:
    load_hub(db)  # type: ignore[arg-type]
    refresh_acct_edge_daily(db)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def synced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("nq_hub") / "hub.duckdb"
    with synced_db(path, _load) as env:
        yield env


def test_ac5_fan_in_rows_and_window(synced: Synced) -> None:
    result = query(synced.db, synced.settings, "fan_in")
    assert list(result.rows.columns) == mod("aml.graph.neo4j.queries").QUERY_COLUMNS["fan_in"]
    assert rows(result, COLUMNS) == BASE
    p0 = result.rows.iloc[0]
    assert pd.Timestamp(p0["window_start"]) == pd.Timestamp("2026-03-01 01:00:00")
    assert pd.Timestamp(p0["window_end"]) == pd.Timestamp("2026-03-01 13:00:00")


def test_ac5_fan_in_total_amount_floor_comes_from_config(synced: Synced) -> None:
    assert "Q0" not in set(query(synced.db, synced.settings, "fan_in").rows["account_id"])
    settings = neo_settings(AML__MONITORING__FAN_IN_OUT__MIN_TOTAL_VND="0")
    got = rows(query(synced.db, settings, "fan_in", record_audit=False), COLUMNS)
    assert ("Q0", 10, 10, 99_990_000) in got
    assert set(BASE) <= set(got)


def test_ac5_fan_in_counterparty_floor_comes_from_config(synced: Synced) -> None:
    settings = neo_settings(AML__MONITORING__FAN_IN_OUT__MIN_COUNTERPARTIES="10")
    result = query(synced.db, settings, "fan_in", record_audit=False)
    assert list(result.rows["account_id"]) == ["P0", "W0"]


def test_ac5_fan_in_account_filter_and_cutoff(synced: Synced) -> None:
    s = synced.settings
    assert query(synced.db, s, "fan_in", account="P0", record_audit=False).n_rows == 1
    assert query(synced.db, s, "fan_in", account="S01", record_audit=False).n_rows == 0
    early = query(synced.db, s, "fan_in", as_of=date(2026, 3, 3), record_audit=False)
    assert list(early.rows["account_id"]) == ["P0", "R0"]


def test_ac5_fan_out_is_empty_with_its_columns(synced: Synced) -> None:
    result = query(synced.db, synced.settings, "fan_out")
    assert result.n_rows == 0
    assert list(result.rows.columns) == mod("aml.graph.neo4j.queries").QUERY_COLUMNS["fan_out"]


def test_ac5_read_timeout_stops_the_query_and_the_graph_stays_usable(synced: Synced) -> None:
    c = client()
    slow = "UNWIND range(1, 2000000000) AS i RETURN count(i) AS n"
    with pytest.raises(c.QueryTimeoutError, match=r"query exceeded 0.5 s") as err:
        c.run_read(synced.driver, synced.settings, slow, timeout=0.5)
    assert isinstance(err.value, mod("aml.graph.neo4j.guard").GraphError)
    frame = c.run_read(synced.driver, synced.settings, "MATCH (a:Account) RETURN count(a) AS n")
    assert int(frame.iloc[0, 0]) == 55
