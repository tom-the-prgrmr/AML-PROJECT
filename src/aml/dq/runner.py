"""Run the enabled data quality rules, store the results and report agreement with dq_labels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.dq.rules import RULES, sync_rules

TABLES = ("customers", "transactions")  # whitelist: table names are put into SQL text
LABEL_ENTITY = {"customers": "customer", "transactions": "transaction"}
RESULT_COLUMNS = [
    "run_id", "rule_id", "run_ts", "as_of", "table_name", "dimension",
    "total_rows", "failed_rows", "fail_rate", "status", "sample_ids",
]  # fmt: skip


@dataclass(frozen=True)
class DqRuleResult:
    rule_id: str
    total_rows: int
    failed_rows: int
    fail_rate: float | None  # round(failed_rows / total_rows, 6); None when NO_DATA
    status: str  # "PASS" | "FAIL" | "NO_DATA"
    failed_ids: frozenset[str]  # every failing entity_id (only a sample is stored)


@dataclass(frozen=True)
class DqRun:
    run_id: int
    as_of: date
    results: tuple[DqRuleResult, ...]  # in RULES order


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def _load_check_sql(db: Database, name: str, as_of: date, max_lag_days: int) -> str:
    """Read a rule file; only {as_of} and {max_feed_lag_days} are substituted, from typed values."""
    text = db.sql_file(name).read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if lines and lines[-1].strip() == "/":  # Oracle terminator
        text = "\n".join(lines[:-1])
    text = text.strip().rstrip(";")
    return text.replace("{as_of}", f"DATE '{as_of.isoformat()}'").replace(
        "{max_feed_lag_days}", str(int(max_lag_days))
    )


def _evaluate(
    db: Database, row: pd.Series, table_rows: dict[str, int], as_of: date, max_lag: int
) -> DqRuleResult:
    rule_id, table = str(row["rule_id"]), str(row["table_name"])
    if table not in TABLES:
        raise ValueError(f"{rule_id}: unsupported table {table!r}")
    if table_rows[table] == 0:
        return DqRuleResult(rule_id, 0, 0, None, "NO_DATA", frozenset())
    sql = _load_check_sql(db, str(row["check_sql"]), as_of, max_lag)
    failed_ids = frozenset(str(x) for x in db.query_df(sql).iloc[:, 0])
    total = table_rows[table] if row["scope"] == "ROW" else 1
    fail_rate = round(len(failed_ids) / total, 6)
    status = "FAIL" if fail_rate > float(row["max_fail_rate"]) else "PASS"
    return DqRuleResult(rule_id, total, len(failed_ids), fail_rate, status, failed_ids)


def _result_rows(
    run_id: int, as_of: date, results: tuple[DqRuleResult, ...], catalogue: pd.DataFrame, n: int
) -> pd.DataFrame:
    meta = catalogue.set_index("rule_id")
    run_ts = datetime.now(UTC).replace(tzinfo=None)
    rows = [
        {
            "run_id": run_id,
            "rule_id": r.rule_id,
            "run_ts": run_ts,
            "as_of": as_of,
            "table_name": meta.at[r.rule_id, "table_name"],
            "dimension": meta.at[r.rule_id, "dimension"],
            "total_rows": r.total_rows,
            "failed_rows": r.failed_rows,
            "fail_rate": r.fail_rate,
            "status": r.status,
            "sample_ids": json.dumps(sorted(r.failed_ids)[:n]),
        }
        for r in results
    ]
    df = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    df["fail_rate"] = df["fail_rate"].astype(object).where(df["fail_rate"].notna(), None)
    return df


def run_dq(db: Database, settings: Settings, *, as_of: date | None = None) -> DqRun:
    """Run every enabled rule in ``dq_rules``, store one row per rule and audit the run."""
    as_of = as_of or settings.data.reference_date
    sync_rules(db)
    run_id = _scalar(db, "SELECT COALESCE(MAX(run_id), 0) + 1 FROM dq_results")
    catalogue = db.query_df(
        "SELECT rule_id, table_name, dimension, scope, check_sql, max_fail_rate, enabled "
        "FROM dq_rules"
    )
    catalogue["enabled"] = catalogue["enabled"].map(bool)
    enabled = catalogue[catalogue["enabled"]].set_index("rule_id", drop=False)
    table_rows = {t: _scalar(db, f"SELECT COUNT(*) FROM {t}") for t in TABLES}

    results = tuple(
        _evaluate(db, enabled.loc[r.rule_id], table_rows, as_of, settings.dq.max_feed_lag_days)
        for r in RULES
        if r.rule_id in enabled.index
    )
    db.insert_df(
        "dq_results", _result_rows(run_id, as_of, results, catalogue, settings.dq.sample_size)
    )
    _audit_run(db, run_id, as_of, results)
    return DqRun(run_id, as_of, results)


def _audit_run(db: Database, run_id: int, as_of: date, results: tuple[DqRuleResult, ...]) -> None:
    failed = [r.rule_id for r in results if r.status == "FAIL"]
    passed = sum(r.status == "PASS" for r in results)
    audit(
        db,
        module="dq",
        entity_type="dq_run",
        entity_id=str(run_id),
        decision="DQ_RUN_COMPLETED",
        reason=(
            f"Ran {len(results)} data quality rules as of {as_of.isoformat()}: {passed} passed, "
            f"{len(failed)} failed."
        ),
        version="dq/rules",
        details={
            "rules": len(results),
            "passed": passed,
            "failed": len(failed),
            "as_of": as_of.isoformat(),
            "failed_rules": failed,
        },
    )


def label_agreement(db: Database, run: DqRun) -> pd.DataFrame:
    """Compare failing ids with the Phase 1 ground truth in ``dq_labels``, per labelled rule."""
    by_rule = {r.rule_id: r for r in run.results}
    rows = []
    for rule in RULES:
        if rule.label_defect_type is None or rule.rule_id not in by_rule:
            continue
        entity = LABEL_ENTITY[rule.table_name]
        labels = db.query_df(
            "SELECT entity_id FROM dq_labels "
            f"WHERE entity_type = '{entity}' AND defect_type = '{rule.label_defect_type}'"
        )
        truth = frozenset(str(x) for x in labels.iloc[:, 0])
        flagged = by_rule[rule.rule_id].failed_ids
        tp, fp, fn = len(flagged & truth), len(flagged - truth), len(truth - flagged)
        rows.append(
            {
                "rule_id": rule.rule_id,
                "defect_type": rule.label_defect_type,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": tp / (tp + fp) if tp + fp else 1.0,
                "recall": tp / (tp + fn) if tp + fn else 1.0,
            }
        )
    return pd.DataFrame(
        rows, columns=["rule_id", "defect_type", "tp", "fp", "fn", "precision", "recall"]
    )
