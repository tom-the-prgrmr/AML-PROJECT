"""Steps shared by the FULL and INCREMENTAL screening runs: decide, record, audit.

``runner`` and ``incremental`` differ only in *which* pairs they screen; turning matches into
decisions, result rows, the run row and audit events is identical, so it lives here once.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pandas as pd

from aml.common.audit import AuditEvent
from aml.common.config import ScreeningConfig, Settings
from aml.common.db import Database
from aml.screening.decision import Decision, decide
from aml.screening.matching import (
    BestMatch,
    ScreeningInputs,
    customer_identifiers,
    entry_identifiers,
)

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
    mode: str  # "FULL" or "INCREMENTAL"
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
class Recorded:
    cif: str
    entry_id: str
    list_type: str | None
    match: BestMatch
    decision: Decision


def scalar(db: Database, sql: str) -> int:
    return int(db.query_df(sql).iloc[0, 0])


def config_hash(settings: Settings) -> str:
    # sql_length_band only shapes the SQL comparison, never a decision: changing it must not
    # force a full screen.
    cfg = settings.screening.model_dump(mode="json", exclude={"sql_length_band"})
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def next_run_id(db: Database) -> int:
    # Results count too: a run that failed before its screening_runs row must not reuse its id.
    return 1 + max(
        scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM screening_runs"),
        scalar(db, "SELECT COALESCE(MAX(run_id), 0) FROM screening_results"),
    )


def decide_pairs(
    best: dict[tuple[str, str], BestMatch],
    inputs: ScreeningInputs,
    cfg: ScreeningConfig,
    as_of: date,
) -> list[Recorded]:
    """Tier 2 for every best pair; pairs that decide() drops are not recorded."""
    wanted_cifs = {cif for cif, _ in best}
    cust_ids = {
        str(r.cif): customer_identifiers(r)
        for r in inputs.customers.itertuples()
        if str(r.cif) in wanted_cifs
    }
    entries = {str(r.entry_id): r for r in inputs.entries.itertuples()}
    recorded: list[Recorded] = []
    for (cif, entry_id), match in sorted(best.items()):
        entry = entries[entry_id]
        outcome = decide(match.score, cust_ids[cif], entry_identifiers(entry), cfg, as_of=as_of)
        if outcome is not None:
            list_type = None if pd.isna(entry.list_type) else str(entry.list_type)
            recorded.append(Recorded(cif, entry_id, list_type, match, outcome))
    return recorded


def result_rows(run_id: int, recorded: list[Recorded]) -> pd.DataFrame:
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


def insert_run_row(db: Database, run: ScreeningRun, settings: Settings) -> None:
    row = {
        **{c: getattr(run, c) for c in RUN_COLUMNS if hasattr(run, c)},
        "run_ts": datetime.now(UTC).replace(tzinfo=None),
        "version": SCREENING_VERSION,
        "config_hash": config_hash(settings),
    }
    df = pd.DataFrame([row], columns=RUN_COLUMNS)
    if db.backend == "oracle":  # MODE is reserved: the column is created quoted ("MODE")
        df = df.rename(columns={"mode": '"MODE"'})
    db.insert_df("screening_runs", df)


def match_events(run: ScreeningRun, recorded: list[Recorded]) -> list[AuditEvent]:
    return [
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


def run_event(run: ScreeningRun, extra: dict[str, int] | None = None) -> AuditEvent:
    """The run summary; ``extra`` adds counts (the INCREMENTAL delta sizes) to ``details``."""
    return AuditEvent(
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
            **(extra or {}),
        },
    )
