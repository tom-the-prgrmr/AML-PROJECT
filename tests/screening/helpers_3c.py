"""Helpers for the Phase 3c tests (specs/screening-oracle-incremental.md): DELTA, snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aml.common.config import Settings
from aml.common.db import Database, DuckDb

from .helpers import mod
from .helpers_3b import AS_OF, duck_settings, load_tiny_duck, query

CURRENT_COLS = "cif, entry_id, matched_name, decision, reason, name_score, final_score"

__all__ = [
    "AS_OF",
    "CURRENT_COLS",
    "apply_delta",
    "audit_count",
    "count",
    "current_set",
    "duck_settings",
    "full_screen_tiny",
    "load_tiny_duck",
    "query",
    "run_full",
    "run_inc",
    "token_stats_from",
]


def run_full(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.screening.runner").run_screening(db, settings, **kw)


def run_inc(db: Database, settings: Settings) -> Any:
    return mod("aml.screening.incremental").run_incremental(db, settings)


def count(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def audit_count(db: Database) -> int:
    return count(db, "SELECT COUNT(*) FROM audit_log")


def full_screen_tiny(tiny_parquet: Path, path: Path) -> tuple[DuckDb, Settings]:
    """TINY loaded into a DuckDB and screened once (FULL-1)."""
    db = load_tiny_duck(tiny_parquet, path)
    settings = duck_settings()
    run_full(db, settings)
    return db, settings


def apply_delta(db: Database) -> None:
    """D1 + D2 + D3 of the spec."""
    db.execute("UPDATE customers SET dob = DATE '1950-03-01' WHERE cif = 'CIF00000214'")
    db.execute(
        "INSERT INTO watchlist (entry_id, list_type, primary_name, name_origin, dob, dob_year, "
        "dob_precision, nationality, program, listed_date) VALUES "
        "('WL900001', 'SANCTIONS', 'NGO THI LAN', 'vi', NULL, NULL, 'NONE', 'VN', 'SDGT', "
        "DATE '2025-12-01')"
    )
    db.execute("DELETE FROM watchlist WHERE entry_id = 'WL000158'")


def current_set(db: Database) -> set[tuple[Any, ...]]:
    df = query(db, f"SELECT {CURRENT_COLS} FROM screening_current")
    return {
        (r.cif, r.entry_id, r.matched_name, r.decision, r.reason,
         round(float(r.name_score), 2), round(float(r.final_score), 2))
        for r in df.itertuples()
    }  # fmt: skip


def token_stats_from(db: Database) -> Any:
    df = query(db, "SELECT token, doc_freq, n_names FROM screening_token_stats")
    n_names = int(df["n_names"].iloc[0])
    doc_freq = {str(t): int(d) for t, d in zip(df["token"], df["doc_freq"], strict=True)}
    return mod("aml.screening.idf").TokenStats(n_names=n_names, doc_freq=doc_freq)
