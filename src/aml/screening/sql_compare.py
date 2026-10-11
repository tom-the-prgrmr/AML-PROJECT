"""SQL screen (Jaro-Winkler inside the database) and its comparison with the two-tier screen.

Python normalises the names once and writes them to two tables; the SQL only reads them. The
comparison counts which (cif, entry_id) pairs each side flags. Synthetic data only.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

import pandas as pd

from aml.common.audit import audit
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.evaluate import Pair, current_pairs, truth_pairs
from aml.screening.matching import (
    PRIMARY,
    ScreeningError,
    customer_norms,
    entry_names,
    load_inputs,
)
from aml.screening.normalize import name_key

SQL_FUNCTIONS = {
    "oracle": "UTL_MATCH.JARO_WINKLER_SIMILARITY",
    "duckdb": "jaro_winkler_similarity",
}
SQL_SCRIPT = "screening/jw_screen.sql"
COMPARE_VERSION = "screening/sql-compare"
SQL_COLUMNS = ["cif", "entry_id", "jw_score"]


@dataclass(frozen=True)
class SqlComparison:
    backend: str
    function: str  # SQL_FUNCTIONS[backend]
    threshold: int  # = screening.alert_threshold
    sql_pairs: int  # (cif, entry_id) pairs returned by the SQL screen
    python_pairs: int  # ALERT + REVIEW pairs in screening_current
    both: int
    sql_only: int
    python_only: int
    truth: int  # ground-truth pairs
    sql_tp: int
    python_tp: int
    sql_seconds: float  # time to run the SQL statement


def sync_screening_names(db: Database, settings: Settings) -> dict[str, int]:
    """Rewrite both name tables from the current customers and watchlist; return row counts."""
    cfg = settings.screening
    inputs = load_inputs(db)
    customers = [
        {"cif": cif, "name_norm": norm, "name_key": name_key(norm)}
        for norm, cifs in customer_norms(inputs, cfg).items()
        for cif in cifs
    ]
    chosen: dict[tuple[str, str], str] = {}  # (entry_id, name_norm) -> name_type, PRIMARY wins
    for norm, items in entry_names(inputs, cfg).items():
        for entry_id, name_type in items:
            key = (entry_id, norm)
            if key not in chosen or (name_type == PRIMARY and chosen[key] != PRIMARY):
                chosen[key] = name_type
    names = [
        {"entry_id": e, "name_type": t, "name_norm": n, "name_key": name_key(n)}
        for (e, n), t in sorted(chosen.items())
    ]

    db.execute("DELETE FROM screening_customer_name")
    db.execute("DELETE FROM screening_list_name")
    db.insert_df(
        "screening_customer_name",
        pd.DataFrame(customers, columns=["cif", "name_norm", "name_key"]),
    )
    db.insert_df(
        "screening_list_name",
        pd.DataFrame(names, columns=["entry_id", "name_type", "name_norm", "name_key"]),
    )
    return {"screening_customer_name": len(customers), "screening_list_name": len(names)}


def _load_sql(db: Database, name: str, threshold: int, length_band: int) -> str:
    """Read a SQL file; only {threshold} and {length_band} are substituted, from integers."""
    text = db.sql_file(name).read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    if lines and lines[-1].strip() == "/":  # Oracle terminator
        text = "\n".join(lines[:-1])
    text = text.strip().rstrip(";")
    return text.replace("{threshold}", str(int(threshold))).replace(
        "{length_band}", str(int(length_band))
    )


def sql_screen(db: Database, settings: Settings) -> pd.DataFrame:
    """Run the SQL screen over the synced name tables: columns cif, entry_id, jw_score (int)."""
    cfg = settings.screening
    sql = _load_sql(db, SQL_SCRIPT, int(cfg.alert_threshold), cfg.sql_length_band)
    df = db.query_df(sql)
    df.columns = [str(c).lower() for c in df.columns]
    out = pd.DataFrame(
        {
            "cif": df["cif"].astype(str),
            "entry_id": df["entry_id"].astype(str),
            "jw_score": df["jw_score"].astype(int),
        },
        columns=SQL_COLUMNS,
    )
    return out.sort_values(["cif", "entry_id"], kind="stable").reset_index(drop=True)


def compare_sql_python(db: Database, settings: Settings) -> SqlComparison:
    """Run the SQL screen and compare its pairs with the two-tier ALERT + REVIEW pairs."""
    runs = int(db.query_df("SELECT COUNT(*) FROM screening_runs").iloc[0, 0])
    if runs == 0:
        raise ScreeningError("no screening run found; run `aml screen` first")
    sync_screening_names(db, settings)
    started = time.perf_counter()
    df = sql_screen(db, settings)
    seconds = time.perf_counter() - started

    sql_set: set[Pair] = set(zip(df["cif"], df["entry_id"], strict=True))
    python_set = current_pairs(db, "'ALERT', 'REVIEW'")
    truth = truth_pairs(db)
    result = SqlComparison(
        backend=db.backend,
        function=SQL_FUNCTIONS[db.backend],
        threshold=int(settings.screening.alert_threshold),
        sql_pairs=len(sql_set),
        python_pairs=len(python_set),
        both=len(sql_set & python_set),
        sql_only=len(sql_set - python_set),
        python_only=len(python_set - sql_set),
        truth=len(truth),
        sql_tp=len(sql_set & truth),
        python_tp=len(python_set & truth),
        sql_seconds=seconds,
    )
    audit(
        db,
        module="screening",
        entity_type="screening_compare",
        entity_id=db.backend,
        decision="COMPARISON_CAPTURED",
        reason=(
            f"{result.function} flagged {result.sql_pairs} pairs at >= {result.threshold}, the "
            f"two-tier screen {result.python_pairs}: {result.both} in both, {result.sql_only} "
            f"only SQL, {result.python_only} only Python; true hits {result.sql_tp}/{result.truth} "
            f"(SQL) and {result.python_tp}/{result.truth} (Python)."
        ),
        version=COMPARE_VERSION,
        details=asdict(result),
    )
    return result
