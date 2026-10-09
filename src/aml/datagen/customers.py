"""Synthetic Vietnamese retail customers with duplicate persons and seeded DQ defects.

Pipeline: build one ``_Person`` per real person -> emit a primary CIF row each -> emit
extra "secondary" CIF rows (with visible variations) for a share of the persons -> shuffle
CIF numbering -> inject data-quality defects with an independent random stream.
"""

from __future__ import annotations

import ipaddress
import unicodedata
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from aml.datagen.rng import table_rng
from aml.datagen.vn_reference import (
    EMAIL_DOMAINS,
    FEMALE_GIVEN,
    FEMALE_MARKER,
    FEMALE_MIDDLE,
    FOREIGN_NAMES,
    MALE_GIVEN,
    MALE_MIDDLE,
    OCCUPATIONS,
    STREETS,
    SURNAME_WEIGHTS,
    build_admin_unit_mapping,
)

if TYPE_CHECKING:
    from aml.common.config import Settings

__all__ = [
    "OCCUPATIONS",
    "CustomerTables",
    "generate_customers",
    "generate_customers_from_settings",
]

CUSTOMER_COLUMNS = [
    "cif", "full_name", "gender", "dob", "nationality", "occupation", "kyc_risk",
    "id_type", "id_number", "phone", "email", "device_id", "ip", "address_format",
    "street", "ward", "district", "province", "address",
]  # fmt: skip
DEFECT_TYPES = ["MISSING_OCCUPATION", "MISSING_NATIONALITY", "INVALID_ID_LENGTH", "FUTURE_DOB"]

# Distribution constants (spec Q8): deliberately not configurable.
FOREIGN_SHARE = 0.03
FOREIGN_NATIONALITIES = ["CN", "KR", "JP", "US", "RU"]
CMND_SHARE = 0.14  # of Vietnamese persons; secondary flips push the row-level share to ~0.16
KYC_WEIGHTS = {"LOW": 0.70, "MEDIUM": 0.25, "HIGH": 0.05}
MIN_AGE_DAYS, MAX_AGE_DAYS = 6600, 29200  # > 18 years and < 81 years (80 completed at most)
FEMALE_MARKER_SHARE = 0.6
MIDDLE_COUNT_WEIGHTS = [0.1, 0.8, 0.1]  # 0, 1 or 2 middle names
SHARED_DEVICE_P = 0.7  # secondary CIF reuses the person's device_id / ip (Q10)
SHARED_EMAIL_P = 0.5
VARIATION_P = {
    "TYPO": 0.30,
    "NO_DIACRITICS": 0.30,
    "NAME_ORDER": 0.30,
    "CMND_VS_CCCD": 0.25,
    "PHONE_FORMAT": 0.30,
    "OLD_VS_NEW_ADDRESS": 0.30,
}
AVG_EXTRA_CIFS = 1.25  # mean of {1, 2} extra CIFs per duplicated person (used for sizing)


@dataclass(frozen=True)
class CustomerTables:
    """Output of the customer generator (one DataFrame per table)."""

    customers: pd.DataFrame  # 1 row / CIF
    customer_person: pd.DataFrame  # ER ground truth: cif, person_id, is_primary, variations
    dq_defects: pd.DataFrame  # DQ ground truth: cif, defect_type
    admin_unit_mapping: pd.DataFrame  # old -> new administrative units


@dataclass
class _Person:
    """Attributes shared by every CIF of one real person."""

    gender: str
    nationality: str
    name: str
    dob: date
    occupation: str
    kyc_risk: str
    id_numbers: dict[str, str]
    id_type: str
    phone: str  # 10 digits, leading 0
    phone_format: int
    email: str
    device_id: str
    ip: str
    address_format: str
    location: int  # row index in the admin mapping
    street: str


# --------------------------------------------------------------------------- helpers


def _quota(
    rng: np.random.Generator, labels: Sequence[str], weights: Sequence[float], n: int
) -> list[str]:
    """Return ``n`` shuffled labels whose counts match ``weights`` as exactly as possible."""
    w = np.asarray(weights, dtype=float)
    raw = w / w.sum() * n
    counts = np.floor(raw).astype(int)
    order = np.argsort(-(raw - counts), kind="stable")
    counts[order[: n - counts.sum()]] += 1
    items = np.repeat(np.asarray(labels, dtype=object), counts)
    return list(rng.permutation(items))


