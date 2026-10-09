"""Append-only audit trail. Every automated decision in the toolkit goes through here.

Each event stores *what* was decided, *why* (a human-readable ``reason``), *by whom*
(system or user actor) and *with which logic* (rule / model / prompt ``version``).
Module-specific extras (e.g. the assistant's question, generated Cypher, retrieved IDs)
go into the JSON ``details`` column so the core schema stays stable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from aml.common.config import get_settings
from aml.common.db import Database


class AuditEvent(BaseModel):
    module: str
    entity_type: str
    entity_id: str
    decision: str
    reason: str = Field(min_length=1)
    version: str | None = None
    actor: str = Field(default_factory=lambda: get_settings().audit.system_actor)
    details: dict[str, Any] | None = None
    event_ts: datetime = Field(default_factory=lambda: datetime.now(UTC))


AUDIT_COLUMNS = [
    "event_ts", "module", "entity_type", "entity_id",
    "decision", "reason", "version", "actor", "details",
]  # fmt: skip


def audit_many(db: Database, events: Iterable[AuditEvent]) -> int:
    """Write a batch of audit events in one round-trip; return the number written."""
    rows = [
        {
            **e.model_dump(exclude={"details", "event_ts"}),
            # Oracle TIMESTAMP WITH TIME ZONE / DuckDB TIMESTAMPTZ both accept naive UTC here.
            "event_ts": e.event_ts.astimezone(UTC).replace(tzinfo=None),
            "details": json.dumps(e.details, ensure_ascii=False) if e.details else None,
        }
        for e in events
    ]
    if not rows:
        return 0
    return db.insert_df("audit_log", pd.DataFrame(rows, columns=AUDIT_COLUMNS))


def audit(db: Database, **fields: Any) -> None:
    """Write a single audit event, e.g. ``audit(db, module=..., decision=..., reason=...)``."""
    audit_many(db, [AuditEvent(**fields)])
