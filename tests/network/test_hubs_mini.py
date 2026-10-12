"""AC5 for specs/network-detections.md: NET_HUB, degree and PageRank features on MINI-HUB."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import cfg, detect, duck_settings, jd, of_rule, ts

RULE = "NET_HUB"
HP_IDS = tuple(f"HP{i:02d}" for i in range(1, 12))
NUMERIC = [
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
    "cycle_alerts",
    "shared_cluster_size",
    "is_hub",
]
P0_REASON = (
    "received 220,000,000 VND from 10 accounts of other customers in 11 transfers between "
    "2026-03-01 01:00:00 and 2026-03-01 12:00:00; PageRank 12.13x the average of 51 active accounts"
)


def _hubs(db: DuckDb, **overrides: str) -> set[str]:
    detections = detect(db, cfg(**overrides))
    return {a.subject_id for a in of_rule(detections, RULE)}


def _row(features: pd.DataFrame, account: str) -> Any:
    return features.set_index("account_id").loc[account]


def test_ac5_default_run_has_one_hub_p0_with_exact_fields(hub: DuckDb) -> None:
    detections = detect(hub, duck_settings())
    assert detections.active_accounts == 51
    assert len(detections.alerts) == 1
    a = detections.alerts[0]
    assert a.rule_id == RULE
    assert a.rule_version == "v1"
    assert a.subject_type == "ACCOUNT"
    assert a.subject_id == "P0"
    assert a.alert_key == "NET_HUB|P0"
    assert a.accounts == (("P0", "SUBJECT"),)
    assert a.txn_ids == HP_IDS  # HP12 comes from EXT-1 and is not a transfer of the graph
    assert a.amount_vnd == 220_000_000
    assert a.window_start == ts("2026-03-01 01:00:00")
    assert a.window_end == ts("2026-03-01 12:00:00")
    details = jd(a.details)
    assert details["in_degree"] == 10  # S01 sent twice but is one sender
    assert details["out_degree"] == 1
    assert details["in_vnd"] == 220_000_000
    assert details["out_vnd"] == 150_000_000
    assert details["transfers"] == 11
    assert details["active_accounts"] == 51
    assert round(details["pagerank_ratio"], 2) == 12.13
    assert a.reason == P0_REASON


def test_ac5_feature_rows_of_the_hub_graph(hub: DuckDb) -> None:
    features = detect(hub, duck_settings()).features
    assert len(features) == 54
    assert list(features["account_id"]) == sorted(features["account_id"])

    q0 = _row(features, "Q0")
    assert int(q0["in_degree"]) == 10
    assert int(q0["in_vnd"]) == 99_990_000
    assert round(float(q0["pagerank_ratio"]), 2) == 3.37
    assert int(q0["is_hub"]) == 0  # below the 100M floor

    assert int(_row(features, "R0")["in_degree"]) == 9
    assert int(_row(features, "W0")["in_degree"]) == 8  # X09 and X10 share W0's owner
    assert int(_row(features, "L0")["in_degree"]) == 9  # HL10 is older than 365 days

    s02 = _row(features, "S02")
    assert int(s02["in_degree"]) == 1
    assert 10.6 <= float(s02["pagerank_ratio"]) <= 10.7
    assert int(s02["is_hub"]) == 0  # high PageRank but a single sender

    assert int(_row(features, "P0")["is_hub"]) == 1
    assert int(features["is_hub"].sum()) == 1
    assert abs(float(features["pagerank"].sum()) - 1.0) <= 0.000001


def test_ac5_account_without_edges_has_zero_in_every_numeric_column(hub: DuckDb) -> None:
    x09 = _row(detect(hub, duck_settings()).features, "X09")
    for column in NUMERIC:
        assert x09[column] == 0, column


def test_ac5_min_inflow_99990000_keeps_p0_and_q0(hub: DuckDb) -> None:
    assert _hubs(hub, HUBS__MIN_INFLOW_VND="99990000") == {"P0", "Q0"}


@pytest.mark.parametrize(
    ("min_in_degree", "expected"),
    [
        ("9", {"L0", "P0", "R0"}),
        ("8", {"L0", "P0", "R0", "W0"}),
        ("1", {"L0", "P0", "R0", "S02", "W0"}),
    ],
)
def test_ac5_lower_min_in_degree_adds_hubs(
    hub: DuckDb, min_in_degree: str, expected: set[str]
) -> None:
    assert _hubs(hub, HUBS__MIN_IN_DEGREE=min_in_degree) == expected


def test_ac5_lookback_366_days_brings_hl10_back(hub: DuckDb) -> None:
    detections = detect(hub, cfg(HUBS__LOOKBACK_DAYS="366"))
    assert detections.active_accounts == 52
    hubs = {a.subject_id: a for a in of_rule(detections, RULE)}
    assert set(hubs) == {"L0", "P0"}
    assert hubs["L0"].txn_ids == tuple(f"HL{i:02d}" for i in range(1, 11))
    assert hubs["L0"].window_start == ts("2025-06-30 10:00:00")


def test_ac5_min_pagerank_ratio_threshold(hub: DuckDb) -> None:
    assert _hubs(hub, HUBS__MIN_PAGERANK_RATIO="12.2") == set()
    assert _hubs(hub, HUBS__MIN_PAGERANK_RATIO="12.1") == {"P0"}


def test_ac5_as_of_cuts_the_graph(hub: DuckDb) -> None:
    detections = detect(hub, duck_settings(), as_of=date(2026, 3, 1))
    assert detections.active_accounts == 13
    assert [a.subject_id for a in detections.alerts] == ["P0"]
    details = jd(detections.alerts[0].details)
    assert details["out_degree"] == 0
    assert details["active_accounts"] == 13
    assert round(details["pagerank_ratio"], 2) == 5.53


def test_ac5_as_of_before_any_transfer_gives_no_alert_and_does_not_raise(hub: DuckDb) -> None:
    # The spec also says active_accounts == 0 here, but HL10 (2025-06-30) is inside the 365-day
    # lookback of this cutoff, so Z10 -> L0 is an edge (the same reasoning gives 13 for 03-01).
    # That clause contradicts the spec itself and is deliberately not asserted (see the report).
    detections = detect(hub, duck_settings(), as_of=date(2026, 2, 28))
    assert detections.alerts == ()
    assert len(detections.features) == 54
    p0 = _row(detections.features, "P0")
    for column in NUMERIC:
        assert p0[column] == 0, column
