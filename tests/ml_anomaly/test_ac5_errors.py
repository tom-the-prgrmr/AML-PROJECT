"""AC5 for specs/ml-anomaly.md: errors come before the first write; detect_anomalies reads only."""

from __future__ import annotations

import pytest

from aml.common.db import DuckDb
from aml.dba.schema import apply_schema

from .helpers import anom_settings, anomaly_error, duck_settings, runner, table_counts

TABLES = (
    "anomaly_runs",
    "anomaly_scores",
    "alerts",
    "alert_accounts",
    "alert_evidence",
    "monitoring_runs",
    "audit_log",
    "case_anomaly_features",
)


def test_ac5_too_few_customer_months(minic: DuckDb) -> None:
    before = table_counts(minic, TABLES)
    with pytest.raises(anomaly_error()) as err:
        runner().run_anomaly(minic, duck_settings())  # default min_samples = 50
    assert str(err.value) == (
        "only 6 customer-months to learn from, need at least ml.anomaly.min_samples=50"
    )
    assert table_counts(minic, TABLES) == before


def test_ac5_empty_transactions(duck: DuckDb) -> None:
    apply_schema(duck)
    before = table_counts(duck, TABLES)
    with pytest.raises(anomaly_error()) as err:
        runner().run_anomaly(duck, duck_settings())
    assert str(err.value) == "transactions is empty; run `aml load` first"
    assert table_counts(duck, TABLES) == before


def test_ac5_detect_anomalies_writes_nothing(minic: DuckDb) -> None:
    tables = (*TABLES, "case_runs", "cases")
    before = table_counts(minic, tables)
    frame = runner().detect_anomalies(minic, anom_settings())
    assert len(frame) == 6
    assert {"score", "rank", "alerted"} <= set(frame.columns)
    assert int(frame["alerted"].sum()) == 1
    assert table_counts(minic, tables) == before
