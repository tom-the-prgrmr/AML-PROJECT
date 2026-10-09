"""Acceptance tests for specs/datagen-typologies.md (AC1-AC9)."""

from __future__ import annotations

import importlib
import re
from datetime import date
from itertools import pairwise
from typing import Any

import pandas as pd
import pytest

cust_mod = importlib.import_module("aml.datagen.customers")
generate_customers = cust_mod.generate_customers

SEED = 42
COUNTS = {
    "structuring": 2,
    "rapid_movement": 2,
    "mule_ring": 1,
    "round_tripping": 2,
    "benign_payroll": 1,
    "benign_merchant": 1,
}
SUSPICIOUS = {"structuring", "rapid_movement", "mule_ring", "round_tripping"}
SCENARIO_ID = re.compile(r"^GT-[A-Z]{3,4}-\d{4}$")
ONE_DAY = pd.Timedelta(hours=24)


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
        "typology_counts": dict(COUNTS),
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


def _scenarios(data: Any, typology: str) -> list[str]:
    gt = data.ground_truth
    return sorted(gt.loc[gt["typology"] == typology, "scenario_id"].unique())


def _accounts(data: Any, sid: str, role: str) -> list[str]:
    gt = data.ground_truth
    sel = gt[(gt["scenario_id"] == sid) & (gt["role"] == role) & (gt["entity_type"] == "account")]
    return list(sel["entity_id"])


def _evidence(data: Any, sid: str) -> pd.DataFrame:
    gt = data.ground_truth
    is_ev = (
        (gt["scenario_id"] == sid)
        & (gt["role"] == "evidence")
        & (gt["entity_type"] == "transaction")
    )
    tx = data.transactions
    return tx[tx["txn_id"].isin(set(gt.loc[is_ev, "entity_id"]))].sort_values(
        "txn_ts", kind="stable"
    )


def _persons(tables: Any, data: Any, account_ids: list[str]) -> list[str]:
    cif_of = data.accounts.set_index("account_id")["cif"]
    person_of = tables.customer_person.set_index("cif")["person_id"]
    return [person_of[cif_of[a]] for a in account_ids]


def _counterparty_counts(data: Any) -> pd.Series:
    tx = data.transactions
    out = tx.loc[tx["from_account_id"].notna() & tx["to_account_id"].notna()]
    edges = pd.concat(
        [
            out[["from_account_id", "to_account_id"]].set_axis(["acct", "other"], axis=1),
            out[["to_account_id", "from_account_id"]].set_axis(["acct", "other"], axis=1),
        ]
    )
    counts = edges.groupby("acct")["other"].nunique()
    cur = data.accounts.loc[data.accounts["account_type"] == "CURRENT", "account_id"]
    return counts.reindex(cur, fill_value=0)


# ---------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def tables_g() -> Any:
    return _tables(300)


@pytest.fixture(scope="module")
def run_g(tables_g: Any) -> Any:
    """(snapshot of input customers, ActivityData) for fixture G; calls the generator once."""
    snapshot = tables_g.customers.copy(deep=True)
    data = _act().generate_activity(tables_g, _params(), SEED)
    return snapshot, data


@pytest.fixture(scope="module")
def data_g(run_g: Any) -> Any:
    return run_g[1]


@pytest.fixture(scope="module")
def data_small_cash(tables_g: Any) -> Any:
    return _act().generate_activity(tables_g, _params(large_cash_vnd=100_000_000), SEED)


# ------------------------------------------------------------------------------- tests


def test_ac1_ground_truth_schema_and_counts(data_g: Any) -> None:
    gt = data_g.ground_truth
    assert list(gt.columns) == list(_act().GROUND_TRUTH_COLUMNS)
    per = gt.groupby("typology")["scenario_id"].nunique().to_dict()
    assert per == {**COUNTS, "prompt_injection": 6}
    assert gt["scenario_id"].map(lambda s: bool(SCENARIO_ID.match(s))).all()
    for typ, flags in gt.groupby("typology")["is_suspicious"].agg(["min", "max"]).iterrows():
        expected = typ in SUSPICIOUS
        assert bool(flags["min"]) is expected
        assert bool(flags["max"]) is expected


def test_ac1_entities_exist_reasons_and_account_exclusivity(data_g: Any) -> None:
    gt = data_g.ground_truth
    known = {
        "account": set(data_g.accounts["account_id"]),
        "transaction": set(data_g.transactions["txn_id"]),
        "customer": set(data_g.customers["cif"]),
    }
    for etype, ids in known.items():
        assert set(gt.loc[gt["entity_type"] == etype, "entity_id"]) <= ids
    assert (gt["reason"].astype(str).str.strip() != "").all()
    acc = gt[gt["entity_type"] == "account"]
    assert len(acc) > 0
    assert (acc.groupby("entity_id")["scenario_id"].nunique() == 1).all()


