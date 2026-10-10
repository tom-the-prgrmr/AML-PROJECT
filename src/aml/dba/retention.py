"""Retention: archive then drop the monthly ``transactions`` partitions older than the cutoff.

Legal note: under the Vietnamese Anti-Money Laundering Law 2022 (Luat Phong, chong rua tien
2022, No. 14/2022/QH15), reporting entities must keep transaction records for at least
5 years from the date the transaction occurred (customer identification records: 5 years from
the end of the transaction / account closure). The hard floor is therefore 60 months and a
lower configuration is rejected. Synthetic-data demo, not legal advice; the article number is
deliberately not cited until the user confirms it.

Per partition (stop at the first error; finished partitions stay finished):
archive to Parquet -> read back and compare the row count -> ``DROP PARTITION ... UPDATE GLOBAL
INDEXES`` -> audit ``PARTITION_DROPPED``. ``audit_log`` is never purged. If at least one
partition was dropped, ``acct_edge_daily`` is refreshed exactly once, also when a later
partition failed: the materialized view is already stale as soon as one partition is gone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.datagen.transactions import TRANSACTION_COLUMNS
from aml.dba.edges import refresh_acct_edge_daily

LEGAL_MIN_MONTHS = 60  # Law 14/2022/QH15: keep transaction records for >= 5 years
ANCHOR_PARTITION = "P_BEFORE_2000"  # range anchor of the interval table, never dropped
PURGEABLE_TABLES = ("transactions",)  # audit_log is deliberately absent

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_$#]{0,127}")


class RetentionError(ValueError):
    """The purge was refused or an archive step failed."""


@dataclass(frozen=True)
class PartitionAction:
    partition: str  # Oracle partition name, e.g. "SYS_P801"
    month: str  # "YYYY-MM": the data month (high value minus one month)
    rows: int  # COUNT(*) of the partition when the plan was made
    archive_path: Path  # <archive_dir>/transactions/transactions_<month>.parquet


@dataclass(frozen=True)
class PurgePlan:
    table: str
    as_of: date
    retention_months: int
    cutoff: datetime  # midnight on the first day of as_of's month, minus retention_months
    drop: tuple[PartitionAction, ...]  # ascending by month
    executed: bool  # False = dry run


def retention_cutoff(as_of: date, retention_months: int) -> datetime:
    """First day of ``as_of``'s month, ``retention_months`` earlier; enforces the legal floor."""
    if retention_months < LEGAL_MIN_MONTHS:
        raise RetentionError(
            f"retention of {retention_months} months is below the legal minimum of "
            f"{LEGAL_MIN_MONTHS} months"
        )
    year, month0 = divmod(as_of.year * 12 + as_of.month - 1 - retention_months, 12)
    return datetime(year, month0 + 1, 1)


def _month_before(high_value: datetime) -> str:
    year, month0 = divmod(high_value.year * 12 + high_value.month - 2, 12)
    return f"{year:04d}-{month0 + 1:02d}"


