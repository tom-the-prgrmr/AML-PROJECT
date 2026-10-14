"""Memo features of a case: six counts over the transactions of its stored window.

They live in their own table (`case_memo_features`), so the Phase 7c feature set and its stored
snapshots stay exactly as they are. The counts use the label in force (a person's label wins), and
`memo_suspicious_wording` only counts labels given by the rule layer or confirmed by a person: the
model gives that label to too many ordinary memos to be trusted on its own.

A run is written all or nothing: one memo without a label and no row is stored, so a value never
depends on when it was computed. `fit_guarded` keeps the three risk columns from ever lowering a
score, so nobody can push a case down the queue by typing a memo.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import pandas as pd

from aml.cases.items import sql_statement
from aml.cases.model import TrainedModel, fit_model
from aml.cases.values import in_filter, lower_columns
from aml.common.config import PrioritizationConfig, Settings
from aml.common.db import Database
from aml.memo.classify import SUSPICIOUS_WORDING
from aml.memo.normalize import MEMO_VERSION, memo_key, normalize_memo
from aml.memo.store import by_method, labels_rev, read_labels, scalar, scope

MEMO_FEATURES = (
    "memo_txns",
    "memo_salary",
    "memo_loan_repayment",
    "memo_gambling_like",
    "memo_crypto_like",
    "memo_suspicious_wording",
)
# Risk columns: a negative weight here would let a memo lower the score of its own case.
NON_NEGATIVE = ("memo_gambling_like", "memo_crypto_like", "memo_suspicious_wording")
MEMO_FEATURE_VERSION = "features/v1+memo/v1"
# Only these methods make a `suspicious_wording` label count (the model alone does not).
TRUSTED_SUSPICIOUS = ("RULE", "HUMAN")

Labels = dict[str, tuple[str, str]]  # memo_key -> (category, method) in force


def _content(value: Any) -> dict[str, Any]:
    """A JSON column as a dict (DuckDB returns text, Oracle text, a LOB or the parsed value)."""
    if hasattr(value, "read"):
        value = value.read()
    return dict(json.loads(value)) if isinstance(value, str) else dict(value)


def _windows(db: Database, run_id: int) -> dict[str, tuple[list[str], date, date] | None]:
    """Every case of a run with the CIFs and the transaction window its snapshot stored."""
    cases = lower_columns(db.query_df(f"SELECT case_id FROM cases WHERE run_id = {run_id}"))
    blocks = lower_columns(
        db.query_df(
            "SELECT case_id, section, content FROM case_enrichment "
            f"WHERE run_id = {run_id} AND section IN ('txn_summary', 'linked_cifs')"
        )
    )
    stored: dict[str, dict[str, dict[str, Any]]] = {}
    for case_id, section, content in zip(
        blocks["case_id"], blocks["section"], blocks["content"], strict=True
    ):
        stored.setdefault(str(case_id), {})[str(section)] = _content(content)
    out: dict[str, tuple[list[str], date, date] | None] = {}
    for case_id in sorted(str(c) for c in cases["case_id"]):
        txn = stored.get(case_id, {}).get("txn_summary", {})
        cifs = [str(c) for c in stored.get(case_id, {}).get("linked_cifs", {}).get("cifs") or []]
        if cifs and txn.get("window_start") and txn.get("window_end"):
            start, end = (date.fromisoformat(txn[k]) for k in ("window_start", "window_end"))
            out[case_id] = (cifs, start, end)
        else:
            out[case_id] = None  # a case without a stored window has no transactions to count
    return out


def case_memos(db: Database, cifs: list[str], start: date, end: date) -> list[Any]:
    """The memo of every transaction of the CIFs in [start, end]; one item per transaction."""
    sql = (
        sql_statement(db, "memo/case_memos.sql")
        .replace("{cif_filter}", in_filter("l.cif", cifs))
        .replace("{window_start}", f"DATE '{start.isoformat()}'")
        .replace("{window_end_next}", f"DATE '{(end + timedelta(days=1)).isoformat()}'")
    )
    return list(lower_columns(db.query_df(sql))["memo"])


def count_memos(memos: Sequence[Any], labels: Labels, max_chars: int) -> dict[str, float] | None:
    """The six counts of one case, or None when a memo has no label yet. Pure."""
    counts = dict.fromkeys(MEMO_FEATURES, 0.0)
    for memo in memos:
        norm = normalize_memo(memo, max_chars)
        if not norm:
            continue
        label = labels.get(memo_key(norm))
        if label is None:
            return None
        category, method = label
        counts["memo_txns"] += 1
        name = f"memo_{category}"
        if category == SUSPICIOUS_WORDING and method not in TRUSTED_SUSPICIOUS:
            continue  # stored and shown, but not counted until a person confirms it
        if name in counts:  # `other` has no column
            counts[name] += 1
    return counts


def _current(settings: Settings, run_id: int, rev: int) -> str:
    return f"run_id = {run_id} AND {scope(settings)} AND labels_rev = {rev}"


def write_memo_features(db: Database, settings: Settings, run_id: int) -> int:
    """Store the six counts of every case of a run; return the number of rows written.

    0 when the run already has rows for the current version, model and ``labels_rev``, when no memo
    has been classified yet, or when any memo in any case window still lacks a label.
    """
    rev = labels_rev(db)
    where = _current(settings, run_id, rev)
    if scalar(db, f"SELECT COUNT(*) FROM case_memo_features WHERE {where}"):
        return 0
    found = read_labels(db, settings)
    if found.empty:
        return 0
    labels: Labels = {
        key: (category, method)
        for key, category, method in zip(
            found["memo_key"], found["category"], found["method"], strict=True
        )
    }
    rows: list[dict[str, Any]] = []
    for case_id, window in _windows(db, run_id).items():
        memos = case_memos(db, *window) if window else []
        counts = count_memos(memos, labels, settings.memo.max_chars)
        if counts is None:
            return 0  # all or nothing
        rows += [
            {
                "run_id": run_id,
                "case_id": case_id,
                "memo_version": MEMO_VERSION,
                "llm_model": settings.ollama.llm_model,
                "labels_rev": rev,
                "feature": name,
                "value": value,
            }
            for name, value in counts.items()
        ]
    return db.insert_df("case_memo_features", pd.DataFrame(rows)) if rows else 0


def read_memo_features(db: Database, settings: Settings, run_id: int) -> pd.DataFrame | None:
    """Stored memo features of a run for the current labels: index ``case_id`` ascending, columns
    in `MEMO_FEATURES` order. None when they have not been written (or the labels changed since)."""
    where = _current(settings, run_id, labels_rev(db))
    df = lower_columns(
        db.query_df(f"SELECT case_id, feature, value FROM case_memo_features WHERE {where}")
    )
    if df.empty:
        return None
    wide = df.pivot(index="case_id", columns="feature", values="value").astype(float)
    wide = wide.reindex(columns=list(MEMO_FEATURES))
    wide.columns.name = None
    return wide.loc[sorted(wide.index)].rename_axis("case_id")


def ensure_memo_features(db: Database, settings: Settings, run_id: int) -> pd.DataFrame | None:
    """Memo features of a run, computed now if this is the first time they are needed."""
    write_memo_features(db, settings, run_id)
    return read_memo_features(db, settings, run_id)


def decided_memo_features(
    db: Database, settings: Settings, decided: pd.DataFrame
) -> pd.DataFrame | None:
    """Memo columns of the decided cases, each from the snapshot its decision saw.

    None when any of those snapshots has a memo without a label: training then falls back to the
    Phase 7c columns alone.
    """
    frames = []
    for run_id, part in decided.groupby("run_id"):
        frame = ensure_memo_features(db, settings, int(run_id))
        if frame is None:
            return None
        frames.append(frame.loc[list(part["case_id"])])
    return pd.concat(frames).sort_index() if frames else None


def memo_info(db: Database, settings: Settings, dropped: Sequence[str]) -> dict[str, Any]:
    """What a model that uses memo columns records about the labels it was trained on."""
    return {
        "version": MEMO_VERSION,
        "model": settings.ollama.llm_model,
        "labels_rev": labels_rev(db),
        "by_method": by_method(read_labels(db, settings)),
        "dropped_features": list(dropped),
    }


def _guarded(columns: Sequence[str], non_negative: Sequence[str]) -> list[str]:
    """The guarded columns present in the data, in `MEMO_FEATURES` order."""
    ordered = [c for c in MEMO_FEATURES if c in non_negative]
    ordered += [c for c in non_negative if c not in MEMO_FEATURES]
    return [c for c in ordered if c in columns]


def fit_guarded(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    cfg: PrioritizationConfig,
    *,
    seed: int,
    kind: str | None = None,
    non_negative: Sequence[str] = NON_NEGATIVE,
    populations: pd.Series | None = None,
) -> tuple[TrainedModel, tuple[str, ...]]:
    """`fit_model`, but a ``non_negative`` column never gets a negative weight.

    Logistic regression: fit, drop the guarded columns whose coefficient is negative, fit again,
    until none is left. LightGBM has no coefficient to check, so every guarded column is dropped
    before the fit. ``populations`` is passed to `fit_model` (metrics per population).
    Returns the model and the dropped columns.
    """
    kind = kind or cfg.model
    guarded = _guarded(list(X.columns), non_negative)
    if kind == "lightgbm":
        model = fit_model(
            X.drop(columns=guarded), y, groups, cfg, seed=seed, kind=kind, populations=populations
        )
        return model, tuple(guarded)
    dropped: set[str] = set()
    while True:
        model = fit_model(
            X.drop(columns=sorted(dropped)), y, groups, cfg, seed=seed, kind=kind,
            populations=populations,
        )  # fmt: skip
        artifact = json.loads(model.artifact)
        coef = dict(zip(artifact["features"], artifact["coef"], strict=True))
        negative = {c for c in guarded if c not in dropped and float(coef[c]) < 0}
        if not negative:
            return model, tuple(c for c in guarded if c in dropped)
        dropped |= negative


def _delta(with_memo: Any, base: Any) -> float | None:
    return None if with_memo is None or base is None else round(float(with_memo) - float(base), 4)


def delta(with_memo: dict[str, Any], base: dict[str, Any], prefix: str) -> dict[str, float | None]:
    """``with_memo - base`` for ROC-AUC and PR-AUC; None when either side is missing."""
    return {
        f"{prefix}_{name}": _delta(with_memo.get(name), base.get(name))
        for name in ("roc_auc", "pr_auc")
    }


def fit_pair(
    X_base: pd.DataFrame,
    X_memo: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    cfg: PrioritizationConfig,
    *,
    seed: int,
    kind: str | None = None,
) -> tuple[TrainedModel, TrainedModel, tuple[str, ...]]:
    """The model without and the model with the memo columns: same cases, folds and seed."""
    base = fit_model(X_base, y, groups, cfg, seed=seed, kind=kind)
    with_memo, dropped = fit_guarded(X_memo, y, groups, cfg, seed=seed, kind=kind)
    return base, with_memo, dropped


def compare_feature_sets(
    X_base: pd.DataFrame,
    X_memo: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    cfg: PrioritizationConfig,
    *,
    seed: int,
    kind: str | None = None,
) -> dict[str, Any]:
    """Cross-validated metrics of both feature sets and their difference. Pure; stores nothing."""
    base, with_memo, dropped = fit_pair(X_base, X_memo, y, groups, cfg, seed=seed, kind=kind)
    return {
        "base": {"features": len(base.features), "cv": base.metrics},
        "with_memo": {
            "features": len(with_memo.features),
            "dropped_features": list(dropped),
            "cv": with_memo.metrics,
        },
        "delta": delta(with_memo.metrics, base.metrics, "cv"),
    }
