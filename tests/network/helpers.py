"""Helpers for the Phase 5c tests (specs/network-detections.md): imports, MINI sets, TINY."""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from aml.common.config import Settings, load_settings
from aml.common.db import Database, DuckDb

AS_OF = date(2026, 6, 30)
M = 1_000_000
RULE_IDS = ("NET_SHARED_ATTRIBUTE", "NET_CYCLE", "NET_HUB")
TYPOLOGIES = [
    "structuring",
    "rapid_movement",
    "mule_ring",
    "round_tripping",
    "benign_payroll",
    "benign_merchant",
]
EVAL_COLUMNS = [
    "rule_id",
    "target_typology",
    "alerts",
    "target_hits",
    "other_suspicious",
    "benign",
    "unlabelled",
    "precision",
    "precision_suspicious",
    "scenarios",
    "detected",
    "recall",
]
EVAL_VALUE_COLUMNS = EVAL_COLUMNS[2:]
# rule_id -> (alerts, target_hits, other_suspicious, benign, unlabelled, precision,
#             precision_suspicious, scenarios, detected, recall) on TINY
EVAL_EXPECTED: dict[str, tuple[Any, ...]] = {
    "NET_SHARED_ATTRIBUTE": (1, 1, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0),
    "NET_CYCLE": (2, 2, 0, 0, 0, 1.0, 1.0, 2, 2, 1.0),
    "NET_HUB": (1, 1, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0),
}
COVERAGE_COLUMNS = [
    "typology",
    "is_suspicious",
    "scenarios",
    "flagged_rule",
    "flagged_network",
    "flagged_any",
    "new_by_network",
    "accounts",
    "accounts_rule",
    "accounts_network",
    "accounts_any",
    "accounts_new",
    "rules",
]
COVERAGE_VALUE_COLUMNS = COVERAGE_COLUMNS[2:12]
# typology -> (scenarios, flagged_rule, flagged_network, flagged_any, new_by_network, accounts,
#              accounts_rule, accounts_network, accounts_any, accounts_new)
COVERAGE_EXPECTED: dict[str, tuple[int, ...]] = {
    "structuring": (2, 2, 0, 2, 0, 2, 2, 0, 2, 0),
    "rapid_movement": (2, 2, 0, 2, 0, 10, 2, 0, 2, 0),
    "mule_ring": (1, 1, 1, 1, 0, 36, 14, 29, 36, 22),
    "round_tripping": (2, 2, 2, 2, 0, 8, 2, 8, 8, 6),
    "benign_payroll": (1, 0, 0, 0, 0, 21, 0, 0, 0, 0),
    "benign_merchant": (1, 0, 0, 0, 0, 35, 0, 0, 0, 0),
}
COVERAGE_RULES = {
    "structuring": "",
    "rapid_movement": "",
    "mule_ring": "NET_HUB,NET_SHARED_ATTRIBUTE",
    "round_tripping": "NET_CYCLE",
    "benign_payroll": "",
    "benign_merchant": "",
}

# TINY facts of the spec (seed 42)
SHR_TINY = "SHARED-CIF00000002"
HUB_TINY = "A4937939209"
MERCHANT_TINY = "A1463821795"
CYCLE_1 = "A1070944972>A8201784530>A3312263346>A9950029109"
CYCLE_2 = "A4750305205>A7799247681>A7641423153>A9059982551"


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings(**env: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


def cfg(**overrides: str) -> Settings:
    """Settings with ``AML__NETWORK__<KEY>`` overrides, e.g. ``cfg(CYCLES__WINDOW_HOURS="169")``."""
    return duck_settings(**{f"AML__NETWORK__{k}": v for k, v in overrides.items()})


def ts(text: str) -> datetime:
    return datetime.fromisoformat(text)


def query(db: Database, sql: str) -> pd.DataFrame:
    df = db.query_df(sql)
    df.columns = [c.lower() for c in df.columns]
    return df


def scalar(db: Database, sql: str) -> Any:
    return db.query_df(sql).iloc[0, 0]


def count(db: Database, table: str, where: str = "") -> int:
    return int(scalar(db, f"SELECT COUNT(*) FROM {table} {where}"))


def js(value: Any) -> Any:
    """Parse a JSON column value (DuckDB returns text, Oracle may return text or a dict)."""
    return json.loads(value) if isinstance(value, str) else value


def jd(value: Any) -> Any:
    """JSON round trip: tuples become lists, as in the stored ``details`` column."""
    return json.loads(json.dumps(value))


def none_if_nan(value: Any) -> Any:
    return None if value is None or bool(pd.isna(value)) else value


def has(line: str, token: str) -> bool:
    """True when ``token`` is a whole word of ``line`` (``alerts=1`` is not ``alerts=12``)."""
    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w.])", line) is not None


