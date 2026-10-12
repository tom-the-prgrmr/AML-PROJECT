"""NET_CYCLE: money that leaves an account and comes back through other customers in time order.

Static cycle enumeration explodes on dense graphs, so the search is bounded three ways: only
transfers above a floor, only edges inside a strongly connected component, and a depth-first
search that must move forward in time inside one window. Every transfer examined is one step
and the total is capped by ``max_search_steps`` (an error, never a silent cut).
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
import pandas as pd

from aml.common.config import CycleConfig
from aml.graph.network.inputs import NetworkError, fmt_ts, rule_version
from aml.monitoring.recording import AlertRecord

RULE_ID = "NET_CYCLE"
Instance = tuple[int, ...]  # row positions of the candidate frame, first transfer first


@dataclass(frozen=True)
class CycleResult:
    alerts: tuple[AlertRecord, ...]
    steps: int


def _candidates(transfers: pd.DataFrame, cfg: CycleConfig) -> pd.DataFrame:
    """Transfers above the floor whose two ends sit in one strongly connected component."""
    big = transfers[transfers["amt"] >= cfg.min_amount_vnd].reset_index(drop=True)
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_edges_from(sorted(set(zip(big["src"], big["dst"], strict=True))))
    component: dict[str, int] = {}
    for k, members in enumerate(nx.strongly_connected_components(graph)):
        if len(members) >= cfg.min_length:
            component.update(dict.fromkeys(members, k))
    src, dst = big["src"].map(component), big["dst"].map(component)
    return big[(src.notna() & (src == dst)).to_numpy()].reset_index(drop=True)


class _Search:
    """Depth-first search for time-ordered cycles over the candidate frame."""

    def __init__(self, edges: pd.DataFrame, owner: dict[str, str], cfg: CycleConfig) -> None:
        self.cfg = cfg
        self.owner = owner
        self.edge_ids: list[str] = edges["txn_id"].tolist()
        self.src: list[str] = edges["src"].tolist()
        self.dst: list[str] = edges["dst"].tolist()
        self.amt: list[int] = edges["amt"].tolist()
        self.sec: list[int] = edges["sec"].tolist()
        self.window = cfg.window_hours * 3600
        self.steps = 0
        self.found: list[Instance] = []
        out: dict[str, list[int]] = defaultdict(list)
        for i, account in enumerate(self.src):
            out[account].append(i)  # edges are already sorted by (txn_ts, txn_id)
        self.out = out
        self.out_sec = {a: [self.sec[i] for i in rows] for a, rows in out.items()}

    def run(self) -> None:
        for i in range(len(self.src)):
            self._extend([i], [self.src[i], self.dst[i]], self.sec[i], self.amt[i], self.amt[i])

    def _extend(self, path: list[int], accounts: list[str], last: int, lo: int, hi: int) -> None:
        rows = self.out.get(accounts[-1], [])
        end = self.sec[path[0]] + self.window
        for pos in range(bisect_right(self.out_sec.get(accounts[-1], []), last), len(rows)):
            i = rows[pos]
            if self.sec[i] >= end:
                break
            self.steps += 1
            if self.steps > self.cfg.max_search_steps:
                raise NetworkError(
                    f"cycle search exceeded max_search_steps ({self.cfg.max_search_steps}); "
                    "raise network.cycles.min_amount_vnd or max_search_steps"
                )
            new_lo, new_hi = min(lo, self.amt[i]), max(hi, self.amt[i])
            if new_lo < self.cfg.min_amount_ratio * new_hi:
                continue
            nxt = self.dst[i]
            if nxt == accounts[0]:
                if len(accounts) >= self.cfg.min_length:
                    self.found.append((*path, i))
                continue
            if nxt in accounts or len(accounts) >= self.cfg.max_length:
                continue
            if self.owner[nxt] in {self.owner[a] for a in accounts}:
                continue
            path.append(i)
            accounts.append(nxt)
            self._extend(path, accounts, self.sec[i], new_lo, new_hi)
            accounts.pop()
            path.pop()


def _canonical(accounts: list[str]) -> tuple[str, ...]:
    """Rotate so the cycle starts at its smallest account id (direction is kept)."""
    k = accounts.index(min(accounts))
    return tuple(accounts[k:] + accounts[:k])


def _episodes(instances: list[Instance], search: _Search) -> list[list[Instance]]:
    """Cycles over the same accounts, grouped into bursts that start within one window."""
    ordered = sorted(
        instances, key=lambda c: (search.sec[c[0]], tuple(search.edge_ids[i] for i in c))
    )
    episodes: list[list[Instance]] = []
    for inst in ordered:
        if episodes and search.sec[inst[0]] < search.sec[episodes[-1][0][0]] + search.window:
            episodes[-1].append(inst)
        else:
            episodes.append([inst])
    return episodes


def _alert(
    episode: list[Instance], canon: tuple[str, ...], search: _Search, edges: pd.DataFrame
) -> AlertRecord:
    first = episode[0]
    rows = sorted({i for inst in episode for i in inst})
    by_time = sorted(rows, key=lambda i: (search.sec[i], search.edge_ids[i]))
    start = edges["txn_ts"][by_time[0]].to_pydatetime()
    end = edges["txn_ts"][by_time[-1]].to_pydatetime()
    path = [search.src[i] for i in first]
    origin, length = path[0], len(path)
    first_vnd, last_vnd = search.amt[first[0]], search.amt[first[-1]]
    hours = (search.sec[first[-1]] - search.sec[first[0]]) // 3600
    subject = ">".join(canon)
    reason = (
        f"{first_vnd:,} VND left {origin} and {last_vnd:,} VND ({last_vnd / first_vnd:.0%}) "
        f"returned after {length} transfers across {length} customers in {hours} hours "
        f"({' -> '.join(path)} -> {origin}) between {fmt_ts(start)} and {fmt_ts(end)}"
    )
    details: dict[str, object] = {
        "length": length,
        "origin": origin,
        "path": path,
        "first_vnd": first_vnd,
        "last_vnd": last_vnd,
        "hours": hours,
        "instances": len(episode),
    }
    return AlertRecord(
        RULE_ID,
        rule_version(RULE_ID),
        "ACCOUNT_GROUP",
        subject,
        tuple((a, "ORIGIN" if a == origin else "HOP") for a in sorted(canon)),
        start,
        end,
        tuple(sorted(search.edge_ids[i] for i in rows)),
        sum(search.amt[i] for i in rows),
        reason,
        details,
        f"{RULE_ID}|{subject}|{start:%Y-%m-%dT%H:%M:%S}",
    )


def detect_cycles(transfers: pd.DataFrame, owner: dict[str, str], cfg: CycleConfig) -> CycleResult:
    edges = _candidates(transfers, cfg)
    search = _Search(edges, owner, cfg)
    search.run()
    groups: dict[tuple[str, ...], list[Instance]] = defaultdict(list)
    for inst in search.found:
        groups[_canonical([search.src[i] for i in inst])].append(inst)
    alerts = [
        _alert(episode, canon, search, edges)
        for canon, instances in groups.items()
        for episode in _episodes(instances, search)
    ]
    alerts.sort(key=lambda a: (a.window_start, a.subject_id))
    return CycleResult(tuple(alerts), search.steps)
