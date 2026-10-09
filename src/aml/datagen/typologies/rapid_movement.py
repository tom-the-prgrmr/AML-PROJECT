"""Rapid movement: a large inflow pushed out to several accounts within 24 hours."""

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
    split_amount,
)

RAPID_MIN_VND, RAPID_MAX_VND = 200_000_000, 2_000_000_000
MAX_INFLOW_SECONDS = 3 * HOUR_SECONDS  # inflows land in the first 3 hours
MIN_OUT_SECONDS, MAX_OUT_SECONDS = 4 * HOUR_SECONDS, 22 * HOUR_SECONDS  # < 24h after first inflow
PASS_THROUGH_MIN, PASS_THROUGH_MAX = 0.955, 0.985  # share of the inflow sent out
SOURCES = (1, 3)
DESTINATIONS = (2, 4)


def build_rapid_movement(
    ctx: TypologyContext, pool: AccountPool, rng: np.random.Generator, scenario_id: str
) -> Scenario:
    """Receive X in 200M-2B VND, then send 95-99% of X to >= 2 accounts within 24 hours."""
    n_src = int(rng.integers(SOURCES[0], SOURCES[1] + 1))
    n_dst = int(rng.integers(DESTINATIONS[0], DESTINATIONS[1] + 1))
    subject, *others = pool.take(1 + n_src + n_dst)
    sources, destinations = others[:n_src], others[n_src:]
    total_in = int(rng.integers(RAPID_MIN_VND // 1000, RAPID_MAX_VND // 1000 + 1)) * 1000
    t0 = random_start(ctx, rng, 2)
    rows = []
    in_offsets = np.sort(rng.integers(0, MAX_INFLOW_SECONDS, size=n_src))
    for src, amount, off in zip(
        sources, split_amount(total_in, n_src, rng), in_offsets.tolist(), strict=True
    ):
        ts = t0 + pd.Timedelta(seconds=off)
        rows.append(make_row(ts, src, subject, amount, "INTERNAL_TRANSFER"))
    share = float(rng.uniform(PASS_THROUGH_MIN, PASS_THROUGH_MAX))
    total_out = round_k(total_in * share)
    out_offsets = rng.integers(MIN_OUT_SECONDS, MAX_OUT_SECONDS + 1, size=n_dst)
    for dst, amount, off in zip(
        destinations, split_amount(total_out, n_dst, rng), out_offsets.tolist(), strict=True
    ):
        ts = t0 + pd.Timedelta(seconds=off)
        rows.append(make_row(ts, subject, dst, amount, pick_channel(rng)))
    roles = [(subject, "subject")]
    roles += [(a, "source") for a in sources] + [(a, "destination") for a in destinations]
    return Scenario(
        scenario_id=scenario_id,
        typology="rapid_movement",
        is_suspicious=True,
        accounts=roles,
        rows=rows_frame(rows),
        reason=(
            f"{total_in:,} VND received and {total_out:,} VND ({share:.0%}) forwarded to "
            f"{n_dst} accounts within 24 hours"
        ),
    )
