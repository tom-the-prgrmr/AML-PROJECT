"""AC2 for specs/case-prioritization.md: the 35 case features and the long `case_features` table."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import CASE_C01_A, CASE_C01_B, CASE_C03, CASE_C04, CASE_C05, load_case, query
from .helpers import record_disposition as dispose
from .helpers import run_cases as rerun
from .prio_helpers import all_features, features_mod, minigt, source_of

ALL = (CASE_C01_A, CASE_C01_B, CASE_C03, CASE_C04, CASE_C05)


def _features(db: DuckDb, case_id: str) -> dict[str, float]:
    return features_mod().case_features(load_case(db, case_id))  # type: ignore[no-any-return]


def _check(got: dict[str, float], expected: dict[str, float], tol: float = 1e-6) -> None:
    for name, value in expected.items():
        assert got[name] == pytest.approx(value, abs=tol), name


def test_ac2_first_case_c01_0302(duck: DuckDb) -> None:
    minigt(duck)
    got = _features(duck, CASE_C01_A)
    assert set(got) == set(all_features())
    assert len(got) == 35
    _check(
        got,
        {
            "alerts": 3,
            "rule_alerts": 2,
            "network_alerts": 1,
            "screening_alerts": 0,
            "distinct_rules": 3,
            "has_structuring": 1,
            "has_rapid_movement": 1,
            "has_high_velocity": 0,
            "has_fan_in": 0,
            "has_fan_out": 0,
            "has_dormant_reactivation": 0,
            "has_net_shared_attribute": 0,
            "has_net_cycle": 1,
            "has_net_hub": 0,
            "has_screening_alert": 0,
            "has_screening_review": 0,
            "has_sanctions_hit": 0,
            "max_screening_score": 0,
            "alert_amount_log": 9.350248,
            "kyc_risk_level": 2,
            "cifs": 2,
            "accounts": 2,
            "dq_issues": 1,  # one element in dq_issues.customer (C02: occupation missing)
            "txn_count": 5,
            "in_vnd_log": 9.068186,
            "out_vnd_log": 8.892095,
            "cash_share": 0.2,
            "counterparties": 4,
            "pass_through": 0.666667,
            "in_degree": 0,
            "out_degree": 0,
            "pagerank_ratio": 0,
            "shared_cluster_size": 0,
            "prior_cases": 0,
            "prior_false_positives": 0,
        },
    )


def test_ac2_second_case_has_screening_sanctions_and_history(duck: DuckDb) -> None:
    minigt(duck)
    got = _features(duck, CASE_C01_B)
    _check(
        got,
        {
            "alerts": 2,
            "rule_alerts": 1,
            "network_alerts": 0,
            "screening_alerts": 1,
            "has_fan_out": 1,
            "has_structuring": 0,
            "has_screening_alert": 1,
            "has_screening_review": 0,
            "has_sanctions_hit": 1,
            "max_screening_score": 100,
            "prior_cases": 1,
            "prior_false_positives": 0,
            # derived from the stored enrichment by the rules of the spec
            "alert_amount_log": math.log10(1 + 50_000_000),
            "txn_count": 3,
            "in_vnd_log": math.log10(1 + 500_000_000),
            "out_vnd_log": math.log10(1 + 530_000_000),
            "cash_share": 0,
            "counterparties": 3,
            "pass_through": 500 / 530,
        },
    )


def test_ac2_screening_review_case_without_transactions(duck: DuckDb) -> None:
    minigt(duck)
    got = _features(duck, CASE_C05)
    _check(
        got,
        {
            "alerts": 1,
            "rule_alerts": 0,
            "network_alerts": 0,
            "screening_alerts": 1,
            "has_screening_alert": 1,
            "has_screening_review": 1,
            "has_sanctions_hit": 0,
            "max_screening_score": 80,
            "txn_count": 0,
            "cash_share": 0,
            "pass_through": 0,
            "kyc_risk_level": 0,
            "cifs": 1,
            "accounts": 1,
            "dq_issues": 0,
            "alert_amount_log": 0,
        },
    )


def test_ac2_every_value_is_a_finite_float(duck: DuckDb) -> None:
    minigt(duck)
    for case_id in ALL:
        got = _features(duck, case_id)
        assert set(got) == set(all_features()), case_id
        for name, value in got.items():
            assert isinstance(value, float), (case_id, name, value)
            assert math.isfinite(value), (case_id, name, value)


def test_ac2_write_features_is_idempotent_and_read_back(duck: DuckDb) -> None:
    minigt(duck)
    m = features_mod()
    assert m.write_features(duck, 1) == 175
    assert (
        int(query(duck, "SELECT COUNT(*) AS n FROM case_features WHERE run_id = 1")["n"][0]) == 175
    )
    assert m.write_features(duck, 1) == 0
    assert int(query(duck, "SELECT COUNT(*) AS n FROM case_features")["n"][0]) == 175

    frame = m.read_features(duck, 1)
    assert frame.shape == (5, 35)
    assert list(frame.index) == sorted(ALL)
    assert list(frame.columns) == list(all_features())
    # the stored rows are the pure function of the stored case
    for case_id in ALL:
        got = _features(duck, case_id)
        for name in all_features():
            assert frame.loc[case_id, name] == pytest.approx(got[name], abs=1e-9), (case_id, name)


def test_ac2_prior_false_positives_follow_the_decision_but_old_snapshot_is_kept(
    duck: DuckDb,
) -> None:
    settings = minigt(duck)
    m = features_mod()
    m.write_features(duck, 1)
    before = m.read_features(duck, 1)

    dispose(duck, settings, CASE_C01_A, "FALSE_POSITIVE", reason="x", actor="analyst01")
    assert rerun(duck, settings).run_id == 2

    assert _features(duck, CASE_C01_B)["prior_false_positives"] == 1
    assert _features(duck, CASE_C01_B)["prior_cases"] == 1
    after: Any = m.read_features(duck, 1)
    pd.testing.assert_frame_equal(before, after)  # run 1 is not recomputed


def test_ac2_features_module_never_reads_ground_truth() -> None:
    assert "ground_truth" not in source_of("aml.cases.features")
