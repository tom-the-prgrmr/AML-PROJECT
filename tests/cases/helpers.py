"""Helpers for the Phase 7a tests (specs/case-consolidation.md): MINI-C, wrappers, CLI."""

from __future__ import annotations

import importlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from typer.testing import CliRunner

from aml.common.config import Settings, load_settings
from aml.common.db import Database, DuckDb

AS_OF = date(2026, 6, 30)
M = 1_000_000
SECTIONS = ("kyc", "linked_cifs", "dq_issues", "txn_summary", "network", "history")
RULE_IDS = (
    "STRUCTURING",
    "RAPID_MOVEMENT",
    "HIGH_VELOCITY",
    "FAN_IN",
    "FAN_OUT",
    "DORMANT_REACTIVATION",
)
NETWORK_RULE_IDS = ("NET_SHARED_ATTRIBUTE", "NET_CYCLE", "NET_HUB")
OFFLINE_URI = "bolt://127.0.0.1:1"
N1_KEY = "NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00"
CASE_C01_A = "C-C01-20260302"
CASE_C01_B = "C-C01-20260531"
CASE_C03 = "C-C03-20260305"
CASE_C04 = "C-C04-20260305"
CASE_C05 = "C-C05-20260630"
MINI_CASES = (CASE_C01_A, CASE_C01_B, CASE_C03, CASE_C04, CASE_C05)
TINY_CASE = "C-CIF00000189-20260413"


def mod(name: str) -> Any:
    return importlib.import_module(name)


def duck_settings(**env: str) -> Settings:
    return load_settings(environ={"DB_BACKEND": "duckdb", **env})


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


def none_if_nan(value: Any) -> Any:
    return None if value is None or bool(pd.isna(value)) else value


def has(line: str, token: str) -> bool:
    """True when ``token`` appears in ``line`` as a whole word (``cases=5`` is not ``cases=52``)."""
    import re

    return re.search(rf"(?<![\w]){re.escape(token)}(?![\w.])", line) is not None


def run_cases(db: Database, settings: Settings, **kw: Any) -> Any:
    return mod("aml.cases.runner").run_cases(db, settings, **kw)


def load_case(db: Database, case_id: str, **kw: Any) -> Any:
    return mod("aml.cases.view").load_case(db, case_id, **kw)


def record_disposition(db: Database, settings: Settings, *args: Any, **kw: Any) -> int:
    return mod("aml.cases.dispositions").record_disposition(db, settings, *args, **kw)


def case_error() -> type[Exception]:
    return mod("aml.cases.runner").CaseError


def cases_current(db: Database) -> dict[str, Any]:
    df = query(db, "SELECT * FROM cases_current")
    return {row.case_id: row for row in df.itertuples()}


def enrichment(db: Database, case_id: str, run_id: int | None = None) -> dict[str, Any]:
    """Parsed ``content`` of the six sections of a case (latest run unless ``run_id`` is given)."""
    where = (
        f"run_id = {run_id}"
        if run_id is not None
        else "run_id = (SELECT MAX(run_id) FROM case_runs)"
    )
    df = query(
        db,
        f"SELECT section, content FROM case_enrichment WHERE {where} AND case_id = '{case_id}'",
    )
    return {r.section: js(r.content) for r in df.itertuples()}


def audit_cases(db: Database, where: str = "1 = 1") -> pd.DataFrame:
    df = query(
        db,
        "SELECT entity_type, entity_id, decision, reason, version, actor, details "
        f"FROM audit_log WHERE module = 'cases' AND ({where}) ORDER BY audit_id",
    )
    df["details"] = [js(d) for d in df["details"]]
    return df


def cli(*args: str) -> Any:
    return CliRunner().invoke(mod("aml.cli").app, list(args))


# ---------------------------------------------------------------- MINI-C
def _insert_customers(db: Database) -> None:
    risk = {"C01": "LOW", "C02": "HIGH", "C03": "MEDIUM"}
    for n in range(1, 7):
        cif = f"C{n:02d}"
        db.execute(
            "INSERT INTO customers (cif, full_name, gender, dob, nationality, occupation, "
            "kyc_risk, id_type, id_number) VALUES (?, ?, 'F', DATE '1990-01-01', 'VN', ?, ?, "
            "'PASSPORT', ?)",
            [
                cif,
                f"Nguyen Thi {cif}",
                None if cif == "C02" else "Kế toán",
                risk.get(cif, "LOW"),
                f"B123456{n}",
            ],
        )


