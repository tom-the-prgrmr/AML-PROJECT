"""Full screening run: Tier 1 candidates, Tier 2 decisions, stored results and audit trail."""

from __future__ import annotations

from datetime import date

from aml.common.audit import audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.decision import ALERT, AUTO_CLEARED, REVIEW
from aml.screening.idf import TokenStats, customer_token_stats
from aml.screening.matching import (
    ScreeningError,
    best_matches,
    customer_norms,
    entry_names,
    load_inputs,
)
from aml.screening.recording import (
    SCREENING_VERSION,
    ScreeningRun,
    decide_pairs,
    insert_run_row,
    match_events,
    next_run_id,
    result_rows,
    run_event,
    scalar,
)
from aml.screening.state import (
    customer_fingerprints,
    entry_fingerprints,
    save_token_stats,
    write_state,
)

__all__ = ["SCREENING_VERSION", "ScreeningError", "ScreeningRun", "run_screening"]


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
    recorded = decide_pairs(best, inputs, cfg, as_of)

    def count(label: str) -> int:
        return sum(r.decision.decision == label for r in recorded)

    run_id = next_run_id(db)
    superseded = scalar(db, "SELECT COUNT(*) FROM screening_results WHERE superseded_by IS NULL")
    run = ScreeningRun(
        run_id, "FULL", as_of, len(inputs.customers), len(inputs.entries), n_candidates,
        len(recorded), count(ALERT), count(REVIEW), count(AUTO_CLEARED), superseded,
    )  # fmt: skip

    # Each statement commits on its own, so the new rows go in before the old ones are
    # superseded: a failed insert leaves the previous alerts current instead of none.
    if recorded:
        db.insert_df("screening_results", result_rows(run_id, recorded))
    db.execute(
        f"UPDATE screening_results SET superseded_by = {run_id} "
        f"WHERE superseded_by IS NULL AND run_id < {run_id}"
    )
    insert_run_row(db, run, settings)
    # What incremental screening needs: who was covered, and the IDF this run used.
    write_state(db, run_id, customer_fingerprints(inputs, cfg), entry_fingerprints(inputs, cfg))
    save_token_stats(db, run_id, stats)
    audit_many(db, [*match_events(run, recorded), run_event(run)])
    return run
