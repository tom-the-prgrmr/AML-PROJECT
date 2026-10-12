"""Record normalisation for entity resolution: one clean row per CIF, bad values become None."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

from aml.common.config import Settings
from aml.screening.normalize import name_key, normalize_name, strip_diacritics

RECORD_COLUMNS = [
    "cif",
    "name_key",
    "dob",
    "phone_norm",
    "id_kind",
    "id_norm",
    "email_norm",
    "province_new",
    "addr_key",
]

_ID_RULES = {"CCCD": r"\d{12}", "CMND": r"\d{9}", "PASSPORT": r"[A-Z0-9]{6,}"}
_AdminLookup = dict[tuple[str, str, str], tuple[str, str]]


def _str(value: object) -> str | None:
    """Return ``value`` if it is a string, else None (covers None, NaN and NaT)."""
    return value if isinstance(value, str) else None


def _text(value: object) -> str | None:
    """Strip diacritics, upper-case and collapse spaces; empty text gives None."""
    text = _str(value)
    if text is None:
        return None
    folded = " ".join(strip_diacritics(text).upper().split())
    return folded or None


def normalize_phone(raw: str | None) -> str | None:
    """Return a 10-digit number starting with 0 (``+84``/``0084`` prefixes folded), else None."""
    text = _str(raw)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if len(digits) == 10 and digits.startswith("0") else None


def normalize_id(id_type: str | None, id_number: str | None) -> tuple[str, str] | None:
    """Return (kind, number) when the number fits the document type, else None."""
    kind, number = _str(id_type), _str(id_number)
    if kind is None or number is None:
        return None
    kind = kind.strip().upper()
    number = re.sub(r"[^A-Z0-9]", "", number.upper())
    pattern = _ID_RULES.get(kind)
    return (kind, number) if pattern and re.fullmatch(pattern, number) else None


def _admin_lookup(mapping: pd.DataFrame) -> _AdminLookup:
    return {
        (r.old_ward, r.old_district, r.old_province): (r.new_ward, r.new_province)
        for r in mapping.itertuples()
    }


def _to_new(
    ward: str | None, district: str | None, province: str | None, lookup: _AdminLookup
) -> tuple[str | None, str | None]:
    if isinstance(district, str):
        return lookup.get((ward, district, province), (ward, province))  # type: ignore[arg-type]
    return ward, province


def to_new_admin_unit(
    ward: str | None, district: str | None, province: str | None, mapping: pd.DataFrame
) -> tuple[str | None, str | None]:
    """Map an old (ward, district, province) to the new (ward, province); others pass through."""
    return _to_new(_str(ward), _str(district), _str(province), _admin_lookup(mapping))


def addr_key(street: object, new_ward: str | None, new_province: str | None) -> str | None:
    """``STREET|WARD|PROVINCE`` (folded, upper-case) from a street and the new admin unit."""
    folded = _text(street)
    if not folded:
        return None
    return "|".join([folded, _text(new_ward) or "", _text(new_province) or ""])


def address_keys(customers: pd.DataFrame, mapping: pd.DataFrame) -> list[str | None]:
    """The ``addr_key`` of every customer row, in row order (old units mapped to new ones)."""
    lookup = _admin_lookup(mapping)
    keys: list[str | None] = []
    for r in customers.itertuples():
        ward, province = _to_new(_str(r.ward), _str(r.district), _str(r.province), lookup)
        keys.append(addr_key(r.street, ward, province))
    return keys


def _dob(value: object, as_of: date) -> str | None:
    """ISO date string, or None when missing or after ``as_of``."""
    if value is None or pd.isna(value):
        return None
    day = pd.Timestamp(value).date()  # type: ignore[arg-type]
    return day.isoformat() if day <= as_of else None


def prepare_records(
    customers: pd.DataFrame, mapping: pd.DataFrame, settings: Settings, *, as_of: date
) -> pd.DataFrame:
    """Build the Splink input: one normalised row per CIF, sorted by cif."""
    lookup = _admin_lookup(mapping)
    rows = []
    for r in customers.itertuples():
        ward, province = _to_new(_str(r.ward), _str(r.district), _str(r.province), lookup)
        id_pair = normalize_id(r.id_type, r.id_number)
        email = (_str(r.email) or "").strip().lower()
        rows.append(
            {
                "cif": r.cif,
                "name_key": name_key(normalize_name(r.full_name, settings.screening)) or None,
                "dob": _dob(r.dob, as_of),
                "phone_norm": normalize_phone(r.phone),
                "id_kind": id_pair[0] if id_pair else None,
                "id_norm": id_pair[1] if id_pair else None,
                "email_norm": email or None,
                "province_new": _text(province),
                "addr_key": addr_key(r.street, ward, province),
            }
        )
    frame = pd.DataFrame(rows, columns=RECORD_COLUMNS)
    return frame.sort_values("cif").reset_index(drop=True)
