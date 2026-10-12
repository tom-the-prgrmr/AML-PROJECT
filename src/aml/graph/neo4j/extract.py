"""Read the source database and shape the Neo4j projection as plain DataFrames (no Neo4j needed).

Every sort is done in Python so the frames do not depend on the backend's ORDER BY or on the
physical row order. Column names are lower-cased because Oracle returns upper-case ones. Only
seven objects are read, all readable by the least-privilege sync user. No cell holds raw PII:
device, phone and address values are replaced by a short sha256 key.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, TypeVar

import numpy as np
import pandas as pd

from aml.common.config import Settings
from aml.common.db import Database, OracleDb, ServiceUnavailableError
from aml.graph.neo4j.guard import GraphError
from aml.graph.network.inputs import fmt_ts
from aml.graph.network.shared import KINDS, attribute_keys

T = TypeVar("T")

NODE_LABELS = ("Customer", "Account", "Device", "Phone", "Address")
REL_TYPES = ("OWNS", "USES_DEVICE", "HAS_PHONE", "LIVES_AT", "TRANSFERRED_TO", "SENT_TO")
COLUMNS: dict[str, list[str]] = {
    "Customer": ["golden_customer_id", "cifs", "cif_count"],
    "Account": [
        "account_id",
        "cif",
        "account_type",
        "branch_id",
        "open_date",
        "currency",
        "is_external",
    ],
    "Device": ["key"],
    "Phone": ["key"],
    "Address": ["key"],
    "OWNS": ["golden_customer_id", "account_id", "cif"],
    "USES_DEVICE": ["golden_customer_id", "key"],
    "HAS_PHONE": ["golden_customer_id", "key"],
    "LIVES_AT": ["golden_customer_id", "key"],
    "TRANSFERRED_TO": ["txn_id", "src", "dst", "amount", "ts", "channel"],
    "SENT_TO": ["src", "dst", "day", "count", "total"],
}
ATTRIBUTE_LABEL = {"device": "Device", "phone": "Phone", "address": "Address"}
ATTRIBUTE_REL = {"device": "USES_DEVICE", "phone": "HAS_PHONE", "address": "LIVES_AT"}
SETUP_HINT = "run `aml security-setup` first"


class SyncError(GraphError):
    """The projection cannot be read from the source (or synced) with what it was given."""


@dataclass(frozen=True)
class Projection:
    frames: dict[str, pd.DataFrame]  # 11 keys = NODE_LABELS + REL_TYPES, columns per COLUMNS
    er_run_id: int
    max_ts: datetime | None  # largest txn_ts among the transfers read


def attribute_key(kind: str, value: str) -> str:
    """Hash of a normalised device / phone / address value: hides it, does not anonymise it."""
    return hashlib.sha256(f"{kind}|{value}".encode()).hexdigest()[:16]


def open_source(db: Database, settings: Settings) -> Database:
    """DuckDB: ``db`` itself. Oracle: a NEW read-only-user connection (the caller closes it)."""
    if db.backend != "oracle":
        return db
    cfg = settings.db.oracle
    if not cfg.demo_password:
        raise SyncError("Oracle sync user has no password: set ORACLE_DEMO_PASSWORD in .env")
    user = settings.graph_sync.oracle_user
    login = cfg.model_copy(update={"user": user, "password": cfg.demo_password})
    as_sync = settings.model_copy(update={"db": settings.db.model_copy(update={"oracle": login})})
    try:
        source = OracleDb(as_sync)
    except ServiceUnavailableError as exc:
        raise SyncError(f"cannot log in as {user}: {exc}; {SETUP_HINT}") from exc
    try:
        source.execute(f"ALTER SESSION SET CURRENT_SCHEMA = {cfg.user}")
    except Exception as exc:
        source.close()
        raise SyncError(f"cannot use schema {cfg.user} as {user}: {exc}; {SETUP_HINT}") from exc
    return source


def _query(source: Database, sql: str, hint: str) -> pd.DataFrame:
    try:
        frame = source.query_df(sql)
    except Exception as exc:  # missing table / no grant: driver-specific error types
        if "ORA-00942" in str(exc):
            hint = f"table or view is not readable; {SETUP_HINT}"
        raise SyncError(f"{hint} ({exc})") from exc
    frame.columns = [str(c).lower() for c in frame.columns]
    return frame


def _read(source: Database, table: str, columns: str, where: str, hint: str) -> pd.DataFrame:
    sql = f"SELECT {columns} FROM {table}{where}"
    return _query(source, sql, f"{table} is unavailable; {hint}")


def _as_date(value: Any) -> date | None:
    if value is None or bool(pd.isna(value)):
        return None
    return pd.Timestamp(value).date()


def _text(value: Any) -> str | None:
    return None if value is None or bool(pd.isna(value)) else str(value)


def _owner_map(golden: pd.DataFrame, cifs: set[str]) -> dict[str, str]:
    by_cif = dict(zip(golden["cif"], golden["golden_customer_id"], strict=True))
    return {c: by_cif.get(c, f"G-{c}") for c in sorted(cifs)}


def _customer_frames(
    attrs: pd.DataFrame, mapping: pd.DataFrame, accounts: pd.DataFrame, owner: dict[str, str]
) -> dict[str, pd.DataFrame]:
    members: dict[str, list[str]] = {}
    for cif, golden in owner.items():
        members.setdefault(golden, []).append(cif)
    customer = pd.DataFrame(
        [(g, sorted(members[g]), len(members[g])) for g in sorted(members)],
        columns=COLUMNS["Customer"],
        dtype=object,
    )
    keys = attribute_keys(attrs, mapping)
    keys["golden"] = keys["cif"].map(owner)
    frames = {"Customer": customer}
    for kind in KINDS:
        pairs = {
            (g, attribute_key(kind, v))
            for g, v in zip(keys["golden"], keys[f"{kind}_key"], strict=True)
            if isinstance(v, str)
        }
        rel = sorted(pairs)
        frames[ATTRIBUTE_REL[kind]] = pd.DataFrame(rel, columns=COLUMNS[ATTRIBUTE_REL[kind]])
        frames[ATTRIBUTE_LABEL[kind]] = pd.DataFrame(
            sorted({k for _, k in rel}), columns=COLUMNS[ATTRIBUTE_LABEL[kind]]
        )
    owned = accounts[accounts["cif"].notna()]
    owns = sorted((owner[c], a, c) for a, c in zip(owned["account_id"], owned["cif"], strict=True))
    frames["OWNS"] = pd.DataFrame(owns, columns=COLUMNS["OWNS"])
    return frames


def _account_frame(accounts: pd.DataFrame, transfers: pd.DataFrame) -> pd.DataFrame:
    known = set(accounts["account_id"])
    seen = set(transfers["src"]) | set(transfers["dst"])
    rows: list[tuple[Any, ...]] = [
        (
            a,
            _text(c),
            _text(t),
            _text(b),
            _as_date(d),
            _text(cur),
            False,
        )
        for a, c, t, b, d, cur in zip(
            accounts["account_id"],
            accounts["cif"],
            accounts["account_type"],
            accounts["branch_id"],
            accounts["open_date"],
            accounts["currency"],
            strict=True,
        )
    ]
    rows += [(a, None, None, None, None, None, True) for a in seen - known]
    rows.sort(key=lambda r: r[0])
    return pd.DataFrame(rows, columns=COLUMNS["Account"], dtype=object).astype(
        {"is_external": bool}
    )


def _transfer_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "txn_id": raw["txn_id"].astype(str),
            "src": raw["src"].astype(str),
            "dst": raw["dst"].astype(str),
            "amount": raw["amount"].astype("int64"),
            "ts": pd.to_datetime(raw["ts"]).astype("datetime64[ns]"),
            "channel": raw["channel"].astype(object).where(raw["channel"].notna(), None),
        }
    )
    return frame.sort_values("txn_id", kind="stable").reset_index(drop=True)[
        COLUMNS["TRANSFERRED_TO"]
    ]


def _daily_frame(raw: pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "src": raw["src"].astype(str),
            "dst": raw["dst"].astype(str),
            "day": pd.Series([_as_date(d) for d in raw["day"]], index=raw.index, dtype=object),
            "count": raw["count"].astype("int64"),
            "total": raw["total"].astype("int64"),
        }
    )
    return frame.sort_values(["src", "dst", "day"], kind="stable").reset_index(drop=True)[
        COLUMNS["SENT_TO"]
    ]


def build_projection(source: Database, *, since: datetime | None = None) -> Projection:
    """Read the source and build the 11 frames; ``since`` limits transfers and daily edges."""
    load = "run `aml load` first"
    attrs = _read(
        source,
        "graph_customer_attrs",
        "cif, phone, device_id, street, ward, district, province",
        "",
        load,
    )
    accounts = _read(
        source,
        "accounts",
        "account_id, cif, account_type, branch_id, open_date, currency",
        "",
        load,
    )
    if attrs.empty or accounts.empty:
        raise SyncError("customers or accounts is empty; run `aml load` first")
    mapping = _read(
        source,
        "admin_unit_mapping",
        "old_ward, old_district, old_province, new_ward, new_province",
        "",
        load,
    )
    golden = _read(
        source, "customer_golden", "run_id, cif, golden_customer_id", "", "run `aml er` first"
    )
    if golden.empty:
        raise SyncError("no entity resolution result; run `aml er` first")

    both = "from_account_id IS NOT NULL AND to_account_id IS NOT NULL"
    where_t = f" WHERE {both}"
    where_e = ""
    if since is not None:
        where_t += f" AND txn_ts >= TIMESTAMP '{fmt_ts(since)}'"
        where_e = f" WHERE day >= DATE '{since.date().isoformat()}'"
    raw_t = _read(
        source,
        "transactions",
        "txn_id, from_account_id AS src, to_account_id AS dst, amount_vnd AS amount, "
        "txn_ts AS ts, channel",
        where_t,
        load,
    )
    raw_e = _read(
        source,
        "acct_edge_daily",
        "src_acct AS src, dst_acct AS dst, day, txn_count AS count, total_amount AS total",
        where_e,
        load,
    )

    accounts = accounts.sort_values("account_id").reset_index(drop=True)
    attrs = attrs.sort_values("cif").reset_index(drop=True)
    owner = _owner_map(golden, set(attrs["cif"]) | set(accounts["cif"].dropna()))
    frames = _customer_frames(attrs, mapping, accounts, owner)
    transfers = _transfer_frame(raw_t)
    frames["Account"] = _account_frame(accounts, transfers)
    frames["TRANSFERRED_TO"] = transfers
    frames["SENT_TO"] = _daily_frame(raw_e)
    ordered = {name: frames[name].reset_index(drop=True) for name in (*NODE_LABELS, *REL_TYPES)}
    max_ts = None if transfers.empty else transfers["ts"].max().to_pydatetime()
    return Projection(ordered, int(golden["run_id"].iloc[0]), max_ts)


def _plain(value: Any) -> Any:
    if isinstance(value, list | tuple | np.ndarray):
        return [_plain(v) for v in value]
    if value is None or bool(pd.isna(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return value


def to_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Rows as dicts of plain Python values (datetime, date, int, bool, str, list, None)."""
    columns = [str(c) for c in frame.columns]
    return [
        {c: _plain(v) for c, v in zip(columns, row, strict=True)}
        for row in frame.itertuples(index=False, name=None)
    ]


def batches(rows: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    if size < 1:
        raise ValueError("batch size must be >= 1")
    for start in range(0, len(rows), size):
        yield rows[start : start + size]
