"""AC10 for specs/memo-analysis.md: Oracle and DuckDB classify, relabel and count the same way.

The Oracle schema is shared and keeps its history, so this test is written to be re-run and to
leave real labels alone:

* every memo of MEMO-C gets a run-unique suffix of letters, so its keys are new on every run and
  never collide with a key of real data (a relabel is stored by key, whatever the model);
* the labels are stored under a run-unique model name, so they never show up in `aml memo list` of
  the configured model;
* no id or row count that depends on history is asserted;
* MEMO-C is inserted without its three screening rows (the Oracle watchlist foreign key would need
  watchlist rows), so both backends build the four rule / network cases; cases that Oracle still
  holds from earlier screening runs are left out of the comparison;
* the dataset tables are replaced the way `aml load` replaces them, and TINY is loaded back at the
  end, which is the state the other Oracle tests leave.
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from aml.common.config import Settings, load_settings, read_environ
from aml.common.db import Database, DuckDb, OracleDb
from tests.cases.helpers import (
    CASE_C01_A,
    CASE_C01_B,
    CASE_C03,
    CASE_C04,
    MINI_ACCOUNTS,
    MINI_TXNS,
    _record_alerts,
    mod,
    query,
    run_cases,
    ts,
)
from tests.cases.prio_helpers import PINNED

from .helpers import (
    K_CRY,
    K_GAM,
    K_INJ,
    K_LOAN,
    K_SAL,
    MEMOS,
    Stub,
    classify,
    features_mod,
    key_of,
    relabel_mod,
)

CASES = [CASE_C01_A, CASE_C01_B, CASE_C03, CASE_C04]
RUN_FIELDS = (
    "transactions", "with_memo", "distinct_memos", "keys", "by_rule", "by_llm", "fallback",
    "llm_calls",
)  # fmt: skip


def _next(db: Database, table: str) -> int:
    return 1 + int(db.query_df(f"SELECT COALESCE(MAX(run_id), 0) FROM {table}").iloc[0, 0])


def build_memoc(db: Database, tag: str) -> None:
    """MEMO-C through the `Database` abstraction only, so the same code fills both backends."""
    mod("aml.dba.schema").apply_schema(db)
    for table in reversed(mod("aml.datagen.pipeline").TABLES):  # children first, as `aml load`
        db.execute(f"DELETE FROM {table}")
    risk = {"C01": "LOW", "C02": "HIGH", "C03": "MEDIUM"}
    customers = [
        {
            "cif": f"C{n:02d}",
            "full_name": f"Nguyen Thi C{n:02d}",
            "gender": "F",
            "dob": date(1990, 1, 1),
            "nationality": "VN",
            "occupation": "Kế toán",
            "kyc_risk": risk.get(f"C{n:02d}", "LOW"),
            "id_type": "PASSPORT",
            "id_number": f"B123456{n}",
        }
        for n in range(1, 7)
    ]
    db.insert_df("customers", pd.DataFrame(customers))
    accounts = [
        {"account_id": a, "cif": c, "account_type": "CURRENT", "open_date": date(2025, 1, 1)}
        for a, c in MINI_ACCOUNTS
    ]
    db.insert_df("accounts", pd.DataFrame(accounts))
    txns = [
        {
            "txn_id": txn_id,
            "txn_ts": ts(when),
            "from_account_id": src,
            "to_account_id": dst,
            "amount_vnd": amount,
            "channel": channel,
            "memo": None if MEMOS[txn_id] is None else f"{MEMOS[txn_id]} {tag}",
        }
        for txn_id, when, src, dst, amount, channel in MINI_TXNS
    ]
    db.insert_df("transactions", pd.DataFrame(txns).astype(object).where(lambda f: f.notna(), None))
    er_run = _next(db, "er_runs")
    db.execute(
        "INSERT INTO er_runs (run_id, run_ts, as_of, customers_resolved, blocked_pairs, "
        "match_pairs, review_pairs, clusters, merged_clusters, merged_cifs, match_threshold, "
        "review_threshold, prior_probability, version, splink_version, config_hash) VALUES "
        f"({er_run}, TIMESTAMP '2026-06-30 00:00:00', DATE '2026-06-30', 6, 1, 1, 0, 5, 1, 2, "
        "0.95, 0.5, 0.001, 'er/v1', '5.0.0', '0000000000000000')"
    )
    golden = [("C01", "G-C01", 2), ("C02", "G-C01", 2)] + [
        (f"C0{n}", f"G-C0{n}", 1) for n in range(3, 7)
    ]
    db.insert_df(
        "er_golden",
        pd.DataFrame(
            [
                {"run_id": er_run, "cif": cif, "golden_customer_id": g, "cluster_size": size}
                for cif, g, size in golden
            ]
        ),
    )
    _record_alerts(db)


def _gather(db: Database, settings: Settings, tag: str) -> SimpleNamespace:
    f, rl = features_mod(), relabel_mod()
    model = settings.ollama.llm_model
    keys = {name: f"{norm} {tag}" for name, norm in _NORMS.items()}
    script = {
        keys["loan"]: "loan_repayment",
        keys["sal"]: "salary",
        keys["cry"]: "crypto_like",
        keys["gam"]: "gambling_like",
    }
    build_memoc(db, tag)
    case_run = run_cases(db, settings).run_id
    run = classify(db, settings, Stub(script, chat_model=model))
    wrote = f.write_memo_features(db, settings, case_run)
    labels = query(
        db,
        "SELECT memo_key, memo_norm, category, method, transactions, reason "
        f"FROM memo_classifications_current WHERE llm_model = '{model}'",
    )
    before = f.read_memo_features(db, settings, case_run)
    rl.relabel_memo(
        db, settings, key_of(keys["loan"]), "other", reason="parity check", actor="analyst01"
    )
    listed = rl.list_labels(db, settings)
    f.write_memo_features(db, settings, case_run)
    after = f.read_memo_features(db, settings, case_run)
    return SimpleNamespace(
        run=run,
        wrote=wrote,
        labels={
            (r.memo_key, r.memo_norm, r.category, r.method, int(r.transactions), r.reason)
            for r in labels.itertuples()
        },
        listed={
            (r.memo_key, r.category, r.method, r.model_category, r.model_method)
            for r in listed.itertuples()
        },
        loan=key_of(keys["loan"]),
        inj=keys["inj"],
        before=before.loc[CASES],
        after=after.loc[CASES],
    )


_NORMS = {"loan": K_LOAN, "sal": K_SAL, "cry": K_CRY, "gam": K_GAM, "inj": K_INJ}


def _same(a: pd.DataFrame, b: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(a.astype(float), b.astype(float), check_exact=True)


@pytest.mark.oracle
def test_ac10_oracle_and_duckdb_agree_on_memo_c(
    tiny_env: Any, tiny_parquet: Path, tmp_path: Path
) -> None:
    schema = mod("aml.dba.schema")
    tag = "".join(chr(ord("a") + int(ch, 16)) for ch in uuid.uuid4().hex[:10])
    extra = {**PINNED, "AML__OLLAMA__LLM_MODEL": f"memo-test-{tag}"}
    osettings = load_settings(environ={**read_environ(), **tiny_env(DB_BACKEND="oracle"), **extra})
    with OracleDb(osettings) as odb:
        try:
            o = _gather(odb, osettings, tag)
            tables = set(odb.query_df("SELECT table_name FROM user_tables").iloc[:, 0])
            views = set(odb.query_df("SELECT view_name FROM user_views").iloc[:, 0])
            schema.apply_schema(odb)  # idempotent on a second call
        finally:
            mod("aml.datagen.load").load_parquet(odb, tiny_parquet)

    dsettings = load_settings(environ={"DB_BACKEND": "duckdb", **extra})
    with DuckDb(tmp_path / "cmp.duckdb") as ddb:
        d = _gather(ddb, dsettings, tag)

    for state in (o, d):
        assert tuple(getattr(state.run, name) for name in RUN_FIELDS) == (8, 7, 7, 5, 1, 4, 0, 4)
        assert state.run.left == 0
    assert d.wrote == 24 and o.wrote >= 24 and o.wrote % 6 == 0
    assert len(d.labels) == 5
    assert o.labels == d.labels  # accented Vietnamese memo_norm included
    assert any(norm == d.inj and method == "RULE" for _, norm, _, method, _, _ in d.labels)
    _same(o.before, d.before)
    assert o.listed == d.listed
    assert (d.loan, "other", "HUMAN", "loan_repayment", "LLM") in o.listed
    _same(o.after, d.after)
    assert float(d.before.loc[CASE_C01_A, "memo_loan_repayment"]) == 1.0
    assert float(d.after.loc[CASE_C01_A, "memo_loan_repayment"]) == 0.0

    assert {"MEMO_RUNS", "MEMO_CLASSIFICATIONS", "MEMO_OVERRIDES", "CASE_MEMO_FEATURES"} <= tables
    assert {
        "MEMO_CLASSIFICATIONS_CURRENT",
        "MEMO_OVERRIDES_CURRENT",
        "MEMO_LABELS_CURRENT",
    } <= views