def test_ac2_injection_memos_labelled(data_g: Any) -> None:
    phrases = list(_act().INJECTION_PHRASES)
    tx = data_g.transactions
    memo = tx["memo"].fillna("")
    hit = set(tx.loc[memo.map(lambda m: any(p in m for p in phrases)), "txn_id"])
    gt = data_g.ground_truth
    inj = gt[gt["typology"] == "prompt_injection"]
    assert len(hit) == 6
    assert set(inj["entity_id"]) == hit
    assert (inj["entity_type"] == "transaction").all()
    assert (inj["role"] == "memo").all()
    assert not inj["is_suspicious"].any()
    sus_ev = gt[
        gt["is_suspicious"] & (gt["role"] == "evidence") & (gt["entity_type"] == "transaction")
    ]
    assert len(hit & set(sus_ev["entity_id"])) >= 1


def test_ac3_structuring_pattern(data_g: Any) -> None:
    sids = _scenarios(data_g, "structuring")
    assert len(sids) == 2
    all_ev: set[str] = set()
    for sid in sids:
        ev = _evidence(data_g, sid)
        all_ev |= set(ev["txn_id"])
        subjects = _accounts(data_g, sid, "subject")
        assert len(subjects) == 1
        assert 4 <= len(ev) <= 8
        assert (ev["channel"] == "CASH").all()
        assert (ev["to_account_id"] == subjects[0]).all()
        assert ev["amount_vnd"].between(360_000_000, 399_999_999).all()
        assert ev["amount_vnd"].sum() >= 400_000_000
        assert ev["txn_ts"].dt.normalize().nunique() >= 3
        assert ev["branch_id"].nunique() >= 2
        assert ev["txn_ts"].max() - ev["txn_ts"].min() <= pd.Timedelta(days=14)
    tx = data_g.transactions
    band = tx[(tx["channel"] == "CASH") & tx["amount_vnd"].between(360_000_000, 399_999_999)]
    assert set(band["txn_id"]) <= all_ev


def test_ac3_structuring_follows_threshold_param(data_small_cash: Any) -> None:
    sids = _scenarios(data_small_cash, "structuring")
    assert len(sids) == 2
    for sid in sids:
        ev = _evidence(data_small_cash, sid)
        assert len(ev) >= 4
        assert ev["amount_vnd"].between(90_000_000, 99_999_999).all()


def test_ac4_rapid_movement_pattern(data_g: Any) -> None:
    sids = _scenarios(data_g, "rapid_movement")
    assert len(sids) == 2
    for sid in sids:
        subjects = _accounts(data_g, sid, "subject")
        assert len(subjects) == 1
        subj = subjects[0]
        ev = _evidence(data_g, sid)
        inc = ev[ev["to_account_id"] == subj]
        out = ev[ev["from_account_id"] == subj]
        assert len(inc) >= 1
        x = inc["amount_vnd"].sum()
        assert 200_000_000 <= x <= 2_000_000_000
        assert out["to_account_id"].nunique() >= 2
        total = out["amount_vnd"].sum()
        assert 0.95 * x <= total <= 0.99 * x
        assert set(out["to_account_id"]) <= set(_accounts(data_g, sid, "destination"))
        assert set(inc["from_account_id"].dropna()) <= set(_accounts(data_g, sid, "source"))
        assert (out["txn_ts"] > inc["txn_ts"].max()).all()
        assert (out["txn_ts"] <= inc["txn_ts"].min() + ONE_DAY).all()