def _insert_golden(db: Database) -> None:
    db.execute(
        "INSERT INTO er_runs (run_id, run_ts, as_of, customers_resolved, blocked_pairs, "
        "match_pairs, review_pairs, clusters, merged_clusters, merged_cifs, match_threshold, "
        "review_threshold, prior_probability, version, splink_version, config_hash) VALUES "
        "(1, TIMESTAMP '2026-06-30 00:00:00', DATE '2026-06-30', 6, 1, 1, 0, 5, 1, 2, "
        "0.95, 0.5, 0.001, 'er/v1', '5.0.0', '0000000000000000')"
    )
    pairs = [("C01", "G-C01", 2), ("C02", "G-C01", 2)] + [
        (f"C0{n}", f"G-C0{n}", 1) for n in range(3, 7)
    ]
    for cif, golden, size in pairs:
        db.execute(
            "INSERT INTO er_golden (run_id, cif, golden_customer_id, cluster_size) "
            "VALUES (1, ?, ?, ?)",
            [cif, golden, size],
        )


MINI_ACCOUNTS = [(f"A0{n}", f"C0{n}") for n in range(1, 7)]
# (txn_id, ts, from, to, amount_vnd, channel)
MINI_TXNS: list[tuple[Any, ...]] = [
    ("T01", "2026-03-02 09:00:00", None, "A01", 390 * M, "CASH"),
    ("T02", "2026-03-05 10:00:00", "A01", "A03", 300 * M, "INTERNAL_TRANSFER"),
    ("T03", "2026-03-06 10:00:00", "A03", "A04", 290 * M, "INTERNAL_TRANSFER"),
    ("T04", "2026-03-07 10:00:00", "A04", "A01", 280 * M, "INTERNAL_TRANSFER"),
    ("T05", "2026-04-20 08:00:00", "EXT-01", "A02", 500 * M, "INTERBANK_TRANSFER"),
    ("T06", "2026-04-20 12:00:00", "A02", "EXT-02", 480 * M, "EBANKING"),
    ("T07", "2026-05-31 09:00:00", "A01", "EXT-03", 50 * M, "EBANKING"),
    ("T08", "2026-01-15 09:00:00", "EXT-01", "A01", 10 * M, "INTERBANK_TRANSFER"),
]
# (cif, entry_id, list_type, decision, final_score)
MINI_SCREENING = [
    ("C02", "WL1", "SANCTIONS", "ALERT", 100.0),
    ("C05", "WL2", "PEP", "REVIEW", 80.0),
    ("C06", "WL3", "PEP", "AUTO_CLEARED", 60.0),
]


def _insert_accounts_txns_screening(db: Database, reverse: bool) -> None:
    accounts = list(reversed(MINI_ACCOUNTS)) if reverse else MINI_ACCOUNTS
    for account_id, cif in accounts:
        db.execute(
            "INSERT INTO accounts (account_id, cif, account_type, open_date) "
            "VALUES (?, ?, 'CURRENT', DATE '2025-01-01')",
            [account_id, cif],
        )
    txns = list(reversed(MINI_TXNS)) if reverse else MINI_TXNS
    for txn_id, when, src, dst, amount, channel in txns:
        db.execute(
            "INSERT INTO transactions (txn_id, txn_ts, from_account_id, to_account_id, "
            "amount_vnd, channel) VALUES (?, ?, ?, ?, ?, ?)",
            [txn_id, when, src, dst, amount, channel],
        )
    db.execute(
        "INSERT INTO screening_runs (run_id, run_ts, mode, as_of, customers_screened, "
        "entries_screened, candidate_pairs, recorded, alerts, reviews, auto_cleared, "
        "superseded, version, config_hash) VALUES (1, TIMESTAMP '2026-06-30 00:00:00', 'FULL', "
        "DATE '2026-06-30', 6, 3, 3, 3, 1, 1, 1, 0, 'screening/v1', '0000000000000000')"
    )
    rows = list(reversed(MINI_SCREENING)) if reverse else MINI_SCREENING
    for cif, entry, list_type, decision, score in rows:
        db.execute(
            "INSERT INTO screening_results (run_id, cif, entry_id, list_type, matched_name, "
            "matched_name_type, token_set, jaro_winkler, fuzzy_score, coverage, name_score, "
            "final_score, decision, reason, superseded_by) VALUES (1, ?, ?, ?, 'LISTED NAME', "
            "'PRIMARY', 1.0, 1.0, 1.0, 1.0, 1.0, ?, ?, 'test reason', NULL)",
            [cif, entry, list_type, score, decision],
        )


def rule_alert(
    rule_id: str, account: str, start: str, end: str, txns: tuple[str, ...], amount: int
) -> Any:
    rec = mod("aml.monitoring.recording")
    return rec.AlertRecord(
        rule_id=rule_id,
        rule_version="v1",
        subject_type="ACCOUNT",
        subject_id=account,
        accounts=((account, "SUBJECT"),),
        window_start=ts(start),
        window_end=ts(end),
        txn_ids=txns,
        amount_vnd=amount,
        reason=f"{rule_id} on {account}",
        details={},
        alert_key=f"{rule_id}|{account}|{ts(start).isoformat()}",
    )


def _run_rules(ids: tuple[str, ...]) -> list[Any]:
    rec = mod("aml.monitoring.recording")
    return [rec.RuleRun(rule_id=r, rule_version="v1", params={}) for r in ids]


