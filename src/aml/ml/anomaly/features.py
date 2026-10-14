"""Behaviour features per customer and calendar month. Pure: no database, no clock.

One sample is a (cif, calendar month) with at least one transaction leg of the customer (an IN or
OUT side of a transaction on one of the customer's own accounts). Ten features describe the
month, three of them against the customer's own baseline before the month, and four come from
the network features of Phase 5c / 6 (one snapshot, the same for every month of a customer). All
of it is vectorised pandas / NumPy: a loop over customers takes over a minute on `small`.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from aml.common.config import AnomalyConfig

ANOMALY_VERSION = "anomaly/v1"  # feature definitions + algorithm + thresholds
ANOMALY_FEATURES = (
    "txns_per_day", "max_txns_day", "amount_log", "cash_ratio", "counterparties", "night_ratio",
    "pass_through", "amount_dev", "txn_dev", "new_counterparty_ratio",
    "in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size",
)  # fmt: skip
GRAPH_FEATURES = ("in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size")
LEG_COLUMNS = (
    "cif", "account_id", "txn_id", "txn_ts", "direction", "amount_vnd", "counterparty_id",
    "channel",
)  # fmt: skip
SAMPLE_COLUMNS = (
    "cif", "month", "window_start", "window_end", "first_ts", "last_ts", "txn_count", "amount_vnd",
    "accounts",
)  # fmt: skip
FEATURE_DOCS: dict[str, str] = {
    "txns_per_day": "Transaction legs of the customer in the month per day of the window.",
    "max_txns_day": "Most transaction legs of the customer on one calendar day of the month.",
    "amount_log": "log10(1 + total VND of all legs of the customer in the month).",
    "cash_ratio": "Share of the month's VND that moved through the CASH channel.",
    "counterparties": "Distinct known counterparty accounts of the customer in the month.",
    "night_ratio": "Share of the month's legs made at night (hour >= start or < end).",
    "pass_through": "min(money in, money out) / max(money in, money out) in the month.",
    "amount_dev": "log10 of daily VND in the month over daily VND in the own baseline.",
    "txn_dev": "log10 of daily legs in the month over daily legs in the own baseline.",
    "new_counterparty_ratio": "Share of the month's counterparties absent from the own baseline.",
    "in_degree": "Largest in-degree among the customer's accounts in the graph snapshot.",
    "out_degree": "Largest out-degree among the customer's accounts in the graph snapshot.",
    "pagerank_ratio": "Largest PageRank ratio among the customer's accounts in the snapshot.",
    "shared_cluster_size": "Largest shared-attribute cluster among the customer's accounts.",
}

_ORDINAL_BASE = 1 << 20  # (entity, day) -> entity * base + day number; a day number stays far below
_DECIMALS = 10


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=[*SAMPLE_COLUMNS, *ANOMALY_FEATURES])


def _day_numbers(days: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    """Days since 1970-01-01 as int64."""
    return np.asarray(days).astype("datetime64[D]").astype(np.int64)


def _prepare(legs: pd.DataFrame, start_date: date, as_of: date, cfg: AnomalyConfig) -> pd.DataFrame:
    """The legs inside the months under review, with the per-leg columns the features sum up."""
    first_month = pd.Period(start_date, freq="M").start_time
    cutoff = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    frame = legs[list(LEG_COLUMNS)].copy()
    frame["txn_ts"] = pd.to_datetime(frame["txn_ts"])
    frame["amount"] = pd.to_numeric(frame["amount_vnd"]).astype("float64")
    frame = frame[(frame["txn_ts"] >= first_month) & (frame["txn_ts"] < cutoff)]
    frame = frame[frame["cif"].notna()].reset_index(drop=True)
    hour = frame["txn_ts"].dt.hour
    frame["month"] = frame["txn_ts"].dt.strftime("%Y-%m")
    frame["day"] = frame["txn_ts"].dt.normalize()
    frame["cash"] = frame["amount"].where(frame["channel"] == "CASH", 0.0)
    frame["night"] = ((hour >= cfg.night_start_hour) | (hour < cfg.night_end_hour)).astype("int64")
    frame["inflow"] = frame["amount"].where(frame["direction"] == "IN", 0.0)
    frame["outflow"] = frame["amount"].where(frame["direction"] == "OUT", 0.0)
    return frame


def _sample_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Per (cif, month): time span, leg totals, distinct transactions, accounts, counterparties."""
    keys = ["cif", "month"]
    s = frame.groupby(keys, sort=True).agg(
        first_ts=("txn_ts", "min"),
        last_ts=("txn_ts", "max"),
        legs=("txn_id", "size"),
        total=("amount", "sum"),
        cash=("cash", "sum"),
        night=("night", "sum"),
        inflow=("inflow", "sum"),
        outflow=("outflow", "sum"),
    )
    # a transfer between two accounts of one customer has two legs but is one transaction
    txns = (
        frame.drop_duplicates([*keys, "txn_id"])
        .groupby(keys)
        .agg(txn_count=("txn_id", "size"), amount_vnd=("amount", "sum"))
    )
    s["txn_count"] = txns["txn_count"].astype("int64")
    s["amount_vnd"] = txns["amount_vnd"].round().astype("int64")
    s["max_txns_day"] = frame.groupby([*keys, "day"]).size().groupby(level=keys).max()
    known = frame.dropna(subset=["counterparty_id"])
    s["counterparties"] = known.groupby(keys)["counterparty_id"].nunique().reindex(s.index)
    s["counterparties"] = s["counterparties"].fillna(0)
    accounts = frame.drop_duplicates([*keys, "account_id"]).sort_values("account_id")
    s["accounts"] = accounts.groupby(keys)["account_id"].agg(list)
    return s


