"""A person corrects or confirms the label of one memo key (`aml memo relabel`, `aml memo list`).

The model proposes, a person decides. A relabel is a new row in `memo_overrides` with the person's
name and reason; the answer of the rule layer or the model is never changed or removed, so reports
still show what the model said. Relabelling raises no alert and changes no case: the memo features
follow at the next scoring run, because the stored feature rows carry the label revision.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.classify import CATEGORIES, MemoError
from aml.memo.normalize import MEMO_VERSION
from aml.memo.store import METHODS, MODULE, labels_rev, now, read_labels

__all__ = ["METHODS", "Relabel", "labels_rev", "list_labels", "relabel_memo"]

MIN_PREFIX = 8
MAX_REASON = 500  # the width of memo_overrides.reason


@dataclass(frozen=True)
class Relabel:
    override_id: int
    memo_key: str
    category: str
    previous_category: str  # the label in force just before this decision
    previous_method: str
    actor: str


def list_labels(
    db: Database, settings: Settings, *, category: str | None = None, method: str | None = None
) -> pd.DataFrame:
    """Every classified key with its label in force and what the rule / model said.

    Columns: memo_key, memo_norm, category, method, transactions, model_category, model_method;
    ordered by ``memo_norm``. ``memo_norm`` is untrusted text, shown for a person to compare.
    """
    labels = read_labels(db, settings)
    if category is not None:
        labels = labels[labels["category"] == category]
    if method is not None:
        labels = labels[labels["method"] == method]
    return labels.reset_index(drop=True)


def _find(labels: pd.DataFrame, key: str) -> pd.Series:
    """The one label row a full key or a prefix of at least `MIN_PREFIX` characters points at."""
    if len(key) < MIN_PREFIX:
        raise MemoError(f"memo key prefix must be at least {MIN_PREFIX} characters")
    hits = labels[labels["memo_key"].str.startswith(key)]
    if hits.empty:
        raise MemoError(f"unknown memo key {key}: run `aml memo list` to see the keys")
    if len(hits) > 1:
        raise MemoError(f"ambiguous memo key prefix {key}: it matches {len(hits)} keys")
    return hits.iloc[0]


def relabel_memo(
    db: Database, settings: Settings, key: str, category: str, *, reason: str, actor: str
) -> Relabel:
    """Record a person's label for a key that `aml memo classify` has already handled.

    Every check comes before the write. The override row and its ``MEMO_RELABELLED`` audit row go
    in one transaction. Relabelling to the label a key already has is allowed: it is how a person
    confirms what the model said.
    """
    if not reason.strip():
        raise ValueError("a relabel needs a reason")
    if len(reason) > MAX_REASON:
        raise ValueError(f"a relabel reason is at most {MAX_REASON} characters")
    if actor == settings.audit.system_actor:
        raise MemoError("a relabel needs a human actor, not the system actor")
    if category not in CATEGORIES:
        raise MemoError(f"unknown category '{category}': use one of {', '.join(CATEGORIES)}")
    row = _find(read_labels(db, settings), key)
    override_id = 1 + labels_rev(db)
    result = Relabel(
        override_id=override_id,
        memo_key=str(row["memo_key"]),
        category=category,
        previous_category=str(row["category"]),
        previous_method=str(row["method"]),
        actor=actor,
    )
    override = {
        "override_id": override_id,
        "memo_key": result.memo_key,
        "memo_version": MEMO_VERSION,
        "llm_model": settings.ollama.llm_model,
        "category": category,
        "previous_category": result.previous_category,
        "previous_method": result.previous_method,
        "reason": reason,
        "actor": actor,
        "decided_ts": now(),
    }
    with db.transaction():
        db.insert_df("memo_overrides", pd.DataFrame([override]))
        audit(
            db,
            module=MODULE,
            entity_type="memo",
            entity_id=result.memo_key,
            decision="MEMO_RELABELLED",
            reason=reason,  # the person's own words, stored as data
            version=MEMO_VERSION,
            actor=actor,
            details={
                "override_id": override_id,
                "category": category,
                "previous_category": result.previous_category,
                "previous_method": result.previous_method,
                "model_category": str(row["model_category"]),
                "model_method": str(row["model_method"]),
            },
        )
    return result