def _strip_diacritics(text: str) -> str:
    """Remove Vietnamese diacritics (including đ/Đ) and return an NFC string."""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    kept = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", kept)


def _typo(rng: np.random.Generator, name: str) -> str:
    """Apply exactly one edit (substitute, delete or swap adjacent letters) to ``name``."""
    letters = [i for i, ch in enumerate(name) if ch.isalpha()]
    deletable = [
        i for i in letters if (i > 0 and name[i - 1].isalpha()) or name[i + 1 : i + 2].isalpha()
    ]
    swappable = [i for i in letters if i > 0 and name[i - 1].isalpha() and name[i - 1] != name[i]]
    ops = ["sub"] + (["del"] if deletable else []) + (["swap"] if swappable else [])
    op = ops[int(rng.integers(len(ops)))]
    if op == "del":
        i = deletable[int(rng.integers(len(deletable)))]
        return name[:i] + name[i + 1 :]
    if op == "swap":
        i = swappable[int(rng.integers(len(swappable)))]
        return name[: i - 1] + name[i] + name[i - 1] + name[i + 1 :]
    i = letters[int(rng.integers(len(letters)))]
    pool = [c for c in "abcdeghiklmnoprstuvy" if c != name[i].lower()]
    new = pool[int(rng.integers(len(pool)))]
    return name[:i] + (new.upper() if name[i].isupper() else new) + name[i + 1 :]


def _format_phone(digits: str, fmt: int) -> str:
    """Render a 10-digit national number in one of the four display formats."""
    if fmt == 0:
        return digits
    if fmt == 1:
        return f"+84 {digits[1:3]} {digits[3:6]} {digits[6:]}"
    sep = " " if fmt == 2 else "."
    return f"{digits[:3]}{sep}{digits[3:6]}{sep}{digits[6:]}"


def _new_email(rng: np.random.Generator, name: str) -> str:
    """Build an ASCII e-mail address derived from the (diacritic-free) name."""
    tokens = _strip_diacritics(name).lower().split()
    local = f"{tokens[-1]}{tokens[0][0]}{int(rng.integers(1, 10000))}"
    return f"{local}@{EMAIL_DOMAINS[int(rng.integers(len(EMAIL_DOMAINS)))]}"


def _new_device(rng: np.random.Generator) -> str:
    return str(uuid.UUID(bytes=rng.bytes(16), version=4))


def _new_public_ip(rng: np.random.Generator) -> str:
    """Draw a random globally routable unicast IPv4 address."""
    while True:
        octets = rng.integers(1, 224, size=4)
        addr = ipaddress.IPv4Address(".".join(str(int(o)) for o in octets))
        if addr.is_global:
            return str(addr)


def _digits(rng: np.random.Generator, width: int) -> str:
    return f"{int(rng.integers(0, 10**width)):0{width}d}"


# ------------------------------------------------------------------ person generation


def _vietnamese_name(rng: np.random.Generator, gender: str, surname: str) -> str:
    """Compose ``surname [middle...] given`` with gender-appropriate parts (2-4 tokens)."""
    n_mid = int(rng.choice(3, p=MIDDLE_COUNT_WEIGHTS))
    middle_pool = FEMALE_MIDDLE if gender == "F" else MALE_MIDDLE
    given_pool = FEMALE_GIVEN if gender == "F" else MALE_GIVEN
    middles: list[str] = []
    for k in range(n_mid):
        if gender == "F" and k == 0 and rng.random() < FEMALE_MARKER_SHARE:
            middles.append(FEMALE_MARKER)
        else:
            middles.append(middle_pool[int(rng.integers(len(middle_pool)))])
    given = given_pool[int(rng.integers(len(given_pool)))]
    return unicodedata.normalize("NFC", " ".join([surname, *middles, given]))


def _foreign_name(rng: np.random.Generator, nationality: str, gender: str) -> str:
    surnames, male, female = FOREIGN_NAMES[nationality]
    givens = female if gender == "F" else male
    return f"{surnames[int(rng.integers(len(surnames)))]} {givens[int(rng.integers(len(givens)))]}"


