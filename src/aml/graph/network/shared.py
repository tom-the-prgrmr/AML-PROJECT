"""NET_SHARED_ATTRIBUTE: customers linked through a shared device, phone or address."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import networkx as nx
import pandas as pd

from aml.common.config import SharedAttributeConfig
from aml.entity_resolution.normalize import address_keys, normalize_phone
from aml.graph.network.inputs import NetworkInputs, fmt_ts, midnight, rule_version
from aml.monitoring.recording import AlertRecord

RULE_ID = "NET_SHARED_ATTRIBUTE"
KINDS = ("device", "phone", "address")


@dataclass(frozen=True)
class SharedResult:
    alerts: tuple[AlertRecord, ...]
    cluster_of: dict[str, tuple[str, int]]  # account_id -> (cluster id, customers in the cluster)


def _device_key(value: object) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def attribute_keys(customers: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """One row per CIF: device, phone and address keys (None when unusable), sorted by cif."""
    frame = pd.DataFrame(
        {
            "cif": customers["cif"],
            "device_key": [_device_key(v) for v in customers["device_id"]],
            "phone_key": [normalize_phone(v) for v in customers["phone"]],
            "address_key": address_keys(customers, mapping),
        },
        dtype=object,
    )
    return frame.sort_values("cif").reset_index(drop=True)


def _link_graph(
    keys: pd.DataFrame, owner_of_cif: dict[str, str], cfg: SharedAttributeConfig
) -> nx.Graph:
    """Bipartite graph owner - (kind, value); a value links only if 2..max owners carry it."""
    graph: nx.Graph = nx.Graph()
    owners = keys["cif"].map(owner_of_cif)
    for kind in KINDS:
        by_value: dict[str, set[str]] = defaultdict(set)
        for owner, value in zip(owners, keys[f"{kind}_key"], strict=True):
            if isinstance(value, str):
                by_value[value].add(owner)
        for value in sorted(by_value):
            members = sorted(by_value[value])
            if 2 <= len(members) <= cfg.max_customers_per_value:
                graph.add_edges_from((("owner", o), (kind, value)) for o in members)
    return graph


def _alert(
    inputs: NetworkInputs,
    component: set[tuple[str, str]],
    graph: nx.Graph,
    cifs_of_owner: dict[str, list[str]],
    accounts_of_cif: dict[str, list[str]],
) -> tuple[AlertRecord, list[str], int]:
    owners = sorted(n[1] for n in component if n[0] == "owner")
    cifs = sorted(c for o in owners for c in cifs_of_owner[o])
    accounts = sorted(a for c in cifs for a in accounts_of_cif.get(c, ()))
    cluster = "SHARED-" + cifs[0]
    links: dict[str, int] = {}
    values: dict[str, int] = {}
    for kind in KINDS:
        nodes = [n for n in component if n[0] == kind]
        values[kind] = len(nodes)
        links[kind] = len({o for n in nodes for o in graph.neighbors(n)})
    members = set(accounts)
    t = inputs.transfers
    ev = t[t["src"].isin(members) & t["dst"].isin(members)]
    total = int(ev["amt"].sum())
    if len(ev):
        start, end = ev["txn_ts"].min().to_pydatetime(), ev["txn_ts"].max().to_pydatetime()
        tail = (
            f"{len(ev)} transfer(s) totalling {total:,} VND between members "
            f"between {fmt_ts(start)} and {fmt_ts(end)}"
        )
    else:
        start = end = midnight(inputs.as_of)
        tail = "no transfers between members"
    reason = (
        f"{len(owners)} customers ({len(accounts)} accounts) linked by shared device "
        f"({links['device']} customers), phone ({links['phone']}), address ({links['address']}); "
        f"{tail}"
    )
    details: dict[str, object] = {
        "customers": len(owners),
        "cifs": cifs,
        "accounts": len(accounts),
        "links": links,
        "shared_values": values,
        "internal_txns": len(ev),
        "internal_vnd": total,
    }
    record = AlertRecord(
        RULE_ID,
        rule_version(RULE_ID),
        "ACCOUNT_GROUP",
        cluster,
        tuple((a, "MEMBER") for a in accounts),
        start,
        end,
        tuple(sorted(ev["txn_id"])),
        total,
        reason,
        details,
        f"{RULE_ID}|{cluster}",
    )
    return record, accounts, len(owners)


def detect_shared(inputs: NetworkInputs, cfg: SharedAttributeConfig) -> SharedResult:
    keys = attribute_keys(inputs.customers, inputs.mapping)
    graph = _link_graph(keys, inputs.owner_of_cif, cfg)
    cifs_of_owner: dict[str, list[str]] = defaultdict(list)
    for cif, owner in inputs.owner_of_cif.items():
        cifs_of_owner[owner].append(cif)
    accounts_of_cif: dict[str, list[str]] = defaultdict(list)
    for account, cif in zip(inputs.accounts["account_id"], inputs.accounts["cif"], strict=True):
        accounts_of_cif[cif].append(account)
    alerts: list[AlertRecord] = []
    cluster_of: dict[str, tuple[str, int]] = {}
    for component in nx.connected_components(graph):
        if sum(1 for n in component if n[0] == "owner") < cfg.min_customers:
            continue
        record, accounts, size = _alert(inputs, component, graph, cifs_of_owner, accounts_of_cif)
        alerts.append(record)
        cluster_of.update((a, (record.subject_id, size)) for a in accounts)
    alerts.sort(key=lambda a: a.subject_id)
    return SharedResult(tuple(alerts), cluster_of)
