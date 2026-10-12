"""Run the monitoring rule SQL files read-only and turn their rows into `Detection`s."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database
from aml.monitoring.reasons import build_reason
from aml.monitoring.rules import RULES, MonitoringRule, rule_params

# columns every rule file returns per (alert, transaction) row; everything else is a metric
_BASE_COLUMNS = ("account_id", "window_start", "window_end", "txn_id", "amount_vnd")


@dataclass(frozen=True)
class Detection:
    rule_id: str
    rule_version: str
    account_id: str
    window_start: datetime  # first evidence transaction
    window_end: datetime  # last evidence transaction
    txn_ids: tuple[str, ...]  # ascending, distinct
    amount_vnd: int  # sum of amount_vnd over the evidence transactions
    metrics: dict[str, int]  # the metric columns of the SQL file
    reason: str
    alert_key: str  # "<rule_id>|<account_id>|<window_start as YYYY-MM-DDTHH:MM:SS>"


def _dt(value: object) -> datetime:
    return pd.Timestamp(value).to_pydatetime()  # type: ignore[arg-type]


def render_sql(db: Database, rule: MonitoringRule, settings: Settings, cutoff: date) -> str:
    """Rule SQL with `{cutoff}` and the rule's typed parameters substituted, terminator removed."""
    lines = db.sql_file(rule.sql_file).read_text(encoding="utf-8").strip().splitlines()
    if lines and lines[-1].strip() == "/":
        lines = lines[:-1]
    text = "\n".join(lines).strip().rstrip(";")
    text = text.replace("{cutoff}", f"TIMESTAMP '{cutoff.isoformat()} 00:00:00'")
    for key, value in rule_params(rule.rule_id, settings).items():
        text = text.replace("{" + key + "}", str(value))
    if "{" in text:
        raise ValueError(f"unresolved placeholder in {rule.sql_file}")
    return text


def _detections(rule: MonitoringRule, df: pd.DataFrame, settings: Settings) -> list[Detection]:
    df.columns = [str(c).lower() for c in df.columns]
    metric_cols = [c for c in df.columns if c not in _BASE_COLUMNS]
    params = rule_params(rule.rule_id, settings)
    found: list[Detection] = []
    for (account_id, start), rows in df.groupby(["account_id", "window_start"], sort=True):
        rows = rows.drop_duplicates("txn_id")
        first = rows.iloc[0]
        metrics = {c: int(first[c]) for c in metric_cols}
        window_start, window_end = _dt(start), _dt(first["window_end"])
        found.append(
            Detection(
                rule_id=rule.rule_id,
                rule_version=rule.rule_version,
                account_id=str(account_id),
                window_start=window_start,
                window_end=window_end,
                txn_ids=tuple(sorted(str(t) for t in rows["txn_id"])),
                amount_vnd=int(sum(int(a) for a in rows["amount_vnd"])),
                metrics=metrics,
                reason=build_reason(rule.rule_id, metrics, params, window_start, window_end),
                alert_key=(
                    f"{rule.rule_id}|{account_id}|{window_start.strftime('%Y-%m-%dT%H:%M:%S')}"
                ),
            )
        )
    return found


def detect(db: Database, settings: Settings, *, as_of: date | None = None) -> tuple[Detection, ...]:
    """All rule detections on transactions up to and including `as_of`; writes nothing."""
    cutoff = (as_of or settings.data.reference_date) + timedelta(days=1)
    out: list[Detection] = []
    for rule in RULES:
        df = db.query_df(render_sql(db, rule, settings, cutoff))
        if not df.empty:
            out.extend(_detections(rule, df, settings))
    return tuple(out)
