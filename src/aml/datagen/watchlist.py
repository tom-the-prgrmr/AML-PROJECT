"""Synthetic sanctions/PEP watchlist with aliases, true hits and screening traps.

Spec: ``specs/datagen-watchlist-output.md`` (Phase 1c). Output: ``watchlist``,
``watchlist_alias`` and the ``ground_truth`` rows (``sanctions_hit`` / ``pep_hit`` /
``screening_trap``) that label which entries are planted on purpose.

* True hits are real customers (all CIFs of one person) whose unaccented primary name is
  put on the list as-is, word-reordered, or only through an alias.
* Traps are look-alikes: they share common Vietnamese name tokens with many customers but
  carry one extra token that no customer has, so a correct screener must not alert.
* No system clock is read: dates derive from ``start_date`` and the seeded streams
  ``table_rng(seed, "watchlist")`` / ``table_rng(seed, "watchlist_alias")``.
"""

from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from aml.datagen.customers import _strip_diacritics, _vietnamese_name
from aml.datagen.rng import table_rng
from aml.datagen.vn_reference import SURNAME_WEIGHTS
from aml.datagen.watchlist_names import (
    AR_FAMILY,
    AR_GIVEN,
    NATIONALITIES,
    OTHER_FAMILY,
    OTHER_GIVEN,
    PEP_PROGRAMS,
    RU_GIVEN,
    RU_SURNAME,
    SANCTIONS_PROGRAMS,
    TRAP_DISTINGUISHERS,
    ZH_GIVEN,
    ZH_SURNAME,
    Variants,
)

if TYPE_CHECKING:
    from aml.common.config import WatchlistConfig

__all__ = ["WatchlistResult", "generate_watchlist"]

DEFAULT_START_DATE = date(2026, 1, 1)  # data.start_date; listed_date is always before it
WATCHLIST_COLUMNS = [
    "entry_id", "list_type", "primary_name", "name_origin", "dob", "dob_year",
    "dob_precision", "nationality", "program", "listed_date",
]  # fmt: skip
ALIAS_COLUMNS = ["alias_id", "entry_id", "alias_name", "alias_type"]
GROUND_TRUTH_COLUMNS = [
    "scenario_id", "typology", "is_suspicious", "entity_type", "entity_id",
    "role", "start_ts", "end_ts", "reason",
]  # fmt: skip

# Distribution constants (spec Q2, Q4): deliberately not configurable.
SANCTIONS_SHARE = 0.60
ORIGINS = ["vi", "ru", "ar", "zh", "other"]
ORIGIN_WEIGHTS = [0.25, 0.22, 0.22, 0.17, 0.14]
MISSING_NATIONALITY_P = 0.03
MAX_ALIASES = 5
SECOND_TRANSLIT_P = 0.40
AKA_P = 0.30
REORDERED_P = 0.25
MIN_AGE_YEARS, MAX_AGE_YEARS = 25, 85
MAX_LISTED_DAYS = 15 * 365
MIN_LISTED_DAYS = 30
TRAP_SHARE_MIN = 0.05  # a trap must share >= 2 tokens with at least this share of customers
TOP_TOKENS = 10
_NON_LETTERS = re.compile(r"[^A-Z ]")


@dataclass(frozen=True)
class WatchlistResult:
    """Output of the watchlist generator."""

    watchlist: pd.DataFrame
    watchlist_alias: pd.DataFrame
    ground_truth_rows: pd.DataFrame


@dataclass
class _Spec:
    """One planned watchlist entry before ids, dates and aliases are assigned."""

    kind: str  # "hit" | "trap" | "bg"
    origin: str
    nationality: str | None
    slots: list[Variants]  # primary name = first variant of every slot
    forced_aliases: list[tuple[str, str]] = field(default_factory=list)
    list_type: str | None = None  # fixed for hits (alternating); others are drawn
    cifs: list[str] = field(default_factory=list)  # hit only: every CIF of the person
    primary_cif: str | None = None
    customer_dob: date | None = None


# --------------------------------------------------------------------------- name helpers


def _normalize(name: str) -> str:
    """Unaccented, uppercase, letters and single spaces only."""
    text = _NON_LETTERS.sub(" ", _strip_diacritics(name).upper())
    return " ".join(text.split())


MAX_BG_RETRIES = 50


