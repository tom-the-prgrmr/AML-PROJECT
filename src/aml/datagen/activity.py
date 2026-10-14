"""Accounts, background transactions and injected typologies (specs 1b-i and 1b-ii).

``generate_activity`` builds accounts, injects the typology scenarios (1b-ii), plans
counterparties and draws background transactions around them, plants prompt-injection memos
and duplicate transactions (a DQ defect), and returns every table in one ``ActivityData``.
With all typology counts at 0 the output is the plain 1b-i data and ``ground_truth`` is empty.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from aml.common.config import RiskMemoConfig
from aml.datagen.accounts import build_accounts
from aml.datagen.memos import (
    INJECTABLE_CHANNELS,
    INJECTION_PHRASES,
    generate_memos,
    inject_prompt_injections,
    plant_risk_memos,
)
from aml.datagen.rng import table_rng
from aml.datagen.transactions import (
    TRANSACTION_COLUMNS,
    assign_txn_ids,
    build_background,
)
from aml.datagen.typologies import (
    SCENARIO_TAG,
    TypologyContext,
    TypologyResult,
    ground_truth_records,
    inject_typologies,
)

if TYPE_CHECKING:
    from aml.common.config import Settings
    from aml.datagen.customers import CustomerTables

__all__ = [
    "GROUND_TRUTH_COLUMNS",
    "INJECTION_PHRASES",
    "ActivityData",
    "TxnGenParams",
    "generate_activity",
]

GROUND_TRUTH_COLUMNS = [
    "scenario_id", "typology", "is_suspicious", "entity_type", "entity_id", "role",
    "start_ts", "end_ts", "reason",
]  # fmt: skip
DQ_LABEL_COLUMNS = ["entity_type", "entity_id", "defect_type", "detail"]
TYPOLOGY_KEYS = (
    "structuring", "rapid_movement", "mule_ring", "round_tripping",
    "benign_payroll", "benign_merchant",
)  # fmt: skip
REQUIRED_CUSTOMER_COLUMNS = ("cif", "device_id", "ip")


@dataclass(frozen=True)
class TxnGenParams:
    """Everything the activity generator needs besides the customers and the seed."""

    n_transactions: int  # background + typology transactions, excluding DQ duplicates
    months: int  # calendar months in the window [start_date, start_date + months)
    counterparties: tuple[int, int]  # min / max distinct counterparties per CURRENT account
    start_date: date
    large_cash_vnd: int
    structuring_band_pct: float
    duplicate_rate: float  # DQ: extra duplicated transactions = round(rate * n_transactions)
    injection_memos: int  # prompt-injection memos planted in background transactions
    typology_counts: dict[str, int]  # scenarios per typology (spec 1b-ii)
    risk_memo_background_rate: float = 0.0  # gambling/crypto memos (spec datagen-memos); 0 = off
    risk_memo_typology_rate: float = 0.0
    risk_memo_gambling_share: float = 0.5

    @classmethod
    def from_settings(cls, settings: Settings) -> TxnGenParams:
        """Map the active data profile, thresholds and DQ rates of ``settings``."""
        profile = settings.data.active
        return cls(
            n_transactions=profile.transactions,
            months=profile.months,
            counterparties=profile.counterparties,
            start_date=settings.data.start_date,
            large_cash_vnd=settings.thresholds.large_cash_vnd,
            structuring_band_pct=settings.thresholds.structuring_band_pct,
            duplicate_rate=settings.data.dq_defect_rate,
            injection_memos=settings.data.injection_memos,
            typology_counts={
                k: settings.data.typologies.get(k, 0) * profile.typology_scale
                for k in TYPOLOGY_KEYS
            },
            risk_memo_background_rate=settings.data.risk_memos.background_rate,
            risk_memo_typology_rate=settings.data.risk_memos.typology_rate,
            risk_memo_gambling_share=settings.data.risk_memos.gambling_share,
        )


@dataclass(frozen=True)
class ActivityData:
    """Output of ``generate_activity`` (one DataFrame per table)."""

    customers: pd.DataFrame  # copy of the input; mule-ring members get shared attributes
    accounts: pd.DataFrame
    transactions: pd.DataFrame
    ground_truth: pd.DataFrame  # typology and prompt-injection labels (empty without typologies)
    dq_labels: pd.DataFrame  # duplicate-transaction labels


def _validate(tables: CustomerTables, params: TxnGenParams) -> None:
    customers = tables.customers
    missing = [c for c in REQUIRED_CUSTOMER_COLUMNS if c not in customers.columns]
    if missing:
        raise ValueError(f"customers is missing required column(s): {', '.join(missing)}")
    if customers.empty:
        raise ValueError("customers is empty")
    lo, hi = params.counterparties
    if not 1 <= lo <= hi:
        raise ValueError(
            f"counterparties must satisfy 1 <= min <= max, got {params.counterparties}"
        )
    if params.months < 1:
        raise ValueError(f"months must be >= 1, got {params.months}")
    if params.n_transactions < 0 or params.injection_memos < 0:
        raise ValueError("n_transactions and injection_memos must be >= 0")
    if not 0.0 <= params.duplicate_rate <= 1.0:
        raise ValueError(f"duplicate_rate must be in [0, 1], got {params.duplicate_rate}")
    if any(params.typology_counts.get(k, 0) < 0 for k in TYPOLOGY_KEYS):
        raise ValueError("typology_counts must be >= 0")


def _ground_truth_frame(records: list[dict[str, object]]) -> pd.DataFrame:
    """Build the ground_truth table (final column order and dtypes) from record dicts."""
    frame = pd.DataFrame(records, columns=GROUND_TRUTH_COLUMNS)
    return frame.astype(
        {
            "scenario_id": object, "typology": object, "is_suspicious": bool,
            "entity_type": object, "entity_id": object, "role": object,
            "start_ts": "datetime64[ns]", "end_ts": "datetime64[ns]", "reason": object,
        }
    )  # fmt: skip


def _duplicate_transactions(
    base: pd.DataFrame, eligible: np.ndarray, params: TxnGenParams, rng: np.random.Generator
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Copy ``round(rate * n)`` eligible base rows under new ids; return (copies, dq labels)."""
    n_dup = round(params.duplicate_rate * params.n_transactions)
    if n_dup > len(eligible):
        raise ValueError(f"cannot duplicate {n_dup} transactions: only {len(eligible)} eligible")
    origins = base.iloc[np.sort(rng.choice(eligible, size=n_dup, replace=False))]
    copies = origins.copy()
    first = len(base) + 1
    copies["txn_id"] = [f"T{k:010d}" for k in range(first, first + n_dup)]
    labels = pd.DataFrame(
        {
            "entity_type": "transaction",
            "entity_id": copies["txn_id"].to_numpy(),
            "defect_type": "DUPLICATE_TRANSACTION",
            "detail": origins["txn_id"].to_numpy(),
        }
    )[DQ_LABEL_COLUMNS]
    return copies, labels.reset_index(drop=True)


