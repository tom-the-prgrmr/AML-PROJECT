"""Helpers for the Phase 7b-i tests (specs/ml-anomaly.md): ANOM settings, LEGS-M, module access."""

from __future__ import annotations

import importlib
from datetime import date
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database
from tests.cases.helpers import duck_settings, js, mod, query, scalar

AS_OF = date(2026, 6, 30)
START = date(2026, 1, 1)
CLI_LINE_END = "anomaly alerts are signals for review: no case is closed or cleared by this model"
C01_03 = ("C01", "2026-03")
# the measured scores of the prototype on the six MINI-C customer-months (scikit-learn 1.9.1)
MINI_SCORES = {
    ("C01", "2026-01"): 0.549925,
    ("C01", "2026-03"): 0.567938,
    ("C01", "2026-05"): 0.511577,
    ("C02", "2026-04"): 0.502817,
    ("C03", "2026-03"): 0.379239,
    ("C04", "2026-03"): 0.380698,
}
MINI_RANKED = [
    ("C01", "2026-03"),
    ("C01", "2026-01"),
    ("C01", "2026-05"),
    ("C02", "2026-04"),
    ("C04", "2026-03"),
    ("C03", "2026-03"),
]
MINI_REASON = (
    "anomaly score 0.5679 ranks 1 of 6 customer-months as of 2026-06-30 (alerting the top 1); "
    "strongest deviations from the median: txns_per_day +1.25, cash_ratio +0.40, amount_dev -0.37 "
    "(IQR units); model anomaly/v1/1; a signal for a person to review, not a finding"
)


def anom_settings(**env: str) -> Settings:
    """ANOM of the spec: DuckDB settings with `min_samples` 5 (MINI-C has 6 customer-months)."""
    return duck_settings(AML__ML__ANOMALY__MIN_SAMPLES="5", **env)


def settings_with(**env: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def features() -> Any:
    return importlib.import_module("aml.ml.anomaly.features")


def model() -> Any:
    return importlib.import_module("aml.ml.anomaly.model")


def runner() -> Any:
    return importlib.import_module("aml.ml.anomaly.runner")


def evaluate() -> Any:
    return importlib.import_module("aml.ml.anomaly.evaluate")


def case_features() -> Any:
    return importlib.import_module("aml.ml.anomaly.case_features")


def card() -> Any:
    return importlib.import_module("aml.ml.anomaly.card")


def anomaly_error() -> type[Exception]:
    return runner().AnomalyError  # type: ignore[no-any-return]


def run_anomaly(db: Database, settings: Settings, **kw: Any) -> Any:
    return runner().run_anomaly(db, settings, **kw)


def read_legs(db: Database) -> pd.DataFrame:
    """LEGS-M (or any loaded data): the legs in the shape `build_samples` takes."""
    cols = ", ".join(features().LEG_COLUMNS)
    return query(db, f"SELECT {cols} FROM txn_legs")


def build(db: Database, settings: Settings, graph: pd.DataFrame | None = None, **kw: Any) -> Any:
    """`build_samples` on the legs of ``db`` with the spec's AC2 dates unless overridden."""
    args = {"as_of": AS_OF, "start_date": START, "cfg": settings.ml.anomaly} | kw
    empty = pd.DataFrame(columns=["account_id", *features().GRAPH_FEATURES])
    return features().build_samples(read_legs(db), empty if graph is None else graph, **args)


def matrix(db: Database, settings: Settings) -> pd.DataFrame:
    """X of AC3: the 14 feature columns of the six MINI-C samples, indexed by (cif, month)."""
    return features().feature_matrix(build(db, settings))


def table_counts(db: Database, tables: tuple[str, ...]) -> dict[str, int]:
    return {t: int(scalar(db, f"SELECT COUNT(*) FROM {t}")) for t in tables}


__all__ = [
    "AS_OF",
    "C01_03",
    "CLI_LINE_END",
    "MINI_RANKED",
    "MINI_REASON",
    "MINI_SCORES",
    "START",
    "anom_settings",
    "anomaly_error",
    "build",
    "card",
    "case_features",
    "duck_settings",
    "evaluate",
    "features",
    "js",
    "matrix",
    "mod",
    "model",
    "query",
    "read_legs",
    "run_anomaly",
    "runner",
    "scalar",
    "settings_with",
    "table_counts",
]
