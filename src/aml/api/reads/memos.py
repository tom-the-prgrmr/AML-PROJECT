"""Memo label reads of the API: the labels in force, as plain JSON data."""

from __future__ import annotations

from typing import Any

from aml.common.config import Settings
from aml.common.db import Database
from aml.memo.normalize import MEMO_VERSION
from aml.memo.relabel import list_labels

COLUMNS = (
    "memo_key", "memo_norm", "category", "method", "transactions", "model_category",
    "model_method",
)  # fmt: skip


def list_memo_labels(
    db: Database,
    settings: Settings,
    *,
    category: str | None,
    method: str | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Labels in force ordered by ``memo_norm``, filtered then paged; returns ``(rows, meta)``."""
    df = list_labels(db, settings, category=category, method=method)
    page = df.iloc[offset : offset + limit]
    rows = [
        {c: (int(row[c]) if c == "transactions" else str(row[c])) for c in COLUMNS}
        for _, row in page.iterrows()
    ]
    meta = {
        "total": len(df),
        "limit": limit,
        "offset": offset,
        "memo_version": MEMO_VERSION,
        "llm_model": settings.ollama.llm_model,
    }
    return rows, meta


def labels_by_key(db: Database, settings: Settings) -> dict[str, tuple[str, str]]:
    """``{memo_key: (category, method)}`` of every classified key."""
    df = list_labels(db, settings)
    return {
        str(row["memo_key"]): (str(row["category"]), str(row["method"])) for _, row in df.iterrows()
    }
