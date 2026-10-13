"""AC4 (DuckDB part and CLI) for specs/neo4j-gds.md: TINY, GDS against the NetworkX features."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from tests.graph.helpers import RND_CYCLE
from tests.network.helpers import run_network

from .helpers import (
    TINY_S11,
    Synced,
    feature_frame,
    feature_tuple,
    run_gds,
    s11,
    synced_db,
)

pytestmark = pytest.mark.neo4j

HUB = "A4937939209"
MERCHANT = "A1463821795"
RND = "A8201784530"
SHARED = "SHARED-CIF00000002"


@dataclass
class Outcome:
    first: Any
    second: Any
    gds: pd.DataFrame  # run 1
    gds2: pd.DataFrame  # run 2
    nx: pd.DataFrame  # nx_account_features_current


@pytest.fixture(scope="module")
def tiny(er_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("gds_tiny") / "tiny.duckdb"
    with synced_db(path, template=er_template, expect_graph=s11(*TINY_S11)) as env:
        run_network(env.db, env.settings)
        yield env


@pytest.fixture(scope="module")
def outcome(tiny: Synced) -> Outcome:
    first = run_gds(tiny.db, tiny.settings)
    second = run_gds(tiny.db, tiny.settings)
    return Outcome(
        first,
        second,
        feature_frame(tiny.db, 1),
        feature_frame(tiny.db, 2),
        feature_frame(tiny.db, None, "nx_account_features_current"),
    )


def test_ac4_run_result(outcome: Outcome) -> None:
    run = outcome.first
    assert run.run_id == 1
    assert run.accounts == 532
    assert run.active_accounts == 298
    assert run.wcc_components == 9
    assert run.louvain_communities == 20
    assert run.shared_clusters == 2
    assert run.graphs == {
        "accounts": (298, 450),
        "accounts_undirected": (298, 900),
        "shared": (35, 66),
    }


def test_ac4_gds_equals_networkx_features(outcome: Outcome) -> None:
    gds, nx = outcome.gds, outcome.nx
    assert len(gds) == len(nx) == 532
    assert list(gds["account_id"]) == list(nx["account_id"])
    for column in ("in_degree", "out_degree", "in_vnd", "out_vnd"):
        assert list(gds[column]) == list(nx[column]), column
    assert (gds["pagerank"] - nx["pagerank"].astype(float)).abs().max() <= 1e-7
    assert (gds["pagerank_ratio"] - nx["pagerank_ratio"].astype(float)).abs().max() <= 2e-4


def test_ac4_hub_set_equals_the_5c_flag(outcome: Outcome) -> None:
    gds, nx = outcome.gds, outcome.nx
    hubs = gds[
        (gds["in_degree"] >= 10) & (gds["pagerank_ratio"] >= 1.8) & (gds["in_vnd"] >= 100_000_000)
    ]
    assert set(hubs["account_id"]) == {HUB}
    assert set(nx.loc[nx["is_hub"] == 1, "account_id"]) == {HUB}


def test_ac4_shared_clusters_cover_those_of_5c(outcome: Outcome) -> None:
    gds, nx = outcome.gds, outcome.nx
    big = gds[gds["shared_cluster_size"] >= 5]
    assert len(big) == 53
    assert set(big["shared_cluster_id"]) == {SHARED}
    assert set(big["shared_cluster_size"]) == {29}
    five_c = nx[nx["shared_cluster_size"] > 0]
    assert set(five_c["account_id"]) <= set(big["account_id"])
    merged = five_c.merge(big, on="account_id", suffixes=("_nx", "_gds"))
    assert len(merged) == len(five_c)
    assert (merged["shared_cluster_id_nx"] == merged["shared_cluster_id_gds"]).all()
    assert (merged["shared_cluster_size_nx"] == merged["shared_cluster_size_gds"]).all()
    assert int((gds["shared_cluster_size"] >= 2).sum()) == 63


def test_ac4_named_account_rows(outcome: Outcome) -> None:
    gds = outcome.gds
    hub = feature_tuple(gds, HUB)
    assert hub[:4] == (31, 3, 2_930_380_000, 2_851_894_000)
    assert hub[4] == pytest.approx(6.7651, abs=1e-9)
    assert hub[5:] == ("A1043446740", 36, "A1043446740", 36, SHARED, 29)

    merchant = feature_tuple(gds, MERCHANT)
    assert merchant[:4] == (34, 0, 38_925_000, 0)
    assert merchant[4] == pytest.approx(7.3002, abs=1e-9)
    assert merchant[5:] == (MERCHANT, 35, MERCHANT, 35, None, 0)

    rnd = feature_tuple(gds, RND)
    assert rnd[:4] == (1, 1, 399_475_000, 456_916_000)
    assert rnd[4] == pytest.approx(1.6277, abs=1e-9)
    assert rnd[5:] == ("A1070944972", 4, "A1070944972", 4, None, 0)


def test_ac4_round_tripping_ring_shares_component_and_community(outcome: Outcome) -> None:
    ring = set(RND_CYCLE.split(">"))
    assert len(ring) == 4
    rows = outcome.gds[outcome.gds["account_id"].isin(ring)]
    assert len(rows) == 4
    assert rows["wcc_id"].nunique() == 1
    assert rows["louvain_id"].nunique() == 1


def test_ac4_largest_component_and_community(outcome: Outcome) -> None:
    assert int(outcome.gds["wcc_size"].max()) == 98
    assert int(outcome.gds["louvain_size"].max()) == 36


def test_ac4_second_run_repeats_the_first(outcome: Outcome) -> None:
    assert outcome.second.run_id == 2
    pd.testing.assert_frame_equal(
        outcome.gds.drop(columns="run_id"), outcome.gds2.drop(columns="run_id")
    )
