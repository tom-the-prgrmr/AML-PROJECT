"""Bank accounts for the synthetic customers: one CURRENT each, optional SAVINGS / CARD."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

ACCOUNT_COLUMNS = ["account_id", "cif", "account_type", "branch_id", "open_date", "currency"]
SAVINGS_P = 0.35  # probability a customer also holds a SAVINGS account
CARD_P = 0.45  # probability a customer also holds a CARD account
N_BRANCHES = 50
MIN_AGE_DAYS, MAX_AGE_DAYS = 30, 3650  # accounts are opened 1 month - 10 years before start
_TYPE_ORDER = {"CURRENT": 0, "SAVINGS": 1, "CARD": 2}
_ID_LOW, _ID_SPAN = 10**9, 9 * 10**9  # 10-digit numbers with a non-zero leading digit


def build_accounts(
    customers: pd.DataFrame, rng: np.random.Generator, start_date: date
) -> pd.DataFrame:
    """Return the account table for ``customers`` (one row per account, sorted by cif).

    Every cif gets exactly one ``CURRENT`` account; ``SAVINGS`` / ``CARD`` are added with
    probabilities ``SAVINGS_P`` / ``CARD_P``. Only ``rng`` and ``customers`` influence the
    result, so the table is independent of how many transactions are generated later.
    """
    cifs = customers["cif"].to_numpy(dtype=object)
    n = len(cifs)
    has_savings = rng.random(n) < SAVINGS_P
    has_card = rng.random(n) < CARD_P
    types = np.concatenate(
        [
            np.full(n, "CURRENT", dtype=object),
            np.full(int(has_savings.sum()), "SAVINGS", dtype=object),
            np.full(int(has_card.sum()), "CARD", dtype=object),
        ]
    )
    owners = np.concatenate([cifs, cifs[has_savings], cifs[has_card]])
    m = len(owners)
    numbers = rng.choice(_ID_SPAN, size=m, replace=False) + _ID_LOW
    ages = rng.integers(MIN_AGE_DAYS, MAX_AGE_DAYS + 1, size=m)
    accounts = pd.DataFrame(
        {
            "account_id": [f"A{k}" for k in numbers.tolist()],
            "cif": owners,
            "account_type": types,
            "branch_id": [f"BR{b:03d}" for b in (rng.integers(1, N_BRANCHES + 1, size=m)).tolist()],
            "open_date": [start_date - timedelta(days=int(d)) for d in ages],
            "currency": "VND",
        }
    )
    rank = accounts["account_type"].map(_TYPE_ORDER)
    order = np.lexsort((rank.to_numpy(), accounts["cif"].to_numpy(dtype=str)))
    return accounts.iloc[order].reset_index(drop=True)[ACCOUNT_COLUMNS]
