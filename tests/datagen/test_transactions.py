"""Acceptance tests for specs/datagen-transactions.md (AC1-AC9)."""

from __future__ import annotations

import dataclasses
import importlib
import re
from datetime import date
from typing import Any

import pandas as pd
import pytest

cust_mod = importlib.import_module("aml.datagen.customers")
generate_customers = cust_mod.generate_customers

SEED = 42
TYPOLOGIES = [
    "structuring",
    "rapid_movement",
    "mule_ring",
    "round_tripping",
    "benign_payroll",
    "benign_merchant",
]
CHANNELS = {"CASH", "INTERNAL_TRANSFER", "INTERBANK_TRANSFER", "CARD", "EBANKING"}
EXT = re.compile(r"^EXT-")


def _act() -> Any:
    return importlib.import_module("aml.datagen.activity")


def _params(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "n_transactions": 5000,
        "months": 6,
        "counterparties": (3, 12),
        "start_date": date(2026, 1, 1),
        "large_cash_vnd": 400_000_000,
        "structuring_band_pct": 0.10,
        "duplicate_rate": 0.02,
        "injection_memos": 6,
        "typology_counts": dict.fromkeys(TYPOLOGIES, 0),
    }
    base.update(overrides)
    return _act().TxnGenParams(**base)


def _tables(n_customers: int) -> Any:
    return generate_customers(
        n_customers=n_customers,
        seed=7,
        duplicate_person_rate=0.08,
        dq_defect_rate=0.02,
        reference_date=date(2026, 6, 30),
    )


def _dup_ids(data: Any) -> set[str]:
    lab = data.dq_labels
    return set(lab.loc[lab["entity_type"] == "transaction", "entity_id"])


def _base(data: Any) -> pd.DataFrame:
    tx = data.transactions
    return tx[~tx["txn_id"].isin(_dup_ids(data))]


def _counterparty_counts(data: Any) -> pd.Series:
    """Distinct counterparties (other side, non-null) per CURRENT account, 0 if none."""
    tx = data.transactions
    out = tx.loc[tx["from_account_id"].notna() & tx["to_account_id"].notna()]
    edges = pd.concat(
        [
            out[["from_account_id", "to_account_id"]].set_axis(["acct", "other"], axis=1),
            out[["to_account_id", "from_account_id"]].set_axis(["acct", "other"], axis=1),
        ]
    )
    # CASH/CARD rows have one null side so they never have a counterparty id: nothing to count.
    counts = edges.groupby("acct")["other"].nunique()
    cur = data.accounts.loc[data.accounts["account_type"] == "CURRENT", "account_id"]
    return counts.reindex(cur, fill_value=0)


# ---------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def tables_f() -> Any:
    return _tables(300)


@pytest.fixture(scope="module")
def run_f(tables_f: Any) -> Any:
    """(snapshot of input customers, ActivityData) for fixture F; calls the generator once."""
    snapshot = tables_f.customers.copy(deep=True)
    data = _act().generate_activity(tables_f, _params(), SEED)
    return snapshot, data


@pytest.fixture(scope="module")
def data_f(run_f: Any) -> Any:
    return run_f[1]


@pytest.fixture(scope="module")
def data_dense() -> Any:
    return _act().generate_activity(
        _tables(200), _params(counterparties=(50, 100), n_transactions=20000), SEED
    )


# ------------------------------------------------------------------------------- tests


def test_ac1_accounts_one_current_per_customer(tables_f: Any, data_f: Any) -> None:
    acc = data_f.accounts
    cifs = set(tables_f.customers["cif"])
    cur = acc[acc["account_type"] == "CURRENT"]
    assert len(cur) == len(cifs)
    assert cur["cif"].is_unique
    assert set(cur["cif"]) == cifs
    assert set(acc["account_type"]) <= {"CURRENT", "SAVINGS", "CARD"}
    assert acc["account_id"].is_unique
    assert acc["account_id"].map(lambda s: re.fullmatch(r"A\d{10}", s) is not None).all()
    assert set(acc["cif"]) <= cifs
    assert (pd.to_datetime(acc["open_date"]) < pd.Timestamp("2026-01-01")).all()