def _typology_context(
    params: TxnGenParams, window: tuple[pd.Timestamp, pd.Timestamp]
) -> TypologyContext:
    return TypologyContext(
        window_start=window[0],
        window_end=window[1],
        months=params.months,
        large_cash_vnd=params.large_cash_vnd,
        structuring_band_pct=params.structuring_band_pct,
    )


def generate_activity(tables: CustomerTables, params: TxnGenParams, seed: int) -> ActivityData:
    """Generate accounts, transactions, typologies and labels for ``tables``, deterministically."""
    _validate(tables, params)
    customers = tables.customers
    start = pd.Timestamp(params.start_date)
    window = (start, start + pd.DateOffset(months=params.months))

    accounts = build_accounts(customers, table_rng(seed, "accounts"), params.start_date)

    typology: TypologyResult | None = None
    if any(params.typology_counts.get(k, 0) for k in TYPOLOGY_KEYS):
        typology = inject_typologies(
            accounts,
            customers,
            tables.customer_person,
            params.typology_counts,
            _typology_context(params, window),
            table_rng(seed, "ground_truth"),
        )
        if len(typology.rows) >= params.n_transactions:
            raise ValueError(
                f"n_transactions={params.n_transactions} cannot hold the "
                f"{len(typology.rows)} typology transactions plus background traffic"
            )
    n_typology = 0 if typology is None else len(typology.rows)

    rng = table_rng(seed, "transactions")
    # Background CASH must stay out of the structuring band [large_cash * (1 - band), large_cash).
    cash_cap = int(params.large_cash_vnd * (1 - params.structuring_band_pct))
    background = build_background(
        accounts,
        customers,
        params.n_transactions - n_typology,
        params.counterparties,
        window,
        cash_cap,
        rng,
        frozenset() if typology is None else typology.accounts,
    )
    memo_rng = table_rng(seed, "transactions.memos")  # own stream: independent of the plan
    background["memo"] = generate_memos(background["channel"].to_numpy(dtype=object), memo_rng)
    background[SCENARIO_TAG] = None
    frame = background
    if typology is not None:
        frame = pd.concat([background, typology.rows], ignore_index=True)

    channels = frame["channel"].to_numpy(dtype=object)
    memo = frame["memo"].to_numpy(dtype=object, copy=True)
    injected = np.zeros(len(frame), dtype=bool)
    count = params.injection_memos
    if typology is not None and count > 0:
        # At least one injection sits on a suspicious scenario's transaction (own stream).
        suspicious = {s.scenario_id for s in typology.scenarios if s.is_suspicious}
        on_suspicious = frame[SCENARIO_TAG].isin(suspicious).to_numpy()
        if (on_suspicious & np.isin(channels, INJECTABLE_CHANNELS)).any():
            pick_rng = table_rng(seed, "ground_truth.injection")
            injected[inject_prompt_injections(memo, channels, ~on_suspicious, 1, pick_rng)] = True
            count -= 1
    injected[inject_prompt_injections(memo, channels, injected, count, memo_rng)] = True
    suspicious_rows = np.zeros(len(frame), dtype=bool)
    if typology is not None:
        suspicious_ids = {s.scenario_id for s in typology.scenarios if s.is_suspicious}
        suspicious_rows = frame[SCENARIO_TAG].isin(suspicious_ids).to_numpy(dtype=bool)
    plant_risk_memos(
        memo,
        channels,
        frame[SCENARIO_TAG].isna().to_numpy(dtype=bool),
        suspicious_rows,
        injected,
        RiskMemoConfig(
            background_rate=params.risk_memo_background_rate,
            typology_rate=params.risk_memo_typology_rate,
            gambling_share=params.risk_memo_gambling_share,
        ),
        table_rng(seed, "transactions.memos.risk"),  # own stream: no existing stream is touched
    )
    frame["memo"] = memo
    frame["injected"] = injected  # keeps the flag aligned through the time sort

    base = assign_txn_ids(frame, first=1)
    # Duplicates copy only background rows without an injection.
    eligible = np.flatnonzero(~base["injected"].to_numpy() & base[SCENARIO_TAG].isna().to_numpy())
    copies, dq_labels = _duplicate_transactions(
        base, eligible, params, table_rng(seed, "transactions.dq")
    )
    transactions = (
        pd.concat([base, copies], ignore_index=True)
        .sort_values("txn_ts", kind="stable")
        .reset_index(drop=True)[TRANSACTION_COLUMNS]
    )
    records: list[dict[str, object]] = []
    if typology is not None:
        records = ground_truth_records(
            typology.scenarios, base, base[base["injected"].to_numpy(dtype=bool)]
        )
    return ActivityData(
        customers=customers.copy() if typology is None else typology.customers,
        accounts=accounts,
        transactions=transactions,
        ground_truth=_ground_truth_frame(records),
        dq_labels=dq_labels,
    )
