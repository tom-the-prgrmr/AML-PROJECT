"""What the last screening covered: entity fingerprints and the frozen IDF statistics.

A fingerprint is the SHA-256 of exactly the fields that feed Tier 1 and Tier 2, joined by ``|``
(null -> empty string). It is computed in Python so both backends agree, and changing a field
that does not influence the decision (phone, address, program...) leaves it unchanged.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from datetime import date
from typing import Any

import pandas as pd

from aml.common.config import ScreeningConfig
from aml.common.db import Database
from aml.screening.idf import TokenStats
from aml.screening.matching import ScreeningInputs, as_date, entry_names
from aml.screening.normalize import normalize_name

CUSTOMER = "customer"
ENTRY = "watchlist_entry"
IN_LIMIT = 1000  # Oracle accepts at most 1000 items in an IN list
STATE_COLUMNS = ["entity_type", "entity_id", "fingerprint", "run_id"]
STATS_COLUMNS = ["token", "doc_freq", "n_names", "run_id"]


def _field(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    day = as_date(value)
    return day.isoformat() if isinstance(day, date) else str(value)


def _digest(parts: Iterable[str]) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def customer_fingerprints(inputs: ScreeningInputs, cfg: ScreeningConfig) -> dict[str, str]:
    """cif -> fingerprint of normalised name, dob, nationality, gender, id_number."""
    return {
        str(r.cif): _digest(
            [
                normalize_name(r.full_name, cfg),
                _field(r.dob),
                _field(r.nationality),
                _field(r.gender),
                _field(r.id_number),
            ]
        )
        for r in inputs.customers.itertuples()
    }


def entry_fingerprints(inputs: ScreeningInputs, cfg: ScreeningConfig) -> dict[str, str]:
    """entry_id -> fingerprint of list type, DOB columns, nationality and every normalised name."""
    names: dict[str, list[str]] = defaultdict(list)
    for norm, items in entry_names(inputs, cfg).items():
        for entry_id, name_type in items:
            names[entry_id].append(f"{name_type}:{norm}")
    out: dict[str, str] = {}
    for r in inputs.entries.itertuples():
        year = "" if pd.isna(r.dob_year) else str(int(r.dob_year))  # float when a column has NULLs
        out[str(r.entry_id)] = _digest(
            [
                _field(r.list_type),
                _field(r.dob),
                year,
                _field(r.dob_precision),
                _field(r.nationality),
                ";".join(sorted(names[str(r.entry_id)])),
            ]
        )
    return out


def chunks(ids: Sequence[str], size: int = IN_LIMIT) -> Iterator[list[str]]:
    for start in range(0, len(ids), size):
        yield list(ids[start : start + size])


def quoted_list(ids: Iterable[str]) -> str:
    """SQL list of string literals; ids are escaped, never concatenated raw."""
    return ", ".join("'" + str(i).replace("'", "''") + "'" for i in ids)


def read_state(db: Database) -> dict[str, dict[str, str]]:
    """entity_type -> {entity_id: fingerprint} as stored by the last screening."""
    df = db.query_df("SELECT entity_type, entity_id, fingerprint FROM screening_state")
    out: dict[str, dict[str, str]] = {CUSTOMER: {}, ENTRY: {}}
    for r in df.itertuples():
        out.setdefault(str(r.entity_type), {})[str(r.entity_id)] = str(r.fingerprint)
    return out


def _state_rows(run_id: int, entity_type: str, fingerprints: dict[str, str]) -> pd.DataFrame:
    rows = [(entity_type, eid, fp, run_id) for eid, fp in sorted(fingerprints.items())]
    return pd.DataFrame(rows, columns=STATE_COLUMNS)


def write_state(
    db: Database, run_id: int, customers: dict[str, str], entries: dict[str, str]
) -> None:
    """Replace the whole state (a FULL run covers every customer and entry)."""
    db.execute("DELETE FROM screening_state")
    for entity_type, fingerprints in ((CUSTOMER, customers), (ENTRY, entries)):
        if fingerprints:
            db.insert_df("screening_state", _state_rows(run_id, entity_type, fingerprints))


def update_state(
    db: Database,
    run_id: int,
    entity_type: str,
    drop: Iterable[str],
    fingerprints: dict[str, str],
) -> None:
    """Targeted update: delete ``drop`` ids, insert ``fingerprints`` (already-changed ids)."""
    for batch in chunks(sorted(drop)):
        db.execute(
            f"DELETE FROM screening_state WHERE entity_type = '{entity_type}' "
            f"AND entity_id IN ({quoted_list(batch)})"
        )
    if fingerprints:
        db.insert_df("screening_state", _state_rows(run_id, entity_type, fingerprints))


def save_token_stats(db: Database, run_id: int, stats: TokenStats) -> None:
    """Replace the frozen IDF statistics with the ones the FULL run just used."""
    db.execute("DELETE FROM screening_token_stats")
    rows = [(t, int(n), stats.n_names, run_id) for t, n in sorted(stats.doc_freq.items())]
    if rows:
        db.insert_df("screening_token_stats", pd.DataFrame(rows, columns=STATS_COLUMNS))


def load_token_stats(db: Database) -> TokenStats | None:
    """The frozen statistics, or None when no FULL run has stored any."""
    df = db.query_df("SELECT token, doc_freq, n_names FROM screening_token_stats")
    if df.empty:
        return None
    doc_freq = {str(t): int(n) for t, n in zip(df["token"], df["doc_freq"], strict=True)}
    return TokenStats(n_names=int(df["n_names"].iloc[0]), doc_freq=doc_freq)
