"""The data quality rule catalogue and its synchronisation into the ``dq_rules`` table.

The definitions live here (and in git); the table is what actually drives the runner, so an
operator can switch a rule off or change its threshold with an UPDATE. ``sync_rules`` therefore
only inserts rules that are missing and never overwrites an existing row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from aml.common.db import Database

DIMENSIONS = ("COMPLETENESS", "VALIDITY", "UNIQUENESS", "CONSISTENCY", "TIMELINESS")


@dataclass(frozen=True)
class DqRule:
    rule_id: str
    table_name: str  # "customers" | "transactions"
    dimension: str  # one of DIMENSIONS
    scope: str  # "ROW" (denominator = table rows) | "TABLE" (denominator = 1)
    description: str
    check_sql: str  # file name under sql/, e.g. "dq/kyc_id_format.sql"
    label_defect_type: str | None  # matching defect_type in dq_labels, if any
    max_fail_rate: float = 0.0
    enabled: bool = True


def _customer(rule_id: str, dimension: str, description: str, label: str | None = None) -> DqRule:
    return DqRule(
        rule_id, "customers", dimension, "ROW", description, f"dq/{rule_id.lower()}.sql", label
    )


def _txn(
    rule_id: str,
    dimension: str,
    description: str,
    label: str | None = None,
    scope: str = "ROW",
) -> DqRule:
    return DqRule(
        rule_id, "transactions", dimension, scope, description, f"dq/{rule_id.lower()}.sql", label
    )


RULES: tuple[DqRule, ...] = (
    _customer("KYC_OCCUPATION_MISSING", "COMPLETENESS", "occupation is NULL", "MISSING_OCCUPATION"),
    _customer(
        "KYC_NATIONALITY_MISSING", "COMPLETENESS", "nationality is NULL", "MISSING_NATIONALITY"
    ),
    _customer(
        "KYC_ID_FORMAT",
        "VALIDITY",
        "id_number does not match the pattern of its id_type (CCCD 12 digits, CMND 9 digits, "
        "PASSPORT letter + 7 digits) or id_type is unknown",
        "INVALID_ID_LENGTH",
    ),
    _customer("KYC_DOB_FUTURE", "VALIDITY", "dob is after the as_of date", "FUTURE_DOB"),
    _customer(
        "KYC_CCCD_DOB_MISMATCH",
        "CONSISTENCY",
        "CCCD digits 5-6 or digit 4 disagree with the birth year or the century and gender",
    ),
    _txn(
        "TXN_DUPLICATE",
        "UNIQUENESS",
        "same from, to, txn_ts, amount and channel as a transaction with a smaller txn_id",
        "DUPLICATE_TRANSACTION",
    ),
    _txn(
        "TXN_VALUE_INVALID",
        "VALIDITY",
        "amount missing or not positive, channel missing or unknown, or txn_ts missing",
    ),
    _txn(
        "TXN_ACCOUNT_UNKNOWN",
        "CONSISTENCY",
        "internal from/to account (not EXT-) that is missing from accounts",
    ),
    _txn(
        "TXN_BEFORE_ACCOUNT_OPEN",
        "CONSISTENCY",
        "transaction dated before the open_date of its internal sender or receiver account",
    ),
    _txn(
        "TXN_FEED_STALE",
        "TIMELINESS",
        "newest transaction is older than as_of minus dq.max_feed_lag_days",
        scope="TABLE",
    ),
)


def sync_rules(db: Database) -> int:
    """Insert catalogue rules that are not in ``dq_rules`` yet; return how many were added."""
    present = set(db.query_df("SELECT rule_id FROM dq_rules").iloc[:, 0])
    missing = [asdict(r) for r in RULES if r.rule_id not in present]
    if not missing:
        return 0
    return db.insert_df("dq_rules", pd.DataFrame(missing))
