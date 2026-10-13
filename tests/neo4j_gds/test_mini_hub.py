"""AC3 (MINI-HUB part) for specs/neo4j-gds.md: GDS features equal the NetworkX ones of 5c."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pandas as pd
import pytest

from aml.dba.edges import refresh_acct_edge_daily
from tests.network.helpers import detect, load_hub

from .helpers import Synced, feature_frame, feature_tuple, run_gds, synced_db

pytestmark = pytest.mark.neo4j


def _load(db: Any) -> None:
    load_hub(db)
    refresh_acct_edge_daily(db)


@pytest.fixture(scope="module")
def synced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("gds_hub") / "hub.duckdb"
    with synced_db(path, _load) as env:
        yield env


@pytest.fixture(scope="module")
def outcome(synced: Synced) -> tuple[Any, pd.DataFrame, pd.DataFrame]:
    run = run_gds(synced.db, synced.settings)
    gds = feature_frame(synced.db, run.run_id)
    nx = detect(synced.db, synced.settings).features.reset_index(drop=True)
    return run, gds, nx


def test_ac3_hub_run_counts(outcome: Any) -> None:
    run, gds, _ = outcome
    assert run.active_accounts == 51
    assert run.wcc_components == 5
    assert run.louvain_communities == 5
    assert run.shared_clusters == 0
    assert run.graphs["shared"] == (0, 0)
    assert len(gds) == 54


def test_ac3_hub_rows(outcome: Any) -> None:
    _, gds, _ = outcome
    p0 = feature_tuple(gds, "P0")
    assert (p0[0], p0[1], p0[2], p0[3]) == (10, 1, 220_000_000, 150_000_000)
    assert p0[4] == pytest.approx(12.1302, abs=1e-9)
    assert (p0[5], p0[6]) == ("P0", 11)
    assert feature_tuple(gds, "W0")[0] == 8  # the two senders with the same owner do not count
    x09 = feature_tuple(gds, "X09")
    assert x09[0] == 0
    assert x09[5] is None


def test_ac3_hub_features_equal_networkx(outcome: Any) -> None:
    _, gds, nx = outcome
    assert list(gds["account_id"]) == list(nx["account_id"])
    for column in ("in_degree", "out_degree", "in_vnd", "out_vnd"):
        assert list(gds[column]) == list(nx[column]), column
    diff = (gds["pagerank"] - nx["pagerank"].astype(float)).abs().max()
    assert diff <= 1e-7
    ratio = (gds["pagerank_ratio"] - nx["pagerank_ratio"].astype(float)).abs().max()
    assert ratio <= 2e-4
