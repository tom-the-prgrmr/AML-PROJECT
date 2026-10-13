"""Turn the raw GDS streams into one feature row per account (pure pandas, no drivers).

GDS hands out internal component / community codes that change between runs, so they never leave
this module: a group is named after its smallest member instead (account id, or CIF for the
shared-attribute clusters), which is stable for the same data.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

GDS_FEATURE_COLUMNS: list[str] = [
    "account_id",
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
    "wcc_id",
    "wcc_size",
    "louvain_id",
    "louvain_size",
    "shared_cluster_id",
    "shared_cluster_size",
]

SHARED_PREFIX = "SHARED-"


@dataclass(frozen=True)
class GdsStreams:
    """Raw stream frames; columns as returned by the `gds/*.cypher` files."""

    in_degree: pd.DataFrame  # account_id, score
    out_degree: pd.DataFrame  # account_id, score
    in_vnd: pd.DataFrame  # account_id, score (weighted by total_vnd)
    out_vnd: pd.DataFrame  # account_id, score
    pagerank: pd.DataFrame  # account_id, score
    wcc: pd.DataFrame  # account_id, component
    louvain: pd.DataFrame  # account_id, community
    shared: pd.DataFrame  # golden_customer_id, component


def _scores(frame: pd.DataFrame) -> dict[str, float]:
    return {str(a): float(s) for a, s in zip(frame["account_id"], frame["score"], strict=True)}


def _int_column(accounts: list[str], frame: pd.DataFrame) -> list[int]:
    # int(float) would lose precision above 2**53; read integers straight from the frame
    values = {str(a): int(s) for a, s in zip(frame["account_id"], frame["score"], strict=True)}
    return [values.get(a, 0) for a in accounts]


def _groups(frame: pd.DataFrame, member: str, group: str) -> dict[str, tuple[str, int]]:
    """member -> (smallest member of its group, group size)."""
    members: dict[object, set[str]] = {}
    for m, g in zip(frame[member], frame[group], strict=True):
        members.setdefault(g, set()).add(str(m))
    return {m: (min(ms), len(ms)) for ms in members.values() for m in ms}


def _pagerank(accounts: list[str], frame: pd.DataFrame) -> tuple[list[float], list[float]]:
    scores = _scores(frame)
    total = sum(scores.values())
    if not scores or total <= 0:
        return [0.0] * len(accounts), [0.0] * len(accounts)
    share = [scores.get(a, 0.0) / total for a in accounts]
    return (
        [round(s, 8) for s in share],
        [round(s * len(scores), 4) for s in share],
    )


def _shared(
    accounts: pd.DataFrame, owner_of_cif: Mapping[str, str], frame: pd.DataFrame
) -> dict[str, tuple[str, int]]:
    """golden customer -> (SHARED-<smallest CIF of the cluster>, customers in the cluster)."""
    cifs_of: dict[str, set[str]] = {}
    for cif, golden in owner_of_cif.items():
        cifs_of.setdefault(golden, set()).add(cif)
    clusters: dict[object, set[str]] = {}
    for golden, comp in zip(frame["golden_customer_id"], frame["component"], strict=True):
        clusters.setdefault(comp, set()).add(str(golden))
    out: dict[str, tuple[str, int]] = {}
    for goldens in clusters.values():
        smallest = min((c for g in goldens for c in cifs_of.get(g, ())), default=None)
        if smallest is None:
            continue
        for g in goldens:
            out[g] = (SHARED_PREFIX + smallest, len(goldens))
    return out


def build_features(
    accounts: pd.DataFrame, owner_of_cif: Mapping[str, str], streams: GdsStreams
) -> pd.DataFrame:
    """One row per account (sorted by account_id) with the `GDS_FEATURE_COLUMNS` columns.

    `accounts` has `account_id` and `cif`; `owner_of_cif` maps a CIF to its golden customer id.
    """
    ordered = accounts.sort_values("account_id", kind="stable").reset_index(drop=True)
    ids = [str(a) for a in ordered["account_id"]]
    pagerank, ratio = _pagerank(ids, streams.pagerank)

    def labelled(groups: dict[str, tuple[str, int]]) -> tuple[list[str | None], list[int]]:
        found = [groups.get(a) for a in ids]
        return [g[0] if g else None for g in found], [g[1] if g else 0 for g in found]

    wcc_id, wcc_size = labelled(_groups(streams.wcc, "account_id", "component"))
    lou_id, lou_size = labelled(_groups(streams.louvain, "account_id", "community"))
    shared = _shared(ordered, owner_of_cif, streams.shared)
    found = [shared.get(owner_of_cif.get(str(c), f"G-{c}")) for c in ordered["cif"]]

    frame = pd.DataFrame(
        {
            "account_id": pd.Series(ids, dtype=object),
            "in_degree": pd.Series(_int_column(ids, streams.in_degree), dtype="int64"),
            "out_degree": pd.Series(_int_column(ids, streams.out_degree), dtype="int64"),
            "in_vnd": pd.Series(_int_column(ids, streams.in_vnd), dtype="int64"),
            "out_vnd": pd.Series(_int_column(ids, streams.out_vnd), dtype="int64"),
            "pagerank": pd.Series(pagerank, dtype="float64"),
            "pagerank_ratio": pd.Series(ratio, dtype="float64"),
            "wcc_id": pd.Series(wcc_id, dtype=object),
            "wcc_size": pd.Series(wcc_size, dtype="int64"),
            "louvain_id": pd.Series(lou_id, dtype=object),
            "louvain_size": pd.Series(lou_size, dtype="int64"),
            "shared_cluster_id": pd.Series([f[0] if f else None for f in found], dtype=object),
            "shared_cluster_size": pd.Series([f[1] if f else 0 for f in found], dtype="int64"),
        }
    )
    return frame[GDS_FEATURE_COLUMNS]
