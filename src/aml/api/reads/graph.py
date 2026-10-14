"""The network graph of one case, built from the system of record (no Neo4j).

Window and subject accounts come from the case enrichment; counterparties, owners and names are
read with plain SQL (``sql/common/api/graph_*.sql``) and combined here with pandas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from aml.api.reads.cases import translate_case_error
from aml.api.values import in_filter, iso_seconds, lower_columns, plain
from aml.cases.runner import CaseError
from aml.cases.view import load_case
from aml.common.db import Database

TYPE_ORDER = {"customer": 0, "account": 1, "external_account": 2}
EDGE_ORDER = {"owns": 0, "transfer": 1}


@dataclass(frozen=True)
class CaseGraph:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    meta: dict[str, Any]  # window_start, window_end, counterparties, truncated
    cifs: list[str]  # CIFs of every customer node, ascending


def _run(db: Database, name: str, **parts: str) -> pd.DataFrame:
    lines = db.sql_file(f"api/{name}").read_text(encoding="utf-8").splitlines()
    # comment lines name the placeholders too: drop them, so a value can never end a comment
    body = [ln for ln in lines if not ln.lstrip().startswith("--")]
    text = " ".join(body).strip().rstrip(";")
    for key, value in parts.items():
        text = text.replace("{" + key + "}", value)
    return lower_columns(db.query_df(text))


def _transfers(db: Database, start: date, end: date, pairs_filter: str) -> pd.DataFrame:
    return _run(
        db,
        "graph_transfers.sql",
        window_start=f"DATE '{start.isoformat()}'",
        window_end_next=f"DATE '{(end + timedelta(days=1)).isoformat()}'",
        pairs_filter=pairs_filter,
    )


def _ranked_counterparties(pairs: pd.DataFrame, subject: set[str]) -> list[str]:
    """Counterparties by (VND exchanged with the subject desc, account_id asc)."""
    totals: dict[str, int] = {}
    for r in pairs.itertuples():
        src, dst = str(r.from_account_id), str(r.to_account_id)
        if (src in subject) == (dst in subject):  # both or neither is the subject's
            continue
        other = dst if src in subject else src
        totals[other] = totals.get(other, 0) + int(plain(r.vnd) or 0)
    return [a for a, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))]


def _owners(db: Database, account_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    """account_id -> (cif, golden_customer_id) for the accounts that exist."""
    df = _run(db, "graph_accounts.sql", account_filter=in_filter("a.account_id", account_ids))
    return {str(r.account_id): (plain(r.cif), plain(r.golden_customer_id)) for r in df.itertuples()}


def _names(db: Database, cifs: list[str], masked: bool) -> dict[str, str | None]:
    df = _run(
        db,
        "graph_customers.sql",
        customers_table="customers_masked" if masked else "customers",
        cif_filter=in_filter("cif", cifs),
    )
    return {str(r.cif): plain(r.full_name) for r in df.itertuples()}


def _node(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": None,
        "type": None,
        "label": None,
        "is_subject": False,
        "golden_customer_id": None,
        "cif": None,
        "cifs": None,
    }
    return {**base, **fields}


def _edge(kind: str, source: str, target: str, **metrics: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"txns": None, "vnd": None, "first_ts": None, "last_ts": None}
    return {
        "id": f"{kind}:{source}>{target}",
        "type": kind,
        "source": source,
        "target": target,
        **base,
        **metrics,
    }


def case_graph(db: Database, case_id: str, *, masked: bool, max_counterparties: int) -> CaseGraph:
    try:
        view = load_case(db, case_id, masked=masked, scored=False)
    except CaseError as exc:
        raise translate_case_error(exc) from exc
    summary = view.enrichment.get("txn_summary", {})
    linked = view.enrichment.get("linked_cifs", {})
    subject_accounts = [str(a["account_id"]) for a in linked.get("accounts", [])]
    subject = set(subject_accounts)
    window = (summary.get("window_start"), summary.get("window_end"))
    start, end = (date.fromisoformat(w) if w else None for w in window)

    ranked: list[str] = []
    if start and end and subject:
        in_subject = in_filter("from_account_id", subject_accounts)
        to_subject = in_filter("to_account_id", subject_accounts)
        ranked = _ranked_counterparties(
            _transfers(db, start, end, f"({in_subject} OR {to_subject})"), subject
        )
    shown = ranked[:max_counterparties]
    account_ids = sorted(subject | set(shown))

    owners = _owners(db, account_ids)
    golden = view.golden_customer_id
    owners.update({a: (owners.get(a, (None, None))[0], golden) for a in subject_accounts})
    cifs_by_golden: dict[str, set[str]] = {golden: {str(c) for c in linked.get("cifs", [])}}
    for account in shown:
        cif, gid = owners.get(account, (None, None))
        if cif and gid:
            cifs_by_golden.setdefault(gid, set()).add(cif)
    names = _names(db, sorted({c for cs in cifs_by_golden.values() for c in cs}), masked)

    nodes = [
        _node(
            id=gid,
            type="customer",
            label=gid,
            is_subject=gid == golden,
            golden_customer_id=gid,
            cifs=[{"cif": c, "full_name": names.get(c)} for c in sorted(cifs)],
        )
        for gid, cifs in cifs_by_golden.items()
    ]
    edges: list[dict[str, Any]] = []
    for account in account_ids:
        known = account in owners
        cif, gid = owners.get(account, (None, None))
        nodes.append(
            _node(
                id=account,
                type="account" if known else "external_account",
                label=account,
                is_subject=account in subject,
                golden_customer_id=gid,
                cif=cif,
            )
        )
        if gid:
            edges.append(_edge("owns", gid, account))

    sources = in_filter("from_account_id", account_ids)
    targets = in_filter("to_account_id", account_ids)
    node_filter = f"({sources} AND {targets})"
    if start and end and account_ids:
        for r in _transfers(db, start, end, node_filter).itertuples():
            edges.append(
                _edge(
                    "transfer",
                    str(r.from_account_id),
                    str(r.to_account_id),
                    txns=int(plain(r.txns)),
                    vnd=int(plain(r.vnd)),
                    first_ts=iso_seconds(r.first_ts),
                    last_ts=iso_seconds(r.last_ts),
                )
            )
    nodes.sort(key=lambda n: (TYPE_ORDER[n["type"]], n["id"]))
    edges.sort(key=lambda e: (EDGE_ORDER[e["type"]], e["source"], e["target"]))
    meta = {
        "window_start": summary.get("window_start"),
        "window_end": summary.get("window_end"),
        "counterparties": {"total": len(ranked), "shown": len(shown)},
        "truncated": len(ranked) > len(shown),
    }
    all_cifs = sorted({c for cs in cifs_by_golden.values() for c in cs})
    return CaseGraph(nodes=nodes, edges=edges, meta=meta, cifs=all_cifs)
