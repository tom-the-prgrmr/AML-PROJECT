"""Reads and writes of the memo tables. Rows are only ever inserted.

Every lookup is by the pair (`MEMO_VERSION`, model): labels of another prompt version or another
model are kept but never mixed in. A person's label is stored by key in `memo_overrides` and wins
over the rule or the model in the view `memo_labels_current`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from aml.cases.values import lower_columns
from aml.common.audit import AuditEvent
from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.classify import CATEGORIES, Classification
from aml.memo.normalize import MEMO_VERSION

MODULE = "memo"
METHODS = ("RULE", "LLM", "HUMAN", "FALLBACK")
LABEL_COLUMNS = [
    "memo_key", "memo_norm", "category", "method", "transactions", "model_category",
    "model_method",
]  # fmt: skip


def scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def quoted(text: str) -> str:
    """A SQL string literal (the values come from config or from code, never from a memo)."""
    return "'" + text.replace("'", "''") + "'"


def scope(settings: Settings) -> str:
    """The WHERE condition that selects the labels of the current prompt version and model."""
    model = quoted(settings.ollama.llm_model)
    return f"memo_version = {quoted(MEMO_VERSION)} AND llm_model = {model}"


def now() -> datetime:
    """UTC without tzinfo: what both backends store in a TIMESTAMP column."""
    return datetime.now(UTC).replace(tzinfo=None)


def read_labels(db: Database, settings: Settings) -> pd.DataFrame:
    """The label in force of every classified key, ordered by ``memo_norm`` (sorted in Python so
    both backends give the same order)."""
    df = lower_columns(
        db.query_df(
            f"SELECT {', '.join(LABEL_COLUMNS)} FROM memo_labels_current WHERE {scope(settings)}"
        )
    )
    df = df.astype({c: str for c in LABEL_COLUMNS if c != "transactions"})
    df["transactions"] = df["transactions"].astype(int)
    return df.sort_values("memo_norm", kind="stable").reset_index(drop=True)


SCHEMA_MISSING = (
    "memo features skipped: the memo tables do not exist (the schema predates DDL 190; "
    "run `aml init-db`)"
)


def memo_schema_ready(db: Database) -> bool:
    """True when the DDL 190 objects exist (a database built before Phase 8d has none)."""
    if db.backend == "oracle":
        sql = (
            "SELECT COUNT(*) FROM user_views WHERE view_name = 'MEMO_LABELS_CURRENT'"
            " UNION ALL "
            "SELECT COUNT(*) FROM user_tables WHERE table_name = 'CASE_MEMO_FEATURES'"
        )
    else:
        sql = (
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name IN ('memo_labels_current', 'case_memo_features')"
        )
    return int(db.query_df(sql).iloc[:, 0].astype(int).sum()) == 2


def labels_rev(db: Database) -> int:
    """The newest ``override_id``; 0 when nobody has relabelled a memo yet."""
    return scalar(db, "SELECT COALESCE(MAX(override_id), 0) FROM memo_overrides")


def count_by(labels: pd.DataFrame, column: str, names: Sequence[str]) -> dict[str, int]:
    """Number of keys per value of ``column``, with every name present (0 when it has none)."""
    counts = labels[column].value_counts()
    return {name: int(counts.get(name, 0)) for name in names}


def by_method(labels: pd.DataFrame) -> dict[str, int]:
    return count_by(labels, "method", METHODS)


def by_category(labels: pd.DataFrame) -> dict[str, int]:
    return count_by(labels, "category", CATEGORIES)


def classification_event(
    c: Classification, *, run_id: int, model: str, transactions: int, actor: str
) -> AuditEvent:
    """The audit row of one classified key. The memo text is not part of it."""
    return AuditEvent(
        module=MODULE,
        entity_type="memo",
        entity_id=c.memo_key,
        decision="MEMO_CLASSIFIED",
        reason=c.reason,
        version=MEMO_VERSION,
        actor=actor,
        details={
            "run_id": run_id,
            "category": c.category,
            "method": c.method,
            "attempts": c.attempts,
            "pattern": c.pattern,
            "model": model,
            "transactions": transactions,
        },
    )


def insert_classifications(
    db: Database, *, run_id: int, model: str, rows: Sequence[tuple[Classification, int]]
) -> None:
    """Store the answers for some keys; each row carries its transaction count at that moment."""
    stamp = now()
    frame: list[dict[str, Any]] = [
        {
            "run_id": run_id,
            "memo_key": c.memo_key,
            "memo_version": MEMO_VERSION,
            "llm_model": model,
            "memo_norm": c.memo_norm,
            "category": c.category,
            "method": c.method,
            "attempts": c.attempts,
            "pattern": c.pattern,
            "transactions": transactions,
            "reason": c.reason,
            "classified_ts": stamp,
        }
        for c, transactions in rows
    ]
    db.insert_df("memo_classifications", pd.DataFrame(frame))