def _id_numbers(
    rng: np.random.Generator, nationality: str, gender: str, dob: date
) -> dict[str, str]:
    """Return the identity documents a person holds, keyed by ``id_type``."""
    if nationality != "VN":
        letter = chr(65 + int(rng.integers(26)))
        return {"PASSPORT": letter + _digits(rng, 7)}
    century_gender = (0 if dob.year < 2000 else 2) + (0 if gender == "M" else 1)
    province_code = f"{int(rng.integers(1, 97)):03d}"
    cccd = f"{province_code}{century_gender}{dob.year % 100:02d}{_digits(rng, 6)}"
    return {"CCCD": cccd, "CMND": _digits(rng, 9)}


def _build_persons(
    rng: np.random.Generator, n_persons: int, reference_date: date, mapping_size: int
) -> list[_Person]:
    """Create ``n_persons`` independent people with quota-balanced categorical attributes."""
    genders = _quota(rng, ["M", "F"], [0.5, 0.5], n_persons)
    n_foreign = round(FOREIGN_SHARE * n_persons)
    foreign = _quota(rng, FOREIGN_NATIONALITIES, [1] * 5, n_foreign)
    nationalities = [*(["VN"] * (n_persons - n_foreign)), *foreign]
    nationalities = list(rng.permutation(np.asarray(nationalities, dtype=object)))
    n_vn = n_persons - n_foreign
    surnames: Iterator[str] = iter(
        _quota(rng, list(SURNAME_WEIGHTS), list(SURNAME_WEIGHTS.values()), n_vn)
    )
    vn_id_types: Iterator[str] = iter(
        _quota(rng, ["CMND", "CCCD"], [CMND_SHARE, 1 - CMND_SHARE], n_vn)
    )
    kyc = _quota(rng, list(KYC_WEIGHTS), list(KYC_WEIGHTS.values()), n_persons)
    formats = _quota(rng, ["OLD", "NEW"], [0.5, 0.5], n_persons)
    phone_formats = _quota(rng, ["0", "1", "2", "3"], [1] * 4, n_persons)

    persons = []
    for i in range(n_persons):
        gender, nat = genders[i], nationalities[i]
        if nat == "VN":
            name = _vietnamese_name(rng, gender, next(surnames))
        else:
            name = _foreign_name(rng, nat, gender)
        dob = reference_date - timedelta(days=int(rng.integers(MIN_AGE_DAYS, MAX_AGE_DAYS + 1)))
        ids = _id_numbers(rng, nat, gender, dob)
        phone = f"0{[3, 5, 7, 8, 9][int(rng.integers(5))]}{_digits(rng, 8)}"
        persons.append(
            _Person(
                gender=gender,
                nationality=nat,
                name=name,
                dob=dob,
                occupation=OCCUPATIONS[int(rng.integers(len(OCCUPATIONS)))],
                kyc_risk=kyc[i],
                id_numbers=ids,
                id_type=next(vn_id_types) if nat == "VN" else "PASSPORT",
                phone=phone,
                phone_format=int(phone_formats[i]),
                email=_new_email(rng, name),
                device_id=_new_device(rng),
                ip=_new_public_ip(rng),
                address_format=formats[i],
                location=int(rng.integers(mapping_size)),
                street=f"{int(rng.integers(1, 300))} {STREETS[int(rng.integers(len(STREETS)))]}",
            )
        )
    return persons


# ------------------------------------------------------------------------ row building


def _address_fields(person: _Person, fmt: str, mapping: pd.DataFrame) -> dict[str, Any]:
    """Render the person's location in the OLD (with district) or NEW (merged) format."""
    unit = mapping.iloc[person.location]
    if fmt == "OLD":
        ward, district, province = unit["old_ward"], unit["old_district"], unit["old_province"]
        parts = [person.street, ward, district, province]
    else:
        ward, district, province = unit["new_ward"], None, unit["new_province"]
        parts = [person.street, ward, province]
    return {
        "address_format": fmt,
        "street": person.street,
        "ward": ward,
        "district": district,
        "province": province,
        "address": ", ".join(parts),
    }


def _row(person: _Person, fields: dict[str, Any], mapping: pd.DataFrame) -> dict[str, Any]:
    """Assemble one CIF row (without ``cif``) from person-level values plus overrides."""
    id_type = fields["id_type"]
    return {
        "full_name": fields["full_name"],
        "gender": person.gender,
        "dob": person.dob,
        "nationality": person.nationality,
        "occupation": person.occupation,
        "kyc_risk": person.kyc_risk,
        "id_type": id_type,
        "id_number": person.id_numbers[id_type],
        "phone": _format_phone(person.phone, fields["phone_format"]),
        "email": fields["email"],
        "device_id": fields["device_id"],
        "ip": fields["ip"],
        **_address_fields(person, fields["address_format"], mapping),
    }


