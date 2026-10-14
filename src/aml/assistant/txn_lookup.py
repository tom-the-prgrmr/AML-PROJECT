"""Look one or more transactions up by id in the system of record (needs only the `Database`).

Memos and cash transactions are not in the Neo4j projection, so this is the one path by which a
question without a case can reach a transaction memo. The memo always travels as an untrusted
field, never inside ``Evidence.text``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from aml.assistant.evidence import (
    Evidence,
    UntrustedField,
    cite,
    fmt_ts,
    fmt_vnd,
    is_citable,
    is_safe_token,
    renumber,
    safe_or_untrusted,
    untrusted_field,
)
from aml.cases.values import in_filter, lower_columns, plain
from aml.common.config import Settings
from aml.common.db import Database

COLUMNS = "txn_id, txn_ts, from_account_id, to_account_id, amount_vnd, channel, memo"


def read_transactions(db: Database, txn_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Rows of ``transactions`` by txn_id. An id that is not a safe token never reaches the SQL."""
    safe = [t for t in dict.fromkeys(txn_ids) if is_safe_token(t)]
    if not safe:
        return {}
    df = lower_columns(
        db.query_df(f"SELECT {COLUMNS} FROM transactions WHERE {in_filter('txn_id', safe)}")
    )
    rows: dict[str, dict[str, Any]] = {}
    for record in df.to_dict("records"):
        row = {str(k): plain(v) for k, v in record.items()}
        row["txn_ts"] = pd.Timestamp(row["txn_ts"]).to_pydatetime()
        row["amount_vnd"] = int(row["amount_vnd"])
        rows[str(row["txn_id"])] = row
    return rows


def transaction_fact(
    txn_id: str,
    row: Mapping[str, Any],
    settings: Settings,
    *,
    retriever: str,
    label: str = "Transaction",
    source: str = "records",
    memo: object = None,
    suffix: str = "",
    extra_citations: Sequence[str] = (),
) -> Evidence:
    """One fact about a money movement; ``row`` has src, dst, amount, ts, channel."""
    cfg = settings.assistant.retrieval
    unsafe: list[UntrustedField] = []
    src, dst = row["src"], row["dst"]
    shown = {
        "src": "-"
        if src is None
        else safe_or_untrusted("src", src, cfg.max_untrusted_chars, unsafe),
        "dst": "-"
        if dst is None
        else safe_or_untrusted("dst", dst, cfg.max_untrusted_chars, unsafe),
        "channel": safe_or_untrusted("channel", row["channel"], cfg.max_untrusted_chars, unsafe),
    }
    text = (
        f"{label} {txn_id}: {fmt_vnd(row['amount'])} from {shown['src']} to {shown['dst']} "
        f"on {fmt_ts(row['ts'])} via {shown['channel']}{suffix}"
    )
    accounts = [cite("account", a) for a in (src, dst) if is_citable(a)]
    memo_field = untrusted_field("memo", memo, cfg.max_untrusted_chars) if cfg.include_memos else ()
    return Evidence(
        ref="E0",
        kind="fact",
        retriever=retriever,
        source=source,
        text=text,
        citations=(cite("txn", txn_id), *accounts, *extra_citations),
        data={
            "txn_id": txn_id,
            "src": src,
            "dst": dst,
            "amount": row["amount"],
            "ts": row["ts"],
            "channel": row["channel"],
        },
        untrusted=(*memo_field, *unsafe),
    )


def record_fact(
    txn_id: str, record: Mapping[str, Any], settings: Settings, retriever: str
) -> Evidence:
    """A fact built from a row of the ``transactions`` table."""
    row = {
        "src": record["from_account_id"],
        "dst": record["to_account_id"],
        "amount": record["amount_vnd"],
        "ts": record["txn_ts"],
        "channel": record["channel"],
    }
    return transaction_fact(txn_id, row, settings, retriever=retriever, memo=record.get("memo"))


def transaction_facts(db: Database, settings: Settings, txn_ids: Sequence[str]) -> list[Evidence]:
    """One `Evidence` per transaction found, in the order asked, without repeats."""
    records = read_transactions(db, txn_ids)
    found = [t for t in dict.fromkeys(txn_ids) if t in records]
    return renumber([record_fact(t, records[t], settings, "txn_lookup") for t in found])
