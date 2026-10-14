"""Features of a screening pair: how well the names, rarity and identifiers agree.

The 19 features are raw evidence, recomputed with the same functions Tier 1 and Tier 2 use. They
never include the rule's own output (final score, decision, reason), so the model is a second
opinion rather than a copy of the rule. Rows are stored long, one per pair and feature.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd

from aml.common.config import ScreeningConfig, Settings
from aml.common.db import Database
from aml.screening.decision import Identifiers
from aml.screening.idf import TokenStats
from aml.screening.matching import (
    PRIMARY,
    as_date,
    customer_identifiers,
    entry_identifiers,
    load_inputs,
)
from aml.screening.ml.model import ScreeningMlError
from aml.screening.ml.store import require_schema, run_query
from aml.screening.normalize import normalize_name
from aml.screening.scoring import score_names
from aml.screening.state import load_token_stats

__all__ = ["FEATURES", "FEATURE_VERSION", "match_features", "read_features", "write_features"]

FEATURE_VERSION = "screening-ml-features/v1"
FEATURES: tuple[str, ...] = (
    "token_set", "jaro_winkler", "fuzzy_score", "coverage", "name_score",
    "matched_tokens", "token_count_gap", "rare_matched", "max_matched_idf", "common_only",
    "dob_known", "dob_gap_years", "dob_within_tolerance",
    "nationality_match", "nationality_mismatch", "gender_mismatch", "id_match",
    "alias_match", "sanctions_list",
)  # fmt: skip
MAX_DOB_GAP = 50  # a larger gap carries no extra information
NO_SCREENING = "no screening results: run `aml screen` first"
KEY = ["result_run_id", "cif", "entry_id"]


def _clean_id(value: str | None) -> str:
    """Upper-case letters and digits only (the ID number rule of Tier 2)."""
    return re.sub(r"[^0-9A-Z]", "", value.upper()) if value else ""


def _flag(condition: bool) -> float:
    return 1.0 if condition else 0.0


def _dob_gap(customer: Identifiers, entry: Identifiers, as_of: date) -> int | None:
    """Birth-year gap, or None when a side has no usable year (same rule as Tier 2)."""
    if customer.dob is None or customer.dob > as_of or entry.dob_year is None:
        return None
    return abs(customer.dob.year - entry.dob_year)


def match_features(
    customer_norm: str,
    list_norm: str,
    customer: Identifiers,
    entry: Identifiers,
    *,
    name_type: str,
    list_type: str | None,
    stats: TokenStats,
    cfg: ScreeningConfig,
    as_of: date,
) -> dict[str, float]:
    """The 19 features of one (customer name, list name) pair; pure."""
    n = score_names(customer_norm, list_norm, stats, cfg)
    gap = _dob_gap(customer, entry, as_of)
    both_nat = customer.nationality is not None and entry.nationality is not None
    same_nat = both_nat and customer.nationality == entry.nationality
    both_gender = customer.gender is not None and entry.gender is not None
    cust_id = _clean_id(customer.id_number)
    values: dict[str, float] = {
        "token_set": n.token_set,
        "jaro_winkler": n.jaro_winkler,
        "fuzzy_score": n.fuzzy,
        "coverage": n.coverage,
        "name_score": n.score,
        "matched_tokens": len(n.matched),
        "token_count_gap": abs(len(customer_norm.split()) - len(list_norm.split())),
        "rare_matched": sum(stats.is_rare(t, cfg.rare_token_max_df_rate) for t in n.matched),
        "max_matched_idf": round(max((stats.idf(t) for t in n.matched), default=0.0), 6),
        "common_only": _flag(n.common_only),
        "dob_known": _flag(gap is not None),
        "dob_gap_years": min(gap, MAX_DOB_GAP) if gap is not None else 0,
        "dob_within_tolerance": _flag(gap is not None and gap <= cfg.dob_tolerance_years),
        "nationality_match": _flag(same_nat),
        "nationality_mismatch": _flag(both_nat and not same_nat),
        "gender_mismatch": _flag(both_gender and customer.gender != entry.gender),
        "id_match": _flag(bool(cust_id) and cust_id == _clean_id(entry.id_number)),
        "alias_match": _flag(name_type != PRIMARY),
        "sanctions_list": _flag(list_type == "SANCTIONS"),
    }
    return {name: float(values[name]) for name in FEATURES}


def _as_of_by_run(db: Database) -> dict[int, date]:
    df = run_query(db, "run_dates")
    return {int(r): as_date(d) for r, d in zip(df["run_id"], df["as_of"], strict=True)}


def _pending(db: Database) -> pd.DataFrame:
    try:
        return run_query(db, "pending_pairs")
    except Exception as exc:  # the tables are missing: driver-specific error types
        raise ScreeningMlError(f"{NO_SCREENING} ({exc})") from exc


def _rows(
    pending: pd.DataFrame,
    db: Database,
    cfg: ScreeningConfig,
    stats: TokenStats,
) -> list[dict[str, Any]]:
    inputs = load_inputs(db)
    cifs, entries = set(pending["cif"]), set(pending["entry_id"])
    customers = {
        str(r.cif): (normalize_name(r.full_name, cfg), customer_identifiers(r))
        for r in inputs.customers[inputs.customers["cif"].isin(cifs)].itertuples()
    }
    listed = {
        str(r.entry_id): entry_identifiers(r)
        for r in inputs.entries[inputs.entries["entry_id"].isin(entries)].itertuples()
    }
    as_of = _as_of_by_run(db)
    out: list[dict[str, Any]] = []
    for p in pending.itertuples():
        cust_norm, cust = customers[str(p.cif)]
        values = match_features(
            cust_norm,
            str(p.matched_name),
            cust,
            listed[str(p.entry_id)],
            name_type=str(p.matched_name_type),
            list_type=None if pd.isna(p.list_type) else str(p.list_type),
            stats=stats,
            cfg=cfg,
            as_of=as_of[int(p.result_run_id)],
        )
        key = {
            "result_run_id": int(p.result_run_id),
            "cif": str(p.cif),
            "entry_id": str(p.entry_id),
        }
        out.extend({**key, "feature": name, "value": value} for name, value in values.items())
    return out


def write_features(db: Database, settings: Settings) -> int:
    """Store the features of the current hits that have none yet; return the pairs written."""
    require_schema(db)
    try:
        stats = load_token_stats(db)
    except Exception as exc:  # the table is missing: driver-specific error types
        raise ScreeningMlError(f"{NO_SCREENING} ({exc})") from exc
    if stats is None:
        raise ScreeningMlError(NO_SCREENING)
    pending = _pending(db)
    if pending.empty:
        return 0
    rows = _rows(pending, db, settings.screening, stats)
    db.insert_df("screening_ml_features", pd.DataFrame(rows))
    return len(pending)


def read_features(db: Database) -> pd.DataFrame:
    """Features of every current hit: index ``(result_run_id, cif, entry_id)``, columns FEATURES."""
    long = run_query(db, "features_current")
    if long.empty:
        return pd.DataFrame(
            columns=list(FEATURES),
            index=pd.MultiIndex.from_arrays([[], [], []], names=KEY),
            dtype=float,
        )
    wide = long.pivot(index=KEY, columns="feature", values="value")
    return wide[list(FEATURES)].astype(float).sort_index()