def test_ac5_mule_ring_pattern(tables_g: Any, data_g: Any) -> None:
    sids = _scenarios(data_g, "mule_ring")
    assert len(sids) == 1
    sid = sids[0]
    collectors = _accounts(data_g, sid, "collector")
    members = sorted(set(_accounts(data_g, sid, "member")) | set(collectors))
    assert len(collectors) >= 1
    assert 5 <= len(members) <= 30
    assert len(set(_persons(tables_g, data_g, members))) == len(members)

    cif_of = data_g.accounts.set_index("account_id")["cif"]
    cifs = [cif_of[m] for m in members]
    cust = data_g.customers.set_index("cif")
    parent = list(range(len(cifs)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for col in ("device_id", "phone", "address"):
        seen: dict[Any, int] = {}
        for i, cif in enumerate(cifs):
            val = cust.loc[cif, col]
            if pd.isna(val):
                continue
            if val in seen:
                parent[find(i)] = find(seen[val])
            else:
                seen[val] = i
    assert len({find(i) for i in range(len(cifs))}) == 1

    ev = _evidence(data_g, sid)
    sources = set(_accounts(data_g, sid, "source"))
    dests = set(_accounts(data_g, sid, "destination"))
    assert not sources & set(members)
    assert not dests & set(members)
    for m in members:
        inc = ev[(ev["to_account_id"] == m) & ev["from_account_id"].isin(sources)]
        assert len(inc) >= 3
        assert inc["from_account_id"].nunique() >= 3
    for c in collectors:
        out = ev[(ev["from_account_id"] == c) & ev["to_account_id"].isin(dests)]
        assert out["to_account_id"].nunique() >= 3


def test_ac5_input_customers_not_modified(tables_g: Any, run_g: Any) -> None:
    snapshot, data = run_g
    assert len(data.ground_truth) > 0
    pd.testing.assert_frame_equal(tables_g.customers, snapshot)


def test_ac6_round_tripping_cycles(tables_g: Any, data_g: Any) -> None:
    sids = _scenarios(data_g, "round_tripping")
    assert len(sids) == 2
    for sid in sids:
        hops = _accounts(data_g, sid, "hop")
        assert len(hops) in (3, 4)
        assert len(set(hops)) == len(hops)
        assert len(set(_persons(tables_g, data_g, hops))) == len(hops)
        ev = _evidence(data_g, sid)
        assert len(ev) == len(hops)
        ts = list(ev["txn_ts"])
        assert all(a < b for a, b in pairwise(ts))
        assert ts[-1] - ts[0] <= pd.Timedelta(hours=168)
        frm, to = list(ev["from_account_id"]), list(ev["to_account_id"])
        assert set(frm) == set(hops)
        assert all(to[i] == frm[(i + 1) % len(hops)] for i in range(len(hops)))
        amt = [int(a) for a in ev["amount_vnd"]]
        assert amt[0] >= 100_000_000
        for prev, cur in pairwise(amt):
            assert 10 * cur >= 9 * prev
            assert cur <= prev


def test_ac7_benign_payroll(data_g: Any) -> None:
    sids = _scenarios(data_g, "benign_payroll")
    assert len(sids) == 1
    sid = sids[0]
    employers = _accounts(data_g, sid, "employer")
    employees = _accounts(data_g, sid, "employee")
    assert len(employers) == 1
    assert len(set(employees)) >= 20
    ev = _evidence(data_g, sid)
    assert (ev["from_account_id"] == employers[0]).all()
    assert ev["memo"].fillna("").str.lower().str.contains("lương").all()
    months = {f"2026-{m:02d}" for m in range(1, 7)}
    for emp in set(employees):
        got = ev[ev["to_account_id"] == emp]
        assert len(got) == 6
        assert set(got["txn_ts"].dt.strftime("%Y-%m")) == months
    assert set(ev["to_account_id"]) == set(employees)


def test_ac7_benign_merchant(data_g: Any) -> None:
    sids = _scenarios(data_g, "benign_merchant")
    assert len(sids) == 1
    sid = sids[0]
    merchants = _accounts(data_g, sid, "merchant")
    payers = _accounts(data_g, sid, "payer")
    assert len(merchants) == 1
    assert len(set(payers)) >= 30
    ev = _evidence(data_g, sid)
    assert (ev["to_account_id"] == merchants[0]).all()
    assert ev["from_account_id"].nunique() >= 30
    assert set(ev["from_account_id"]) <= set(payers)
    assert ev["amount_vnd"].between(50_000, 5_000_000).all()


def test_ac8_baseline_invariants_hold(tables_g: Any, data_g: Any) -> None:
    tx, dq, gt = data_g.transactions, data_g.dq_labels, data_g.ground_truth
    dup_ids = set(dq.loc[dq["entity_type"] == "transaction", "entity_id"])
    assert (~tx["txn_id"].isin(dup_ids)).sum() == 5000
    gt_tx = set(gt.loc[gt["entity_type"] == "transaction", "entity_id"])
    details = set(dq.loc[dq["entity_type"] == "transaction", "detail"])
    assert not details & gt_tx
    gt_accounts = set(gt.loc[gt["entity_type"] == "account", "entity_id"])
    counts = _counterparty_counts(data_g)
    free = counts[~counts.index.isin(gt_accounts)]
    assert len(free) > 0
    assert free.between(3, 12).all()
    again = _act().generate_activity(tables_g, _params(), SEED)
    pd.testing.assert_frame_equal(gt, again.ground_truth)


def test_ac9_not_enough_accounts() -> None:
    with pytest.raises(ValueError, match="not enough accounts"):
        _act().generate_activity(_tables(40), _params(), SEED)


def test_ac9_n_transactions_too_small(tables_g: Any) -> None:
    with pytest.raises(ValueError, match="n_transactions"):
        _act().generate_activity(tables_g, _params(n_transactions=200), SEED)
