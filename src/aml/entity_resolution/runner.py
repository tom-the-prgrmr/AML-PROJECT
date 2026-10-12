"""Entity-resolution run: normalise, score with Splink, store results, audit, explain clusters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import splink

from aml.common.audit import audit_many
from aml.common.config import Settings
from aml.common.db import Database
from aml.entity_resolution.model import score_records
from aml.entity_resolution.normalize import prepare_records
from aml.entity_resolution.recording import (
    ER_VERSION,
    MATCH,
    REVIEW,
    decide_pairs,
    golden_ids,
    golden_rows,
    insert_run_row,
    merge_events,
    model_rows,
    next_run_id,
    pair_rows,
    review_events,
    run_event,
)

__all__ = ["ER_VERSION", "MATCH", "REVIEW", "ErError", "ErRun", "explain_cluster", "run_er"]

CUSTOMER_COLUMNS = (
    "cif, full_name, dob, id_type, id_number, phone, email, street, ward, district, province"
)


class ErError(RuntimeError):
    """Entity resolution cannot run (or explain) with the data it was given."""


@dataclass(frozen=True)
class ErRun:
    run_id: int
    as_of: date
    customers_resolved: int
    blocked_pairs: int  # pairs scored by Splink (all blocking rules, before any threshold)
    match_pairs: int
    review_pairs: int
    clusters: int  # distinct golden_customer_id, single-CIF clusters included
    merged_clusters: int  # clusters with 2+ CIFs
    merged_cifs: int  # CIFs inside those clusters


def _load(db: Database) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        customers = db.query_df(f"SELECT {CUSTOMER_COLUMNS} FROM customers ORDER BY cif")
        mapping = db.query_df(
            "SELECT old_ward, old_district, old_province, new_ward, new_province "
            "FROM admin_unit_mapping"
        )
    except Exception as exc:  # table not created yet: driver-specific error types
        raise ErError(f"customers is unavailable ({exc}); run `aml load` first") from exc
    if customers.empty:
        raise ErError("customers is empty; run `aml load` first")
    return customers, mapping


def run_er(db: Database, settings: Settings, *, as_of: date | None = None) -> ErRun:
    """Resolve every customer into a golden id; store the run, its evidence and its audit trail."""
    as_of = as_of or settings.data.reference_date
    cfg = settings.entity_resolution
    customers, mapping = _load(db)  # raises ErError before anything is written
    records = prepare_records(customers, mapping, settings, as_of=as_of)
    scored = score_records(records, cfg, seed=settings.seed)
    decided = decide_pairs(scored, cfg)
    golden = golden_ids(list(records["cif"]), scored)

    merged = golden[golden["cluster_size"] > 1]
    run_id = next_run_id(db)
    run = ErRun(
        run_id=run_id,
        as_of=as_of,
        customers_resolved=len(records),
        blocked_pairs=len(scored.pairs),
        match_pairs=int((decided["decision"] == MATCH).sum()),
        review_pairs=int((decided["decision"] == REVIEW).sum()),
        clusters=int(golden["golden_customer_id"].nunique()),
        merged_clusters=int(merged["golden_customer_id"].nunique()),
        merged_cifs=len(merged),
    )

    # er_runs goes last: the views follow MAX(run_id) there, so they switch to the new run only
    # once its model, pairs and golden ids are all stored.
    db.insert_df("er_model", model_rows(run_id, scored))
    if not decided.empty:
        db.insert_df("er_pairs", pair_rows(run_id, decided))
    db.insert_df("er_golden", golden_rows(run_id, golden))
    insert_run_row(db, run, settings, prior=scored.prior, splink_version=splink.__version__)
    audit_many(
        db,
        [*merge_events(run_id, golden, decided), *review_events(run_id, decided), run_event(run)],
    )
    return run


def explain_cluster(db: Database, golden_customer_id: str) -> pd.DataFrame:
    """MATCH pairs inside one cluster of the current run, ordered by (cif_l, cif_r)."""
    gid = golden_customer_id.replace("'", "''")
    known = db.query_df(f"SELECT COUNT(*) FROM customer_golden WHERE golden_customer_id = '{gid}'")
    if int(known.iloc[0, 0]) == 0:
        raise ErError(f"unknown golden_customer_id {golden_customer_id!r}")
    return db.query_df(
        "SELECT p.cif_l, p.cif_r, p.match_weight, p.match_probability, p.mw_prior, p.mw_name, "
        "p.mw_dob, p.mw_phone, p.mw_email, p.mw_address, p.mw_id, p.decision, p.reason "
        "FROM er_pairs p "
        "JOIN customer_golden g ON g.cif = p.cif_l "
        "JOIN customer_golden r ON r.cif = p.cif_r AND r.golden_customer_id = g.golden_customer_id "
        "WHERE p.run_id = (SELECT MAX(run_id) FROM er_runs) AND p.decision = 'MATCH' "
        f"AND g.golden_customer_id = '{gid}' ORDER BY p.cif_l, p.cif_r"
    )
