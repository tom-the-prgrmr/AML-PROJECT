"""Full screening run: Tier 1 candidates, Tier 2 decisions, stored results and audit trail."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from aml.common.audit import AuditEvent, audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.decision import ALERT, AUTO_CLEARED, REVIEW, Decision, decide
from aml.screening.idf import TokenStats, customer_token_stats
from aml.screening.matching import (
    BestMatch,
    ScreeningError,
    best_matches,
    customer_identifiers,
    customer_norms,
    entry_identifiers,
    entry_names,
    load_inputs,
)

__all__ = ["SCREENING_VERSION", "ScreeningError", "ScreeningRun", "run_screening"]

SCREENING_VERSION = "screening/v1"
RESULT_COLUMNS = [
    "run_id",
    "cif",
    "entry_id",
    "list_type",
    "matched_name",
    "matched_name_type",
    "token_set",
    "jaro_winkler",
    "fuzzy_score",
    "coverage",
    "name_score",
    "final_score",
    "dob_gap_years",
    "decision",
    "reason",
]  # fmt: skip  (superseded_by is left NULL = current row)
RUN_COLUMNS = [
    "run_id", "run_ts", "mode", "as_of", "customers_screened", "entries_screened",
    "candidate_pairs", "recorded", "alerts", "reviews", "auto_cleared", "superseded",
    "version", "config_hash",
]  # fmt: skip


@dataclass(frozen=True)
class ScreeningRun:
    run_id: int
    mode: str  # "FULL" (3c adds "INCREMENTAL")
    as_of: date
    customers_screened: int
    entries_screened: int
    candidate_pairs: int  # distinct (cif, entry_id) with at least one candidate name pair
    recorded: int  # rows written to screening_results by this run
    alerts: int
    reviews: int
    auto_cleared: int
    superseded: int  # rows of earlier runs that this run replaced


@dataclass(frozen=True)
class _Recorded:
    cif: str
    entry_id: str
    list_type: str | None
    match: BestMatch
    decision: Decision


def _scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def _config_hash(settings: Settings) -> str:
    text = json.dumps(settings.screening.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _result_rows(run_id: int, recorded: list[_Recorded]) -> pd.DataFrame:
    rows = [
        {
            "run_id": run_id,
            "cif": r.cif,
            "entry_id": r.entry_id,
            "list_type": r.list_type,
            "matched_name": r.match.name,
            "matched_name_type": r.match.name_type,
            "token_set": round(r.match.score.token_set, 2),
            "jaro_winkler": round(r.match.score.jaro_winkler, 2),
            "fuzzy_score": round(r.match.score.fuzzy, 2),
            "coverage": r.match.score.coverage,
            "name_score": round(r.match.score.score, 2),
            "final_score": round(r.decision.final_score, 2),
            "dob_gap_years": r.decision.dob_gap_years,
            "decision": r.decision.decision,
            "reason": r.decision.reason,
        }
        for r in recorded
    ]
    df = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    df["dob_gap_years"] = (
        df["dob_gap_years"].astype(object).where(df["dob_gap_years"].notna(), None)
    )
    return df


def _run_row(run: ScreeningRun, settings: Settings) -> pd.DataFrame:
    row = {
        **{c: getattr(run, c) for c in RUN_COLUMNS if hasattr(run, c)},
        "run_ts": datetime.now(UTC).replace(tzinfo=None),
        "version": SCREENING_VERSION,
        "config_hash": _config_hash(settings),
    }
    return pd.DataFrame([row], columns=RUN_COLUMNS)


def _audit_events(run: ScreeningRun, recorded: list[_Recorded]) -> list[AuditEvent]:
    events = [
        AuditEvent(
            module="screening",
            entity_type="screening_match",
            entity_id=f"{r.cif}:{r.entry_id}",
            decision=r.decision.decision,
            reason=r.decision.reason,
            version=SCREENING_VERSION,
            details={
                "run_id": run.run_id,
                "name_score": round(r.match.score.score, 2),
                "final_score": round(r.decision.final_score, 2),
                "matched_name": r.match.name,
                "list_type": r.list_type,
            },
        )
        for r in recorded
    ]
    events.append(
        AuditEvent(
            module="screening",
            entity_type="screening_run",
            entity_id=str(run.run_id),
            decision="SCREENING_RUN_COMPLETED",
            reason=(
                f"Screened {run.customers_screened} customers against {run.entries_screened} "
                f"watchlist entries as of {run.as_of.isoformat()}: {run.alerts} ALERT, "
                f"{run.reviews} REVIEW, {run.auto_cleared} AUTO_CLEARED."
            ),
            version=SCREENING_VERSION,
            details={
                "mode": run.mode,
                "as_of": run.as_of.isoformat(),
                "customers": run.customers_screened,
                "entries": run.entries_screened,
                "candidate_pairs": run.candidate_pairs,
                "recorded": run.recorded,
                "alerts": run.alerts,
                "reviews": run.reviews,
                "auto_cleared": run.auto_cleared,
                "superseded": run.superseded,
            },
        )
    )
    return events


def run_screening(
    db: Database,
    settings: Settings,
    *,
    as_of: date | None = None,
    token_stats: TokenStats | None = None,
) -> ScreeningRun:
    """Screen every customer against the watchlist, store the results and audit each one."""
    as_of = as_of or settings.data.reference_date
    cfg = settings.screening
    inputs = load_inputs(db)  # raises ScreeningError before anything is written
    customers = customer_norms(inputs, cfg)
    stats = token_stats or customer_token_stats(db, cfg)
    best, n_candidates = best_matches(customers, entry_names(inputs, cfg), stats, cfg)

    cust_ids = {str(r.cif): customer_identifiers(r) for r in inputs.customers.itertuples()}
    entries = {str(r.entry_id): r for r in inputs.entries.itertuples()}
    recorded: list[_Recorded] = []
    for (cif, entry_id), match in sorted(best.items()):
        entry = entries[entry_id]
        outcome = decide(match.score, cust_ids[cif], entry_identifiers(entry), cfg, as_of=as_of)
        if outcome is not None:
            list_type = None if pd.isna(entry.list_type) else str(entry.list_type)
            recorded.append(_Recorded(cif, entry_id, list_type, match, outcome))

    def count(label: str) -> int:
        return sum(r.decision.decision == label for r in recorded)

    # Results count too: a run that failed before its screening_runs row must not reuse its id.
    run_id = 1 + max(
        _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM screening_runs"),
        _scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM screening_results"),
    )
    superseded = _scalar(db, "SELECT COUNT(*) FROM screening_results WHERE superseded_by IS NULL")
    run = ScreeningRun(
        run_id, "FULL", as_of, len(inputs.customers), len(inputs.entries), n_candidates,
        len(recorded), count(ALERT), count(REVIEW), count(AUTO_CLEARED), superseded,
    )  # fmt: skip

    # Each statement commits on its own, so the new rows go in before the old ones are
    # superseded: a failed insert leaves the previous alerts current instead of none.
    if recorded:
        db.insert_df("screening_results", _result_rows(run_id, recorded))
    db.execute(
        f"UPDATE screening_results SET superseded_by = {run_id} "
        f"WHERE superseded_by IS NULL AND run_id < {run_id}"
    )
    run_row = _run_row(run, settings)
    if db.backend == "oracle":  # MODE is reserved: the column is created quoted ("MODE")
        run_row = run_row.rename(columns={"mode": '"MODE"'})
    db.insert_df("screening_runs", run_row)
    audit_many(db, _audit_events(run, recorded))
    return run
