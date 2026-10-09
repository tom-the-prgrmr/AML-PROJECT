"""Regression: background watchlist entries never equal a customer name at token-set level."""

from __future__ import annotations

from datetime import date

import pandas as pd

from aml.common.config import WatchlistConfig
from aml.datagen.activity import GROUND_TRUTH_COLUMNS
from aml.datagen.customers import generate_customers
from aml.datagen.watchlist import _tokens, generate_watchlist

SEED = 42


def test_background_entries_and_aliases_do_not_collide_with_customers() -> None:
    t = generate_customers(2000, SEED, 0.08, 0.02, date(2026, 6, 30))
    gt = pd.DataFrame({c: pd.Series(dtype="object") for c in GROUND_TRUTH_COLUMNS})
    cfg = WatchlistConfig(
        entries=2000, true_hits=20, traps=30, year_only_dob_rate=0.30, unknown_dob_rate=0.05
    )
    res = generate_watchlist(t.customers, t.customer_person, t.dq_defects, gt, cfg, SEED)
    special = set(res.ground_truth_rows["entity_id"])
    cust_sets = {_tokens(n) for n in t.customers["full_name"]}
    bg = res.watchlist[~res.watchlist["entry_id"].isin(special)]
    assert len(bg) > 1900
    for name in bg["primary_name"]:
        assert _tokens(name) not in cust_sets, name
    bg_alias = res.watchlist_alias[res.watchlist_alias["entry_id"].isin(set(bg["entry_id"]))]
    for name in bg_alias["alias_name"]:
        assert _tokens(name) not in cust_sets, name
