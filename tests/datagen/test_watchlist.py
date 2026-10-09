"""Acceptance tests for specs/datagen-watchlist-output.md (AC1-AC4: watchlist generator)."""

from __future__ import annotations

import importlib
import re
import unicodedata
from collections import Counter
from datetime import date
from typing import Any

import pandas as pd

from aml.datagen.customers import generate_customers

SEED = 42
NAME_RE = re.compile(r"^[A-Z]+( [A-Z]+)*$")
ENTRY_RE = re.compile(r"^WL\d{6}$")
HIT_TYPOLOGIES = {"sanctions_hit", "pep_hit"}
GT_COLUMNS = [
    "scenario_id", "typology", "is_suspicious", "entity_type", "entity_id",
    "role", "start_ts", "end_ts", "reason",
]  # fmt: skip


def _wl() -> Any:
    return importlib.import_module("aml.datagen.watchlist")


def _cfg(**overrides: Any) -> Any:
    config_mod = importlib.import_module("aml.common.config")
    base: dict[str, Any] = {
        "entries": 200,
        "true_hits": 5,
        "traps": 6,
        "year_only_dob_rate": 0.30,
        "unknown_dob_rate": 0.05,
    }
    base.update(overrides)
    return config_mod.WatchlistConfig(**base)


def _empty_gt() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in GT_COLUMNS})


def _tables() -> Any:
    return generate_customers(
        n_customers=300,
        seed=SEED,
        duplicate_person_rate=0.08,
        dq_defect_rate=0.02,
        reference_date=date(2026, 6, 30),
    )


def _run(cfg: Any, ground_truth: pd.DataFrame | None = None) -> Any:
    t = _tables()
    gt = _empty_gt() if ground_truth is None else ground_truth
    return _wl().generate_watchlist(t.customers, t.customer_person, t.dq_defects, gt, cfg, SEED)


def _tokens(name: str) -> frozenset[str]:
    """Strip diacritics (incl. d-stroke), uppercase, split into a token set."""
    text = name.replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return frozenset(re.sub(r"[^A-Za-z ]", " ", text).upper().split())


def _mule_gt(cifs: list[str]) -> pd.DataFrame:
    rows = [
        {
            "scenario_id": "GT-MULE-0001",
            "typology": "mule_ring",
            "is_suspicious": True,
            "entity_type": "customer",
            "entity_id": cif,
            "role": "member",
            "start_ts": pd.Timestamp("2026-03-01"),
            "end_ts": pd.Timestamp("2026-03-20"),
            "reason": "mule ring",
        }
        for cif in cifs
    ]
    return pd.DataFrame(rows, columns=GT_COLUMNS)


def test_ac1_watchlist_shape_and_dob_consistency() -> None:
    wl = _run(_cfg()).watchlist
    assert len(wl) == 200
    assert wl["entry_id"].is_unique
    assert wl["entry_id"].map(lambda v: bool(ENTRY_RE.match(v))).all()
    assert set(wl["list_type"]) == {"SANCTIONS", "PEP"}
    assert wl["primary_name"].map(lambda v: bool(NAME_RE.match(v))).all()
    nat = wl["nationality"].dropna()
    assert nat.map(lambda v: bool(re.match(r"^[A-Z]{2}$", v))).all()
    assert (pd.to_datetime(wl["listed_date"]) < pd.Timestamp("2026-01-01")).all()
    assert set(wl["dob_precision"]) <= {"DAY", "YEAR", "NONE"}
    for row in wl.itertuples():
        if row.dob_precision == "DAY":
            assert not pd.isna(row.dob)
            assert int(row.dob_year) == pd.Timestamp(row.dob).year
        elif row.dob_precision == "YEAR":
            assert pd.isna(row.dob)
            assert not pd.isna(row.dob_year)
        else:
            assert row.dob_precision == "NONE"
            assert pd.isna(row.dob)
            assert pd.isna(row.dob_year)


