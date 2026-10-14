"""Helpers for the specs/datagen-memos.md tests: TINY runs with risk memos on or off."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import load_settings

OFF = {
    "AML__DATA__RISK_MEMOS__BACKGROUND_RATE": "0",
    "AML__DATA__RISK_MEMOS__TYPOLOGY_RATE": "0",
}
INJECTABLE = {"INTERNAL_TRANSFER", "INTERBANK_TRANSFER", "EBANKING"}


def tiny_env_dict(**extra: str) -> dict[str, str]:
    """The env of the ``tiny_parquet`` fixture (tests/datagen/conftest.py) plus ``extra``."""
    env = {
        "DB_BACKEND": "duckdb",
        "AML__SEED": "42",
        "AML__DATA__INJECTION_MEMOS": "6",
        "AML__DATA__WATCHLIST__ENTRIES": "200",
        "AML__DATA__WATCHLIST__TRUE_HITS": "5",
        "AML__DATA__WATCHLIST__TRAPS": "6",
        "AML__DATA__PROFILES__SMALL__CUSTOMERS": "300",
        "AML__DATA__PROFILES__SMALL__TRANSACTIONS": "5000",
        "AML__DATA__PROFILES__SMALL__MONTHS": "6",
        "AML__DATA__TYPOLOGIES__STRUCTURING": "2",
        "AML__DATA__TYPOLOGIES__RAPID_MOVEMENT": "2",
        "AML__DATA__TYPOLOGIES__MULE_RING": "1",
        "AML__DATA__TYPOLOGIES__ROUND_TRIPPING": "2",
        "AML__DATA__TYPOLOGIES__BENIGN_PAYROLL": "1",
        "AML__DATA__TYPOLOGIES__BENIGN_MERCHANT": "1",
    }
    env.update(extra)
    return env


def run_tiny(out: Path, **extra: str) -> Path:
    """``run_pipeline`` on TINY (seed 42 unless overridden) into ``out``."""
    pipeline: Any = importlib.import_module("aml.datagen.pipeline")
    pipeline.run_pipeline(load_settings(environ=tiny_env_dict(**extra)), out)
    return out


def risk_patterns() -> list[tuple[str, str, re.Pattern[str]]]:
    """(kind, template, full-match regex) for the 12 risk templates; ``{ref}`` is 2-3 digits."""
    memos: Any = importlib.import_module("aml.datagen.memos")
    out = []
    for kind, templates in (("gambling", memos.GAMBLING_MEMOS), ("crypto", memos.CRYPTO_MEMOS)):
        for template in templates:
            pattern = re.escape(template).replace(re.escape("{ref}"), r"\d{2,3}")
            out.append((kind, template, re.compile(pattern)))
    return out


def risk_template(memo: object) -> str | None:
    """The template a risk memo was generated from, or None for any other value."""
    if not isinstance(memo, str):
        return None
    for _, template, rx in risk_patterns():
        if rx.fullmatch(memo):
            return template
    return None


def risk_kind(memo: object) -> str | None:
    """'gambling' / 'crypto' when ``memo`` is a risk memo, else None."""
    if not isinstance(memo, str):
        return None
    for kind, _, rx in risk_patterns():
        if rx.fullmatch(memo):
            return kind
    return None


def read_tx(pq: Path) -> pd.DataFrame:
    return pd.read_parquet(pq / "transactions.parquet")


def read_gt(pq: Path) -> pd.DataFrame:
    return pd.read_parquet(pq / "ground_truth.parquet")


def memo_differs(a: pd.DataFrame, b: pd.DataFrame) -> pd.Series:
    """True where the memo of row i differs between ``a`` and ``b`` (null equals null)."""
    same = (a["memo"] == b["memo"]) | (a["memo"].isna() & b["memo"].isna())
    return ~same


def suspicious_evidence_ids(gt: pd.DataFrame) -> set[str]:
    sel = gt[
        gt["is_suspicious"] & (gt["role"] == "evidence") & (gt["entity_type"] == "transaction")
    ]
    return set(sel["entity_id"])


def risk_ids(tx: pd.DataFrame) -> set[str]:
    mask = tx["memo"].map(risk_kind).notna()
    return set(tx.loc[mask, "txn_id"])