def lines_for(lines: Sequence[str], name: str, marker: str) -> list[str]:
    return [ln for ln in lines if ln.lstrip().startswith(name) and marker in ln]


def detect(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.graph.network.runner").detect_network(db, settings, **kw)


def run_network(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.graph.network.runner").run_network(db, settings, **kw)


def run_monitoring(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.monitoring.runner").run_monitoring(db, settings, **kw)


def run_er(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.entity_resolution.runner").run_er(db, settings, **kw)


def network_error() -> type[Exception]:
    return mod("aml.graph.network.runner").NetworkError


def of_rule(detections: Any, rule_id: str) -> list[Any]:
    return [a for a in detections.alerts if a.rule_id == rule_id]


def subjects(detections: Any, rule_id: str) -> list[str]:
    return [a.subject_id for a in of_rule(detections, rule_id)]


def load_tiny_duck(tiny_parquet: Path, path: Path) -> DuckDb:
    db = DuckDb(path)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return db


# ---------------------------------------------------------------- MINI data sets
Row = tuple[Any, ...]


def add_customers(db: Database, rows: Iterable[Row]) -> None:
    """rows: (cif, phone, device_id, street, ward, district, province)."""
    frame = pd.DataFrame(
        [
            {
                "cif": cif,
                "full_name": f"Khach {cif}",
                "gender": None,
                "dob": None,
                "nationality": "VN",
                "occupation": None,
                "kyc_risk": None,
                "id_type": None,
                "id_number": None,
                "phone": phone,
                "email": None,
                "device_id": device,
                "ip": None,
                "address_format": None if street is None else ("OLD" if district else "NEW"),
                "street": street,
                "ward": ward,
                "district": district,
                "province": province,
                "address": None,
            }
            for cif, phone, device, street, ward, district, province in rows
        ]
    )
    db.insert_df("customers", frame)


def add_accounts(db: Database, rows: Iterable[tuple[str, str, str]]) -> None:
    """rows: (account_id, cif, account_type)."""
    frame = pd.DataFrame(
        [
            {
                "account_id": account_id,
                "cif": cif,
                "account_type": account_type,
                "branch_id": "BR001",
                "open_date": date(2025, 1, 1),
                "currency": "VND",
            }
            for account_id, cif, account_type in rows
        ]
    )
    db.insert_df("accounts", frame)


def add_golden(db: Database, pairs: Sequence[tuple[str, str]]) -> None:
    """One er_runs row (run_id 1) and er_golden rows (cif, golden_customer_id)."""
    db.execute(
        "INSERT INTO er_runs (run_id, run_ts, as_of, customers_resolved, blocked_pairs, "
        "match_pairs, review_pairs, clusters, merged_clusters, merged_cifs, match_threshold, "
        "review_threshold, prior_probability, version, splink_version, config_hash) VALUES "
        "(1, TIMESTAMP '2026-06-30 00:00:00', DATE '2026-06-30', 0, 0, 0, 0, 0, 0, 0, "
        "0.95, 0.5, 0.001, 'er/v1', '5.0.0', '0000000000000000')"
    )
    sizes = pd.Series([g for _, g in pairs]).value_counts().to_dict()
    db.insert_df(
        "er_golden",
        pd.DataFrame(
            [
                {"run_id": 1, "cif": cif, "golden_customer_id": g, "cluster_size": sizes[g]}
                for cif, g in pairs
            ]
        ),
    )


def add_txns(db: Database, rows: Iterable[Row]) -> None:
    """rows: (txn_id, 'YYYY-MM-DD HH:MM:SS', from, to, amount_vnd); channel INTERNAL_TRANSFER."""
    frame = pd.DataFrame(
        [
            {
                "txn_id": txn_id,
                "txn_ts": pd.Timestamp(when),
                "from_account_id": src,
                "to_account_id": dst,
                "amount_vnd": int(amount),
                "channel": "INTERNAL_TRANSFER",
                "branch_id": None,
                "device_id": None,
                "ip": None,
                "counterparty_bank": None,
                "counterparty_name": None,
                "memo": None,
            }
            for txn_id, when, src, dst, amount in rows
        ]
    )
    frame["txn_ts"] = frame["txn_ts"].astype("datetime64[ns]")
    db.insert_df("transactions", frame)


def _own_customers(db: Database, names: Sequence[str]) -> None:
    add_customers(db, [(f"C-{n}", None, None, None, None, None, None) for n in names])


def load_shr(db: Database) -> None:
    mod("aml.dba.schema").apply_schema(db)
    hn = ("Phường An Phú", None, "Hà Nội")
    add_customers(
        db,
        [
            ("C01", "0901000001", "DEV-R", "1 Lê Lợi", "Phường An Phú", None, "TP. Hồ Chí Minh"),
            ("C02", "+84 90 100 0001", "DEV-02", "2 Hai Bà Trưng", *hn),
            ("C03", "0903000003", "DEV-R", "3 Hai Bà Trưng", *hn),
            (
                "C04",
                "0904000004",
                "DEV-04",
                "1 Lê Lợi",
                "Phường Bình Thạnh",
                "Quận Tân Phú",
                "Bà Rịa - Vũng Tàu",
            ),
            ("C05", "0905000005", "DEV-04", "5 Hai Bà Trưng", *hn),
            ("C06", "0906000006", "DEV-06", "6 Nguyễn Huệ", *hn),
            ("C07", "0906000006", "DEV-06", "6 Nguyễn Huệ", *hn),
            ("C08", "0906000006", "DEV-06", "6 Nguyễn Huệ", *hn),
            ("C09", "0909000009", "DEV-09", "6 Nguyễn Huệ", *hn),
            ("C10", "0910000010", "DEV-06", "10 Hai Bà Trưng", *hn),
            ("C11", "0906 000 006", "DEV-11", "11 Hai Bà Trưng", *hn),
            ("C12", "0912000012", "DEV-12", "12 Pasteur", *hn),
            ("C13", "0913000013", "DEV-13", "12 Pasteur", *hn),
            *[(f"C{n}", "0999999999", f"DEV-{n}", f"{n} Hai Bà Trưng", *hn) for n in range(14, 20)],
            ("C20", "12345", None, None, None, None, None),
            ("C21", "12345", None, None, None, None, None),
            ("C22", None, "", "", None, None, None),
        ],
    )
    db.insert_df(
        "admin_unit_mapping",
        pd.DataFrame(
            [
                {
                    "old_ward": "Phường Bình Thạnh",
                    "old_district": "Quận Tân Phú",
                    "old_province": "Bà Rịa - Vũng Tàu",
                    "new_ward": "Phường An Phú",
                    "new_province": "TP. Hồ Chí Minh",
                }
            ]
        ),
    )
    add_accounts(
        db,
        [(f"A{n:02d}", f"C{n:02d}", "CURRENT") for n in range(1, 23)]
        + [("A01S", "C01", "SAVINGS")],
    )
    golden = [(f"C{n:02d}", f"G-C{n:02d}") for n in range(1, 23) if n not in (7, 8, 19)]
    add_golden(db, [*golden, ("C07", "G-C06"), ("C08", "G-C06")])
    add_txns(
        db,
        [
            ("T01", "2026-03-01 10:00:00", "A02", "A01", 10 * M),
            ("T02", "2026-03-02 10:00:00", "A03", "A01", 20 * M),
            ("T03", "2026-03-03 10:00:00", "A01", "EXT-01", 25 * M),
            ("T04", "2026-03-03 11:00:00", "A01", "A20", 5 * M),
            ("T05", "2026-03-04 10:00:00", "A01", "A01S", 3 * M),
            ("T06", "2026-07-01 10:00:00", "A04", "A01", 7 * M),
            ("T07", "2026-03-05 10:00:00", "A05", "A04", 1 * M),
        ],
    )


CYC_NAMES = [
    *("B1", "B2", "B3", "D1", "D2", "D3", "E1", "E2", "E3", "F1", "F2"),
    *("G1", "G2", "G3", "G4", "H1", "H2", "H3", "I1", "I2", "I3"),
    *("J1", "J2", "J3", "J4", "J5", "J6", "L1", "L2", "L3", "M1", "M2"),
]


def load_cyc(db: Database) -> None:
    mod("aml.dba.schema").apply_schema(db)
    _own_customers(db, CYC_NAMES)
    add_accounts(db, [(n, f"C-{n}", "CURRENT") for n in CYC_NAMES] + [("G1S", "C-G1", "SAVINGS")])
    add_golden(db, [(f"C-{n}", f"G-C-{n}") for n in CYC_NAMES])
    add_txns(
        db,
        [
            ("Y01", "2026-03-01 10:00:00", "B1", "B2", 100 * M),
            ("Y02", "2026-03-02 10:00:00", "B2", "B3", 95 * M),
            ("Y02D", "2026-03-02 10:00:00", "B2", "B3", 95 * M),
            ("Y03", "2026-03-03 10:00:00", "B3", "B1", 90 * M),
            ("Y11", "2026-05-01 10:00:00", "B2", "B3", 80 * M),
            ("Y12", "2026-05-02 10:00:00", "B3", "B1", 80 * M),
            ("Y13", "2026-05-03 10:00:00", "B1", "B2", 80 * M),
            ("Y21", "2026-03-05 10:00:00", "D1", "D2", 100 * M),
            ("Y22", "2026-03-04 10:00:00", "D2", "D3", 100 * M),
            ("Y23", "2026-03-06 10:00:00", "D3", "D1", 100 * M),
            ("Y31", "2026-04-01 10:00:00", "E1", "E2", 100 * M),
            ("Y32", "2026-04-03 10:00:00", "E2", "E3", 100 * M),
            ("Y33", "2026-04-08 10:00:00", "E3", "E1", 100 * M),
            ("Y41", "2026-03-01 10:00:00", "F1", "F2", 100 * M),
            ("Y42", "2026-03-02 10:00:00", "F2", "F1", 100 * M),
            ("Y51", "2026-03-01 10:00:00", "G1", "G2", 100 * M),
            ("Y52", "2026-03-02 10:00:00", "G2", "G3", 100 * M),
            ("Y53", "2026-03-03 10:00:00", "G3", "G1S", 100 * M),
            ("Y54", "2026-03-04 10:00:00", "G1S", "G4", 100 * M),
            ("Y55", "2026-03-05 10:00:00", "G4", "G1", 100 * M),
            ("Y61", "2026-03-01 10:00:00", "H1", "H2", 100 * M),
            ("Y62", "2026-03-02 10:00:00", "H2", "H3", 69 * M),
            ("Y63", "2026-03-03 10:00:00", "H3", "H1", 69 * M),
            ("Y71", "2026-03-01 10:00:00", "I1", "I2", 60 * M),
            ("Y72", "2026-03-02 10:00:00", "I2", "I3", 49_999_000),
            ("Y73", "2026-03-03 10:00:00", "I3", "I1", 55 * M),
            *[
                (
                    f"Y8{k + 1}",
                    f"2026-03-01 {10 + k}:00:00",
                    f"J{k + 1}",
                    f"J{(k + 1) % 6 + 1}",
                    100 * M,
                )
                for k in range(6)
            ],
            ("Y91", "2026-03-10 10:00:00", "L1", "L2", 100 * M),
            ("Y92", "2026-03-10 10:00:00", "L2", "L3", 100 * M),
            ("Y93", "2026-03-11 10:00:00", "L3", "L1", 100 * M),
            ("Y101", "2026-03-01 10:00:00", "M1", "EXT-5", 100 * M),
            ("Y102", "2026-03-02 10:00:00", "EXT-5", "M2", 100 * M),
            ("Y103", "2026-03-03 10:00:00", "M2", "M1", 100 * M),
        ],
    )


def load_hub(db: Database) -> None:
    mod("aml.dba.schema").apply_schema(db)
    hubs = ["P0", "Q0", "R0", "W0", "L0"]
    senders = (
        [f"S{k:02d}" for k in range(1, 11)]
        + [f"U{k:02d}" for k in range(1, 11)]
        + [f"V{k:02d}" for k in range(1, 10)]
        + [f"X{k:02d}" for k in range(1, 11)]
        + [f"Z{k:02d}" for k in range(1, 11)]
    )
    names = hubs + senders
    _own_customers(db, names)
    add_accounts(db, [(n, f"C-{n}", "CURRENT") for n in names])
    add_golden(db, [(f"C-{n}", "G-C-W0" if n in ("X09", "X10") else f"G-C-{n}") for n in names])
    rows: list[Row] = []
    for k in range(1, 11):
        rows.append((f"HP{k:02d}", f"2026-03-01 {k:02d}:00:00", f"S{k:02d}", "P0", 20 * M))
        rows.append((f"HQ{k:02d}", f"2026-03-02 {k:02d}:00:00", f"U{k:02d}", "Q0", 9_999_000))
        rows.append((f"HW{k:02d}", f"2026-03-04 {k:02d}:00:00", f"X{k:02d}", "W0", 20 * M))
        when = "2025-06-30 10:00:00" if k == 10 else f"2026-03-05 {k:02d}:00:00"
        rows.append((f"HL{k:02d}", when, f"Z{k:02d}", "L0", 20 * M))
    for k in range(1, 10):
        rows.append((f"HR{k:02d}", f"2026-03-03 {k:02d}:00:00", f"V{k:02d}", "R0", 20 * M))
    rows.append(("HP11", "2026-03-01 12:00:00", "S01", "P0", 20 * M))
    rows.append(("HP12", "2026-03-01 13:00:00", "EXT-1", "P0", 500 * M))
    rows.append(("HP13", "2026-03-06 10:00:00", "P0", "S02", 150 * M))
    add_txns(db, rows)