def test_ac2_transactions_basic_invariants(data_f: Any) -> None:
    tx, acc = data_f.transactions, data_f.accounts
    assert len(_base(data_f)) == 5000
    assert tx["txn_id"].is_unique
    assert tx["txn_id"].map(lambda s: re.fullmatch(r"T\d{10}", s) is not None).all()
    assert tx["amount_vnd"].dtype == "int64"
    assert (tx["amount_vnd"] > 0).all()
    assert (tx["amount_vnd"] % 1000 == 0).all()
    assert tx["txn_ts"].min() >= pd.Timestamp("2026-01-01 00:00:00")
    assert tx["txn_ts"].max() < pd.Timestamp("2026-07-01 00:00:00")
    known = set(acc["account_id"])
    for col in ("from_account_id", "to_account_id"):
        ids = tx[col].dropna()
        ok = ids.isin(known) | ids.map(lambda s: EXT.match(s) is not None)
        assert ok.all()
    ext_ids = pd.concat([tx["from_account_id"], tx["to_account_id"]]).dropna()
    assert not (ext_ids[ext_ids.map(lambda s: EXT.match(s) is not None)].isin(known)).any()
    gt = data_f.ground_truth
    assert len(gt) == 0
    assert list(gt.columns) == list(_act().GROUND_TRUTH_COLUMNS)


def test_ac3_channel_rules(tables_f: Any, data_f: Any) -> None:
    tx, acc = data_f.transactions, data_f.accounts
    internal = set(acc["account_id"])
    assert set(tx["channel"]) == CHANNELS

    def is_int(s: pd.Series) -> pd.Series:
        return s.isin(internal)

    def is_ext(s: pd.Series) -> pd.Series:
        return s.map(lambda v: isinstance(v, str) and EXT.match(v) is not None).astype(bool)

    ch = tx["channel"]
    cash = tx[ch == "CASH"]
    assert (cash["from_account_id"].isna() ^ cash["to_account_id"].isna()).all()
    assert cash["branch_id"].notna().all()

    web = tx[ch == "EBANKING"]
    assert is_int(web["from_account_id"]).all()
    owner = acc.set_index("account_id")["cif"]
    cust = tables_f.customers.set_index("cif")
    cifs = web["from_account_id"].map(owner)
    assert (web["device_id"].to_numpy() == cust.loc[cifs, "device_id"].to_numpy()).all()
    assert (web["ip"].to_numpy() == cust.loc[cifs, "ip"].to_numpy()).all()
    assert web["device_id"].notna().all()
    assert web["ip"].notna().all()

    other = tx[ch != "EBANKING"]
    assert other["device_id"].isna().all()
    assert other["ip"].isna().all()

    it = tx[ch == "INTERNAL_TRANSFER"]
    assert is_int(it["from_account_id"]).all()
    assert is_int(it["to_account_id"]).all()

    ib = tx[ch == "INTERBANK_TRANSFER"]
    n_ext = is_ext(ib["from_account_id"]).astype(int) + is_ext(ib["to_account_id"]).astype(int)
    assert (n_ext == 1).all()
    assert ib["counterparty_bank"].notna().all()

    card = tx[ch == "CARD"]
    types = acc.set_index("account_id")["account_type"]
    assert (card["from_account_id"].map(types) == "CARD").all()
    assert card["to_account_id"].isna().all()
    assert card["counterparty_name"].notna().all()


