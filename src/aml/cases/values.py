"""Turn database values (pandas, numpy, Oracle types) into plain values for the enrichment JSON.

DuckDB and Oracle return the same data in different Python types (DATE as Timestamp or datetime,
NUMBER as int, float or Decimal, NULL as None or NaN). Everything stored in ``case_enrichment``
goes through here, so the JSON of both backends is the same.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

# Shape produced by `case_id_for`: C-<golden id without G->-<YYYYMMDD>.
_CASE_ID = re.compile(r"C-[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)*-[0-9]{8}")


def is_case_id(text: str) -> bool:
    """True when ``text`` has the shape of a case id; guards ids that come from a user."""
    return _CASE_ID.fullmatch(text) is not None


def plain(value: Any) -> Any:
    """None for NULL / NaN / NaT, else a plain Python value (a whole Decimal becomes int)."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def whole(value: Any) -> int:
    """An integer count or amount; NULL counts as 0."""
    number = plain(value)
    return 0 if number is None else int(number)


def iso_date(value: Any) -> str | None:
    number = plain(value)
    return None if number is None else pd.Timestamp(number).date().isoformat()


def iso_ts(value: Any) -> str | None:
    number = plain(value)
    return None if number is None else pd.Timestamp(number).isoformat()


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


def floats(value: Any) -> Any:
    """Recursively turn Decimal (Oracle JSON numbers) into int or float."""
    if isinstance(value, dict):
        return {k: floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [floats(v) for v in value]
    return plain(value) if isinstance(value, Decimal) else value
