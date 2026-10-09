"""Round-tripping: money circles through 3-4 unrelated accounts back to its origin."""

from __future__ import annotations

import numpy as np
import pandas as pd

from aml.datagen.typologies._common import (
    HOUR_SECONDS,
    AccountPool,
    Scenario,
    TypologyContext,
    make_row,
    pick_channel,
    random_start,
    round_k,
    rows_frame,
)

ROUND_TRIP_WINDOW_HOURS = 168
HOPS = (3, 4)
FIRST_STEP_VND = (100_000_000, 1_000_000_000)
STEP_FACTOR = (0.92, 1.0)  # each step carries 92-100% of the previous one (spec: >= 90%)
MAX_GAP_SECONDS = 50 * HOUR_SECONDS  # 3 gaps stay well inside 168 hours


def build_round_tripping(
    ctx: TypologyContext, pool: AccountPool, rng: np.random.Generator, scenario_id: str
) -> Scenario:
    """Cycle A->B->C(->D)->A with strictly increasing timestamps and shrinking amounts."""
    n = int(rng.integers(HOPS[0], HOPS[1] + 1))
    hops = pool.take(n)
    amount = int(rng.integers(FIRST_STEP_VND[0] // 1000, FIRST_STEP_VND[1] // 1000 + 1)) * 1000
    ts = random_start(ctx, rng, ROUND_TRIP_WINDOW_HOURS // 24)
    rows = []
    for i in range(n):
        rows.append(make_row(ts, hops[i], hops[(i + 1) % n], amount, pick_channel(rng)))
        ts = ts + pd.Timedelta(seconds=int(rng.integers(HOUR_SECONDS, MAX_GAP_SECONDS)))
        amount = round_k(amount * float(rng.uniform(*STEP_FACTOR)))
    return Scenario(
        scenario_id=scenario_id,
        typology="round_tripping",
        is_suspicious=True,
        accounts=[(a, "hop") for a in hops],
        rows=rows_frame(rows),
        reason=f"funds returned to the origin account after {n} transfers within 7 days",
    )
