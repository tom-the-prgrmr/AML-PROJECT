"""Benign look-alikes: monthly payroll and a busy merchant (must not be flagged)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from aml.datagen.typologies._common import (
    AccountPool,
    Scenario,
    TypologyContext,
    make_row,
    pick_channel,
    round_k,
    rows_frame,
)

EMPLOYEES = (20, 30)
SALARY_VND = (6_000_000, 40_000_000)
PAY_DAY_OFFSET = 4  # paid on the 5th of each month
PAYERS = (30, 40)
PURCHASES_PER_PAYER = (1, 3)
PURCHASE_MEDIAN_VND, PURCHASE_SIGMA = 400_000, 0.9
PURCHASE_BOUNDS = (50_000, 5_000_000)


def build_benign_payroll(
    ctx: TypologyContext, pool: AccountPool, rng: np.random.Generator, scenario_id: str
) -> Scenario:
    """One employer pays each of 20-30 employees once per calendar month."""
    n = int(rng.integers(EMPLOYEES[0], EMPLOYEES[1] + 1))
    employer, *employees = pool.take(1 + n)
    first_month = pd.Timestamp(ctx.window_start.year, ctx.window_start.month, 1)
    salaries = rng.integers(SALARY_VND[0] // 1000, SALARY_VND[1] // 1000 + 1, size=n) * 1000
    rows = []
    for k in range(ctx.months):
        month = first_month + pd.DateOffset(months=k)
        memo = f"Lương tháng {month.month:02d}/{month.year}"
        for emp, salary in zip(employees, salaries.tolist(), strict=True):
            hour, minute = int(rng.integers(8, 11)), int(rng.integers(60))
            ts = month + pd.Timedelta(days=PAY_DAY_OFFSET, hours=hour, minutes=minute)
            rows.append(make_row(ts, employer, emp, salary, "INTERNAL_TRANSFER", memo=memo))
    return Scenario(
        scenario_id=scenario_id,
        typology="benign_payroll",
        is_suspicious=False,
        accounts=[(employer, "employer")] + [(e, "employee") for e in employees],
        rows=rows_frame(rows),
        reason=f"monthly salary run from one employer to {n} employees (benign look-alike)",
    )


def build_benign_merchant(
    ctx: TypologyContext, pool: AccountPool, rng: np.random.Generator, scenario_id: str
) -> Scenario:
    """One small-business account receives modest payments from 30-40 different payers."""
    n = int(rng.integers(PAYERS[0], PAYERS[1] + 1))
    merchant, *payers = pool.take(1 + n)
    span = int((ctx.window_end - ctx.window_start).total_seconds())
    low, high = PURCHASES_PER_PAYER
    rows = []
    for payer in payers:
        for _ in range(int(rng.integers(low, high + 1))):
            amount = round_k(rng.lognormal(np.log(PURCHASE_MEDIAN_VND), PURCHASE_SIGMA))
            amount = min(max(amount, PURCHASE_BOUNDS[0]), PURCHASE_BOUNDS[1])
            ts = ctx.window_start + pd.Timedelta(seconds=int(rng.integers(0, span)))
            memo = f"Thanh toán đơn hàng {int(rng.integers(10_000, 99_999))}"
            rows.append(make_row(ts, payer, merchant, amount, pick_channel(rng), memo=memo))
    return Scenario(
        scenario_id=scenario_id,
        typology="benign_merchant",
        is_suspicious=False,
        accounts=[(merchant, "merchant")] + [(p, "payer") for p in payers],
        rows=rows_frame(rows),
        reason=f"small business receiving retail payments from {n} payers (benign look-alike)",
    )