def add_r5(db: Database) -> None:
    """R5: HIGH_VELOCITY on A01 2026-04-25 09:00:00 -> 10:00:00, as a new rule run."""
    r5 = rule_alert("HIGH_VELOCITY", "A01", "2026-04-25 09:00:00", "2026-04-25 10:00:00", (), 1)
    mod("aml.monitoring.recording").record_run(
        db, as_of=AS_OF, source="RULE", rules=_run_rules(("HIGH_VELOCITY",)), alerts=[r5]
    )


def _record_alerts(db: Database) -> None:
    rec = mod("aml.monitoring.recording")
    r1, r2, r3, r4 = "STRUCTURING", "RAPID_MOVEMENT", "FAN_OUT", "DORMANT_REACTIVATION"
    rules = [
        rule_alert(r1, "A01", "2026-03-02 09:00:00", "2026-03-02 09:00:00", ("T01",), 390 * M),
        rule_alert(
            r2, "A02", "2026-04-20 08:00:00", "2026-04-20 12:00:00", ("T05", "T06"), 980 * M
        ),
        rule_alert(r3, "A01", "2026-05-31 09:00:00", "2026-05-31 09:00:00", ("T07",), 50 * M),
        rule_alert(
            r4, "A03", "2026-03-05 10:00:00", "2026-03-06 10:00:00", ("T02", "T03"), 590 * M
        ),
    ]
    rec.record_run(db, as_of=AS_OF, source="RULE", rules=_run_rules(RULE_IDS), alerts=rules)
    n1 = rec.AlertRecord(
        rule_id="NET_CYCLE",
        rule_version="v1",
        subject_type="ACCOUNT_GROUP",
        subject_id="A01>A03>A04",
        accounts=(("A01", "ORIGIN"), ("A03", "HOP"), ("A04", "HOP")),
        window_start=ts("2026-03-05 10:00:00"),
        window_end=ts("2026-03-07 10:00:00"),
        txn_ids=("T02", "T03", "T04"),
        amount_vnd=870 * M,
        reason="cycle A01>A03>A04",
        details={},
        alert_key=N1_KEY,
    )
    rec.record_run(
        db, as_of=AS_OF, source="NETWORK", rules=_run_rules(NETWORK_RULE_IDS), alerts=[n1]
    )


def load_minic(db: Database, *, reverse: bool = False) -> Database:
    """MINI-C of the spec: schema, customers, ER, accounts, transactions, alerts, screening."""
    mod("aml.dba.schema").apply_schema(db)
    _insert_customers(db)
    _insert_golden(db)
    _insert_accounts_txns_screening(db, reverse)
    _record_alerts(db)
    return db


def add_nx_features(db: Database) -> None:
    for acct, vals in {
        "A01": "2, 1, 290000000, 300000000, 0.3, 1.8, 1, NULL, 0, 0",
        "A02": "1, 3, 500000000, 480000000, 0.1, 0.6, 0, 'SHARED-C02', 5, 1",
    }.items():
        db.execute(
            "INSERT INTO nx_account_features (run_id, account_id, in_degree, out_degree, in_vnd, "
            "out_vnd, pagerank, pagerank_ratio, cycle_alerts, shared_cluster_id, "
            f"shared_cluster_size, is_hub) VALUES (1, '{acct}', {vals})"
        )


def add_gds_features(db: Database, gds_as_of: str = "2026-06-30") -> None:
    db.execute(
        "INSERT INTO gds_runs (run_id, run_ts, as_of, source_backend, sync_run_id, "
        "txn_watermark, gds_version, accounts, active_accounts, wcc_components, "
        "louvain_communities, shared_clusters, seconds, params) VALUES "
        f"(1, TIMESTAMP '2026-06-30 00:00:00', DATE '{gds_as_of}', 'duckdb', 1, NULL, '2.6', "
        "6, 4, 2, 2, 1, 0.1, NULL)"
    )
    db.execute(
        "INSERT INTO gds_account_features (run_id, account_id, in_degree, out_degree, in_vnd, "
        "out_vnd, pagerank, pagerank_ratio, wcc_id, wcc_size, louvain_id, louvain_size, "
        "shared_cluster_id, shared_cluster_size) VALUES "
        "(1, 'A01', 7, 0, 0, 0, 0.1, 1.0, 'W1', 4, 'L1', 3, NULL, 0)"
    )


# ---------------------------------------------------------------- TINY
def load_tiny_duck(tiny_parquet: Path, path: Path) -> DuckDb:
    db = DuckDb(path)
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    return db


def approx_equal(a: Any, b: Any, tol: float = 1e-9) -> bool:
    """Deep comparison of parsed JSON; floats within ``tol``."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b, strict=True))
    if isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool):
        return abs(a - b) <= tol
    return bool(a == b)


def all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in all_keys(v)}
    return set()
