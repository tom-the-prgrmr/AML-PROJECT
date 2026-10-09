"""Structuring: repeated cash deposits just under the large-cash threshold."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from aml.datagen.typologies._common import (
    N_BRANCHES,
    AccountPool,
    Scenario,
    TypologyContext,
    make_row,
    random_start,
    rows_frame,
)

STRUCTURING_WINDOW_DAYS = 14
MIN_DEPOSITS, MAX_DEPOSITS = 4, 8
MIN_DAYS = 3  # deposits span at least this many calendar days
MIN_BRANCHES, MAX_BRANCHES = 2, 3


def build_structuring(
    ctx: TypologyContext, pool: AccountPool, rng: np.random.Generator, scenario_id: str
) -> Scenario:
    """Deposit 4-8 times in [cap*(1-band), cap) into one account within 14 days."""
    (subject,) = pool.take(1)
    n = int(rng.integers(MIN_DEPOSITS, MAX_DEPOSITS + 1))
    n_days = int(rng.integers(MIN_DAYS, min(n, STRUCTURING_WINDOW_DAYS) + 1))
    days = np.sort(rng.choice(STRUCTURING_WINDOW_DAYS, size=n_days, replace=False))
    day_of = np.concatenate([np.arange(n_days), rng.integers(n_days, size=n - n_days)])
    n_branches = int(rng.integers(MIN_BRANCHES, MAX_BRANCHES + 1))
    branches = rng.choice(N_BRANCHES, size=n_branches, replace=False) + 1
    cap = ctx.large_cash_vnd
    low_k = math.ceil(round(cap * (1 - ctx.structuring_band_pct), 3) / 1000)
    amounts = rng.integers(low_k, (cap - 1) // 1000 + 1, size=n) * 1000
    start = random_start(ctx, rng, STRUCTURING_WINDOW_DAYS).normalize()
    rows = []
    for i in range(n):
        hour, minute = int(rng.integers(8, 17)), int(rng.integers(0, 60))
        ts = start + pd.Timedelta(days=int(days[day_of[i]]), hours=hour, minutes=minute)
        branch = f"BR{int(branches[i % n_branches]):03d}"
        rows.append(make_row(ts, None, subject, int(amounts[i]), "CASH", branch_id=branch))
    return Scenario(
        scenario_id=scenario_id,
        typology="structuring",
        is_suspicious=True,
        accounts=[(subject, "subject")],
        rows=rows_frame(rows),
        reason=(
            f"{n} cash deposits just under the {cap:,} VND reporting threshold within "
            f"{STRUCTURING_WINDOW_DAYS} days across several branches"
        ),
    )
