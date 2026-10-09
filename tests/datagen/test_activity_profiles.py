"""Regression: the real config profiles must be feasible and honour the counterparty range."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from aml.common.config import load_settings
from aml.datagen.activity import TxnGenParams, generate_activity
from aml.datagen.customers import generate_customers
from aml.datagen.transactions import plan_edges

SEED = 42
SCALE = 25  # shrink customers and transactions by the same factor (keeps the budget ratio)


def _counts(data: pd.DataFrame, accounts: pd.DataFrame) -> pd.Series:
    out = data.loc[data["from_account_id"].notna() & data["to_account_id"].notna()]
    edges = pd.concat(
        [
            out[["from_account_id", "to_account_id"]].set_axis(["acct", "other"], axis=1),
            out[["to_account_id", "from_account_id"]].set_axis(["acct", "other"], axis=1),
        ]
    )
    cur = accounts.loc[accounts["account_type"] == "CURRENT", "account_id"]
    return edges.groupby("acct")["other"].nunique().reindex(cur, fill_value=0)


@pytest.mark.parametrize("profile", ["small", "dense"])
def test_scaled_profile_generates_within_range(profile: str) -> None:
    s = load_settings(environ={"AML__DATA__PROFILE": profile})
    params = TxnGenParams.from_settings(s)
    n_customers = s.data.active.customers // SCALE
    params = TxnGenParams(
        **{
            **params.__dict__,
            "n_transactions": params.n_transactions // SCALE,
            "typology_counts": dict.fromkeys(params.typology_counts, 0),  # too few customers
        }
    )
    tables = generate_customers(
        n_customers,
        SEED,
        s.data.duplicate_person_rate,
        s.data.dq_defect_rate,
        s.data.reference_date,
    )
    data = generate_activity(tables, params, SEED)
    counts = _counts(data.transactions, data.accounts)
    lo, hi = params.counterparties
    assert counts.min() >= lo
    assert counts.max() <= hi


@pytest.mark.parametrize("profile", ["small", "dense", "large"])
def test_full_size_edge_plan_fits_budget(profile: str) -> None:
    """Cheap feasibility check at full size: the edge plan alone fits the transaction budget."""
    p = load_settings(environ={"AML__DATA__PROFILE": profile}).data.active
    m = p.customers
    current = np.arange(m)
    savings = np.where(np.random.default_rng(0).random(m) < 0.35, m + np.arange(m), -1)
    plan = plan_edges(current, savings, p.counterparties, p.transactions, np.random.default_rng(1))
    assert len(plan) <= p.transactions


def test_full_size_small_profile_with_typologies() -> None:
    """The default profile at full size plants every configured typology scenario (~1-2 s)."""
    s = load_settings(environ={})
    params = TxnGenParams.from_settings(s)
    tables = generate_customers(
        s.data.active.customers,
        SEED,
        s.data.duplicate_person_rate,
        s.data.dq_defect_rate,
        s.data.reference_date,
    )
    data = generate_activity(tables, params, SEED)
    gt = data.ground_truth
    scenarios = gt.groupby("typology")["scenario_id"].nunique()
    for typology, expected in params.typology_counts.items():
        assert scenarios.get(typology, 0) == expected, typology
    assert scenarios.get("prompt_injection", 0) == params.injection_memos
