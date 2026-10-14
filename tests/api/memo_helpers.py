"""Shared constants and helpers for the Phase 9d tests (specs/ui-memo-relabel.md)."""

from __future__ import annotations

from typing import Any

from aml.common.db import Database
from tests.memo.helpers import MODEL, SCRIPT, Stub, set_memos

from .helpers import api_settings, count, mod

__all__ = ["MODEL", "api_memo", "state", "tables"]

K_LOAN = "341c388f76f6a4d3c64ee0b9c2f27fef"
K_SAL = "65564dbab541a930d6e69a33bb4e0907"
K_INJ = "33c04fc4c32f7b9692e6002dec092e51"
K_CRY = "cb821efd04cda1860ba5bfed24b8019e"
K_GAM = "e56b5af5d87420613eaf89347c81361f"
C1 = "C-C01-20260302"
C5 = "C-C05-20260630"
NOPE = "C-NOPE-20260101"
V1 = "/api/v1"
TXN = f"{V1}/cases/{C1}/transactions"
MEMOS_URL = f"{V1}/memos"
GOOD = {"category": "suspicious_wording", "reason": "borrower is a known mule collector"}
KEYS9 = [
    "txn_id",
    "txn_ts",
    "from_account_id",
    "to_account_id",
    "amount_vnd",
    "channel",
    "memo",
    "counterparty_name",
    "item_keys",
]
KEYS12 = [*KEYS9, "memo_key", "memo_category", "memo_method"]
LABEL_KEYS = [
    "memo_key",
    "memo_norm",
    "category",
    "method",
    "transactions",
    "model_category",
    "model_method",
]
UNTOUCHED = (
    "cases",
    "case_alerts",
    "case_dispositions",
    "alerts",
    "case_scores",
    "case_models",
    "memo_classifications",
)
MEMO_STATE = (*UNTOUCHED, "memo_overrides", "memo_runs", "case_memo_features", "audit_log")


def relabel_url(key: str) -> str:
    return f"{V1}/memos/{key}/relabel"


def api_memo(db: Database) -> Database:
    """API-MEMO: (API-MINI already loaded) + the eight memos of MEMO-C + one classify run."""
    set_memos(db)
    mod("aml.memo.runner").classify_memos(db, api_settings(), Stub(SCRIPT))
    return db


def tables(db: Database, names: tuple[str, ...] = UNTOUCHED) -> dict[str, int]:
    return {t: count(db, t) for t in names}


def state(db: Database) -> dict[str, int]:
    return tables(db, MEMO_STATE)


def tri(row: dict[str, Any]) -> tuple[Any, Any, Any]:
    return row["memo_key"], row["memo_category"], row["memo_method"]