def _tokens(name: str) -> frozenset[str]:
    return frozenset(_normalize(name).split())


def _collides(name: str, customer_token_sets: set[frozenset[str]]) -> bool:
    """True when ``name`` has exactly the token set of some customer name."""
    return _tokens(name) in customer_token_sets


def _join(slots: list[Variants], picks: list[int]) -> str:
    return " ".join(slot[i] for slot, i in zip(slots, picks, strict=True))


def _single(tokens: list[str]) -> list[Variants]:
    return [(t,) for t in tokens]


def _rotate(name: str) -> str:
    """Move the last token to the front (``A B C`` -> ``C A B``)."""
    parts = name.split()
    return " ".join([parts[-1], *parts[:-1]]) if len(parts) > 1 else name


def _pick(rng: np.random.Generator, items: list) -> object:
    return items[int(rng.integers(len(items)))]


def _vietnamese_slots(rng: np.random.Generator) -> list[Variants]:
    surnames = [_strip_diacritics(s) for s in SURNAME_WEIGHTS]
    weights = np.asarray(list(SURNAME_WEIGHTS.values()), dtype=float)
    surname = surnames[int(rng.choice(len(surnames), p=weights / weights.sum()))]
    gender = "F" if rng.random() < 0.5 else "M"
    return _single(_normalize(_vietnamese_name(rng, gender, surname)).split())


def _background_slots(rng: np.random.Generator, origin: str) -> list[Variants]:
    """Slots of a random name of the given origin."""
    if origin == "vi":
        return _vietnamese_slots(rng)
    if origin == "ru":
        return [_pick(rng, RU_GIVEN), _pick(rng, RU_SURNAME)]  # type: ignore[list-item]
    if origin == "ar":
        slots: list[Variants] = [_pick(rng, AR_GIVEN)]  # type: ignore[list-item]
        if rng.random() < 0.4:
            slots.append(_pick(rng, AR_GIVEN))  # type: ignore[arg-type]
        slots.append(_pick(rng, AR_FAMILY))  # type: ignore[arg-type]
        return slots
    if origin == "zh":
        return [_pick(rng, ZH_SURNAME), _pick(rng, ZH_GIVEN)]  # type: ignore[list-item]
    return _single([str(_pick(rng, OTHER_GIVEN)), str(_pick(rng, OTHER_FAMILY))])


def _nationality(rng: np.random.Generator, origin: str) -> str | None:
    if rng.random() < MISSING_NATIONALITY_P:
        return None
    return str(_pick(rng, NATIONALITIES[origin]))


# --------------------------------------------------------------------------- planning


def _quota(rng: np.random.Generator, counts: dict[str, int]) -> list[str]:
    """Shuffled labels with exactly the given counts."""
    labels = [label for label, k in counts.items() for _ in range(k)]
    return [labels[i] for i in rng.permutation(len(labels))]


def _eligible_persons(
    customers: pd.DataFrame,
    customer_person: pd.DataFrame,
    dq_defects: pd.DataFrame,
    ground_truth: pd.DataFrame,
) -> list[str]:
    """Sorted person_ids whose CIFs are clean (no DQ defect, not in any customer GT row)."""
    blocked = set(dq_defects["cif"])
    if len(ground_truth):
        blocked |= set(ground_truth.loc[ground_truth["entity_type"] == "customer", "entity_id"])
    cust = customers.set_index("cif")
    complete = {
        cif
        for cif in customer_person.loc[customer_person["is_primary"], "cif"]
        if cif in cust.index
        and not pd.isna(cust.at[cif, "nationality"])
        and not pd.isna(cust.at[cif, "dob"])
        and not pd.isna(cust.at[cif, "full_name"])
    }
    per_person = customer_person.groupby("person_id")["cif"].apply(list)
    return sorted(
        str(pid)
        for pid, cifs in per_person.items()
        if not (set(cifs) & blocked) and (set(cifs) & complete)
    )