def _primary_row(person: _Person, mapping: pd.DataFrame) -> dict[str, Any]:
    fields = {
        "full_name": person.name,
        "id_type": person.id_type,
        "phone_format": person.phone_format,
        "email": person.email,
        "device_id": person.device_id,
        "ip": person.ip,
        "address_format": person.address_format,
    }
    return _row(person, fields, mapping)


def _pick_variations(rng: np.random.Generator, person: _Person) -> list[str]:
    """Choose a non-empty, sorted set of variation codes that are applicable to ``person``."""
    allowed = list(VARIATION_P)
    if person.nationality != "VN":
        allowed.remove("CMND_VS_CCCD")  # passport holders have no CMND/CCCD to switch to
    if _strip_diacritics(person.name) == person.name:
        allowed.remove("NO_DIACRITICS")
    chosen = [c for c in allowed if rng.random() < VARIATION_P[c]]
    if not chosen:
        chosen = [allowed[int(rng.integers(len(allowed)))]]
    return sorted(chosen)


def _varied_name(rng: np.random.Generator, name: str, codes: list[str]) -> str:
    """Apply NAME_ORDER, then TYPO, then NO_DIACRITICS (in that order) to ``name``."""
    if "NAME_ORDER" in codes:
        tokens = name.split()
        name = " ".join(tokens[1:] + tokens[:1])
    if "TYPO" in codes:
        name = _typo(rng, name)
    if "NO_DIACRITICS" in codes:
        name = _strip_diacritics(name)
    return name


def _secondary_row(
    rng: np.random.Generator, person: _Person, codes: list[str], mapping: pd.DataFrame
) -> dict[str, Any]:
    """Build a duplicate CIF row for ``person`` showing each variation in ``codes``."""
    id_type = person.id_type
    if "CMND_VS_CCCD" in codes:
        id_type = "CMND" if id_type == "CCCD" else "CCCD"
    phone_format = person.phone_format
    if "PHONE_FORMAT" in codes:
        phone_format = (phone_format + 1 + int(rng.integers(3))) % 4
    address_format = person.address_format
    if "OLD_VS_NEW_ADDRESS" in codes:
        address_format = "NEW" if address_format == "OLD" else "OLD"
    share_device = rng.random() < SHARED_DEVICE_P
    fields = {
        "full_name": _varied_name(rng, person.name, codes),
        "id_type": id_type,
        "phone_format": phone_format,
        "email": person.email if rng.random() < SHARED_EMAIL_P else _new_email(rng, person.name),
        "device_id": person.device_id if share_device else _new_device(rng),
        "ip": person.ip if share_device else _new_public_ip(rng),
        "address_format": address_format,
    }
    return _row(person, fields, mapping)


