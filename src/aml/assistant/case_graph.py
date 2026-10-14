"""Case graph retriever: k-hop facts around a case or a golden customer.

Neo4j gives the structure (accounts, transfers, shared attributes, matched typologies). The system
of record gives what the projection does not hold: transaction memos, and evidence transactions
with one side missing (cash). ``hops`` decides how far the facts go:

    1 = the customer's accounts
    2 = + transfers in the case window and customers sharing a device / phone / address
    3 = + the owner of each counterparty account

`build_case_evidence` is pure: it turns rows already read into `Evidence`, in a fixed order.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from aml.assistant.evidence import (
    Evidence,
    RetrievalError,
    RetrievalUnavailableError,
    UntrustedField,
    cite,
    fmt_day,
    fmt_ts,
    fmt_vnd,
    is_citable,
    renumber,
    safe_or_untrusted,
    untrusted_field,
)
from aml.assistant.txn_lookup import read_transactions, record_fact, transaction_fact
from aml.cases.values import plain
from aml.cases.view import CaseAlert, CaseView, load_case
from aml.common.config import Settings
from aml.common.db import Database, ServiceUnavailableError
from aml.graph.neo4j.client import run_read_file
from aml.graph.neo4j.session import StaleGraphError, require_fresh, shared_driver

RETRIEVER = "case_graph"


@dataclass(frozen=True)
class CaseGraphRows:
    """What was read, before it becomes Evidence."""

    golden_customer_id: str
    cif_count: int
    window: tuple[date, date]  # first and last day (inclusive) of the transfer window
    accounts: list[dict[str, Any]]  # account_id, cif, account_type, currency, open_date
    totals: dict[str, int]  # transfers, in_count, in_vnd, out_count, out_vnd, own_count
    transfers: list[dict[str, Any]]  # txn_id, src, dst, amount, ts, channel, src_owner, dst_owner
    shared: list[dict[str, Any]]  # other, kind
    typologies: list[dict[str, Any]]  # typology_id, name, evidence_ids
    records: dict[str, dict[str, Any]]  # txn_id -> row of the transactions table


# ---------------------------------------------------------------- building Evidence (pure)
def _fact(
    source: str,
    text: str,
    citations: tuple[str, ...],
    data: dict[str, Any],
    untrusted: tuple[UntrustedField, ...] = (),
) -> Evidence:
    return Evidence("E0", "fact", RETRIEVER, source, text, citations, data, untrusted)


def _case_fact(case: CaseView) -> Evidence:
    text = (
        f"Case {case.case_id} ({case.status}) on customer {case.golden_customer_id}: "
        f"{len(case.alerts)} alert(s) between {fmt_ts(case.first_alert_ts)} "
        f"and {fmt_ts(case.last_alert_ts)}"
    )
    data = {
        "case_id": case.case_id,
        "status": case.status,
        "golden_customer_id": case.golden_customer_id,
        "alerts": len(case.alerts),
        "first_alert_ts": case.first_alert_ts,
        "last_alert_ts": case.last_alert_ts,
    }
    citations = (cite("case", case.case_id), cite("customer", case.golden_customer_id))
    return _fact("cases", text, citations, data)


def _alert_fact(alert: CaseAlert, case_id: str, max_chars: int) -> Evidence:
    unsafe: list[UntrustedField] = []
    rule = safe_or_untrusted("rule_id", alert.rule_id, max_chars, unsafe)
    source = safe_or_untrusted("source", alert.source, max_chars, unsafe)
    text = f"Alert {rule} ({source}) at {fmt_ts(alert.event_ts)}: {fmt_vnd(alert.amount_vnd)}"
    data = {
        "item_key": alert.item_key,
        "rule_id": alert.rule_id,
        "source": alert.source,
        "event_ts": alert.event_ts,
        "amount_vnd": alert.amount_vnd,
    }
    subject = (cite("alert", alert.item_key),) if is_citable(alert.item_key) else ()
    reason = untrusted_field("alert_reason", alert.reason, max_chars)
    return _fact("cases", text, (*subject, cite("case", case_id)), data, (*reason, *unsafe))


def _typology_fact(row: dict[str, Any], case_id: str, max_chars: int) -> Evidence | None:
    typology_id = row["typology_id"]
    if not is_citable(typology_id):
        return None
    text = f"Case {case_id} matches typology {typology_id}"
    data = {"typology_id": typology_id, "evidence_ids": list(row.get("evidence_ids") or [])}
    citations = (cite("case", case_id), cite("typology", typology_id))
    return _fact(
        "neo4j", text, citations, data, untrusted_field("name", row.get("name"), max_chars)
    )


def _account_fact(row: dict[str, Any], gid: str, max_chars: int) -> Evidence:
    unsafe: list[UntrustedField] = []
    shown = {
        key: safe_or_untrusted(key, row[key], max_chars, unsafe)
        for key in ("account_id", "account_type", "currency", "cif")
    }
    opened = fmt_day(row["open_date"]) if row.get("open_date") else "unknown"
    text = (
        f"Account {shown['account_id']} ({shown['account_type']}, {shown['currency']}) "
        f"of CIF {shown['cif']}, opened {opened}"
    )
    account = (cite("account", row["account_id"]),) if is_citable(row["account_id"]) else ()
    return _fact("neo4j", text, (*account, cite("customer", gid)), dict(row), tuple(unsafe))


def _totals_fact(rows: CaseGraphRows) -> Evidence:
    t = rows.totals
    start, end = rows.window
    text = (
        f"{t['transfers']} transfer(s) between {fmt_day(start)} and {fmt_day(end)}: "
        f"{t['in_count']} in totalling {fmt_vnd(t['in_vnd'])}, "
        f"{t['out_count']} out totalling {fmt_vnd(t['out_vnd'])}, "
        f"{t['own_count']} between own accounts; {len(rows.transfers)} listed"
    )
    data = {**t, "start": start, "end": end, "listed": len(rows.transfers)}
    return _fact("neo4j", text, (cite("customer", rows.golden_customer_id),), data)


def _counterparty(row: dict[str, Any], gid: str) -> tuple[str, tuple[str, ...]]:
    """The 3-hop suffix of a transfer and the citation it adds."""
    src_owner, dst_owner = row.get("src_owner"), row.get("dst_owner")
    if src_owner == gid and dst_owner == gid:
        return f"; both accounts belong to {gid}", ()
    account, owner = (row["dst"], dst_owner) if src_owner == gid else (row["src"], src_owner)
    if not is_citable(account):
        return "", ()
    if owner is None or not is_citable(owner):
        return f"; counterparty {account} is external", ()
    return f"; counterparty {account} is owned by {owner}", (cite("customer", owner),)


def _transfer_fact(
    row: dict[str, Any], rows: CaseGraphRows, settings: Settings, hops: int
) -> Evidence:
    suffix, extra = _counterparty(row, rows.golden_customer_id) if hops >= 3 else ("", ())
    return transaction_fact(
        row["txn_id"],
        row,
        settings,
        retriever=RETRIEVER,
        label="Transfer",
        source="neo4j",
        memo=rows.records.get(row["txn_id"], {}).get("memo"),
        suffix=suffix,
        extra_citations=extra,
    )


def _off_graph_facts(rows: CaseGraphRows, settings: Settings) -> list[Evidence]:
    """Evidence transactions that are not among the listed transfers (cash has no graph edge)."""
    listed = {t["txn_id"] for t in rows.transfers}
    wanted = dict.fromkeys(i for t in rows.typologies for i in (t.get("evidence_ids") or []))
    found = [
        i for i in wanted if i not in listed and rows.records.get(i, {}).get("txn_ts") is not None
    ]
    limit = settings.assistant.retrieval.max_transfers
    return [record_fact(i, rows.records[i], settings, RETRIEVER) for i in found[:limit]]


def _shared_fact(row: dict[str, Any], gid: str) -> Evidence | None:
    other, kind = row["other"], row["kind"]
    if not is_citable(other) or kind not in ("device", "phone", "address"):
        return None
    text = f"Customer {gid} shares a {kind} with customer {other}"
    citations = (cite("customer", gid), cite("customer", other))
    return _fact("neo4j", text, citations, {"other": other, "kind": kind})


def build_case_evidence(
    rows: CaseGraphRows,
    settings: Settings,
    *,
    case: CaseView | None = None,
    hops: int | None = None,
) -> list[Evidence]:
    """Facts in a fixed order: case, customer, alerts, typologies, accounts, transfers, shared."""
    cfg = settings.assistant.retrieval
    depth = cfg.hops if hops is None else hops
    gid, cut = rows.golden_customer_id, cfg.max_untrusted_chars
    out: list[Evidence | None] = []
    if case is not None:
        out.append(_case_fact(case))
    customer_text = (
        f"Customer {gid} has {rows.cif_count} CIF(s) and {len(rows.accounts)} account(s)"
    )
    customer_data = {
        "golden_customer_id": gid,
        "cif_count": rows.cif_count,
        "accounts": len(rows.accounts),
    }
    out.append(_fact("neo4j", customer_text, (cite("customer", gid),), customer_data))
    if case is not None:
        out += [_alert_fact(a, case.case_id, cut) for a in case.alerts]
        out += [_typology_fact(t, case.case_id, cut) for t in rows.typologies]
    if depth >= 1:
        out += [_account_fact(a, gid, cut) for a in rows.accounts]
    if depth >= 2:
        out.append(_totals_fact(rows))
        out += [_transfer_fact(t, rows, settings, depth) for t in rows.transfers]
        if case is not None:
            out += _off_graph_facts(rows, settings)
        out += [_shared_fact(s, gid) for s in rows.shared]
    return renumber([e for e in out if e is not None])


# ---------------------------------------------------------------- reading
def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): plain(v) for k, v in row.items()} for row in frame.to_dict("records")]


def _window(settings: Settings, case: CaseView | None, as_of: date | None) -> tuple[date, date]:
    """``cases.txn_summary_days`` days ending on the day of the last alert (or ``as_of``)."""
    fallback = as_of or settings.data.reference_date
    end = case.last_alert_ts.date() if case is not None else fallback
    return end - timedelta(days=settings.cases.txn_summary_days - 1), end


def _read_rows(
    db: Database, settings: Settings, customer: str, case: CaseView | None, hops: int,
    window: tuple[date, date],
) -> CaseGraphRows:  # fmt: skip
    cfg = settings.assistant.retrieval
    driver = shared_driver(settings)
    require_fresh(driver, db, settings)

    def read(name: str, **params: Any) -> list[dict[str, Any]]:
        return _records(run_read_file(driver, settings, f"retrieval/{name}.cypher", params))

    owned = read("customer", customer=customer)
    if not owned:
        raise RetrievalError(f"unknown customer {customer}")
    span = {
        "customer": customer,
        "start": datetime.combine(window[0], time.min),
        "end": datetime.combine(window[1] + timedelta(days=1), time.min),
    }
    typologies = read("typologies", case_id=case.case_id) if case is not None else []
    evidence_ids = list(dict.fromkeys(i for t in typologies for i in (t["evidence_ids"] or [])))
    totals = read("transfer_totals", **span)[0]
    transfers = read(
        "transfers",
        **span,
        evidence_ids=evidence_ids,
        limit=cfg.max_transfers,
        with_owners=hops >= 3,
    )
    shared = read(
        "shared",
        customer=customer,
        max_customers_per_value=settings.network.shared_attributes.max_customers_per_value,
        limit=cfg.max_shared,
    )
    for account in owned:
        if account["open_date"] is not None:
            account["open_date"] = pd.Timestamp(account["open_date"]).date()
    return CaseGraphRows(
        golden_customer_id=customer,
        cif_count=int(owned[0]["cif_count"] or 0),
        window=window,
        accounts=[
            {k: a[k] for k in ("account_id", "cif", "account_type", "currency", "open_date")}
            for a in owned
            if a["account_id"] is not None
        ],
        totals={k: int(v or 0) for k, v in totals.items()},
        transfers=[{k: v for k, v in t.items() if k != "rank"} for t in transfers],
        shared=shared,
        typologies=typologies,
        records=read_transactions(db, [*(t["txn_id"] for t in transfers), *evidence_ids]),
    )


def case_graph(
    db: Database,
    settings: Settings,
    *,
    case_id: str | None = None,
    customer: str | None = None,
    hops: int | None = None,
    as_of: date | None = None,
) -> list[Evidence]:
    """Facts around a case (``case_id``) or a golden customer (``customer``): exactly one of them.

    ``as_of`` ends the transfer window when there is no case (default: ``data.reference_date``).
    An unknown case raises `CaseError`; Neo4j down or a stale graph `RetrievalUnavailableError`.
    """
    if (case_id is None) == (customer is None):
        raise RetrievalError("give exactly one of case_id or customer")
    depth = settings.assistant.retrieval.hops if hops is None else hops
    if not 1 <= depth <= 3:
        raise RetrievalError(f"hops must be between 1 and 3, got {depth}")
    case = load_case(db, case_id, masked=True) if case_id is not None else None
    gid = case.golden_customer_id if case is not None else str(customer)
    try:
        rows = _read_rows(db, settings, gid, case, depth, _window(settings, case, as_of))
    except ServiceUnavailableError as exc:
        raise RetrievalUnavailableError(f"neo4j not available: {exc}") from exc
    except StaleGraphError as exc:
        raise RetrievalUnavailableError(str(exc)) from exc
    return build_case_evidence(rows, settings, case=case, hops=depth)
