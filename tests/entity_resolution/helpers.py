"""Helpers for the Phase 4 tests (specs/entity-resolution.md): lazy module access, TINY, MUT."""

from __future__ import annotations

import importlib
import itertools
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database, DuckDb

AS_OF = date(2026, 6, 30)

MATCH_REASON_95_253 = (
    "match probability 1.0000 >= 0.95 (weight 24.36: prior -10.30, name +6.40, dob +10.31, "
    "phone +9.57, email -0.86, address +9.24, id +0.00)"
)


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings(**extra: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **extra})


def load_tiny_duck(tiny_parquet: Path, path: Path) -> DuckDb:
    db = DuckDb(path)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return db


def query(db: Database, sql: str) -> pd.DataFrame:
    df = db.query_df(sql)
    df.columns = [c.lower() for c in df.columns]
    return df


def scalar(db: Database, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def run_er(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.entity_resolution.runner").run_er(db, settings, **kw)


def truth_pairs(db: Database) -> set[tuple[str, str]]:
    """All CIF pairs of the same person_id (ground truth), ordered (low, high)."""
    df = query(db, "SELECT cif, person_id FROM customer_person")
    pairs: set[tuple[str, str]] = set()
    for _, grp in df.groupby("person_id"):
        for a, b in itertools.combinations(sorted(grp["cif"]), 2):
            pairs.add((a, b))
    return pairs


def pairs_of(db: Database, run_id: int) -> pd.DataFrame:
    return query(db, f"SELECT * FROM er_pairs WHERE run_id = {run_id}")


def pair_row(df: pd.DataFrame, cif_l: str, cif_r: str) -> Any:
    sel = df[(df["cif_l"] == cif_l) & (df["cif_r"] == cif_r)]
    assert len(sel) == 1, (cif_l, cif_r, len(sel))
    return sel.iloc[0]


def has_pair(df: pd.DataFrame, cif_l: str, cif_r: str) -> bool:
    return bool(((df["cif_l"] == cif_l) & (df["cif_r"] == cif_r)).any())


def r2(value: Any) -> float:
    return round(float(value), 2)


def er_audit(db: Database) -> pd.DataFrame:
    return query(
        db,
        "SELECT entity_type, entity_id, decision, reason, version FROM audit_log "
        "WHERE module = 'entity_resolution' ORDER BY audit_id",
    )


def apply_mut(db: Database) -> None:
    """M1-M4 of the spec, in order."""
    db.execute("UPDATE customers SET phone = '0901234567' WHERE cif = 'CIF00000186'")
    db.execute(
        "INSERT INTO customers (cif, full_name, gender, dob, nationality, id_type, id_number, "
        "phone, email, address_format, street, ward, district, province, address) VALUES "
        "('CIF90000001', 'Lý Minh Long', 'M', DATE '1978-09-21', 'VN', 'CCCD', '001078000001', "
        "'0912345678', 'lml@example.com', 'NEW', '5 Lê Lợi', 'Phường An Phú', NULL, 'Hà Nội', "
        "'5 Lê Lợi, Phường An Phú, Hà Nội')"
    )
    db.execute(
        "INSERT INTO customer_person (cif, person_id, is_primary, variations) "
        "VALUES ('CIF90000001', 'P9000001', TRUE, NULL)"
    )
    db.execute(
        "INSERT INTO customers (cif, full_name, gender, dob, nationality, id_type, id_number, "
        "email, phone, address_format, street, ward, district, province, address) "
        "SELECT 'CIF90000002', 'Ngô Thị Lam', 'F', DATE '1999-03-03', 'VN', 'CMND', '123456789', "
        "'lam@example.com', phone, address_format, street, ward, district, province, address "
        "FROM customers WHERE cif = 'CIF00000002'"
    )
    db.execute(
        "INSERT INTO customer_person (cif, person_id, is_primary, variations) "
        "VALUES ('CIF90000002', 'P9000002', TRUE, NULL)"
    )
    db.execute(
        "UPDATE customers SET phone = '0934567890', address_format = 'NEW', "
        "ward = 'Phường An Phú', district = NULL, province = 'Huế', "
        "address = '205 Lê Lợi, Phường An Phú, Huế' WHERE cif = 'CIF00000006'"
    )
