"""Helpers for the Phase 7b-supp tests (specs/case-suppression.md): MINI-S, HIB, wrappers.

MINI-S = MINI-C of 7a plus four `screening_state` rows and two HIGH_VELOCITY alerts (H1, H2) on
A04. The spec records H1 and H2 in the same `record_run` as R1..R4; here they are a second run of
HIGH_VELOCITY on top of `load_minic` (helpers.py is locked). `alerts_current` reads the latest run
of each rule and the base run holds no HIGH_VELOCITY alert, so the items are the same.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database

from .helpers import (
    AS_OF,
    CASE_C05,
    M,
    load_minic,
    mod,
    none_if_nan,
    query,
    rule_alert,
    ts,
)

CASE_C04_S = "C-C04-20260201"  # MINI-S: H1, H2, N1 of G-C04
CASE_C04_LATE = "C-C04-20260609"  # opened by H6 once H7 is hibernated
CASE_C01_PEP = "C-C01-20260531"  # R3 and the screening pair C02 x WL1
GG_CASE = "C-CIF00000041-20260630"  # TINY: the screening-only case of CIF00000041 x WL000199
GG_KEY = "SCREENING|CIF00000041|WL000199"
S2_KEY = "SCREENING|C05|WL2"
S1_KEY = "SCREENING|C02|WL1"
SUPPRESSED_S2 = (
    "good-guy list: C05 x WL2 cleared on 2026-06-30 by analyst01 (case C-C05-20260630); "
    "valid until 2027-06-30; customer and watchlist entry unchanged"
)
STATE_ROWS = (
    ("customer", "C02", "fp-c02"),
    ("customer", "C05", "fp-c05"),
    ("watchlist_entry", "WL1", "fp-wl1"),
    ("watchlist_entry", "WL2", "fp-wl2"),
)


def supp() -> Any:
    return mod("aml.cases.suppression")


def hv_alert(start: str, amount: int) -> Any:
    """HIGH_VELOCITY on A04 (owned by C04), one hour long, without transactions."""
    end = (ts(start) + timedelta(hours=1)).isoformat(sep=" ")
    return rule_alert("HIGH_VELOCITY", "A04", start, end, (), amount)


def hv_key(start: str) -> str:
    return f"HIGH_VELOCITY|A04|{ts(start).isoformat()}"


H_STARTS = {
    "H1": ("2026-02-01 09:00:00", 100 * M),
    "H2": ("2026-02-20 09:00:00", 120 * M),
    "H3": ("2026-04-10 09:00:00", 150 * M),
    "H4": ("2026-04-15 09:00:00", 180 * M),
    "H5": ("2026-04-20 09:00:00", 180_000_001),
    "H6": ("2026-06-09 09:00:00", 100 * M),
    "H7": ("2026-06-08 23:00:00", 100 * M),
}
H_KEYS = {name: hv_key(start) for name, (start, _) in H_STARTS.items()}


def _record_hv(db: Database, names: tuple[str, ...]) -> None:
    rec = mod("aml.monitoring.recording")
    alerts = [hv_alert(*H_STARTS[n]) for n in names]
    rules = [rec.RuleRun(rule_id="HIGH_VELOCITY", rule_version="v1", params={})]
    rec.record_run(db, as_of=AS_OF, source="RULE", rules=rules, alerts=alerts)


def load_minis(db: Database, *, without: tuple[str, ...] = ()) -> Database:
    """MINI-S; ``without`` lists `screening_state` entity ids to leave out."""
    load_minic(db)
    for entity_type, entity_id, fingerprint in STATE_ROWS:
        if entity_id not in without:
            db.execute(
                "INSERT INTO screening_state (entity_type, entity_id, fingerprint, run_id) "
                "VALUES (?, ?, ?, 1)",
                [entity_type, entity_id, fingerprint],
            )
    _record_hv(db, ("H1", "H2"))
    return db


def add_hib(db: Database) -> None:
    """HIB: a new HIGH_VELOCITY run with H1..H7 (H1 and H2 are the same alerts as before)."""
    _record_hv(db, tuple(H_STARTS))


def dispose(
    db: Database,
    settings: Settings,
    case_id: str,
    disposition: str = "FALSE_POSITIVE",
    *,
    reason: str = "test clearance",
    actor: str = "analyst01",
    decided_on: date | None = None,
) -> int:
    kw: dict[str, Any] = {"reason": reason, "actor": actor}
    if decided_on is not None:
        kw["decided_on"] = decided_on
    return int(
        mod("aml.cases.dispositions").record_disposition(db, settings, case_id, disposition, **kw)
    )


def day(value: Any) -> date:
    return pd.Timestamp(value).date()


def item(db: Database, item_key: str, golden: str | None = None) -> Any:
    """The row of an item in `case_alerts_current` (exactly one expected)."""
    extra = f" AND golden_customer_id = '{golden}'" if golden else ""
    df = query(db, f"SELECT * FROM case_alerts_current WHERE item_key = '{item_key}'{extra}")
    assert len(df) == 1, (item_key, len(df))
    return df.iloc[0]


def item_set(db: Database) -> set[tuple[Any, ...]]:
    df = query(
        db,
        "SELECT item_key, golden_customer_id, status, suppression_reason FROM case_alerts_current",
    )
    return {tuple(none_if_nan(v) for v in r) for r in df.itertuples(index=False)}


def audit_mark(db: Database) -> int:
    """The newest ``audit_id`` so far; pass it to `audit_since` to see only what came after."""
    return int(query(db, "SELECT COALESCE(MAX(audit_id), 0) AS m FROM audit_log").iloc[0, 0])


def audit_since(db: Database, mark: int, where: str = "1 = 1") -> pd.DataFrame:
    return query(
        db,
        "SELECT entity_type, entity_id, decision, reason, version, actor, details "
        f"FROM audit_log WHERE audit_id > {mark} AND ({where}) ORDER BY audit_id",
    )


def good_guys(db: Database, where: str = "") -> pd.DataFrame:
    return query(db, f"SELECT * FROM good_guy_list {where} ORDER BY entry_no")


__all__ = [
    "CASE_C01_PEP",
    "CASE_C04_LATE",
    "CASE_C04_S",
    "CASE_C05",
    "GG_CASE",
    "GG_KEY",
    "H_KEYS",
    "S1_KEY",
    "S2_KEY",
    "SUPPRESSED_S2",
    "add_hib",
    "audit_mark",
    "audit_since",
    "day",
    "dispose",
    "good_guys",
    "hv_alert",
    "hv_key",
    "item",
    "item_set",
    "load_minis",
    "supp",
]