def _high_value(raw: object) -> datetime:
    """``high_value_json`` arrives as a dict or a JSON string depending on the driver."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    return datetime.fromisoformat(str(raw["high_value"]))  # type: ignore[index]


def _identifier(name: str) -> str:
    if not _IDENTIFIER.fullmatch(name):
        raise RetentionError(f"unsafe partition name from the data dictionary: {name!r}")
    return name


def _plan_actions(
    db: Database, settings: Settings, cutoff: datetime
) -> tuple[PartitionAction, ...]:
    parts = db.query_df(
        "SELECT partition_name, high_value_json FROM user_tab_partitions "
        "WHERE table_name = 'TRANSACTIONS'"
    )
    root = settings.path(settings.retention.archive_dir) / "transactions"
    old = sorted(
        (_high_value(raw), _identifier(str(name)))
        for name, raw in zip(parts["partition_name"], parts["high_value_json"], strict=True)
        if str(name) != ANCHOR_PARTITION and _high_value(raw) <= cutoff
    )
    actions = []
    for high, name in old:
        rows = db.query_df(f"SELECT COUNT(*) AS n FROM transactions PARTITION ({name})")
        month = _month_before(high)
        actions.append(
            PartitionAction(
                name, month, int(rows["n"].iloc[0]), root / f"transactions_{month}.parquet"
            )
        )
    return tuple(actions)


def _write_archive(df: pd.DataFrame, target: Path) -> None:
    """Write ``df`` to ``target`` via a temp file; never overwrite; verify the row count."""
    if target.exists():
        raise RetentionError(f"archive already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")  # keeps the month, does not end in .parquet
    try:
        df.to_parquet(tmp)
        tmp.rename(target)
    finally:
        tmp.unlink(missing_ok=True)
    stored = len(pd.read_parquet(target))
    if stored != len(df):
        target.unlink()
        raise RetentionError(f"archive row count mismatch for {target}: {stored} != {len(df)}")


def _archive_partition(db: Database, action: PartitionAction) -> Path | None:
    # Always re-read: rows that arrived after planning must never be dropped unarchived.
    df = db.query_df(
        f"SELECT {', '.join(TRANSACTION_COLUMNS)} FROM transactions "
        f"PARTITION ({_identifier(action.partition)}) ORDER BY txn_id"
    )
    if len(df) != action.rows:
        raise RetentionError(
            f"partition {action.partition} changed since planning: {len(df)} != {action.rows} rows"
        )
    if action.rows == 0:
        return None
    _write_archive(df, action.archive_path)
    return action.archive_path


def _drop_partition(db: Database, action: PartitionAction) -> Path | None:
    """Archive, verify, then drop one partition. Returns the archive path (None if empty)."""
    archived = _archive_partition(db, action)
    db.execute(
        f"ALTER TABLE transactions DROP PARTITION {_identifier(action.partition)} "
        "UPDATE GLOBAL INDEXES"
    )
    return archived


def _audit_drop(
    db: Database, plan: PurgePlan, action: PartitionAction, archived: Path | None
) -> None:
    where = f"archived to {archived}" if archived else "empty partition, nothing to archive"
    audit(
        db,
        module="dba",
        entity_type="partition",
        entity_id=f"transactions:{action.month}",
        decision="PARTITION_DROPPED",
        reason=(
            f"Dropped partition {action.partition} ({action.rows} rows, {where}) with UPDATE "
            f"GLOBAL INDEXES: older than cutoff {plan.cutoff.date()} "
            f"({plan.retention_months} months retention)."
        ),
        details={
            "rows": action.rows,
            "archive_path": str(archived) if archived else None,
            "cutoff": plan.cutoff.date().isoformat(),
            "retention_months": plan.retention_months,
        },
    )


def purge_transactions(
    db: Database,
    settings: Settings,
    *,
    as_of: date | None = None,
    dry_run: bool = True,
    table: str = "transactions",
) -> PurgePlan:
    """Plan (and unless ``dry_run``, execute) the purge of old ``transactions`` partitions."""
    if table not in PURGEABLE_TABLES:
        raise RetentionError(
            f"{table} is excluded from purge (purgeable: {', '.join(PURGEABLE_TABLES)})"
        )
    months = settings.retention.transactions_months
    as_of = as_of or settings.data.reference_date
    cutoff = retention_cutoff(as_of, months)  # legal floor, before any DB query
    if db.backend != "oracle":
        raise RetentionError("retention is Oracle only (partitions); active backend is duckdb")

    plan = PurgePlan(table, as_of, months, cutoff, _plan_actions(db, settings, cutoff), not dry_run)
    if dry_run:
        audit(
            db,
            module="dba",
            entity_type="table",
            entity_id=table,
            decision="RETENTION_DRY_RUN",
            reason=(
                f"Dry run: {len(plan.drop)} partition(s) of {table} older than cutoff "
                f"{cutoff.date()} would be archived and dropped; nothing changed."
            ),
            details={
                "months": [a.month for a in plan.drop],
                "cutoff": cutoff.date().isoformat(),
                "retention_months": months,
            },
        )
        return plan

    dropped = 0
    try:
        for action in plan.drop:
            archived = _drop_partition(db, action)
            dropped += 1  # counted before the audit so the MV is refreshed even if audit fails
            _audit_drop(db, plan, action, archived)
    finally:
        if dropped:
            refresh_acct_edge_daily(db)
    return plan
