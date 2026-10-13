"""Helpers for the Phase 7c tests (specs/case-prioritization.md): MINI-GT, TOY, TINY-L.

Fixtures are plain builder functions (helpers.py and conftest.py are locked); the tests pass the
`duck` / `tiny_cases` fixtures in. Nothing here imports scikit-learn.
"""

from __future__ import annotations

import inspect
import json
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database, DuckDb

from .helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    CASE_C05,
    audit_cases,
    duck_settings,
    js,
    load_minic,
    mod,
    query,
    record_disposition,
    run_cases,
)

SIM_ACTOR = "simulated_analyst"
SIM_PREFIX = "simulated from ground truth:"
PINNED = {"AML__CASES__GRAPH_FEATURES": "networkx"}  # Oracle may hold GDS rows from other tests
FRACTION = "AML__CASES__PRIORITIZATION__SIMULATE_FRACTION"

# (scenario_id, typology, is_suspicious, entity_type, entity_id, role)
MINI_TRUTH: list[tuple[str, str, bool, str, str, str]] = [
    ("GT-STR-0001", "structuring", True, "account", "A01", "subject"),
    ("GT-RND-0001", "round_tripping", True, "account", "A03", "hop"),
    ("GT-PAY-0001", "benign_payroll", False, "account", "A04", "employer"),
    ("GT-SAN-0001", "sanctions_hit", True, "customer", "C05", "subject"),
    ("GT-SAN-0001", "sanctions_hit", True, "watchlist_entry", "WL2", "listed_entry"),
]
TINY_TOP = "C-CIF00000189-20260413"
# the 35 feature names in the order of the "Thiết kế" section of the spec
EXPECTED_FEATURES: tuple[str, ...] = (
    "alerts", "rule_alerts", "network_alerts", "screening_alerts", "distinct_rules",
    "has_structuring", "has_rapid_movement", "has_high_velocity", "has_fan_in", "has_fan_out",
    "has_dormant_reactivation", "has_net_shared_attribute", "has_net_cycle", "has_net_hub",
    "has_screening_alert", "has_screening_review", "has_sanctions_hit", "max_screening_score",
    "alert_amount_log",
    "kyc_risk_level", "cifs", "accounts", "dq_issues",
    "txn_count", "in_vnd_log", "out_vnd_log", "cash_share", "counterparties", "pass_through",
    "in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size",
    "prior_cases", "prior_false_positives",
)  # fmt: skip


# ---------------------------------------------------------------- modules
def features_mod() -> Any:
    return mod("aml.cases.features")


def labels_mod() -> Any:
    return mod("aml.cases.labels")


def model_mod() -> Any:
    return mod("aml.cases.model")


def prio_mod() -> Any:
    return mod("aml.cases.prioritize")


def prio_error() -> type[Exception]:
    return model_mod().PrioritizationError  # type: ignore[no-any-return]


def source_of(module_name: str) -> str:
    return inspect.getsource(mod(module_name))


def all_features() -> tuple[str, ...]:
    """The feature names the tests build their frames with (AC1 pins FEATURES to this tuple)."""
    return EXPECTED_FEATURES


# ---------------------------------------------------------------- MINI-GT
def insert_truth(db: Database, rows: Sequence[tuple[Any, ...]] = ()) -> None:
    for scenario, typology, suspicious, entity_type, entity_id, role in rows or MINI_TRUTH:
        db.execute(
            "INSERT INTO ground_truth (scenario_id, typology, is_suspicious, entity_type, "
            "entity_id, role, start_ts, end_ts, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 'test')",
            [scenario, typology, suspicious, entity_type, entity_id, role],
        )


def minigt(db: Database, *, run: bool = True, **env: str) -> Settings:
    """MINI-GT = MINI-C + ground_truth, then `run_cases` (run 1, 5 cases) unless ``run`` is off."""
    load_minic(db)
    insert_truth(db)
    settings = duck_settings(**env)
    if run:
        run_cases(db, settings)
    return settings


