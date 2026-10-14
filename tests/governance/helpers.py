"""Helpers for the Phase 7b-iii tests (specs/ml-governance.md): TINY-B, TINY-L, module access.

TINY-B is `tiny_cases` after `run_cases` (run 1, 52 cases); TINY-L is the state of
specs/case-prioritization.md (run 2 current, 38 dispositions). Both pin the graph feature source
to networkx and use a below-the-line sample size of 50 unless told otherwise.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings
from aml.common.db import Database, DuckDb
from tests.cases.helpers import cli, count, duck_settings, js, mod, query, run_cases, scalar
from tests.cases.prio_helpers import PINNED, copy_tiny, make_tiny_l, table_digest
from tests.memo.helpers import MODEL, Stub, risk_script

SAMPLE = "AML__CASES__PRIORITIZATION__BELOW_THE_LINE__SAMPLE_SIZE"
SIMULATE = "AML__CASES__PRIORITIZATION__SIMULATE_DISPOSITIONS"
BTL_LAST_LINE = (
    "below-the-line sample is measurement only: no customer was alerted, closed or cleared"
)
NEVER_ACTS = "This model never closes, clears, files or dispositions anything."
DECISION_TABLES = (
    ("case_dispositions", "disposition_id"),
    ("good_guy_list", "entry_no"),
    ("case_alerts", "run_id, item_key, golden_customer_id"),
    ("alerts", "alert_id"),
    ("screening_results", "run_id, cif, entry_id"),
)


def btl_settings(size: int = 50, **env: str) -> Settings:
    """DuckDB settings of the 7b-iii tests: networkx features, a sample of ``size`` customers."""
    return duck_settings(**PINNED, **{SAMPLE: str(size)}, **env)


def build_tiny_b(
    stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory, **env: str
) -> tuple[DuckDb, Settings]:
    """A private TINY-B: the TINY stage after DQ, then `run_cases` (run 1)."""
    db = copy_tiny(stages, tmp_path_factory.mktemp("btl_b") / "b.duckdb")
    settings = btl_settings(**env)
    run_cases(db, settings)
    return db, settings


def build_tiny_l(
    stages: dict[str, Path], tmp_path_factory: pytest.TempPathFactory, **env: str
) -> tuple[DuckDb, Settings]:
    """A private TINY-L (run 2 current, 27 SUSPICIOUS and 11 FALSE_POSITIVE dispositions)."""
    db = copy_tiny(stages, tmp_path_factory.mktemp("btl_l") / "l.duckdb")
    settings = btl_settings(**env)
    make_tiny_l(db, settings)
    return db, settings


def stub_risk() -> Stub:
    """STUB(RISK) of specs/memo-analysis.md: gambling / crypto templates, `other` for the rest."""
    return Stub(risk_script())


def btl() -> Any:
    return importlib.import_module("aml.cases.btl")


def btl_model() -> Any:
    return importlib.import_module("aml.cases.btl_model")


def prio() -> Any:
    return importlib.import_module("aml.cases.prioritize")


def prio_store() -> Any:
    return importlib.import_module("aml.cases.prio_store")


def cards() -> Any:
    return importlib.import_module("aml.governance.cards")


def audit_check() -> Any:
    return importlib.import_module("aml.governance.audit_check")


def guard() -> Any:
    return importlib.import_module("aml.governance.guard")


def prio_error() -> type[Exception]:
    return importlib.import_module("aml.cases.model").PrioritizationError  # type: ignore[no-any-return]


def case_error() -> type[Exception]:
    return importlib.import_module("aml.cases.runner").CaseError  # type: ignore[no-any-return]


def audit_df(db: Database, where: str) -> pd.DataFrame:
    """audit_log rows (oldest first) with ``details`` parsed into a dict (or None)."""
    df = query(
        db,
        "SELECT module, entity_type, entity_id, decision, reason, version, actor, details "
        f"FROM audit_log WHERE {where} ORDER BY audit_id",
    )
    df["details"] = [js(d) if isinstance(d, str) else None for d in df["details"]]
    return df


def decision_digest(db: Database) -> dict[str, Any]:
    """Content of the tables where a decision lives, and the status of every case of every run."""
    out: dict[str, Any] = {t: table_digest(db, t, order) for t, order in DECISION_TABLES}
    out["case_status"] = table_digest(db, "cases", "run_id, case_id")
    return out


def counts(db: Database, *tables: str) -> list[int]:
    return [count(db, t) for t in tables]


__all__ = [
    "BTL_LAST_LINE",
    "MODEL",
    "NEVER_ACTS",
    "PINNED",
    "SAMPLE",
    "SIMULATE",
    "audit_check",
    "audit_df",
    "btl",
    "btl_model",
    "btl_settings",
    "build_tiny_b",
    "build_tiny_l",
    "cards",
    "case_error",
    "cli",
    "count",
    "counts",
    "decision_digest",
    "guard",
    "js",
    "mod",
    "prio",
    "prio_error",
    "prio_store",
    "query",
    "scalar",
    "stub_risk",
]
