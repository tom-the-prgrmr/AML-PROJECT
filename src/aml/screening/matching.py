"""Read the screening inputs and reduce Tier 1 candidates to one best match per (cif, entry)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from aml.common.config import ScreeningConfig
from aml.common.db import Database
from aml.screening.candidates import candidate_name_pairs
from aml.screening.decision import Identifiers
from aml.screening.idf import TokenStats
from aml.screening.normalize import normalize_name
from aml.screening.scoring import NameScore, score_names

PRIMARY = "PRIMARY"
INPUT_TABLES = ("customers", "watchlist", "watchlist_alias")  # whitelist: names go into SQL


class ScreeningError(RuntimeError):
    """Screening cannot run (for example, the input tables are empty)."""


@dataclass(frozen=True)
class ScreeningInputs:
    customers: pd.DataFrame  # cif, full_name, gender, dob, nationality, id_number
    entries: pd.DataFrame  # entry_id, list_type, primary_name, dob*, nationality (see load_inputs)
    aliases: pd.DataFrame  # entry_id, alias_name, alias_type


@dataclass(frozen=True)
class BestMatch:
    name: str  # matched list name, normalised
    name_type: str
    score: NameScore


def load_inputs(db: Database) -> ScreeningInputs:
    """Read the three input tables; raise ``ScreeningError`` if any is missing or empty."""
    for table in INPUT_TABLES:
        try:
            n = int(db.query_df(f"SELECT COUNT(*) FROM {table}").iloc[0, 0])
        except Exception as exc:  # table not created yet: driver-specific error types
            raise ScreeningError(f"{table} is unavailable ({exc}); run `aml load` first") from exc
        if n == 0:
            raise ScreeningError(f"{table} is empty; run `aml load` first")
    return ScreeningInputs(
        customers=db.query_df(
            "SELECT cif, full_name, gender, dob, nationality, id_number FROM customers"
        ),
        entries=db.query_df(
            "SELECT entry_id, list_type, primary_name, dob, dob_year, dob_precision, nationality "
            "FROM watchlist"
        ),
        aliases=db.query_df("SELECT entry_id, alias_name, alias_type FROM watchlist_alias"),
    )


def _text(value: Any) -> str | None:
    return None if value is None or pd.isna(value) else str(value)


def as_date(value: Any) -> date | None:
    """DuckDB gives datetime64 and Oracle datetime for DATE columns; both become ``date``."""
    if value is None or pd.isna(value):
        return None
    return value.date() if isinstance(value, datetime) else value


def customer_identifiers(row: Any) -> Identifiers:
    dob = as_date(row.dob)
    return Identifiers(
        dob=dob,
        dob_year=dob.year if dob else None,
        nationality=_text(row.nationality),
        gender=_text(row.gender),
        id_number=_text(row.id_number),
    )


def entry_identifiers(row: Any) -> Identifiers:
    year = None if pd.isna(row.dob_year) else int(row.dob_year)
    return Identifiers(dob_year=year, nationality=_text(row.nationality))


def customer_norms(inputs: ScreeningInputs, cfg: ScreeningConfig) -> dict[str, list[str]]:
    """Normalised customer name -> CIFs (empty names dropped)."""
    out: dict[str, list[str]] = defaultdict(list)
    for cif, name in zip(inputs.customers["cif"], inputs.customers["full_name"], strict=True):
        norm = normalize_name(name, cfg)
        if norm:
            out[norm].append(str(cif))
    return out


def entry_names(inputs: ScreeningInputs, cfg: ScreeningConfig) -> dict[str, list[tuple[str, str]]]:
    """Normalised list name -> [(entry_id, name type)]: the primary name plus every alias."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    primary = zip(
        inputs.entries["entry_id"],
        inputs.entries["primary_name"],
        [PRIMARY] * len(inputs.entries),
        strict=True,
    )
    aliases = zip(
        inputs.aliases["entry_id"],
        inputs.aliases["alias_name"],
        inputs.aliases["alias_type"],
        strict=True,
    )
    for entry_id, name, name_type in [*primary, *aliases]:
        norm = normalize_name(name, cfg)
        if norm:
            out[norm].append((str(entry_id), str(name_type)))
    return out


def match_candidates(
    customers: dict[str, list[str]],
    names: dict[str, list[tuple[str, str]]],
    stats: TokenStats,
    cfg: ScreeningConfig,
) -> tuple[dict[tuple[str, str], BestMatch], set[tuple[str, str]]]:
    """Best name per (cif, entry_id) with fuzzy >= review_threshold, and every candidate pair."""
    pairs = candidate_name_pairs(customers, names, stats, cfg)
    scores: dict[tuple[str, str], NameScore] = {}  # one score per distinct name pair
    candidates: set[tuple[str, str]] = set()
    best: dict[tuple[str, str], BestMatch] = {}
    rank: dict[tuple[str, str], tuple[float, float, bool, str]] = {}
    for cust_name, list_name in sorted(pairs):
        if (cust_name, list_name) not in scores:
            scores[(cust_name, list_name)] = score_names(cust_name, list_name, stats, cfg)
        score = scores[(cust_name, list_name)]
        for entry_id, name_type in names[list_name]:
            for cif in customers[cust_name]:
                key = (cif, entry_id)
                candidates.add(key)
                if score.fuzzy < cfg.review_threshold:
                    continue
                order = (-score.score, -score.fuzzy, name_type != PRIMARY, list_name)
                if key not in rank or order < rank[key]:
                    rank[key] = order
                    best[key] = BestMatch(list_name, name_type, score)
    return best, candidates


def best_matches(
    customers: dict[str, list[str]],
    names: dict[str, list[tuple[str, str]]],
    stats: TokenStats,
    cfg: ScreeningConfig,
) -> tuple[dict[tuple[str, str], BestMatch], int]:
    """Like ``match_candidates`` but returns only the number of candidate pairs."""
    best, candidates = match_candidates(customers, names, stats, cfg)
    return best, len(candidates)