# ---------------------------------------------------------------- TOY
def toy_frame() -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """TOY of the spec: 40 rows; ``network_alerts`` = 1 on even i, the only separating feature."""
    ids = [f"C-T{i:02d}-20260101" for i in range(40)]
    X = pd.DataFrame(0.0, index=pd.Index(ids, name="case_id"), columns=list(all_features()))
    for i, case_id in enumerate(ids):
        X.loc[case_id, "network_alerts"] = 1.0 if i % 2 == 0 else 0.0
        X.loc[case_id, "alerts"] = float(1 + (i // 2) % 4)
    y = pd.Series([1 if i % 2 == 0 else 0 for i in range(40)], index=X.index)
    return X, y, pd.Series(list(X.index), index=X.index)


def toy_config(settings: Settings | None = None) -> Any:
    return (settings or duck_settings()).cases.prioritization


def fit_toy(**kw: Any) -> tuple[Any, pd.DataFrame, pd.Series, pd.Series]:
    X, y, groups = toy_frame()
    model = model_mod().fit_model(X, y, groups, toy_config(), seed=42, **kw)
    return model, X, y, groups


def is_even(case_id: str) -> bool:
    return int(case_id[3:5]) % 2 == 0


def float_keys(d: dict[Any, Any]) -> dict[float, Any]:
    """Metrics keyed by fraction: float keys in memory, string keys after a JSON round trip."""
    return {float(k): v for k, v in d.items()}


def logit_intercept(artifact: str) -> float:
    value = json.loads(artifact)["intercept"]
    return float(np.asarray(value, dtype=float).ravel()[0])


# ---------------------------------------------------------------- TINY-L
def make_tiny_l(db: Database, settings: Settings | None = None, *, final_run: bool = True) -> Any:
    """run_cases (run 1), 11 RULE-only cases FALSE_POSITIVE, 27 NETWORK-only SUSPICIOUS, run 2.

    ``final_run=False`` stops before run 2: the dispositions are recorded on run 1 and the next
    `run_cases` (for example the one inside `aml score`) is the run that closes the 38 cases.
    """
    settings = settings or duck_settings()
    run_cases(db, settings)
    cur = query(db, "SELECT case_id, sources FROM cases_current ORDER BY case_id")
    rule = [c for c, s in zip(cur["case_id"], cur["sources"], strict=True) if s == "RULE"]
    network = [c for c, s in zip(cur["case_id"], cur["sources"], strict=True) if s == "NETWORK"]
    for case_id in rule:
        record_disposition(db, settings, case_id, "FALSE_POSITIVE", reason="x", actor="analyst01")
    for case_id in network:
        record_disposition(db, settings, case_id, "SUSPICIOUS", reason="x", actor="analyst01")
    return run_cases(db, settings) if final_run else None


def table_digest(db: Database, table: str, order_by: str) -> list[tuple[Any, ...]]:
    df = query(db, f"SELECT * FROM {table} ORDER BY {order_by}")
    return [tuple(None if pd.isna(v) else str(v) for v in r) for r in df.itertuples(index=False)]


def audit_rows(db: Database, where: str) -> pd.DataFrame:
    return audit_cases(db, where)


def state_digest(db: Database) -> dict[str, list[tuple[Any, ...]]]:
    """Content of the tables a model must never touch (AC6)."""
    return {
        "case_dispositions": table_digest(db, "case_dispositions", "disposition_id"),
        "cases": table_digest(db, "cases", "run_id, case_id"),
        "case_alerts": table_digest(db, "case_alerts", "run_id, item_key, golden_customer_id"),
        "good_guy_list": table_digest(db, "good_guy_list", "entry_no"),
    }


def copy_tiny(stages: dict[str, Path], dest: Path, stage: str = "full") -> DuckDb:
    """A private writable DuckDB copy of a TINY stage (the `tiny_stages` fixture)."""
    shutil.copy(stages[stage], dest)
    return DuckDb(dest)


def text(value: Any) -> str:
    """A CLOB column as text (DuckDB returns str, Oracle a LOB)."""
    return str(value.read()) if hasattr(value, "read") else str(value)


def sigmoid(z: Any) -> Any:
    return 1.0 / (1.0 + np.exp(-np.asarray(z, dtype=float)))


def numpy_scores(artifact: str, features: pd.DataFrame) -> pd.Series:
    """Score a frame from a logreg `artifact` with NumPy only (AC6)."""
    a = json.loads(artifact)
    x = features[list(a["features"])].to_numpy(dtype=float)
    mean = np.asarray(a["mean"], dtype=float)
    scale = np.asarray(a["scale"], dtype=float)
    coef = np.asarray(a["coef"], dtype=float).ravel()
    z = ((x - mean) / scale) @ coef + logit_intercept(artifact)
    return pd.Series(sigmoid(z), index=features.index)


class Lazy:
    """Build an expensive read-only state once per module; the error is cached and re-raised.

    A module fixture would turn a missing 7c module into a setup ERROR; building inside the test
    keeps it a FAIL, and the cache keeps the cost at one build per file.
    """

    def __init__(self, build: Callable[..., Any]) -> None:
        self._build = build
        self._done = False
        self._value: Any = None
        self._error: BaseException | None = None

    def get(self, *args: Any) -> Any:
        if not self._done:
            try:
                self._value = self._build(*args)
            except BaseException as exc:
                self._error = exc
            self._done = True
        if self._error is not None:
            raise self._error
        return self._value


__all__ = [
    "CASE_C01_A",
    "CASE_C01_B",
    "CASE_C03",
    "CASE_C04",
    "CASE_C05",
    "EXPECTED_FEATURES",
    "FRACTION",
    "MINI_TRUTH",
    "PINNED",
    "SIM_ACTOR",
    "SIM_PREFIX",
    "TINY_TOP",
    "Lazy",
    "all_features",
    "audit_rows",
    "copy_tiny",
    "features_mod",
    "fit_toy",
    "float_keys",
    "insert_truth",
    "is_even",
    "js",
    "labels_mod",
    "logit_intercept",
    "make_tiny_l",
    "minigt",
    "model_mod",
    "numpy_scores",
    "prio_error",
    "prio_mod",
    "sigmoid",
    "source_of",
    "state_digest",
    "table_digest",
    "text",
    "toy_config",
    "toy_frame",
]
