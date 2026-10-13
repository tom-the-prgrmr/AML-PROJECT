"""Hibernation: read what people cleared as false positives and apply the pure rule to new alerts.

A pattern is one (golden customer, rule) pair. It is built from the latest disposition of each
case, when that disposition is FALSE_POSITIVE, and from the case snapshot the disposition refers
to. Reads only; `aml.cases.suppression` turns the outcomes into stored statuses and audit events.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from aml.cases.items import sql_statement
from aml.cases.suppression_rules import (
    HIBERNATION,
    HibernationPattern,
    Outcome,
    hibernation_verdict,
)
from aml.cases.values import lower_columns, plain_date, whole
from aml.common.config import Settings
from aml.common.db import Database

__all__ = ["hibernation_outcomes"]

_HIBERNATING_SOURCES = ("RULE", "NETWORK")  # a screening item never hibernates


def _load_patterns(db: Database) -> dict[tuple[str, str], HibernationPattern]:
    """One pattern per (golden customer, rule) from the cases cleared as false positives.

    ``handled`` holds every item of those cases' snapshots: they stay in their closed case.
    """
    df = lower_columns(db.query_df(sql_statement(db, "cases/hibernation.sql")))
    patterns: dict[tuple[str, str], HibernationPattern] = {}
    for (golden, rule_id), g in df.groupby(["golden_customer_id", "rule_id"]):
        keys = frozenset(str(k) for k in g["item_key"])
        patterns[(str(golden), str(rule_id))] = HibernationPattern(
            golden_customer_id=str(golden),
            rule_id=str(rule_id),
            false_positives=len(keys),
            cleared_on=max(plain_date(d) for d in g["decided_on"]),
            max_amount_vnd=int(g["amount_vnd"].max()),
            handled=keys,
        )
    return patterns


def hibernation_outcomes(
    db: Database, settings: Settings, items: pd.DataFrame
) -> dict[int, Outcome]:
    """RULE / NETWORK items (by index) that hibernate or whose hibernation was lifted."""
    cfg = settings.cases.suppression
    candidates = items[items["source"].isin(_HIBERNATING_SOURCES)]
    if candidates.empty:
        return {}
    patterns = _load_patterns(db)
    out: dict[int, Outcome] = {}
    for r in candidates.itertuples():
        pattern = patterns.get((str(r.golden_customer_id), str(r.rule_id)))
        if pattern is None:
            continue
        verdict = hibernation_verdict(
            pattern,
            item_key=str(r.item_key),
            event_ts=pd.Timestamp(r.event_ts).to_pydatetime(),
            amount_vnd=whole(r.amount_vnd),
            cfg=cfg,
        )
        if verdict.suppress or verdict.lifted:
            until = pattern.cleared_on + timedelta(days=cfg.hibernation_days)
            out[int(r.Index)] = Outcome(HIBERNATION, verdict, pattern.cleared_on, until)
    return out