def test_ac2_dob_rates_origins_and_transliteration_aliases() -> None:
    res = _run(_cfg(entries=2000))
    wl, alias = res.watchlist, res.watchlist_alias
    assert len(wl) == 2000
    share = wl["dob_precision"].value_counts(normalize=True)
    assert 0.25 <= share.get("YEAR", 0.0) <= 0.35
    assert 0.02 <= share.get("NONE", 0.0) <= 0.08
    origin = wl["name_origin"].value_counts(normalize=True)
    for o in ("ru", "ar", "zh"):
        assert origin.get(o, 0.0) >= 0.10, o

    assert alias["alias_name"].map(lambda v: bool(NAME_RE.match(v))).all()
    assert set(alias["alias_type"]) <= {"AKA", "TRANSLITERATION", "REORDERED"}
    assert set(alias["entry_id"]) <= set(wl["entry_id"])
    assert alias["alias_id"].is_unique
    assert alias.groupby("entry_id").size().max() <= 5

    translit = alias[alias["alias_type"] == "TRANSLITERATION"]
    by_entry = {eid: set(g["alias_name"]) for eid, g in translit.groupby("entry_id")}
    for row in wl[wl["name_origin"].isin(["ru", "ar", "zh"])].itertuples():
        names = by_entry.get(row.entry_id, set())
        assert any(n != row.primary_name for n in names), row.entry_id


def test_ac3_true_hits_ground_truth() -> None:
    t = _tables()
    res = _wl().generate_watchlist(
        t.customers, t.customer_person, t.dq_defects, _empty_gt(), _cfg(), SEED
    )
    gt = res.ground_truth_rows
    hits = gt[gt["typology"].isin(HIT_TYPOLOGIES)]
    assert hits["scenario_id"].nunique() == 5
    assert hits["is_suspicious"].all()

    wl = res.watchlist.set_index("entry_id")
    alias = res.watchlist_alias
    cust = t.customers.set_index("cif")
    person = t.customer_person
    defect_cifs = set(t.dq_defects["cif"])

    for sid, case in hits.groupby("scenario_id"):
        assert case["typology"].nunique() == 1
        typology = case["typology"].iloc[0]
        entry_rows = case[case["entity_type"] == "watchlist_entry"]
        assert len(entry_rows) == 1
        entry_id = entry_rows["entity_id"].iloc[0]
        entry = wl.loc[entry_id]
        expected = "sanctions_hit" if entry["list_type"] == "SANCTIONS" else "pep_hit"
        assert typology == expected, sid

        cifs = set(case[case["entity_type"] == "customer"]["entity_id"])
        assert cifs
        pid = person[person["cif"].isin(cifs)]["person_id"].unique()
        assert len(pid) == 1
        assert cifs == set(person[person["person_id"] == pid[0]]["cif"])
        assert not (cifs & defect_cifs)

        primary = person[(person["person_id"] == pid[0]) & person["is_primary"]]["cif"].iloc[0]
        c = cust.loc[primary]
        acceptable = {_tokens(entry["primary_name"])} | {
            _tokens(n) for n in alias[alias["entry_id"] == entry_id]["alias_name"]
        }
        assert _tokens(c["full_name"]) in acceptable, sid
        if not pd.isna(entry["dob_year"]):
            assert int(entry["dob_year"]) == pd.Timestamp(c["dob"]).year
        assert entry["nationality"] == c["nationality"]

        assert case["reason"].map(lambda r: isinstance(r, str) and r.strip() != "").all()


def test_ac4_trap_entries_and_mule_ring_exclusion() -> None:
    t = _tables()
    mule_cifs = list(t.customers["cif"].iloc[:10])
    res = _wl().generate_watchlist(
        t.customers, t.customer_person, t.dq_defects, _mule_gt(mule_cifs), _cfg(), SEED
    )
    gt = res.ground_truth_rows
    traps = gt[gt["typology"] == "screening_trap"]
    assert traps["scenario_id"].nunique() == 6
    assert not traps["is_suspicious"].any()
    for _, case in traps.groupby("scenario_id"):
        assert (case["entity_type"] == "watchlist_entry").sum() == 1

    cust_tokens = [_tokens(n) for n in t.customers["full_name"]]
    top10 = {tok for tok, _ in Counter(tok for ts in cust_tokens for tok in ts).most_common(10)}
    wl = res.watchlist.set_index("entry_id")
    for entry_id in traps[traps["entity_type"] == "watchlist_entry"]["entity_id"]:
        trap = _tokens(wl.loc[entry_id, "primary_name"])
        assert len(trap & top10) >= 2, entry_id
        sharing = sum(1 for ts in cust_tokens if len(trap & ts) >= 2)
        assert sharing >= 15, entry_id
        assert not any(trap <= ts for ts in cust_tokens), entry_id

    hit_cifs = set(
        gt[gt["typology"].isin(HIT_TYPOLOGIES) & (gt["entity_type"] == "customer")]["entity_id"]
    )
    assert not (hit_cifs & set(mule_cifs))
