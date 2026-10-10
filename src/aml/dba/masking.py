"""Reference (pure Python) PII masking for the analyst-facing ``customers_masked`` view.

The same rules are written in SQL in ``sql/duckdb/ddl/050_customers_masked.sql`` and
``sql/oracle/ddl/050_security_objects.sql``; tests compare all three implementations.
Digits are matched with ``[0-9]`` everywhere so Python, DuckDB and Oracle agree.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd

MASKED_COLUMNS: tuple[str, ...] = (
    "cif",
    "full_name",
    "gender",
    "birth_year",
    "nationality",
    "occupation",
    "kyc_risk",
    "id_type",
    "id_number",
    "phone",
    "email",
    "address_format",
    "ward",
    "district",
    "province",
)

_PASSTHROUGH = tuple(c for c in MASKED_COLUMNS if c not in {"birth_year"})
_NON_DIGIT = re.compile(r"[^0-9]")


def _clean(value: str | None) -> str | None:
    """None for NULL, empty or whitespace-only input (Oracle treats '' as NULL)."""
    if value is None or not isinstance(value, str) or not value.strip():
        return None
    return value


def _keep_tail(text: str, keep: int) -> str:
    if len(text) <= keep:
        return "*" * len(text)
    return "*" * (len(text) - keep) + text[-keep:]


def mask_name(value: str | None) -> str | None:
    """Keep the family name (first token); later tokens shrink to ``X.``."""
    text = _clean(value)
    if text is None:
        return None
    first, *rest = text.split()
    if not rest:
        return first[0] + "."
    return " ".join([first, *(t[0] + "." for t in rest)])


def mask_id(value: str | None) -> str | None:
    """Keep the last 4 characters; everything before becomes ``*``."""
    text = _clean(value)
    return None if text is None else _keep_tail(text, 4)


def mask_phone(value: str | None) -> str | None:
    """Digits only, keep the last 3; no digits at all gives None."""
    text = _clean(value)
    if text is None:
        return None
    digits = _NON_DIGIT.sub("", text)
    return _keep_tail(digits, 3) if digits else None


def mask_email(value: str | None) -> str | None:
    """``d***@domain`` when there is a local part before the first ``@``, else ``***``."""
    text = _clean(value)
    if text is None:
        return None
    local, at, domain = text.partition("@")
    if at and local:
        return f"{local[0]}***@{domain}"
    return "***"


def _masked(series: pd.Series, fn: Callable[[str | None], str | None]) -> pd.Series:
    values = [fn(v) if pd.notna(v) else None for v in series]
    return pd.Series(values, dtype="str", index=series.index)


def mask_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Return the ``customers_masked`` projection of ``customers`` (columns = MASKED_COLUMNS)."""
    out = customers.loc[:, list(_PASSTHROUGH)].copy()
    out["full_name"] = _masked(customers["full_name"], mask_name)
    out["id_number"] = _masked(customers["id_number"], mask_id)
    out["phone"] = _masked(customers["phone"], mask_phone)
    out["email"] = _masked(customers["email"], mask_email)
    out["birth_year"] = pd.to_datetime(customers["dob"]).dt.year.astype("Int64")
    return out.loc[:, list(MASKED_COLUMNS)]
