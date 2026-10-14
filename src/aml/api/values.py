"""Value helpers of the API (its own copies, so the API does not reach into ``aml.cases``)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd


def plain(value: Any) -> Any:
    """None for NULL / NaN / NaT / pd.NA, else a plain Python value (whole Decimal -> int)."""
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def iso_date(value: Any) -> str | None:
    number = plain(value)
    return None if number is None else pd.Timestamp(number).date().isoformat()


def iso_seconds(value: Any) -> str | None:
    """``YYYY-MM-DDTHH:MM:SS`` (no fraction, no zone)."""
    number = plain(value)
    return None if number is None else pd.Timestamp(number).strftime("%Y-%m-%dT%H:%M:%S")


def lower_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Oracle returns upper-case column names; the code works with lower case."""
    df.columns = [str(c).lower() for c in df.columns]
    return df


def in_filter(column: str, values: Sequence[str], chunk: int = 500) -> str:
    """``(col IN (...) OR col IN (...))``; Oracle allows at most 1000 items in one list."""
    if not values:
        return "1 = 0"
    parts = []
    for start in range(0, len(values), chunk):
        literals = ", ".join(
            "'" + v.replace("'", "''") + "'" for v in values[start : start + chunk]
        )
        parts.append(f"{column} IN ({literals})")
    return "(" + " OR ".join(parts) + ")"
