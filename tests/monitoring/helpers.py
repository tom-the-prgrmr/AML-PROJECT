"""Helpers for the Phase 5a tests (specs/monitoring-rules.md): imports, MINI data sets, TINY."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database, DuckDb

AS_OF = date(2026, 6, 30)
M = 1_000_000
RULE_IDS = (
    "STRUCTURING",
    "RAPID_MOVEMENT",
    "HIGH_VELOCITY",
    "FAN_IN",
    "FAN_OUT",
    "DORMANT_REACTIVATION",
)
TINY_BY_RULE = {
    "STRUCTURING": 2,
    "RAPID_MOVEMENT": 5,
    "HIGH_VELOCITY": 6,
    "FAN_IN": 1,
    "FAN_OUT": 4,
    "DORMANT_REACTIVATION": 13,
}
# (alerts, evidence) per rule in the monitoring_runs table of TINY
TINY_RUNS_ROWS = {
    "STRUCTURING": (2, 14),
    "RAPID_MOVEMENT": (5, 27),
    "HIGH_VELOCITY": (6, 109),
    "FAN_IN": (1, 31),
    "FAN_OUT": (4, 87),
    "DORMANT_REACTIVATION": (13, 55),
}
STR_REASON_A1 = (
    "3 cash deposits of 360,000,000 to 399,999,999 VND (just under the 400,000,000 VND "
    "reporting threshold) totalling 1,139,999,000 VND at 2 branch(es) between "
    "2026-03-01 09:00:00 and 2026-03-15 08:59:59"
)
# rule_id -> (alerts, target_hits, other_suspicious, benign, unlabelled, precision,
#             precision_suspicious, scenarios, detected, recall) on TINY
EVAL_EXPECTED: dict[str, tuple[Any, ...]] = {
    "STRUCTURING": (2, 2, 0, 0, 0, 1.0, 1.0, 2, 2, 1.0),
    "RAPID_MOVEMENT": (5, 2, 3, 0, 0, 0.4, 1.0, 2, 2, 1.0),
    "HIGH_VELOCITY": (6, None, 6, 0, 0, None, 1.0, None, None, None),
    "FAN_IN": (1, 1, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0),
    "FAN_OUT": (4, 4, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0),
    "DORMANT_REACTIVATION": (13, None, 13, 0, 0, None, 1.0, None, None, None),
}
EVAL_COLUMNS = [
    "rule_id",
    "target_typology",
    "alerts",
    "target_hits",
    "other_suspicious",
    "benign",
    "unlabelled",
    "precision",
    "precision_suspicious",
    "scenarios",
    "detected",
    "recall",
]
EVAL_VALUE_COLUMNS = EVAL_COLUMNS[2:]


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings(**env: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def ts(text: str) -> datetime:
    return datetime.fromisoformat(text)


def query(db: Database, sql: str) -> pd.DataFrame:
    df = db.query_df(sql)
    df.columns = [c.lower() for c in df.columns]
    return df


def scalar(db: Database, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def js(value: Any) -> Any:
    """Parse a JSON column value (DuckDB returns text, Oracle may return text or a dict)."""
    return json.loads(value) if isinstance(value, str) else value


def none_if_nan(value: Any) -> Any:
    return None if value is None or bool(pd.isna(value)) else value


def load_tiny_duck(tiny_parquet: Path, path: Path) -> DuckDb:
    db = DuckDb(path)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return db


def run_monitoring(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.monitoring.runner").run_monitoring(db, settings, **kw)


# ---------------------------------------------------------------- MINI data sets
# txn tuple: (txn_id, ts, from_account, to_account, amount_vnd, channel[, branch_id])
Txn = tuple[Any, ...]
ACC = {f"A{i}": "2025-01-01" for i in range(1, 6)}
IN_CH = "INTERBANK_TRANSFER"
OUT_CH = "EBANKING"


def load_mini(db: Database, txns: Iterable[Txn], accounts: dict[str, str] | None = None) -> None:
    """Apply the schema, insert accounts A1..A5 (cif C1..C5) and the given transactions."""
    mod("aml.dba.schema").apply_schema(db)
    for account_id, opened in (accounts or ACC).items():
        db.execute(
            "INSERT INTO accounts (account_id, cif, account_type, open_date) "
            "VALUES (?, ?, 'CURRENT', ?)",
            [account_id, "C" + account_id[1:], opened],
        )
    for t in txns:
        branch = t[6] if len(t) > 6 else None
        db.execute(
            "INSERT INTO transactions (txn_id, txn_ts, from_account_id, to_account_id, "
            "amount_vnd, channel, branch_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [t[0], t[1], t[2], t[3], t[4], t[5], branch],
        )


def detect(db: Database, settings: Settings, rules: Sequence[str], **kw: Any) -> list[Any]:
    found = mod("aml.monitoring.detect").detect(db, settings, **kw)
    return [d for d in found if d.rule_id in rules]


def accounts_of(detections: Iterable[Any]) -> set[str]:
    return {d.account_id for d in detections}


def ids(prefix: str, lo: int, hi: int) -> tuple[str, ...]:
    return tuple(f"{prefix}{i:02d}" for i in range(lo, hi + 1))


def _tx(txn_id: str, when: str, account: str, cp: str, amount: int, incoming: bool) -> Txn:
    if incoming:
        return (txn_id, when, cp, account, amount, IN_CH)
    return (txn_id, when, account, cp, amount, OUT_CH)


def burst(
    prefix: str,
    account: str,
    day: str,
    n: int,
    amount: int,
    *,
    incoming: bool | None = None,
    cps: Sequence[str] | None = None,
    start: str = "09:00:00",
) -> list[Txn]:
    """n transactions one hour apart from ``day`` ``start``; ``incoming=None`` alternates IN/OUT."""
    base = datetime.fromisoformat(f"{day} {start}")
    rows: list[Txn] = []
    for i in range(n):
        when = (base + timedelta(hours=i)).isoformat(sep=" ")
        cp = cps[i] if cps else f"EXT-{prefix}{i}"
        inc = (i % 2 == 0) if incoming is None else incoming
        rows.append(_tx(f"{prefix}{i + 1:02d}", when, account, cp, amount, inc))
    return rows


def mini_str() -> list[Txn]:
    def cash(tid: str, when: str, acct: str, amount: int, br: str) -> Txn:
        return (tid, when, None, acct, amount, "CASH", br)

    return [
        cash("S01", "2026-03-01 09:00:00", "A1", 360 * M, "BR001"),
        cash("S02", "2026-03-05 10:00:00", "A1", 399_999_000, "BR002"),
        cash("S03", "2026-03-15 08:59:59", "A1", 380 * M, "BR001"),
        cash("S04", "2026-03-01 09:00:00", "A2", 370 * M, "BR003"),
        cash("S05", "2026-03-02 09:00:00", "A2", 370 * M, "BR003"),
        cash("S06", "2026-03-15 09:00:00", "A2", 370 * M, "BR003"),
        cash("S07", "2026-03-01 09:00:00", "A3", 390 * M, "BR004"),
        cash("S08", "2026-03-02 09:00:00", "A3", 390 * M, "BR004"),
        cash("S09", "2026-03-03 09:00:00", "A3", 400 * M, "BR004"),
        cash("S10", "2026-03-04 09:00:00", "A3", 359_999_000, "BR004"),
        cash("S11", "2026-03-01 09:00:00", "A4", 390 * M, "BR005"),
        cash("S12", "2026-03-02 09:00:00", "A4", 390 * M, "BR005"),
        ("S13", "2026-03-03 09:00:00", "A4", None, 390 * M, "CASH", "BR005"),
        ("S14", "2026-03-04 09:00:00", "EXT-01", "A4", 390 * M, "INTERNAL_TRANSFER"),
        cash("S15", "2026-01-05 09:00:00", "A5", 365 * M, "BR006"),
        cash("S16", "2026-01-06 09:00:00", "A5", 365 * M, "BR006"),
        cash("S17", "2026-01-07 09:00:00", "A5", 365 * M, "BR006"),
        cash("S18", "2026-01-21 09:00:01", "A5", 365 * M, "BR007"),
        cash("S19", "2026-01-22 09:00:00", "A5", 365 * M, "BR007"),
        cash("S20", "2026-01-23 09:00:00", "A5", 365 * M, "BR007"),
    ]


def mini_rap() -> list[Txn]:
    return [
        ("R01", "2026-03-01 10:00:00", None, "A1", 100 * M, "CASH", "BR001"),
        ("R02", "2026-03-01 11:00:00", "EXT-01", "A1", 200 * M, IN_CH),
        ("R03", "2026-03-01 15:00:00", "A1", "EXT-02", 150 * M, OUT_CH),
        ("R04", "2026-03-02 09:59:59", "A1", "EXT-03", 130 * M, OUT_CH),
        ("R05", "2026-03-01 10:00:00", "EXT-01", "A2", 300 * M, IN_CH),
        ("R06", "2026-03-01 12:00:00", "A2", "EXT-02", 269_999_000, OUT_CH),
        ("R07", "2026-03-01 10:00:00", "EXT-01", "A3", 300 * M, IN_CH),
        ("R08", "2026-03-02 10:00:00", "A3", "EXT-02", 280 * M, OUT_CH),
        ("R09", "2026-03-01 10:00:00", "EXT-01", "A4", 199_999_000, IN_CH),
        ("R10", "2026-03-01 12:00:00", "A4", "EXT-02", 199 * M, OUT_CH),
        ("R11", "2026-03-01 09:00:00", "A5", "EXT-02", 280 * M, OUT_CH),
        ("R12", "2026-03-01 10:00:00", "EXT-01", "A5", 300 * M, IN_CH),
    ]


def mini_vel() -> list[Txn]:
    rows: list[Txn] = [("V00", "2026-01-01 00:00:00", "EXT-99", "A5", 1 * M, IN_CH)]
    va = burst("VA", "A1", "2026-03-01", 8, 15 * M)
    va[0] = ("VA01", "2026-03-01 09:00:00", None, "A1", 15 * M, "CASH", "BR001")
    va[1] = ("VA02", "2026-03-01 10:00:00", "A1", None, 15 * M, "CARD")
    rows += va
    rows += burst("VB", "A2", "2026-03-01", 7, 20 * M)
    rows += burst("VC", "A3", "2026-03-01", 8, 12 * M)
    rows += burst("VD", "A4", "2026-01-14", 8, 15 * M)
    pay = [f"EXT-P{j}" for j in range(8)]
    rows += burst("VE", "A5", "2026-02-01", 8, 15 * M, incoming=False, cps=pay)
    rows += burst("VF", "A5", "2026-03-01", 8, 15 * M, incoming=False, cps=pay)
    return rows


def _cps(letter: str) -> list[str]:
    return [f"EXT-{letter}{i}" for i in range(8)]


def mini_fan(extra_new_receivers: bool = False) -> list[Txn]:
    """MINI-FAN; ``extra_new_receivers=True`` gives FAN+ (adds FH01-FH08)."""
    rows: list[Txn] = [("F00", "2026-01-01 00:00:00", "EXT-99", "A5", 1 * M, IN_CH)]
    for i in range(7):
        when = f"2026-03-{1 + i:02d} 09:00:00"
        rows.append(_tx(f"FA{i + 1:02d}", when, "A1", f"EXT-A{i}", 15 * M, True))
    rows.append(_tx("FA08", "2026-03-08 08:59:59", "A1", "EXT-A7", 15 * M, True))
    fb_cps = [f"EXT-B{min(i, 6)}" for i in range(8)]
    rows += burst("FB", "A2", "2026-03-01", 8, 20 * M, incoming=True, cps=fb_cps)
    rows += burst("FC", "A3", "2026-03-10", 8, 20 * M, incoming=False, cps=_cps("C"))
    rows += burst("FD", "A4", "2026-03-10", 8, 12 * M, incoming=False, cps=_cps("D"))
    for prefix, day in (("FE", "2026-01-05"), ("FF", "2026-02-05"), ("FG", "2026-03-05")):
        rows += burst(prefix, "A5", day, 8, 20 * M, incoming=False, cps=_cps("E"))
    if extra_new_receivers:
        rows += burst(
            "FH", "A5", "2026-03-05", 8, 20 * M, incoming=False, cps=_cps("N"), start="09:30:00"
        )
    return rows


MINI_DOR_ACCOUNTS = {**ACC, "A4": "2026-02-15"}


def mini_dor() -> list[Txn]:
    return [
        ("D00", "2026-01-01 00:00:00", "EXT-99", "A5", 1 * M, IN_CH),
        ("D01", "2026-01-10 10:00:00", "EXT-01", "A1", 5 * M, IN_CH),
        ("D02", "2026-04-10 10:00:00", "EXT-01", "A1", 60 * M, IN_CH),
        ("D03", "2026-04-11 09:59:59", "A1", "EXT-02", 50 * M, OUT_CH),
        ("D04", "2026-04-11 10:00:00", "A1", "EXT-02", 500 * M, OUT_CH),
        ("D05", "2026-01-10 10:00:00", "EXT-01", "A2", 5 * M, IN_CH),
        ("D06", "2026-04-10 09:59:59", "EXT-01", "A2", 200 * M, IN_CH),
        ("D07", "2026-04-01 00:00:00", "EXT-01", "A3", 150 * M, IN_CH),
        ("D08", "2026-05-01 09:00:00", "EXT-01", "A4", 500 * M, IN_CH),
        ("D09", "2026-05-01 09:00:00", "EXT-01", "A5", 99_999_000, IN_CH),
    ]