def _plan_duplicates(n_customers: int, rate: float) -> tuple[int, int, int]:
    """Return ``(n_persons, n_duplicated, n_extra_cifs)`` so that persons + extras = n_customers."""
    n_persons = max(1, round(n_customers / (1 + AVG_EXTRA_CIFS * rate)))
    n_extra = n_customers - n_persons
    n_dup = round(rate * n_persons)
    n_dup = max(min(n_dup, n_extra), -(-n_extra // 2))  # keep extras within [dup, 2*dup]
    return n_persons, n_dup, n_extra


def _build_rows(
    n_customers: int, seed: int, duplicate_person_rate: float, reference_date: date,
    mapping: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[tuple[int, bool, str]]]:  # fmt: skip
    """Return CIF rows (no cif yet) and parallel ``(person_idx, is_primary, variations)``."""
    n_persons, n_dup, n_extra = _plan_duplicates(n_customers, duplicate_person_rate)
    rng = table_rng(seed, "customers")
    persons = _build_persons(rng, n_persons, reference_date, len(mapping))
    rows = [_primary_row(p, mapping) for p in persons]
    meta = [(i, True, "") for i in range(n_persons)]

    dup_rng = table_rng(seed, "customers.duplicates")
    dup_people = dup_rng.choice(n_persons, size=n_dup, replace=False)
    three_cif = set(dup_rng.choice(n_dup, size=n_extra - n_dup, replace=False).tolist())
    for k, person_idx in enumerate(dup_people.tolist()):
        for _ in range(2 if k in three_cif else 1):
            codes = _pick_variations(dup_rng, persons[person_idx])
            rows.append(_secondary_row(dup_rng, persons[person_idx], codes, mapping))
            meta.append((person_idx, False, ",".join(codes)))
    return rows, meta


# ------------------------------------------------------------------------ DQ defects


def _inject_defects(
    customers: pd.DataFrame, rate: float, seed: int, reference_date: date
) -> pd.DataFrame:
    """Corrupt exactly ``round(rate * n)`` rows per defect type; return the defect log."""
    rng = table_rng(seed, "customers.dq")
    n_defects = round(rate * len(customers))
    non_passport = np.flatnonzero((customers["id_type"] != "PASSPORT").to_numpy())
    everyone = np.arange(len(customers))
    log: list[tuple[str, str]] = []
    for defect in DEFECT_TYPES:
        pool = non_passport if defect == "INVALID_ID_LENGTH" else everyone
        picked = np.sort(rng.choice(pool, size=min(n_defects, len(pool)), replace=False))
        for pos in picked.tolist():
            if defect == "MISSING_OCCUPATION":
                customers.iat[pos, customers.columns.get_loc("occupation")] = None
            elif defect == "MISSING_NATIONALITY":
                customers.iat[pos, customers.columns.get_loc("nationality")] = None
            elif defect == "INVALID_ID_LENGTH":
                width = int(rng.choice([6, 7, 8, 10, 11, 13, 14]))
                customers.iat[pos, customers.columns.get_loc("id_number")] = _digits(rng, width)
            else:
                future = reference_date + timedelta(days=int(rng.integers(1, 3651)))
                customers.iat[pos, customers.columns.get_loc("dob")] = future
            log.append((customers.iat[pos, 0], defect))
    return pd.DataFrame(log, columns=["cif", "defect_type"])


# ------------------------------------------------------------------------- public API


def _validate(n_customers: int, duplicate_person_rate: float, dq_defect_rate: float) -> None:
    if n_customers < 1:
        raise ValueError(f"n_customers must be >= 1, got {n_customers}")
    if not 0.0 <= duplicate_person_rate <= 1.0:
        raise ValueError(f"duplicate_person_rate must be in [0, 1], got {duplicate_person_rate}")
    if not 0.0 <= dq_defect_rate <= 1.0:
        raise ValueError(f"dq_defect_rate must be in [0, 1], got {dq_defect_rate}")


def generate_customers(
    n_customers: int,
    seed: int,
    duplicate_person_rate: float,
    dq_defect_rate: float,
    reference_date: date,
) -> CustomerTables:
    """Generate ``n_customers`` CIF rows plus ER / DQ ground truth, deterministically."""
    _validate(n_customers, duplicate_person_rate, dq_defect_rate)
    mapping = build_admin_unit_mapping()
    rows, meta = _build_rows(n_customers, seed, duplicate_person_rate, reference_date, mapping)

    cif_numbers = table_rng(seed, "customers.cif").permutation(n_customers) + 1
    cifs = [f"CIF{num:08d}" for num in cif_numbers.tolist()]
    customers = pd.DataFrame(rows)
    customers.insert(0, "cif", cifs)
    person = pd.DataFrame(
        {
            "cif": cifs,
            "person_id": [f"P{idx + 1:07d}" for idx, _, _ in meta],
            "is_primary": [primary for _, primary, _ in meta],
            "variations": [variations for _, _, variations in meta],
        }
    )
    order = np.argsort(np.asarray(cifs))
    customers = customers.iloc[order].reset_index(drop=True)[CUSTOMER_COLUMNS]
    person = person.iloc[order].reset_index(drop=True)

    defects = _inject_defects(customers, dq_defect_rate, seed, reference_date)
    return CustomerTables(customers, person, defects, mapping)


def generate_customers_from_settings(settings: Settings) -> CustomerTables:
    """Generate customers using the active data profile and rates from ``settings``."""
    return generate_customers(
        settings.data.active.customers,
        settings.seed,
        settings.data.duplicate_person_rate,
        settings.data.dq_defect_rate,
        settings.data.reference_date,
    )
