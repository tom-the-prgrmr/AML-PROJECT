"""Mule ring: many linked accounts collect small inflows and funnel them to one collector."""

from __future__ import annotations

import numpy as np
import pandas as pd

from aml.datagen.typologies._common import (
    DAY_SECONDS,
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

MULE_MIN_MEMBERS, MULE_MAX_MEMBERS = 5, 30
SOURCES = (3, 5)  # distinct outside accounts feeding the ring
DESTINATIONS = (3, 4)
INFLOWS_PER_MEMBER = 3
INFLOW_VND = (5_000_000, 60_000_000)
RETENTION = (0.01, 0.05)  # share each hop keeps before passing money on
# Day offsets from the ring start: inflows < FORWARD_DAY <= member -> collector < PAYOUT_DAY.
FORWARD_DAY, PAYOUT_DAY = 3, 5
SHARED_ATTRIBUTES: dict[str, list[str]] = {
    "device_id": ["device_id"],
    "phone": ["phone"],
    "address": ["address_format", "street", "ward", "district", "province", "address"],
}


def build_mule_ring(
    ctx: TypologyContext, pool: AccountPool, rng: np.random.Generator, scenario_id: str
) -> Scenario:
    """Collect from outside sources into 5-30 members, funnel to a collector, pay out."""
    n_members = int(rng.integers(MULE_MIN_MEMBERS, MULE_MAX_MEMBERS + 1))
    n_src = int(rng.integers(SOURCES[0], SOURCES[1] + 1))
    n_dst = int(rng.integers(DESTINATIONS[0], DESTINATIONS[1] + 1))
    taken = pool.take(n_members + n_src + n_dst)
    members, sources = taken[:n_members], taken[n_members : n_members + n_src]
    destinations = taken[n_members + n_src :]
    collector = members[0]
    t0 = random_start(ctx, rng, PAYOUT_DAY + 2).normalize()
    rows = []
    collected = 0
    for member in members:
        received = 0
        for k in rng.choice(n_src, size=INFLOWS_PER_MEMBER, replace=False).tolist():
            amount = int(rng.integers(INFLOW_VND[0] // 1000, INFLOW_VND[1] // 1000 + 1)) * 1000
            ts = t0 + pd.Timedelta(seconds=int(rng.integers(0, FORWARD_DAY * DAY_SECONDS)))
            rows.append(make_row(ts, sources[k], member, amount, pick_channel(rng)))
            received += amount
        if member == collector:
            collected += received
            continue
        sent = round_k(received * (1 - float(rng.uniform(*RETENTION))))
        offset = FORWARD_DAY * DAY_SECONDS + int(rng.integers(0, 2 * DAY_SECONDS))
        rows.append(
            make_row(t0 + pd.Timedelta(seconds=offset), member, collector, sent, pick_channel(rng))
        )
        collected += sent
    payout = round_k(collected * (1 - float(rng.uniform(*RETENTION))))
    for dst, amount in zip(destinations, split_amount(payout, n_dst, rng), strict=True):
        offset = PAYOUT_DAY * DAY_SECONDS + int(rng.integers(0, DAY_SECONDS))
        rows.append(
            make_row(t0 + pd.Timedelta(seconds=offset), collector, dst, amount, pick_channel(rng))
        )
    roles = [(collector, "collector")] + [(m, "member") for m in members[1:]]
    roles += [(a, "source") for a in sources] + [(a, "destination") for a in destinations]
    return Scenario(
        scenario_id=scenario_id,
        typology="mule_ring",
        is_suspicious=True,
        accounts=roles,
        rows=rows_frame(rows),
        reason=(
            f"{n_members} linked accounts (shared device, phone or address) collected funds "
            f"from {n_src} sources and funnelled them through one collector to {n_dst} accounts"
        ),
        linked_cifs=tuple(pool.cif(m) for m in members),
    )


def link_members(customers: pd.DataFrame, cifs: tuple[str, ...], rng: np.random.Generator) -> None:
    """Overwrite shared attributes of ``cifs[1:]`` in place with those of ``cifs[0]``.

    Each member copies one attribute group (device, phone or address) verbatim from the first
    member, so the members form a star in the shared-attribute graph. ``customers`` must be a
    private copy.
    """
    anchor = customers.index[customers["cif"] == cifs[0]][0]
    usable = [g for g, cols in SHARED_ATTRIBUTES.items() if pd.notna(customers.at[anchor, cols[0]])]
    for cif in cifs[1:]:
        group = usable[int(rng.integers(len(usable)))]
        row = customers.index[customers["cif"] == cif][0]
        for col in SHARED_ATTRIBUTES[group]:
            customers.at[row, col] = customers.at[anchor, col]
