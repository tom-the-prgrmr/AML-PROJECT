"""Incremental screening: re-screen only what changed since the last FULL run.

Changes are found by comparing entity fingerprints with ``screening_state``. The IDF is frozen at
the last FULL run, so a re-screened pair scores exactly as in a FULL run that used the same IDF.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from aml.common.audit import AuditEvent, audit_many
from aml.common.config import ScreeningConfig, Settings
from aml.common.db import Database
from aml.screening.decision import ALERT, AUTO_CLEARED, REVIEW
from aml.screening.idf import TokenStats
from aml.screening.matching import (
    BestMatch,
    ScreeningError,
    ScreeningInputs,
    customer_norms,
    entry_names,
    load_inputs,
    match_candidates,
)
from aml.screening.recording import (
    SCREENING_VERSION,
    Recorded,
    ScreeningRun,
    config_hash,
    decide_pairs,
    insert_run_row,
    match_events,
    next_run_id,
    result_rows,
    run_event,
)
from aml.screening.runner import run_screening
from aml.screening.state import (
    CUSTOMER,
    ENTRY,
    chunks,
    customer_fingerprints,
    entry_fingerprints,
    load_token_stats,
    quoted_list,
    read_state,
    update_state,
)

__all__ = ["Delta", "detect_delta", "run_incremental"]

Pair = tuple[str, str]


@dataclass(frozen=True)
class Delta:
    customers_changed: frozenset[str]  # new CIFs or CIFs whose fingerprint changed
    customers_removed: frozenset[str]
    entries_changed: frozenset[str]  # new entry_ids or entries whose fingerprint changed
    entries_removed: frozenset[str]


def _diff(current: dict[str, str], stored: dict[str, str]) -> tuple[frozenset[str], frozenset[str]]:
    changed = frozenset(i for i, fp in current.items() if stored.get(i) != fp)
    return changed, frozenset(stored) - frozenset(current)


def detect_delta(db: Database, settings: Settings) -> Delta:
    """Compare the current fingerprints with ``screening_state``; read-only."""
    return _compare(db, load_inputs(db), settings.screening)[0]


def _compare(
    db: Database, inputs: ScreeningInputs, cfg: ScreeningConfig
) -> tuple[Delta, dict[str, str], dict[str, str]]:
    stored = read_state(db)
    cust_fp, entry_fp = customer_fingerprints(inputs, cfg), entry_fingerprints(inputs, cfg)
    c_changed, c_removed = _diff(cust_fp, stored[CUSTOMER])
    e_changed, e_removed = _diff(entry_fp, stored[ENTRY])
    return Delta(c_changed, c_removed, e_changed, e_removed), cust_fp, entry_fp


def _last_full_hash(db: Database) -> str | None:
    df = db.query_df(
        "SELECT config_hash FROM screening_runs WHERE run_id = "
        "(SELECT MAX(run_id) FROM screening_runs WHERE \"MODE\" = 'FULL')"
    )
    return None if df.empty else str(df.iloc[0, 0])


def _rescreen(
    inputs: ScreeningInputs, delta: Delta, stats: TokenStats, cfg: ScreeningConfig
) -> tuple[dict[Pair, BestMatch], set[Pair]]:
    """Tier 1 on (changed customers x all names) and (all customers x changed entries' names)."""
    customers, names = customer_norms(inputs, cfg), entry_names(inputs, cfg)
    changed_customers = {
        n: kept
        for n, cifs in customers.items()
        if (kept := [c for c in cifs if c in delta.customers_changed])
    }
    changed_names = {
        n: kept
        for n, items in names.items()
        if (kept := [i for i in items if i[0] in delta.entries_changed])
    }
    best: dict[Pair, BestMatch] = {}
    candidates: set[Pair] = set()
    for cust_side, name_side in ((changed_customers, names), (customers, changed_names)):
        if cust_side and name_side:
            part_best, part_candidates = match_candidates(cust_side, name_side, stats, cfg)
            best.update(part_best)  # a pair seen by both passes gets identical results
            candidates |= part_candidates
    return best, candidates


def _supersede(db: Database, run_id: int, delta: Delta) -> pd.DataFrame:
    """Mark current rows of changed/removed entities as replaced; return those rows."""
    by_column = (
        ("cif", delta.customers_changed | delta.customers_removed),
        ("entry_id", delta.entries_changed | delta.entries_removed),
    )
    replaced: list[pd.DataFrame] = [pd.DataFrame(columns=["cif", "entry_id", "decision"])]
    for column, ids in by_column:
        for batch in chunks(sorted(ids)):
            where = (
                f"superseded_by IS NULL AND run_id < {run_id} "
                f"AND {column} IN ({quoted_list(batch)})"
            )
            replaced.append(
                db.query_df(f"SELECT cif, entry_id, decision FROM screening_results WHERE {where}")
            )
            db.execute(f"UPDATE screening_results SET superseded_by = {run_id} WHERE {where}")
    return pd.concat(replaced, ignore_index=True)


def _withdrawn_events(
    run_id: int, replaced: pd.DataFrame, recorded: list[Recorded], delta: Delta
) -> list[AuditEvent]:
    """ALERT/REVIEW rows that were replaced and have no new row: the alert disappeared."""
    kept = {(r.cif, r.entry_id) for r in recorded}
    events: list[AuditEvent] = []
    for r in replaced.itertuples():
        if r.decision not in (ALERT, REVIEW) or (r.cif, r.entry_id) in kept:
            continue
        if r.entry_id in delta.entries_removed:
            why = "watchlist entry removed"
        elif r.cif in delta.customers_removed:
            why = "customer removed"
        else:
            why = "no longer a recorded match after change"
        events.append(
            AuditEvent(
                module="screening",
                entity_type="screening_match",
                entity_id=f"{r.cif}:{r.entry_id}",
                decision="WITHDRAWN",
                reason=f"Previous {r.decision} withdrawn by run {run_id}: {why}.",
                version=SCREENING_VERSION,
                details={"run_id": run_id, "previous_decision": r.decision},
            )
        )
    return events


def run_incremental(db: Database, settings: Settings, *, as_of: date | None = None) -> ScreeningRun:
    """Re-screen only the changed customers and watchlist entries since the last FULL run."""
    as_of = as_of or settings.data.reference_date
    cfg = settings.screening
    state = read_state(db)
    last_hash = _last_full_hash(db) if state[CUSTOMER] or state[ENTRY] else None
    if last_hash is None:
        return run_screening(db, settings, as_of=as_of)
    if last_hash != config_hash(settings):
        raise ScreeningError(
            "screening config changed since the last FULL run; full screen required"
        )
    stats = load_token_stats(db)
    if stats is None:
        raise ScreeningError("no stored token statistics: full screen required")

    inputs = load_inputs(db)
    delta, cust_fp, entry_fp = _compare(db, inputs, cfg)
    best, candidates = _rescreen(inputs, delta, stats, cfg)
    recorded = decide_pairs(best, inputs, cfg, as_of)
    run_id = next_run_id(db)

    # Same order as a FULL run: new rows first, then supersede, so a failure keeps old alerts.
    if recorded:
        db.insert_df("screening_results", result_rows(run_id, recorded))
    replaced = _supersede(db, run_id, delta)
    update_state(
        db, run_id, CUSTOMER, delta.customers_changed | delta.customers_removed,
        {c: cust_fp[c] for c in delta.customers_changed},
    )  # fmt: skip
    update_state(
        db, run_id, ENTRY, delta.entries_changed | delta.entries_removed,
        {e: entry_fp[e] for e in delta.entries_changed},
    )  # fmt: skip

    def count(label: str) -> int:
        return sum(r.decision.decision == label for r in recorded)

    run = ScreeningRun(
        run_id, "INCREMENTAL", as_of, len(delta.customers_changed), len(delta.entries_changed),
        len(candidates), len(recorded), count(ALERT), count(REVIEW), count(AUTO_CLEARED),
        len(replaced),
    )  # fmt: skip
    insert_run_row(db, run, settings)
    extra = {
        "customers_changed": len(delta.customers_changed),
        "customers_removed": len(delta.customers_removed),
        "entries_changed": len(delta.entries_changed),
        "entries_removed": len(delta.entries_removed),
    }
    events = [
        *match_events(run, recorded),
        *_withdrawn_events(run_id, replaced, recorded, delta),
        run_event(run, extra),
    ]
    audit_many(db, events)
    return run