def test_ac4_memos_non_ascii_and_injection(data_f: Any) -> None:
    tx = data_f.transactions
    memo = tx["memo"]
    nonempty = memo[memo.notna() & (memo != "")]
    assert len(nonempty) > 0
    non_ascii = nonempty.map(lambda s: any(ord(c) > 127 for c in s))
    assert non_ascii.mean() >= 0.5

    phrases = [p.lower() for p in _act().INJECTION_PHRASES]
    assert any(p.isascii() for p in phrases)
    assert any(not p.isascii() for p in phrases)

    def has_phrase(s: Any) -> bool:
        return isinstance(s, str) and any(p in s.lower() for p in phrases)

    hit_all = tx[memo.map(has_phrase).astype(bool)]
    assert set(hit_all["channel"]) <= {"INTERNAL_TRANSFER", "INTERBANK_TRANSFER", "EBANKING"}
    base = _base(data_f)
    assert int(base["memo"].map(has_phrase).astype(bool).sum()) == 6


def test_ac5_duplicate_transactions(data_f: Any) -> None:
    tx, lab = data_f.transactions, data_f.dq_labels
    assert list(lab.columns) == ["entity_type", "entity_id", "defect_type", "detail"]
    dups = lab[
        (lab["entity_type"] == "transaction") & (lab["defect_type"] == "DUPLICATE_TRANSACTION")
    ]
    assert len(dups) == 100
    assert len(lab[lab["entity_type"] == "transaction"]) == 100
    ids = set(tx["txn_id"])
    assert dups["entity_id"].is_unique
    assert set(dups["entity_id"]) <= ids
    assert set(dups["detail"]) <= ids
    assert not set(dups["detail"]) & set(dups["entity_id"])
    indexed = tx.set_index("txn_id")
    copies = indexed.loc[dups["entity_id"].tolist()].reset_index(drop=True)
    origins = indexed.loc[dups["detail"].tolist()].reset_index(drop=True)
    pd.testing.assert_frame_equal(copies, origins)


def test_ac6_counterparty_counts_dense(data_dense: Any) -> None:
    counts = _counterparty_counts(data_dense)
    assert len(counts) == 200
    assert counts.min() >= 50
    assert counts.max() <= 100


def test_ac6_counterparty_counts_default(data_f: Any) -> None:
    counts = _counterparty_counts(data_f)
    assert len(counts) == 300
    assert counts.min() >= 3
    assert counts.max() <= 12


def test_ac7_determinism_and_substreams(tables_f: Any, data_f: Any) -> None:
    act = _act()
    again = act.generate_activity(tables_f, _params(), SEED)
    for name in ("customers", "accounts", "transactions", "ground_truth", "dq_labels"):
        pd.testing.assert_frame_equal(getattr(data_f, name), getattr(again, name))
    other_seed = act.generate_activity(tables_f, _params(), SEED + 1)
    assert not other_seed.transactions.equals(data_f.transactions)
    bigger = act.generate_activity(tables_f, _params(n_transactions=6000), SEED)
    pd.testing.assert_frame_equal(bigger.accounts, data_f.accounts)


def test_ac8_input_customers_not_mutated(tables_f: Any, run_f: Any) -> None:
    snapshot, data = run_f
    pd.testing.assert_frame_equal(tables_f.customers, snapshot)
    pd.testing.assert_frame_equal(data.customers, tables_f.customers)


def test_ac9_missing_device_id_column() -> None:
    tables = _tables(200)
    broken = dataclasses.replace(tables, customers=tables.customers.drop(columns=["device_id"]))
    with pytest.raises(ValueError, match="device_id"):
        _act().generate_activity(broken, _params(), SEED)


def test_ac9_empty_customers() -> None:
    tables = _tables(200)
    empty = dataclasses.replace(tables, customers=tables.customers.iloc[0:0])
    with pytest.raises(ValueError, match="customers is empty"):
        _act().generate_activity(empty, _params(), SEED)


def test_ac9_too_few_transactions_for_counterparties() -> None:
    params = _params(counterparties=(50, 100), n_transactions=100)
    with pytest.raises(ValueError, match="n_transactions"):
        _act().generate_activity(_tables(200), params, SEED)
