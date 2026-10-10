"""Partition-pruning evidence: queries on ``transactions`` and their Oracle execution plans."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from aml.common.config import Settings
from aml.common.db import Database


@dataclass(frozen=True)
class PruningQuery:
    name: str
    sql: str
    expected_op: str


def _month_start(start: date, offset: int) -> date:
    """First day of the month ``offset`` months after the month of ``start``."""
    index = start.year * 12 + start.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


def _total(where: str = "") -> str:
    return f"SELECT SUM(amount_vnd) FROM transactions{where}"


def _between(start: date, first: int, after: int) -> str:
    lo, hi = _month_start(start, first), _month_start(start, after)
    return (
        f" WHERE txn_ts >= TIMESTAMP '{lo.isoformat()} 00:00:00'"
        f" AND txn_ts < TIMESTAMP '{hi.isoformat()} 00:00:00'"
    )


def pruning_queries(settings: Settings) -> list[PruningQuery]:
    """One query per pruning shape; literal predicates (no binds) keep Pstart/Pstop static."""
    start = settings.data.start_date
    return [
        PruningQuery("single", _total(_between(start, 1, 2)), "PARTITION RANGE SINGLE"),
        PruningQuery("iterator", _total(_between(start, 1, 3)), "PARTITION RANGE ITERATOR"),
        PruningQuery("all", _total(), "PARTITION RANGE ALL"),
    ]


def explain_plan(db: Database, sql: str) -> str:
    """Return the ``DBMS_XPLAN`` TYPICAL plan text for ``sql`` (Oracle only)."""
    if db.backend != "oracle":
        raise NotImplementedError("explain_plan is Oracle only")
    statement_id = f"PRUNE_{uuid.uuid4().hex[:20]}"
    db.execute(f"EXPLAIN PLAN SET STATEMENT_ID = '{statement_id}' FOR {sql}")
    df = db.query_df(
        "SELECT plan_table_output FROM TABLE(DBMS_XPLAN.DISPLAY("
        f"'PLAN_TABLE', '{statement_id}', 'TYPICAL'))"
    )
    db.execute(f"DELETE FROM plan_table WHERE statement_id = '{statement_id}'")
    return "\n".join(str(line) for line in df["plan_table_output"])
