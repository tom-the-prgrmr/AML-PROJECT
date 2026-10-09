"""Shared pieces for the typology builders: context, scenario record, account pool, row helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

ROW_COLUMNS = [
    "txn_ts", "from_account_id", "to_account_id", "amount_vnd", "channel", "branch_id",
    "device_id", "ip", "counterparty_bank", "counterparty_name", "memo",
]  # fmt: skip
# Typology transfers use only channels that may carry an injected memo.
TRANSFER_CHANNELS = ("INTERNAL_TRANSFER", "EBANKING")
N_BRANCHES = 50
DAY_SECONDS = 86_400
HOUR_SECONDS = 3_600


@dataclass(frozen=True)
class TypologyContext:
    """Window and thresholds shared by every builder."""

    window_start: pd.Timestamp
    window_end: pd.Timestamp  # exclusive
    months: int
    large_cash_vnd: int
    structuring_band_pct: float


@dataclass
class Scenario:
    """One injected scenario: its accounts with roles, its evidence rows and its label text."""

    scenario_id: str
    typology: str
    is_suspicious: bool
    accounts: list[tuple[str, str]]  # (account_id, role)
    rows: pd.DataFrame  # ROW_COLUMNS; one row per evidence transaction
    reason: str
    linked_cifs: tuple[str, ...] = field(
        default_factory=tuple
    )  # mule ring: cifs sharing attributes


class AccountPool:
    """Shuffled CURRENT accounts, one per real person; every account is handed out once."""

    def __init__(self, account_ids: list[str], cif_of: dict[str, str]) -> None:
        self._ids = account_ids
        self._cif_of = cif_of
        self._next = 0

    def __len__(self) -> int:
        return len(self._ids)

    def take(self, n: int) -> list[str]:
        """Return ``n`` unused accounts or raise ``ValueError`` ("not enough accounts")."""
        if self._next + n > len(self._ids):
            raise ValueError(
                f"not enough accounts: the typology scenarios need more distinct-person "
                f"CURRENT accounts than the {len(self._ids)} available"
            )
        taken = self._ids[self._next : self._next + n]
        self._next += n
        return taken

    def cif(self, account_id: str) -> str:
        """Return the owning cif of a pool account."""
        return self._cif_of[account_id]


def round_k(value: float) -> int:
    """Round down to whole thousands of VND."""
    return int(value) // 1000 * 1000


def split_amount(total: int, parts: int, rng: np.random.Generator) -> list[int]:
    """Split ``total`` (a multiple of 1000) into ``parts`` positive thousands that sum to it."""
    weights = 0.5 / parts + 0.5 * rng.dirichlet(np.ones(parts))
    shares = [max(1000, round_k(total * float(w))) for w in weights[:-1]]
    return [*shares, total - sum(shares)]


def random_start(ctx: TypologyContext, rng: np.random.Generator, span_days: int) -> pd.Timestamp:
    """Pick a start (daytime) so that ``span_days`` more days still fit in the window."""
    total_days = (ctx.window_end - ctx.window_start).days
    offset = int(rng.integers(0, max(1, total_days - span_days)))
    return ctx.window_start + pd.Timedelta(days=offset, hours=int(rng.integers(8, 17)))


def make_row(
    ts: pd.Timestamp,
    source: str | None,
    target: str | None,
    amount: int,
    channel: str,
    *,
    memo: str | None = None,
    branch_id: str | None = None,
) -> dict[str, object]:
    """Return one transaction row with the typology column set."""
    return {
        "txn_ts": ts,
        "from_account_id": source,
        "to_account_id": target,
        "amount_vnd": int(amount),
        "channel": channel,
        "branch_id": branch_id,
        "device_id": None,
        "ip": None,
        "counterparty_bank": None,
        "counterparty_name": None,
        "memo": memo,
    }


def rows_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    """Build the evidence frame with the dtypes of the background transactions."""
    frame = pd.DataFrame(rows, columns=ROW_COLUMNS)
    frame["txn_ts"] = frame["txn_ts"].astype("datetime64[ns]")
    frame["amount_vnd"] = frame["amount_vnd"].astype("int64")
    return frame


def pick_channel(rng: np.random.Generator) -> str:
    """Pick one of ``TRANSFER_CHANNELS`` at random."""
    return TRANSFER_CHANNELS[int(rng.integers(len(TRANSFER_CHANNELS)))]
