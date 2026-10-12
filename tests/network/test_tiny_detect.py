"""AC6 for specs/network-detections.md: `detect_network` on TINY (DuckDB, after `run_er`)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import (
    AS_OF,
    CYCLE_1,
    CYCLE_2,
    HUB_TINY,
    MERCHANT_TINY,
    RULE_IDS,
    SHR_TINY,
    cfg,
    detect,
    duck_settings,
    jd,
    mod,
    of_rule,
    query,
    ts,
)

FEATURE_COLUMNS = [
    "account_id",
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
    "cycle_alerts",
    "shared_cluster_id",
    "shared_cluster_size",
    "is_hub",
]
NUMERIC = [c for c in FEATURE_COLUMNS if c not in ("account_id", "shared_cluster_id")]
SHR_REASON = (
    "29 customers (53 accounts) linked by shared device (16 customers), phone (7), address (8); "
    "28 transfer(s) totalling 2,849,484,000 VND between members between "
    "2026-04-16 01:11:48 and 2026-04-17 23:16:36"
)
CYC1_REASON = (
    "456,916,000 VND left A8201784530 and 399,475,000 VND (87%) returned after 4 transfers "
    "across 4 customers in 105 hours (A8201784530 -> A3312263346 -> A9950029109 -> "
    "A1070944972 -> A8201784530) between 2026-03-22 15:00:00 and 2026-03-27 00:11:51"
)
HUB_REASON = (
    "received 2,930,380,000 VND from 31 accounts of other customers in 31 transfers between "
    "2026-04-13 09:28:12 and 2026-04-17 23:16:36; PageRank 6.77x the average of 298 active accounts"
)


@pytest.fixture(scope="module")
def tiny(er_template: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[DuckDb]:
    """TINY after ER, read-only for this module (a private copy of the template)."""
    path = tmp_path_factory.mktemp("net_tiny_detect") / "tiny.duckdb"
    shutil.copy(er_template, path)
    db = DuckDb(path)
    yield db
    db.close()


@pytest.fixture(scope="module")
def result(tiny: DuckDb) -> Any:
    return detect(tiny, duck_settings())


def _gt_set(db: DuckDb, scenario: str, entity_type: str, roles: tuple[str, ...]) -> set[str]:
    quoted = ", ".join(f"'{r}'" for r in roles)
    df = query(
        db,
        f"SELECT entity_id FROM ground_truth WHERE scenario_id = '{scenario}' "
        f"AND entity_type = '{entity_type}' AND role IN ({quoted})",
    )
    return set(df["entity_id"])


def test_ac6_four_alerts_in_order(result: Any) -> None:
    assert result.active_accounts == 298
    assert result.cycle_search_steps == 12
    assert [a.rule_id for a in result.alerts] == [
        "NET_SHARED_ATTRIBUTE",
        "NET_CYCLE",
        "NET_CYCLE",
        "NET_HUB",
    ]
    assert {a.rule_version for a in result.alerts} == {"v1"}


def test_ac6_shared_attribute_alert(tiny: DuckDb, result: Any) -> None:
    a = of_rule(result, "NET_SHARED_ATTRIBUTE")[0]
    assert a.subject_id == SHR_TINY
    assert len(a.accounts) == 53
    assert {role for _, role in a.accounts} == {"MEMBER"}
    ids = [acct for acct, _ in a.accounts]
    assert ids == sorted(ids)
    assert (ids[0], ids[-1]) == ("A1043446740", "A9840068430")
    assert len(a.txn_ids) == 28
    assert (a.txn_ids[0], a.txn_ids[-1]) == ("T0000002986", "T0000003071")
    assert a.amount_vnd == 2_849_484_000
    assert a.window_start == ts("2026-04-16 01:11:48")
    assert a.window_end == ts("2026-04-17 23:16:36")
    details = jd(a.details)
    assert details["customers"] == 29
    assert details["links"] == {"device": 16, "phone": 7, "address": 8}
    assert details["shared_values"] == {"device": 1, "phone": 1, "address": 1}
    assert a.reason == SHR_REASON

    # the 53 accounts belong to exactly the CIFs of the 29 collector/member accounts of the ring
    ring_accounts = _gt_set(tiny, "GT-MULE-0001", "account", ("collector", "member"))
    assert len(ring_accounts) == 29
    cif_of = query(tiny, "SELECT account_id, cif FROM accounts").set_index("account_id")["cif"]
    assert {cif_of[acct] for acct in ids} == {cif_of[acct] for acct in ring_accounts}


def test_ac6_first_cycle_alert_matches_ground_truth(tiny: DuckDb, result: Any) -> None:
    a = of_rule(result, "NET_CYCLE")[0]
    assert a.subject_id == CYCLE_1
    assert a.alert_key == f"NET_CYCLE|{CYCLE_1}|2026-03-22T15:00:00"
    roles = dict(a.accounts)
    assert roles["A8201784530"] == "ORIGIN"
    assert sorted(roles.values()) == ["HOP", "HOP", "HOP", "ORIGIN"]
    assert a.txn_ids == ("T0000002197", "T0000002246", "T0000002299", "T0000002327")
    assert set(a.txn_ids) == _gt_set(tiny, "GT-RND-0001", "transaction", ("evidence",))
    assert a.amount_vnd == 1_722_240_000
    assert a.reason == CYC1_REASON


def test_ac6_second_cycle_alert_matches_ground_truth(tiny: DuckDb, result: Any) -> None:
    a = of_rule(result, "NET_CYCLE")[1]
    assert a.subject_id == CYCLE_2
    roles = dict(a.accounts)
    assert roles["A9059982551"] == "ORIGIN"
    assert sorted(roles.values()) == ["HOP", "HOP", "HOP", "ORIGIN"]
    assert a.txn_ids == ("T0000002277", "T0000002283", "T0000002332", "T0000002400")
    assert set(a.txn_ids) == _gt_set(tiny, "GT-RND-0002", "transaction", ("evidence",))
    assert a.amount_vnd == 1_532_271_000
    assert jd(a.details)["hours"] == 94


def test_ac6_hub_alert(result: Any) -> None:
    a = of_rule(result, "NET_HUB")[0]
    assert a.subject_id == HUB_TINY
    assert len(a.txn_ids) == 31
    assert a.amount_vnd == 2_930_380_000
    details = jd(a.details)
    assert details["in_degree"] == 31
    assert details["out_degree"] == 3
    assert a.reason == HUB_REASON


def test_ac6_features_table(result: Any) -> None:
    f = result.features
    assert list(f.columns) == FEATURE_COLUMNS
    assert mod("aml.graph.network.runner").FEATURE_COLUMNS == FEATURE_COLUMNS
    assert len(f) == 532
    assert list(f["account_id"]) == sorted(f["account_id"])
    assert int((f["pagerank"] > 0).sum()) == 298
    in_cluster = f[f["shared_cluster_id"] == SHR_TINY]
    assert len(in_cluster) == 53
    assert set(in_cluster["shared_cluster_size"]) == {29}
    assert int((f["cycle_alerts"] == 1).sum()) == 8
    assert int(f["is_hub"].sum()) == 1

    by_id = f.set_index("account_id")
    merchant = by_id.loc[MERCHANT_TINY]
    assert int(merchant["in_degree"]) == 34
    assert int(merchant["in_vnd"]) == 38_925_000
    assert round(float(merchant["pagerank_ratio"]), 2) == 7.30
    assert int(merchant["is_hub"]) == 0

    idle = by_id.loc["A6457424962"]
    for column in NUMERIC:
        assert idle[column] == 0, column


def test_ac6_attribute_keys_equal_the_er_normalisation(tiny: DuckDb) -> None:
    customers = tiny.query_df("SELECT * FROM customers")
    mapping = tiny.query_df("SELECT * FROM admin_unit_mapping")
    keys = mod("aml.graph.network.shared").attribute_keys(customers, mapping)
    records = mod("aml.entity_resolution.normalize").prepare_records(
        customers, mapping, duck_settings(), as_of=AS_OF
    )
    assert len(keys) == 300
    assert list(keys["cif"]) == sorted(keys["cif"])
    left = keys.set_index("cif")
    right = records.set_index("cif")

    def clean(series: pd.Series) -> dict[str, Any]:
        return {cif: (None if pd.isna(v) else v) for cif, v in series.items()}

    assert clean(left["phone_key"]) == clean(right["phone_norm"])
    assert clean(left["address_key"]) == clean(right["addr_key"])


def test_ac6_min_customers_2_adds_a_pair_of_customers(tiny: DuckDb) -> None:
    alerts = of_rule(detect(tiny, cfg(SHARED_ATTRIBUTES__MIN_CUSTOMERS="2")), RULE_IDS[0])
    assert [a.subject_id for a in alerts] == [SHR_TINY, "SHARED-CIF00000148"]
    pair = jd(alerts[1].details)
    assert pair["customers"] == 2
    assert pair["links"] == {"device": 0, "phone": 0, "address": 2}


def test_ac6_max_customers_per_value_15_drops_the_shared_device(tiny: DuckDb) -> None:
    alerts = of_rule(
        detect(tiny, cfg(SHARED_ATTRIBUTES__MAX_CUSTOMERS_PER_VALUE="15")), RULE_IDS[0]
    )
    assert [a.subject_id for a in alerts] == ["SHARED-CIF00000014"]
    details = jd(alerts[0].details)
    assert details["customers"] == 14
    assert details["links"]["device"] == 0


def test_ac6_result_does_not_depend_on_physical_row_order(
    tiny: DuckDb, result: Any, tmp_path: Path
) -> None:
    shuffled = DuckDb(tmp_path / "shuffled.duckdb")
    try:
        mod("aml.dba.schema").apply_schema(shuffled)
        for table in ("admin_unit_mapping", "er_runs", "er_golden"):
            shuffled.insert_df(table, tiny.query_df(f"SELECT * FROM {table}"))
        for table in ("customers", "accounts", "transactions"):
            frame = tiny.query_df(f"SELECT * FROM {table}")
            shuffled.insert_df(table, frame.sample(frac=1, random_state=7).reset_index(drop=True))
        again = detect(shuffled, duck_settings())
    finally:
        shuffled.close()
    assert again.alerts == result.alerts
    pd.testing.assert_frame_equal(again.features, result.features)
    assert (again.active_accounts, again.cycle_search_steps) == (298, 12)
