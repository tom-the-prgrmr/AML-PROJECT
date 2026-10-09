"""Background transactions: counterparty edge plan, per-channel row builders, id assignment.

The generator first draws, for every CURRENT account, how many distinct counterparties it
must have (the profile's ``counterparties`` range). That target is met by an *undirected edge
plan*: each account gets a few internal edges (a regular circulant graph over a random
permutation of the accounts), at most one edge to its own SAVINGS account, and the remaining
degree as edges to shared ``EXT-`` accounts. Every edge carries at least one transaction and
the leftover budget is spread over existing edges, so counterparty counts are exact by
construction. CASH and CARD transactions are one-sided and never create edges.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRANSACTION_COLUMNS = [
    "txn_id", "txn_ts", "from_account_id", "to_account_id", "amount_vnd", "channel",
    "branch_id", "device_id", "ip", "counterparty_bank", "counterparty_name", "memo",
]  # fmt: skip

INTERNAL_SHARE = 0.4  # target share of a CURRENT account's counterparties that are internal
ONE_SIDED_SHARE = 0.3  # share of the budget spent on CASH / CARD transactions (if affordable)
CASH_SHARE = 0.45  # of the one-sided transactions (rest is CARD, when CARD accounts exist)
OUTBOUND_P = 0.5  # probability the plan's "first" account is the sender
EXT_BANK_P = 0.6  # outbound EXT transfers that use INTERBANK_TRANSFER (rest: EBANKING)
EBANKING_P = 0.35  # share of internal transfers made through e-banking
DEPOSIT_P = 0.6  # share of CASH transactions that are deposits
MIN_EXT_POOL = 2000

EDGE_EXT, EDGE_INTERNAL, EDGE_SAVINGS = 0, 1, 2

BANKS = [
    "Vietcombank", "VietinBank", "BIDV", "Agribank", "Techcombank", "MB Bank", "ACB",
    "VPBank", "Sacombank", "TPBank", "HDBank", "SHB", "OCB", "MSB", "VIB",
]  # fmt: skip
MERCHANTS = [
    "Circle K", "Highlands Coffee", "WinMart", "Bách Hóa Xanh", "Co.opmart", "Grab",
    "Shopee", "Thế Giới Di Động", "Phúc Long", "GS25", "Vincom Cinema", "Petrolimex",
]  # fmt: skip

# channel -> (median VND, lognormal sigma); rounded to whole thousands.
_AMOUNTS = {
    "CASH": (3_000_000, 1.2),
    "CARD": (300_000, 1.0),
    "EBANKING": (2_000_000, 1.3),
    "INTERNAL_TRANSFER": (3_000_000, 1.4),
    "INTERBANK_TRANSFER": (6_000_000, 1.5),
}
_MAX_AMOUNT = 5_000_000_000
# Relative likelihood of each hour of the day (daytime-heavy, quiet at night).
_HOUR_WEIGHTS = np.array(
    [1, 1, 1, 1, 1, 2, 4, 8, 12, 14, 14, 12, 10, 12, 14, 14, 12, 12, 12, 10, 8, 5, 3, 2],
    dtype=float,
)
_HOUR_P = _HOUR_WEIGHTS / _HOUR_WEIGHTS.sum()


@dataclass(frozen=True)
class EdgePlan:
    """Undirected counterparty edges; edge ``k`` links ``a[k]`` with ``b[k]`` or EXT ``ext[k]``."""

    kind: np.ndarray  # EDGE_EXT / EDGE_INTERNAL / EDGE_SAVINGS
    a: np.ndarray  # account row of the CURRENT account (always internal)
    b: np.ndarray  # account row of the other internal side, -1 for EXT edges
    ext: np.ndarray  # index into the EXT pool, -1 for internal edges

    def __len__(self) -> int:
        return len(self.kind)


def ext_account_id(index: int) -> str:
    """Return the id of the ``index``-th external (other-bank) account."""
    return f"EXT-{index:06d}"


def plan_edges(
    current_rows: np.ndarray,
    savings_rows: np.ndarray,
    counterparties: tuple[int, int],
    budget: int,
    rng: np.random.Generator,
) -> EdgePlan:
    """Draw the counterparty edges so each CURRENT account ends with its target degree.

    ``current_rows[i]`` is the account row of the i-th CURRENT account and ``savings_rows[i]``
    the row of its owner's SAVINGS account (``-1`` if none). The degree of account ``i`` is
    ``internal (2 per shift) + savings (0/1) + external`` and is drawn from ``counterparties``.
    ``budget`` (transactions available) makes the internal share adaptive.
    """
    lo, hi = counterparties
    m = len(current_rows)
    targets = rng.integers(lo, hi + 1, size=m)
    max_shifts = max(0, min((lo - 1) // 2, (m - 1) // 2))
    # An internal edge serves two accounts with one transaction, so when the budget is tight
    # (e.g. the dense profile) raise the internal share until the plan fits, up to max_shifts.
    affordable = (1 - ONE_SIDED_SHARE) * budget
    needed = int(np.ceil((targets.sum() - affordable) / m))  # edges = sum(targets) - m * shifts
    n_shifts = min(max_shifts, max(1 if max_shifts else 0, int(INTERNAL_SHARE * lo) // 2, needed))
    has_sav = savings_rows >= 0
    ext_degree = targets - 2 * n_shifts - has_sav

    # Internal edges: node perm[j] is linked to perm[j + s] for each chosen shift s; distinct
    # shifts below m/2 never repeat an edge and add exactly 2 to every node's degree.
    perm = current_rows[rng.permutation(m)]
    shifts = rng.choice(np.arange(1, (m - 1) // 2 + 1), size=n_shifts, replace=False)
    int_a = np.concatenate([perm] * n_shifts) if n_shifts else np.empty(0, dtype=np.int64)
    int_b = np.concatenate([np.roll(perm, -int(s)) for s in shifts]) if n_shifts else int_a

    # External edges: each account picks its own distinct EXT ids from a shared pool.
    pool = max(MIN_EXT_POOL, 3 * hi)
    ext_a = np.repeat(current_rows, ext_degree)
    picks = [rng.choice(pool, size=int(k), replace=False) for k in ext_degree if k > 0]
    ext_x = np.concatenate(picks) if picks else np.empty(0, dtype=np.int64)

    sav_a, sav_b = current_rows[has_sav], savings_rows[has_sav]
    n_int, n_sav, n_ext = len(int_a), len(sav_a), len(ext_a)
    return EdgePlan(
        kind=np.repeat(
            np.array([EDGE_INTERNAL, EDGE_SAVINGS, EDGE_EXT], dtype=np.int8), [n_int, n_sav, n_ext]
        ),
        a=np.concatenate([int_a, sav_a, ext_a]).astype(np.int64),
        b=np.concatenate([int_b, sav_b, np.full(n_ext, -1)]).astype(np.int64),
        ext=np.concatenate([np.full(n_int + n_sav, -1), ext_x]).astype(np.int64),
    )


def _timestamps(
    n: int, window: tuple[pd.Timestamp, pd.Timestamp], rng: np.random.Generator
) -> np.ndarray:
    """Draw ``n`` naive local timestamps in ``[window[0], window[1])``, daytime-heavy."""
    start, end = window
    days = rng.integers(0, (end - start).days, size=n)
    hours = rng.choice(24, size=n, p=_HOUR_P)
    seconds = days * 86_400 + hours * 3_600 + rng.integers(0, 3_600, size=n)
    return (start + pd.to_timedelta(seconds, unit="s")).to_numpy()


def _amounts(channels: np.ndarray, cash_cap: int, rng: np.random.Generator) -> np.ndarray:
    """Lognormal VND amounts per channel, whole thousands; CASH stays below ``cash_cap``."""
    amounts = np.empty(len(channels), dtype=np.int64)
    for channel, (median, sigma) in _AMOUNTS.items():
        pos = np.flatnonzero(channels == channel)
        raw = rng.lognormal(np.log(median), sigma, size=len(pos))
        amounts[pos] = np.clip(np.round(raw / 1000) * 1000, 1000, _MAX_AMOUNT).astype(np.int64)
    cash = channels == "CASH"
    amounts[cash] = np.minimum(amounts[cash], max(1000, (cash_cap - 1) // 1000 * 1000))
    return amounts


def _two_sided_rows(
    plan: EdgePlan, edge_idx: np.ndarray, ids: np.ndarray, owner_device: np.ndarray,
    owner_ip: np.ndarray, rng: np.random.Generator,
) -> pd.DataFrame:  # fmt: skip
    """Rows for transfers over the planned edges ``edge_idx`` (INTERNAL / INTERBANK / EBANKING)."""
    n = len(edge_idx)
    a, b, x, kind = plan.a[edge_idx], plan.b[edge_idx], plan.ext[edge_idx], plan.kind[edge_idx]
    is_ext = kind == EDGE_EXT
    a_sends = rng.random(n) < OUTBOUND_P
    u = rng.random(n)
    # An EXT account never sends through EBANKING, so only outbound EXT rows may use it.
    channel = np.where(
        is_ext,
        np.where(a_sends & (u >= EXT_BANK_P), "EBANKING", "INTERBANK_TRANSFER"),
        np.where(u < EBANKING_P, "EBANKING", "INTERNAL_TRANSFER"),
    ).astype(object)

    ext_names = np.array([ext_account_id(k) for k in range(max(int(x.max()), 0) + 1)], dtype=object)
    other = np.where(is_ext, ext_names[np.maximum(x, 0)], ids[np.maximum(b, 0)])
    mine = ids[a]
    sender_row = np.where(a_sends | is_ext, a, b)  # internal row of the sender (EBANKING only)
    web = channel == "EBANKING"
    banks = np.array(BANKS, dtype=object)[np.maximum(x, 0) % len(BANKS)]
    return pd.DataFrame(
        {
            "from_account_id": np.where(a_sends, mine, other),
            "to_account_id": np.where(a_sends, other, mine),
            "channel": channel,
            "branch_id": None,
            "device_id": np.where(web, owner_device[sender_row], None),
            "ip": np.where(web, owner_ip[sender_row], None),
            "counterparty_bank": np.where(is_ext, banks, None),
            "counterparty_name": None,
        }
    )


def _one_sided_rows(
    channel: str, rows: np.ndarray, ids: np.ndarray, branches: np.ndarray, rng: np.random.Generator
) -> pd.DataFrame:
    """CASH (deposit or withdrawal at the account's branch) or CARD (merchant spend) rows."""
    n = len(rows)
    mine = ids[rows]
    empty = np.full(n, None, dtype=object)
    if channel == "CASH":
        deposit = rng.random(n) < DEPOSIT_P
        sender, receiver = np.where(deposit, None, mine), np.where(deposit, mine, None)
        branch, merchant = branches[rows], empty
    else:
        sender, receiver, branch = mine, empty, empty
        merchant = np.array(MERCHANTS, dtype=object)[rng.integers(len(MERCHANTS), size=n)]
    return pd.DataFrame(
        {
            "from_account_id": sender,
            "to_account_id": receiver,
            "channel": channel,
            "branch_id": branch,
            "device_id": None,
            "ip": None,
            "counterparty_bank": None,
            "counterparty_name": merchant,
        }
    )


def build_background(
    accounts: pd.DataFrame,
    customers: pd.DataFrame,
    budget: int,
    counterparties: tuple[int, int],
    window: tuple[pd.Timestamp, pd.Timestamp],
    cash_cap: int,
    rng: np.random.Generator,
    excluded_accounts: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Build ``budget`` background transactions (without ``txn_id`` and ``memo``).

    ``excluded_accounts`` is the seam for typology injection: every account of a customer that
    owns an excluded account is left out of the plan, so scenario accounts carry no background
    traffic. ``cash_cap`` bounds background CASH amounts (exclusive). Raises ``ValueError`` if
    the counterparty plan alone needs more than ``budget`` transactions.
    """
    ids = accounts["account_id"].to_numpy(dtype=object)
    types = accounts["account_type"].to_numpy(dtype=object)
    cifs = accounts["cif"].to_numpy(dtype=object)
    banned = set(accounts.loc[accounts["account_id"].isin(excluded_accounts), "cif"])
    keep = ~accounts["cif"].isin(banned).to_numpy()
    cust = customers.set_index("cif")
    owner_device = accounts["cif"].map(cust["device_id"]).to_numpy(dtype=object)
    owner_ip = accounts["cif"].map(cust["ip"]).to_numpy(dtype=object)

    current = np.flatnonzero(keep & (types == "CURRENT"))
    if len(current) == 0:
        raise ValueError("no CURRENT account available for background transactions")
    sav_mask = keep & (types == "SAVINGS")
    sav_lookup = pd.Series(np.flatnonzero(sav_mask), index=cifs[sav_mask])
    savings = sav_lookup.reindex(cifs[current]).fillna(-1).to_numpy(dtype=np.int64)

    plan = plan_edges(current, savings, counterparties, budget, rng)
    if len(plan) > budget:
        raise ValueError(
            f"n_transactions too small: the counterparty plan needs {len(plan)} transactions "
            f"but only {budget} are available"
        )
    cards = np.flatnonzero(keep & (types == "CARD"))
    n_one = min(round(ONE_SIDED_SHARE * budget), budget - len(plan))
    n_cash = round(CASH_SHARE * n_one) if len(cards) else n_one
    n_card = n_one - n_cash

    # Every edge once, then the remaining two-sided budget spread over edges (heavy-tailed).
    weights = rng.lognormal(0.0, 1.0, size=len(plan))
    extra = rng.choice(len(plan), size=budget - n_one - len(plan), p=weights / weights.sum())
    edge_idx = np.concatenate([np.arange(len(plan)), extra])
    parts = [_two_sided_rows(plan, edge_idx, ids, owner_device, owner_ip, rng)]
    branches = accounts["branch_id"].to_numpy(dtype=object)
    if n_cash:
        parts.append(_one_sided_rows("CASH", rng.choice(current, size=n_cash), ids, branches, rng))
    if n_card:
        parts.append(_one_sided_rows("CARD", rng.choice(cards, size=n_card), ids, branches, rng))
    frame = pd.concat(parts, ignore_index=True)
    frame.insert(0, "txn_ts", _timestamps(len(frame), window, rng))
    frame.insert(3, "amount_vnd", _amounts(frame["channel"].to_numpy(dtype=object), cash_cap, rng))
    return frame


def assign_txn_ids(frame: pd.DataFrame, first: int) -> pd.DataFrame:
    """Return ``frame`` sorted by time with sequential ``txn_id`` values from ``first``."""
    out = frame.sort_values("txn_ts", kind="stable").reset_index(drop=True)
    out.insert(0, "txn_id", [f"T{k:010d}" for k in range(first, first + len(out))])
    return out
