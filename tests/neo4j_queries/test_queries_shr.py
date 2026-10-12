"""AC5 (shared attributes part) for specs/neo4j-queries.md: MINI-G."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.neo4j_sync.helpers import load_mini_g

from .helpers import Synced, cells, mod, neo_settings, query, rows, synced_db

pytestmark = pytest.mark.neo4j

ATTR = ["kind", "key", "customers", "customer_ids"]
CLUSTER = ["customer", "distance", "via", "accounts"]
G01_ROWS = [
    ("address", "01dabfcfc5ec16dc", 2, ["G-C01", "G-C04"]),
    ("device", "9780efe92205e69d", 2, ["G-C01", "G-C03"]),
    ("phone", "1582642d9e86c0cf", 2, ["G-C01", "G-C02"]),
]
BIG = ("phone", "842dd8fe262d43a0", 6, ["G-C14", "G-C15", "G-C16", "G-C17", "G-C18", "G-C19"])


@pytest.fixture(scope="module")
def synced(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Synced]:
    path = tmp_path_factory.mktemp("nq_shr") / "mini_g.duckdb"
    with synced_db(path, load_mini_g) as env:
        yield env


def _cluster(synced: Synced, customer: str, **env: str) -> list[tuple]:
    settings = neo_settings(**env) if env else synced.settings
    result = query(synced.db, settings, "shared_cluster", customer=customer, record_audit=False)
    return rows(result, CLUSTER)


def test_ac5_shared_attributes_all(synced: Synced) -> None:
    result = query(synced.db, synced.settings, "shared_attributes")
    assert (
        list(result.rows.columns)
        == mod("aml.graph.neo4j.queries").QUERY_COLUMNS["shared_attributes"]
    )
    got = rows(result, ATTR)
    assert len(got) == 9
    assert got[0] == BIG
    rest = got[1:]
    assert all(r[2] == 2 for r in rest)
    assert [r[0] for r in rest] == ["address"] * 3 + ["device"] * 3 + ["phone"] * 2
    for kind in ("address", "device", "phone"):
        keys = [r[1] for r in rest if r[0] == kind]
        assert keys == sorted(keys)
    for expected in G01_ROWS:
        assert expected in rest


def test_ac5_shared_attributes_for_one_customer(synced: Synced) -> None:
    result = query(
        synced.db, synced.settings, "shared_attributes", customer="G-C01", record_audit=False
    )
    assert sorted(rows(result, ATTR)) == sorted(G01_ROWS)


def test_ac5_shared_attributes_cap_comes_from_config(synced: Synced) -> None:
    settings = neo_settings(AML__NETWORK__SHARED_ATTRIBUTES__MAX_CUSTOMERS_PER_VALUE="5")
    result = query(synced.db, settings, "shared_attributes", record_audit=False)
    assert result.n_rows == 8
    assert BIG not in rows(result, ATTR)


def test_ac5_shared_cluster_g_c01(synced: Synced) -> None:
    result = query(synced.db, synced.settings, "shared_cluster", customer="G-C01")
    assert (
        list(result.rows.columns) == mod("aml.graph.neo4j.queries").QUERY_COLUMNS["shared_cluster"]
    )
    assert rows(result, CLUSTER) == [
        ("G-C02", 1, ["phone"], 1),
        ("G-C03", 1, ["device"], 1),
        ("G-C04", 1, ["address"], 1),
        ("G-C05", 2, ["address", "device"], 1),
    ]


def test_ac5_shared_cluster_g_c05_shortest_paths(synced: Synced) -> None:
    got = _cluster(synced, "G-C05")
    assert len(got) == 4
    assert ("G-C04", 1, ["device"], 1) in got
    assert ("G-C01", 2, ["device", "address"], 2) in got
    assert {r[0]: r[1] for r in got if r[0] in ("G-C02", "G-C03")} == {"G-C02": 3, "G-C03": 3}


def test_ac5_shared_cluster_other_customers(synced: Synced) -> None:
    g06 = _cluster(synced, "G-C06")
    assert sorted(r[0] for r in g06) == ["G-C09", "G-C10", "G-C11"]
    assert {r[1] for r in g06} == {1}

    assert len(_cluster(synced, "G-C14")) == 5
    capped = {"AML__NETWORK__SHARED_ATTRIBUTES__MAX_CUSTOMERS_PER_VALUE": "5"}
    assert _cluster(synced, "G-C14", **capped) == []

    assert _cluster(synced, "G-C20") == []
    assert _cluster(synced, "G-NOPE") == []


def test_ac5_results_hold_no_personal_values(synced: Synced) -> None:
    attributes = query(synced.db, synced.settings, "shared_attributes", record_audit=False)
    cluster = query(
        synced.db, synced.settings, "shared_cluster", customer="G-C01", record_audit=False
    )
    text = " ".join(cells(attributes.rows) + cells(cluster.rows))
    for secret in ("0901000001", "DEV-R", "Lê Lợi"):
        assert secret not in text
