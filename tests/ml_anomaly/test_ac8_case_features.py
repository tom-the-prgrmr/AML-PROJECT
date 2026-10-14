"""AC8 for specs/ml-anomaly.md: the two anomaly columns of a case (`case_anomaly_features`)."""

from __future__ import annotations

import pytest

from aml.cases.features import write_features
from aml.common.db import DuckDb
from tests.cases.helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    run_cases,
)

from .helpers import anom_settings, case_features, query, run_anomaly, scalar


@pytest.fixture
def ready(minic: DuckDb) -> DuckDb:
    run_anomaly(minic, anom_settings())
    run_cases(minic, anom_settings())
    return minic


def test_ac8_write_is_all_or_nothing_and_idempotent(ready: DuckDb) -> None:
    cf = case_features()
    settings = anom_settings()
    assert cf.write_anomaly_features(ready, settings, 1) == 10
    assert cf.write_anomaly_features(ready, settings, 1) == 0
    assert scalar(ready, "SELECT COUNT(*) FROM case_anomaly_features") == 10
    assert set(
        query(ready, "SELECT anomaly_run_id FROM case_anomaly_features")["anomaly_run_id"]
    ) == {1}


def test_ac8_read_gives_the_measured_values(ready: DuckDb) -> None:
    cf = case_features()
    settings = anom_settings()
    cf.write_anomaly_features(ready, settings, 1)
    frame = cf.read_anomaly_features(ready, settings, 1)
    assert frame is not None
    assert frame.index.is_monotonic_increasing and len(frame) == 5
    assert list(frame.columns) == list(cf.ANOMALY_CASE_FEATURES)
    expected = {
        CASE_C01_A: (0.567938, 1),
        CASE_C01_B: (0.511577, 0),
        CASE_C03: (0.379239, 0),
        CASE_C04: (0.380698, 0),
        CASE_C05: (0.0, 0.0),
    }
    for case_id, (score, months) in expected.items():
        assert frame.loc[case_id, "anomaly_max_score"] == pytest.approx(score, abs=1e-6), case_id
        assert frame.loc[case_id, "anomaly_flagged_months"] == months, case_id


def test_ac8_before_any_anomaly_run_there_is_nothing(minic: DuckDb) -> None:
    run_cases(minic, anom_settings())
    cf = case_features()
    assert cf.write_anomaly_features(minic, anom_settings(), 1) == 0
    assert cf.read_anomaly_features(minic, anom_settings(), 1) is None
    assert scalar(minic, "SELECT COUNT(*) FROM case_anomaly_features") == 0


def test_ac8_a_newer_anomaly_run_gets_its_own_rows(ready: DuckDb) -> None:
    cf = case_features()
    settings = anom_settings()
    cf.write_anomaly_features(ready, settings, 1)
    run_anomaly(ready, settings)  # anomaly run 2 (same scores)
    assert cf.read_anomaly_features(ready, settings, 1) is None  # nothing stored for run 2 yet
    assert cf.write_anomaly_features(ready, settings, 1) == 10
    rows = query(ready, "SELECT DISTINCT anomaly_run_id FROM case_anomaly_features")
    assert sorted(rows["anomaly_run_id"]) == [1, 2]
    frame = cf.read_anomaly_features(ready, settings, 1)
    assert frame is not None
    stored = query(
        ready,
        "SELECT case_id, feature, value FROM case_anomaly_features WHERE anomaly_run_id = 2",
    )
    assert len(stored) == 10  # the values read are the rows of anomaly run 2
    for r in stored.itertuples():
        assert frame.loc[r.case_id, r.feature] == r.value


def test_ac8_the_phase_7c_features_do_not_hold_anomaly_columns(ready: DuckDb) -> None:
    assert write_features(ready, 1) == 35 * 5
    assert (
        scalar(
            ready, "SELECT COUNT(*) FROM case_features WHERE feature LIKE 'anomaly\\_%' ESCAPE '\\'"
        )
        == 0
    )