def _hit_specs(
    rng: np.random.Generator,
    customers: pd.DataFrame,
    customer_person: pd.DataFrame,
    persons: list[str],
    n_hits: int,
) -> list[_Spec]:
    """Plan ``n_hits`` true hits on randomly chosen eligible persons."""
    if n_hits > len(persons):
        raise ValueError(f"true_hits={n_hits} but only {len(persons)} eligible persons")
    chosen = [persons[i] for i in rng.choice(len(persons), size=n_hits, replace=False)]
    cust = customers.set_index("cif")
    by_person = customer_person.groupby("person_id")
    specs: list[_Spec] = []
    for idx, pid in enumerate(chosen):
        group = by_person.get_group(pid)
        primary = str(group.loc[group["is_primary"], "cif"].iloc[0])
        row = cust.loc[primary]
        true_name = _normalize(str(row["full_name"]))
        nationality = str(row["nationality"])
        origin = "vi" if nationality == "VN" else "other"
        mode = int(rng.integers(3))  # 0 as-is, 1 reordered, 2 alias-only
        spec = _Spec(
            kind="hit",
            origin=origin,
            nationality=nationality,
            slots=_single(true_name.split()),
            list_type="SANCTIONS" if idx % 2 == 0 else "PEP",
            cifs=sorted(str(c) for c in group["cif"]),
            primary_cif=primary,
            customer_dob=pd.Timestamp(row["dob"]).date(),
        )
        if mode == 1 and len(true_name.split()) > 1:
            spec.slots = _single(_rotate(true_name).split())
            spec.forced_aliases.append((true_name, "REORDERED"))
        elif mode == 2:
            other = _background_slots(rng, origin)
            if _tokens(_join(other, [0] * len(other))) == _tokens(true_name):
                other = [*other, ("JR",)]
            spec.slots = other
            spec.forced_aliases.append((true_name, "AKA"))
        specs.append(spec)
    return specs


