"""Read-only view of one case: alerts, enrichment, subjects and the latest human decision.

Used by the CLI now and by scoring, summaries, the assistant and the UI later. It never writes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from aml.cases.runner import SECTIONS, CaseError
from aml.cases.values import floats, in_filter, is_case_id, iso_date, lower_columns, plain
from aml.common.db import Database

__all__ = [
    "CaseAlert",
    "CaseView",
    "Disposition",
    "SuppressedItem",
    "list_suppressed",
    "load_case",
]


@dataclass(frozen=True)
class CaseAlert:
    item_key: str
    source: str
    rule_id: str
    alert_ref: str
    cif: str
    event_ts: datetime
    end_ts: datetime
    amount_vnd: int
    reason: str


@dataclass(frozen=True)
class Disposition:
    disposition_id: int
    disposition: str
    reason: str
    actor: str
    origin: str
    decided_on: date
    run_id: int


@dataclass(frozen=True)
class CaseView:
    case_id: str
    run_id: int
    golden_customer_id: str
    status: str
    window_start: datetime
    first_alert_ts: datetime
    last_alert_ts: datetime
    reason: str
    alerts: tuple[CaseAlert, ...]  # ordered by (event_ts, item_key)
    enrichment: dict[str, dict[str, Any]]  # keys = SECTIONS
    subjects: tuple[dict[str, Any], ...]  # customers_masked (or customers) row of each CIF
    disposition: Disposition | None
    score: dict[str, Any] | None  # filled by the prioritization phase; None until then


def _read(db: Database, sql: str) -> pd.DataFrame:
    return lower_columns(db.query_df(sql))


def _json(value: Any) -> dict[str, Any]:
    """A JSON column as a dict (DuckDB returns text, Oracle may return text or a parsed value)."""
    parsed = json.loads(value) if isinstance(value, str) else value
    return dict(floats(parsed))


def _quote(case_id: str) -> str:
    """Literal for a case id. The shape is checked first, so no user text reaches the SQL."""
    if not is_case_id(case_id):
        raise CaseError(f"unknown case_id {case_id}")
    return "'" + case_id + "'"


def _alerts(db: Database, run_id: int, case_id: str) -> tuple[CaseAlert, ...]:
    df = _read(
        db,
        "SELECT item_key, source, rule_id, alert_ref, cif, event_ts, end_ts, amount_vnd, reason "
        f"FROM case_alerts WHERE run_id = {run_id} AND case_id = {_quote(case_id)}",
    )
    df = df.sort_values(["event_ts", "item_key"], kind="stable")
    return tuple(
        CaseAlert(
            item_key=str(r.item_key),
            source=str(r.source),
            rule_id=str(r.rule_id),
            alert_ref=str(r.alert_ref),
            cif=str(r.cif),
            event_ts=pd.Timestamp(r.event_ts).to_pydatetime(),
            end_ts=pd.Timestamp(r.end_ts).to_pydatetime(),
            amount_vnd=int(r.amount_vnd),
            reason=str(plain(r.reason) or ""),
        )
        for r in df.itertuples()
    )


def _enrichment(db: Database, run_id: int, case_id: str) -> dict[str, dict[str, Any]]:
    df = _read(
        db,
        "SELECT section, content FROM case_enrichment "
        f"WHERE run_id = {run_id} AND case_id = {_quote(case_id)}",
    )
    blocks = {str(r.section): _json(r.content) for r in df.itertuples()}
    return {s: blocks[s] for s in SECTIONS if s in blocks}


def _subjects(db: Database, cifs: list[str], masked: bool) -> tuple[dict[str, Any], ...]:
    table = "customers_masked" if masked else "customers"
    df = _read(db, f"SELECT * FROM {table} WHERE {in_filter('cif', cifs)} ORDER BY cif")
    return tuple({str(k): plain(v) for k, v in row.items()} for row in df.to_dict("records"))


def _disposition(db: Database, case_id: str) -> Disposition | None:
    df = _read(
        db,
        "SELECT disposition_id, disposition, reason, actor, origin, decided_on, run_id "
        f"FROM case_dispositions_current WHERE case_id = {_quote(case_id)}",
    )
    if df.empty:
        return None
    r = df.iloc[0]
    return Disposition(
        disposition_id=int(r["disposition_id"]),
        disposition=str(r["disposition"]),
        reason=str(r["reason"]),
        actor=str(r["actor"]),
        origin=str(r["origin"]),
        decided_on=date.fromisoformat(str(iso_date(r["decided_on"]))),
        run_id=int(r["run_id"]),
    )


@dataclass(frozen=True)
class SuppressedItem:
    item_key: str
    suppression_rule: str
    suppression_reason: str


def list_suppressed(db: Database, *, limit: int | None = None) -> tuple[int, list[SuppressedItem]]:
    """The SUPPRESSED items of the latest run: their total and the first ``limit`` of them.

    Ordered by (item_key, golden customer); raise `CaseError` when no run exists yet.
    """
    if int(db.query_df("SELECT COUNT(*) FROM case_runs").iloc[0, 0]) == 0:
        raise CaseError("no case run yet: run `aml cases build` first")
    df = _read(
        db,
        "SELECT item_key, suppression_rule, suppression_reason FROM case_alerts_current "
        "WHERE status = 'SUPPRESSED' ORDER BY item_key, golden_customer_id",
    )
    items = [
        SuppressedItem(str(r.item_key), str(r.suppression_rule), str(r.suppression_reason))
        for r in df.itertuples()
    ]
    return len(items), items if limit is None else items[: max(limit, 0)]


def load_case(
    db: Database, case_id: str, *, run_id: int | None = None, masked: bool = True
) -> CaseView:
    """Load a case from a run (the latest by default); raise `CaseError` when it is not there."""
    if run_id is None:
        run_id = int(db.query_df("SELECT COALESCE(MAX(run_id), 0) FROM case_runs").iloc[0, 0])
    head = _read(db, f"SELECT * FROM cases WHERE run_id = {run_id} AND case_id = {_quote(case_id)}")
    if head.empty:
        raise CaseError(f"unknown case_id {case_id}")
    case = head.iloc[0]
    enrichment = _enrichment(db, run_id, case_id)
    kyc_cifs = [str(c["cif"]) for c in enrichment.get("kyc", {}).get("cifs", [])]
    return CaseView(
        case_id=case_id,
        run_id=run_id,
        golden_customer_id=str(case["golden_customer_id"]),
        status=str(case["status"]),
        window_start=pd.Timestamp(case["window_start"]).to_pydatetime(),
        first_alert_ts=pd.Timestamp(case["first_alert_ts"]).to_pydatetime(),
        last_alert_ts=pd.Timestamp(case["last_alert_ts"]).to_pydatetime(),
        reason=str(case["reason"]),
        alerts=_alerts(db, run_id, case_id),
        enrichment=enrichment,
        subjects=_subjects(db, kyc_cifs, masked),
        disposition=_disposition(db, case_id),
        score=None,
    )