def _window_sums(
    keys: np.ndarray, cumulative: np.ndarray, entity: np.ndarray, lo: np.ndarray, hi: np.ndarray
) -> np.ndarray:
    """Sum of the per-day values of ``entity`` for day numbers in [lo, hi)."""
    first = np.searchsorted(keys, entity * _ORDINAL_BASE + lo, side="left")
    last = np.searchsorted(keys, entity * _ORDINAL_BASE + hi, side="left")
    return cumulative[last] - cumulative[first]


def _baseline_legs(
    frame: pd.DataFrame, s: pd.DataFrame, lo: np.ndarray, hi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Legs and VND of every sample's customer in [lo, hi) (day numbers), from daily totals."""
    daily = frame.groupby(["cif", "day"]).agg(legs=("txn_id", "size"), amount=("amount", "sum"))
    cif_codes = pd.Index(sorted(frame["cif"].unique()))
    entity = cif_codes.get_indexer(daily.index.get_level_values("cif")).astype(np.int64)
    keys = entity * _ORDINAL_BASE + _day_numbers(daily.index.get_level_values("day"))
    order = np.argsort(keys, kind="stable")
    legs = np.concatenate([[0], np.cumsum(daily["legs"].to_numpy()[order])])
    amount = np.concatenate([[0.0], np.cumsum(daily["amount"].to_numpy()[order])])
    sample_cif = cif_codes.get_indexer(s.index.get_level_values("cif")).astype(np.int64)
    sorted_keys = keys[order]
    return (
        _window_sums(sorted_keys, legs, sample_cif, lo, hi).astype("float64"),
        _window_sums(sorted_keys, amount, sample_cif, lo, hi),
    )


def _new_counterparty_ratio(
    frame: pd.DataFrame, s: pd.DataFrame, lo: np.ndarray, hi: np.ndarray
) -> np.ndarray:
    """Share of each sample's counterparties with no leg with the same customer in [lo, hi)."""
    known = frame.dropna(subset=["counterparty_id"]).copy()
    ratio = np.zeros(len(s))
    if known.empty:
        return ratio
    known["pair"] = known.groupby(["cif", "counterparty_id"], sort=False).ngroup().astype("int64")
    daily = known.drop_duplicates(["pair", "day"])
    seen_keys = np.sort(daily["pair"].to_numpy() * _ORDINAL_BASE + _day_numbers(daily["day"]))
    pairs = known.drop_duplicates(["cif", "month", "pair"])
    at = s.index.get_indexer(pd.MultiIndex.from_frame(pairs[["cif", "month"]]))
    pair = pairs["pair"].to_numpy()
    before = np.searchsorted(seen_keys, pair * _ORDINAL_BASE + lo[at], side="left")
    after = np.searchsorted(seen_keys, pair * _ORDINAL_BASE + hi[at], side="left")
    unseen = np.bincount(at, weights=(after == before).astype("float64"), minlength=len(s))
    total = np.bincount(at, minlength=len(s)).astype("float64")
    return np.divide(unseen, total, out=ratio, where=total > 0)


def _graph_columns(frame: pd.DataFrame, s: pd.DataFrame, graph: pd.DataFrame) -> pd.DataFrame:
    """MAX of each graph feature over the accounts of the customer, the same for every month.

    The graph is one snapshot, so a month does not select accounts: every account of the customer
    that has a leg in the months under review counts.
    """
    out = pd.DataFrame(0.0, index=s.index, columns=list(GRAPH_FEATURES))
    if graph.index.name == "account_id":
        graph = graph.reset_index()
    present = [c for c in GRAPH_FEATURES if c in graph.columns]
    if graph.empty or "account_id" not in graph.columns or not present:
        return out
    # accounts with a graph row but no leg before the cutoff are ignored
    owned = frame.drop_duplicates(["cif", "account_id"])[["cif", "account_id"]]
    values = graph[["account_id", *present]].copy()
    values[present] = values[present].apply(pd.to_numeric).astype("float64")
    best = owned.merge(values, on="account_id", how="left").groupby("cif")[present].max()
    out[present] = best.reindex(s.index.get_level_values("cif")).fillna(0.0).to_numpy()
    return out


def build_samples(
    legs: pd.DataFrame, graph: pd.DataFrame, *, as_of: date, start_date: date, cfg: AnomalyConfig
) -> pd.DataFrame:
    """One row per (cif, month) with a leg: `SAMPLE_COLUMNS` then `ANOMALY_FEATURES`.

    The months run from the month of ``start_date`` to the month of ``as_of``; the window of the
    last month stops at the end of ``as_of``. ``graph`` has an ``account_id`` (column or index)
    and any of `GRAPH_FEATURES`; an account without a row, or an empty frame, gives 0.
    """
    frame = _prepare(legs, start_date, as_of, cfg)
    if frame.empty:
        return _empty()
    s = _sample_table(frame)
    cutoff = pd.Timestamp(as_of) + pd.Timedelta(days=1)
    months = pd.PeriodIndex(s.index.get_level_values("month"), freq="M")
    start = months.start_time
    end = pd.DatetimeIndex(np.minimum((months + 1).start_time.values, cutoff.to_datetime64()))
    window_days = np.asarray((end - start).days, dtype="float64")
    base_start = start - pd.Timedelta(days=cfg.baseline_days)
    base_start = base_start.where(base_start >= pd.Timestamp(start_date), pd.Timestamp(start_date))
    base_start = base_start.where(base_start <= start, start)  # a mid-month start_date
    base_days = np.asarray((start - base_start).days, dtype="float64")
    lo, hi = _day_numbers(base_start), _day_numbers(start)
    legs_b, amount_b = _baseline_legs(frame, s, lo, hi)
    judged = (base_days >= cfg.min_baseline_days) & (base_days > 0)  # else no baseline to compare
    per_day = np.where(judged, base_days, 1.0)

    total, count = s["total"].to_numpy(), s["legs"].to_numpy().astype("float64")
    biggest = np.maximum(s["inflow"].to_numpy(), s["outflow"].to_numpy())
    smallest = np.minimum(s["inflow"].to_numpy(), s["outflow"].to_numpy())
    zeros = np.zeros(len(s))
    amount_dev = np.log10((1 + total / window_days) / (1 + amount_b / per_day))
    txn_dev = np.log10((1 + count / window_days) / (1 + legs_b / per_day))
    features = pd.DataFrame(
        {
            "txns_per_day": count / window_days,
            "max_txns_day": s["max_txns_day"].to_numpy().astype("float64"),
            "amount_log": np.log10(1 + total),
            "cash_ratio": np.divide(s["cash"].to_numpy(), total, out=zeros.copy(), where=total > 0),
            "counterparties": s["counterparties"].to_numpy().astype("float64"),
            "night_ratio": s["night"].to_numpy() / count,
            "pass_through": np.divide(smallest, biggest, out=zeros.copy(), where=biggest > 0),
            "amount_dev": np.where(judged, amount_dev, 0.0),
            "txn_dev": np.where(judged, txn_dev, 0.0),
            "new_counterparty_ratio": np.where(
                judged, _new_counterparty_ratio(frame, s, lo, hi), 0.0
            ),
        },
        index=s.index,
    ).join(_graph_columns(frame, s, graph))
    out = pd.DataFrame(
        {
            "window_start": start,
            "window_end": end,
            "first_ts": s["first_ts"],
            "last_ts": s["last_ts"],
            "txn_count": s["txn_count"],
            "amount_vnd": s["amount_vnd"],
            "accounts": s["accounts"],
        },
        index=s.index,
    ).join(features[list(ANOMALY_FEATURES)].round(_DECIMALS))
    return out.reset_index()[[*SAMPLE_COLUMNS, *ANOMALY_FEATURES]]


def feature_matrix(samples: pd.DataFrame) -> pd.DataFrame:
    """The 14 feature columns of `build_samples`, indexed by (cif, month), as floats."""
    return samples.set_index(["cif", "month"])[list(ANOMALY_FEATURES)].astype("float64")