def _trap_specs(rng: np.random.Generator, customers: pd.DataFrame, n_traps: int) -> list[_Spec]:
    """Plan traps: 2-3 frequent customer tokens plus one token no customer has."""
    if n_traps == 0:
        return []
    cust_tokens = [_tokens(str(n)) for n in customers["full_name"]]
    counter = Counter(tok for ts in cust_tokens for tok in ts)
    top = [tok for tok, _ in counter.most_common(TOP_TOKENS)]
    threshold = max(2, math.ceil(TRAP_SHARE_MIN * len(cust_tokens)))
    combos = [
        combo
        for size in (2, 3)
        for combo in itertools.combinations(sorted(top), size)
        if sum(1 for ts in cust_tokens if len(ts & set(combo)) >= 2) >= threshold
    ]
    if not combos:
        raise ValueError("customers share no frequent name tokens; cannot build trap entries")
    known = set(counter)
    pool = [t for t in TRAP_DISTINGUISHERS if t not in known]
    specs: list[_Spec] = []
    order = [combos[i] for i in rng.permutation(len(combos))]
    for k in range(n_traps):
        combo = list(order[k % len(order)])
        base = pool[k % len(pool)]
        dist = base + "".join("Z" for _ in range(k // len(pool)))  # keep tokens unique
        while dist in known:
            dist += "X"
        parts = [*combo, dist]
        shuffled = [parts[i] for i in rng.permutation(len(parts))]
        specs.append(_Spec("trap", "vi", "VN", _single(shuffled)))
    return specs


# --------------------------------------------------------------------------- aliases


def _alias_rows(
    rng: np.random.Generator, spec: _Spec, primary: str, picks: list[int]
) -> list[tuple[str, str]]:
    """Aliases (name, type) for one entry: forced ones first, at most ``MAX_ALIASES``."""
    out: list[tuple[str, str]] = []
    seen = {primary}

    def add(name: str, kind: str) -> None:
        if name and name not in seen and len(out) < MAX_ALIASES:
            seen.add(name)
            out.append((name, kind))

    for name, kind in spec.forced_aliases:
        add(name, kind)
    if spec.kind == "trap":
        return out
    if spec.origin in ("ru", "ar", "zh"):
        movable = [i for i, slot in enumerate(spec.slots) if len(slot) > 1]
        first = list(picks)
        slot_i = movable[int(rng.integers(len(movable)))]
        first[slot_i] = int(rng.integers(1, len(spec.slots[slot_i])))
        for i, slot in enumerate(spec.slots):
            if i != slot_i:
                first[i] = int(rng.integers(len(slot)))
        add(_join(spec.slots, first), "TRANSLITERATION")
        if rng.random() < SECOND_TRANSLIT_P:
            second = [int(rng.integers(len(slot))) for slot in spec.slots]
            add(_join(spec.slots, second), "TRANSLITERATION")
    parts = primary.split()
    if rng.random() < AKA_P and len(parts) > 1:
        add(" ".join([parts[0][0], *parts[1:]]), "AKA")
    if rng.random() < REORDERED_P:
        add(_rotate(primary), "REORDERED")
    return out


# --------------------------------------------------------------------------- generator


def _program(rng: np.random.Generator, list_type: str) -> str:
    return str(_pick(rng, SANCTIONS_PROGRAMS if list_type == "SANCTIONS" else PEP_PROGRAMS))


def _hit_reason(cif: str, entry_id: str, list_type: str, precision: str) -> str:
    kind = "sanctions" if list_type == "SANCTIONS" else "PEP"
    fields = "name, DOB year and nationality" if precision != "NONE" else "name and nationality"
    return f"Customer {cif} is listed as {entry_id} ({kind}); {fields} match"


def _gt_row(
    scenario: str, typology: str, suspicious: bool, kind: str, entity: str, role: str,
    start: pd.Timestamp, reason: str,
) -> dict[str, object]:  # fmt: skip
    return {
        "scenario_id": scenario, "typology": typology, "is_suspicious": suspicious,
        "entity_type": kind, "entity_id": entity, "role": role,
        "start_ts": start, "end_ts": pd.NaT, "reason": reason,
    }  # fmt: skip


def generate_watchlist(
    customers: pd.DataFrame,
    customer_person: pd.DataFrame,
    dq_defects: pd.DataFrame,
    ground_truth: pd.DataFrame,
    cfg: WatchlistConfig,
    seed: int,
    start_date: date = DEFAULT_START_DATE,
) -> WatchlistResult:
    """Generate the watchlist, its aliases and the ground-truth rows for hits and traps.

    ``customers`` is ``ActivityData.customers``; ``ground_truth`` is the 1b ground truth,
    used so that no true hit picks a person already in another case. ``start_date``
    (``data.start_date``) bounds ``listed_date``.
    """
    n = cfg.entries
    n_special = cfg.true_hits + cfg.traps
    if n < n_special:
        raise ValueError(f"entries={n} is smaller than true_hits + traps = {n_special}")
    rng = table_rng(seed, "watchlist")
    rng_alias = table_rng(seed, "watchlist_alias")

    persons = _eligible_persons(customers, customer_person, dq_defects, ground_truth)
    specs = _hit_specs(rng, customers, customer_person, persons, cfg.true_hits)
    specs += _trap_specs(rng, customers, cfg.traps)
    cust_sets = {_tokens(str(name)) for name in customers["full_name"]}
    for origin in _quota_origins(rng, n - n_special):
        nationality = _nationality(rng, origin)
        slots = _background_slots(rng, origin)
        for _ in range(MAX_BG_RETRIES):
            if not _collides(_join(slots, [0] * len(slots)), cust_sets):
                break
            slots = _background_slots(rng, origin)
        else:  # still colliding: an extra token guarantees a distinct token set
            slots = [*slots, ("JR",)]
        specs.append(_Spec("bg", origin, nationality, slots))
    specs = [specs[i] for i in rng.permutation(len(specs))]

    # list types: hits are fixed (alternating); the rest fill the 60/40 target
    fixed = sum(1 for s in specs if s.list_type == "SANCTIONS")
    free = [s for s in specs if s.list_type is None]
    n_sanc = int(np.clip(round(SANCTIONS_SHARE * n) - fixed, 0, len(free)))
    for spec, lt in zip(
        free, _quota(rng, {"SANCTIONS": n_sanc, "PEP": len(free) - n_sanc}), strict=True
    ):
        spec.list_type = lt

    n_none = round(cfg.unknown_dob_rate * n)
    n_year = round(cfg.year_only_dob_rate * n)
    precisions = _quota(rng, {"NONE": n_none, "YEAR": n_year, "DAY": n - n_none - n_year})

    min_dob = start_date - timedelta(days=MAX_AGE_YEARS * 365)
    dob_span = (MAX_AGE_YEARS - MIN_AGE_YEARS) * 365
    wl_rows: list[dict[str, object]] = []
    alias_rows: list[dict[str, object]] = []
    gt_hits: list[dict[str, object]] = []
    gt_traps: list[dict[str, object]] = []
    counters = {"SAN": 0, "PEP": 0, "TRAP": 0}

    for pos, (spec, precision) in enumerate(zip(specs, precisions, strict=True), start=1):
        entry_id = f"WL{pos:06d}"
        assert spec.list_type is not None
        picks = [0] * len(spec.slots)
        primary = _join(spec.slots, picks)
        random_dob = min_dob + timedelta(days=int(rng.integers(dob_span)))
        dob = spec.customer_dob if spec.kind == "hit" else random_dob
        assert dob is not None
        listed = start_date - timedelta(days=int(rng.integers(MIN_LISTED_DAYS, MAX_LISTED_DAYS)))
        wl_rows.append(
            {
                "entry_id": entry_id,
                "list_type": spec.list_type,
                "primary_name": primary,
                "name_origin": spec.origin,
                "dob": dob if precision == "DAY" else None,
                "dob_year": dob.year if precision != "NONE" else None,
                "dob_precision": precision,
                "nationality": spec.nationality,
                "program": _program(rng, spec.list_type),
                "listed_date": listed,
            }
        )
        for name, kind in _alias_rows(rng_alias, spec, primary, picks):
            if spec.kind == "bg" and _collides(name, cust_sets):
                continue  # background aliases must not equal a customer's token set
            alias_rows.append(
                {
                    "alias_id": f"WA{len(alias_rows) + 1:07d}",
                    "entry_id": entry_id,
                    "alias_name": name,
                    "alias_type": kind,
                }
            )
        start_ts = pd.Timestamp(listed)
        if spec.kind == "hit":
            code = "SAN" if spec.list_type == "SANCTIONS" else "PEP"
            counters[code] += 1
            sid = f"GT-{code}-{counters[code]:04d}"
            typology = "sanctions_hit" if code == "SAN" else "pep_hit"
            kind = "sanctions" if code == "SAN" else "PEP"
            gt_hits.append(
                _gt_row(
                    sid,
                    typology,
                    True,
                    "watchlist_entry",
                    entry_id,
                    "listed_entry",
                    start_ts,
                    f"Watchlist entry {entry_id} ({kind}) planted on customer "
                    f"{spec.primary_cif} and {len(spec.cifs)} CIF(s) of the same person",
                )
            )
            for cif in spec.cifs:
                reason = _hit_reason(cif, entry_id, spec.list_type, precision)
                gt_hits.append(
                    _gt_row(sid, typology, True, "customer", cif, "subject", start_ts, reason)
                )
        elif spec.kind == "trap":
            counters["TRAP"] += 1
            gt_traps.append(
                _gt_row(
                    f"GT-TRAP-{counters['TRAP']:04d}", "screening_trap", False,
                    "watchlist_entry", entry_id, "trap_entry", start_ts,
                    f"Entry {entry_id} shares common name tokens with many customers but "
                    "matches none of them",
                )
            )  # fmt: skip

    watchlist = pd.DataFrame(wl_rows, columns=WATCHLIST_COLUMNS).astype(
        {"dob_year": "Int64", "dob": object, "listed_date": object}
    )
    alias = pd.DataFrame(alias_rows, columns=ALIAS_COLUMNS)
    gt = pd.DataFrame([*gt_hits, *gt_traps], columns=GROUND_TRUTH_COLUMNS).astype(
        {
            "scenario_id": object,
            "typology": object,
            "is_suspicious": bool,
            "entity_type": object,
            "entity_id": object,
            "role": object,
            "start_ts": "datetime64[ns]",
            "end_ts": "datetime64[ns]",
            "reason": object,
        }
    )
    return WatchlistResult(watchlist, alias, gt)


def _quota_origins(rng: np.random.Generator, n: int) -> list[str]:
    """``n`` origins following ``ORIGIN_WEIGHTS`` as exactly as possible (shuffled)."""
    raw = np.asarray(ORIGIN_WEIGHTS) * n
    counts = np.floor(raw).astype(int)
    order = np.argsort(-(raw - counts), kind="stable")
    counts[order[: n - counts.sum()]] += 1
    return _quota(rng, dict(zip(ORIGINS, (int(c) for c in counts), strict=True)))
