"""AC3 (MINI-G part) for specs/neo4j-gds.md: `run_gds` against a real Neo4j and DuckDB.

MINI-G is synced once per module and `run_gds` runs four times in a fixed order (run 1 and 2 with
the default `as_of`, run 3 with 2026-07-01, run 4 before every transaction); the results of each
run are captured right after it, so the tests do not depend on their own order.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd
import pytest

from tests.neo4j_sync.test_sync_neo4j import NODE_PROPS, REL_PROPS

from .helpers import (
    MINI_S11,
    NeoState,
    Synced,
    client,
    feature_frame,
    feature_tuple,
    graph_audit,
    load_mini_g,
    mod,
    neo_state,
    parse_json,
    run_gds,
    s11,
    scalar,
    synced_db,
)

pytestmark = pytest.mark.neo4j

ACTOR = "analyst01"
COLUMNS = [
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank_ratio",
    "wcc_id",
    "wcc_size",
    "louvain_id",
    "louvain_size",
    "shared_cluster_id",
    "shared_cluster_size",
]
REASON_END = (
    "wrote features for 23 accounts, 6 with transfers; "
    "2 components, 2 communities, 4 shared-attribute clusters"
)


@dataclass
class Snap:
    run: Any
    features: pd.DataFrame  # rows of the run
    total_rows: int  # gds_account_features after the run
    current: pd.DataFrame  # gds_account_features_current after the run
    runs: pd.DataFrame  # gds_runs after the run
    audit: pd.DataFrame  # GDS_FEATURES_WRITTEN rows after the run
    neo: NeoState


@dataclass
class Sequence:
    snaps: list[Snap]
    before: dict[str, int]
    after: dict[str, int]


@pytest.fixture(scope="module")
def synced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("gds_mini") / "mini.duckdb"
    with synced_db(path, load_mini_g, expect_graph=s11(*MINI_S11)) as env:
        yield env


def _counts(env: Synced) -> dict[str, int]:
    return {
        t: int(scalar(env.db, f"SELECT COUNT(*) FROM {t}"))
        for t in ("alerts", "nx_account_features", "transactions")
    }


def _snap(env: Synced, run: Any) -> Snap:
    db = env.db
    runs = db.query_df("SELECT * FROM gds_runs ORDER BY run_id")
    runs.columns = [c.lower() for c in runs.columns]
    return Snap(
        run,
        feature_frame(db, run.run_id),
        int(scalar(db, "SELECT COUNT(*) FROM gds_account_features")),
        feature_frame(db, None, "gds_account_features_current"),
        runs,
        graph_audit(db, "decision = 'GDS_FEATURES_WRITTEN'"),
        neo_state(env),
    )


@pytest.fixture(scope="module")
def seq(synced: Synced) -> Sequence:
    before = _counts(synced)
    snaps = []
    for kw in ({"actor": ACTOR}, {}, {"as_of": date(2026, 7, 1)}, {"as_of": date(2026, 2, 28)}):
        run = run_gds(synced.db, synced.settings, **kw)
        snaps.append(_snap(synced, run))
    return Sequence(snaps, before, _counts(synced))


def _same_without_run_id(a: pd.DataFrame, b: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(
        a.drop(columns="run_id").reset_index(drop=True),
        b.drop(columns="run_id").reset_index(drop=True),
    )


# --------------------------------------------------------------------------------- run 1
def test_ac3_first_run_result(seq: Sequence) -> None:
    run = seq.snaps[0].run
    assert run.run_id == 1
    assert run.as_of == date(2026, 6, 30)
    assert run.accounts == 23
    assert run.active_accounts == 6
    assert run.wcc_components == 2
    assert run.louvain_communities == 2
    assert run.shared_clusters == 4
    assert run.graphs == {"accounts": (6, 4), "accounts_undirected": (6, 8), "shared": (26, 44)}
    assert run.sync_run_id == 1
    assert run.watermark == datetime(2026, 7, 1, 10, 0, 0)
    assert run.gds_version.startswith("2.13")


def test_ac3_first_run_feature_rows(seq: Sequence) -> None:
    frame = seq.snaps[0].features
    assert len(frame) == 23
    assert set(frame["run_id"]) == {1}
    expected = {
        "A01": (2, 1, 34_000_000, 5_000_000, 1.4938, "A01", 4, "A01", 4, "SHARED-C01", 5),
        "A20": (1, 0, 5_000_000, 0, 1.823, "A01", 4, "A01", 4, None, 0),
        "A04": (1, 0, 1_000_000, 0, 1.0235, "A04", 2, "A04", 2, "SHARED-C01", 5),
        "A02": (0, 1, 0, 14_000_000, 0.5533, "A01", 4, "A01", 4, "SHARED-C01", 5),
        "A01S": (0, 0, 0, 0, 0.0, None, 0, None, 0, "SHARED-C01", 5),
        "A07": (0, 0, 0, 0, 0.0, None, 0, None, 0, "SHARED-C06", 4),
    }
    for account, want in expected.items():
        got = feature_tuple(frame, account)
        assert got[:4] == want[:4], account
        assert got[4] == pytest.approx(want[4], abs=1e-9), account
        assert got[5:] == want[5:], account
    pagerank = frame.set_index("account_id")["pagerank"]
    assert pagerank["A01"] == pytest.approx(0.248963, abs=1e-6)
    assert pagerank["A20"] == pytest.approx(0.303827, abs=1e-6)
    assert pagerank.sum() == pytest.approx(1.0, abs=1e-6)


def test_ac3_first_run_shared_clusters(seq: Sequence) -> None:
    frame = seq.snaps[0].features.set_index("account_id")
    assert (frame.loc["A12", "shared_cluster_id"], frame.loc["A12", "shared_cluster_size"]) == (
        "SHARED-C12",
        2,
    )
    assert (frame.loc["A19", "shared_cluster_id"], frame.loc["A19", "shared_cluster_size"]) == (
        "SHARED-C14",
        6,
    )
    for account in ("A21", "A22"):
        # NULL in the table; pandas reads a NULL of a text column back as NaN
        assert pd.isna(frame.loc[account, "shared_cluster_id"]), account
    assert int((frame["shared_cluster_size"] >= 2).sum()) == 20


def test_ac3_first_run_current_view_runs_and_audit(seq: Sequence) -> None:
    snap = seq.snaps[0]
    pd.testing.assert_frame_equal(snap.current, snap.features)
    assert len(snap.current) == 23
    assert snap.total_rows == 23

    assert len(snap.runs) == 1
    row = snap.runs.iloc[0]
    assert int(row["run_id"]) == 1
    assert pd.Timestamp(row["as_of"]).date() == date(2026, 6, 30)
    assert row["source_backend"] == "duckdb"
    assert int(row["sync_run_id"]) == 1
    assert int(row["accounts"]) == 23
    assert int(row["active_accounts"]) == 6
    assert int(row["shared_clusters"]) == 4
    params = parse_json(row["params"])
    assert params["concurrency"] == 1
    assert params["lookback_days"] == 365

    assert len(snap.audit) == 1
    audit = snap.audit.iloc[0]
    assert audit["entity_type"] == "gds_run"
    assert audit["entity_id"] == "1"
    assert audit["version"] == "gds/v1"
    assert audit["actor"] == ACTOR
    assert audit["details"]["accounts"] == 23
    assert audit["reason"].endswith(REASON_END)


def test_ac3_excluded_transfers_are_not_counted(seq: Sequence) -> None:
    """T06 (after the cutoff), T03 (to EXT-01) and T05 (A01 -> A01S, same owner) add nothing."""
    frame = seq.snaps[0].features
    a01 = feature_tuple(frame, "A01")
    assert (a01[0], a01[1], a01[2], a01[3]) == (2, 1, 34_000_000, 5_000_000)


# --------------------------------------------------------------------------------- Neo4j
def test_ac3_neo4j_is_unchanged_after_every_run(seq: Sequence) -> None:
    for snap in seq.snaps:
        state = snap.neo
        assert state.graphs == 0, snap.run.run_id
        assert state.nodes == 83
        assert state.rels == 89
        assert state.node_keys == frozenset(NODE_PROPS)
        assert state.rel_keys == frozenset(REL_PROPS)


def test_ac3_source_tables_are_untouched(seq: Sequence) -> None:
    assert seq.after == seq.before


# --------------------------------------------------------------------------------- run 2..4
def test_ac3_second_run_repeats_the_first(seq: Sequence) -> None:
    first, second = seq.snaps[0], seq.snaps[1]
    assert second.run.run_id == 2
    assert len(second.features) == 23
    _same_without_run_id(first.features, second.features)
    assert second.total_rows == 46
    assert len(second.current) == 23
    assert set(second.current["run_id"]) == {2}
    assert len(second.runs) == 2
    assert len(second.audit) == 2
    assert (
        second.audit.iloc[1]["actor"]
        == mod("aml.common.config").load_settings(environ={}).audit.system_actor
    )


def test_ac3_as_of_after_the_late_transfer_includes_it(seq: Sequence) -> None:
    snap = seq.snaps[2]
    run = snap.run
    assert run.run_id == 3
    assert run.active_accounts == 6
    assert run.wcc_components == 1
    assert run.louvain_communities == 2
    assert run.graphs["accounts"] == (6, 5)
    a01 = feature_tuple(snap.features, "A01")
    assert (a01[0], a01[2], a01[6]) == (3, 41_000_000, 6)  # in_degree, in_vnd, wcc_size


def test_ac3_as_of_before_every_transaction_gives_an_empty_graph(seq: Sequence) -> None:
    snap = seq.snaps[3]
    run = snap.run
    assert run.run_id == 4
    assert run.active_accounts == 0
    assert run.wcc_components == 0
    assert run.graphs["accounts"] == (0, 0)
    assert run.shared_clusters == 4
    assert len(snap.features) == 23
    assert set(snap.features["in_degree"]) == {0}
    assert set(snap.features["wcc_size"]) == {0}


# --------------------------------------------------------------------------------- failures
def test_ac3_a_failing_stream_leaves_nothing_behind(
    synced: Synced, monkeypatch: pytest.MonkeyPatch
) -> None:
    gds_module = mod("aml.graph.neo4j.gds")
    graph_error = mod("aml.graph.neo4j.guard").GraphError
    original = client().run_read_file

    def failing(driver: Any, settings: Any, name: str, *args: Any, **kw: Any) -> Any:
        if name == "gds/pagerank.cypher":
            raise graph_error(f"boom in {name}")
        return original(driver, settings, name, *args, **kw)

    monkeypatch.setattr(client(), "run_read_file", failing)
    monkeypatch.setattr(gds_module, "run_read_file", failing, raising=False)

    def tables() -> tuple[int, int, int]:
        db = synced.db
        return (
            int(scalar(db, "SELECT COUNT(*) FROM gds_runs")),
            int(scalar(db, "SELECT COUNT(*) FROM gds_account_features")),
            len(graph_audit(db, "decision = 'GDS_FEATURES_WRITTEN'")),
        )

    before = tables()
    with pytest.raises(gds_module.GdsError):
        run_gds(synced.db, synced.settings)
    assert tables() == before
    assert neo_state(synced).graphs == 0
