"""Screening reads of the API: the current hits with customer, human review and case."""

from __future__ import annotations

from typing import Any

import pandas as pd

from aml.api.values import in_filter, iso_date, lower_columns, plain
from aml.common.config import Settings
from aml.common.db import Database
from aml.screening.review import ScreeningReview, latest_reviews

DECISIONS = ("ALERT", "REVIEW", "AUTO_CLEARED")
CUSTOMER_KEYS = ("cif", "full_name", "birth_year", "nationality", "gender", "id_type", "id_number")


def _read(db: Database, name: str, where: str = "") -> pd.DataFrame:
    text = db.sql_file(f"api/{name}").read_text(encoding="utf-8").strip().rstrip(";")
    return lower_columns(db.query_df(f"{text} WHERE {where}" if where else text))


def _latest_screening_run(db: Database) -> tuple[int | None, str | None]:
    df = lower_columns(
        db.query_df(
            "SELECT run_id, as_of FROM screening_runs "
            "WHERE run_id = (SELECT MAX(run_id) FROM screening_runs)"
        )
    )
    if df.empty:
        return None, None
    return int(df.iloc[0]["run_id"]), iso_date(df.iloc[0]["as_of"])


def _customers(db: Database, cifs: list[str], *, masked: bool) -> dict[str, dict[str, Any]]:
    name = "screening_customers_masked.sql" if masked else "screening_customers_full.sql"
    df = _read(db, name, in_filter("cif", cifs))
    out: dict[str, dict[str, Any]] = {}
    for _, row in df.iterrows():
        customer = {key: plain(row[key]) for key in CUSTOMER_KEYS}
        if customer["birth_year"] is not None:
            customer["birth_year"] = int(customer["birth_year"])
        out[str(row["cif"])] = customer
    return out


def _review(review: ScreeningReview | None) -> dict[str, Any] | None:
    if review is None:
        return None
    return {
        "decision": review.decision,
        "reason": review.reason,
        "actor": review.actor,
        "decided_on": review.decided_on.isoformat(),
    }


def list_hits(
    db: Database,
    settings: Settings,
    *,
    decision: str | None,
    limit: int,
    offset: int,
    masked: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Hits ordered ALERT, REVIEW, AUTO_CLEARED, then score desc; returns ``(rows, meta)``."""
    run_id, as_of = _latest_screening_run(db)
    df = _read(db, "screening_hits.sql")
    counts = {name: int((df["decision"] == name).sum()) for name in DECISIONS}
    if decision is not None:
        df = df[df["decision"] == decision]
    df = df.assign(_rank=df["decision"].map({name: i for i, name in enumerate(DECISIONS)}))
    df = df.sort_values(
        ["_rank", "final_score", "cif", "entry_id"], ascending=[True, False, True, True]
    )
    page = df.iloc[offset : offset + limit]
    cifs = sorted({str(c) for c in page["cif"]})
    customers = _customers(db, cifs, masked=masked) if cifs else {}
    cases = {
        (str(r["cif"]), str(r["entry_id"])): str(r["case_id"])
        for _, r in _read(db, "screening_hit_cases.sql").iterrows()
    }
    reviews = latest_reviews(db)
    rows: list[dict[str, Any]] = []
    for _, r in page.iterrows():
        key = (str(r["cif"]), str(r["entry_id"]))
        row = {name: plain(r[name]) for name in page.columns if name != "_rank"}
        row["dob_gap_years"] = None if row["dob_gap_years"] is None else int(row["dob_gap_years"])
        row["run_id"] = int(row["run_id"])
        row["customer"] = customers.get(key[0])
        row["review"] = _review(reviews.get(key))
        row["case_id"] = cases.get(key)
        rows.append(row)
    meta: dict[str, Any] = {
        "run_id": run_id,
        "as_of": as_of,
        "total": len(df),
        "limit": limit,
        "offset": offset,
        "counts": counts,
        "thresholds": {
            "alert": settings.screening.alert_threshold,
            "review": settings.screening.review_threshold,
        },
    }
    return rows, meta
