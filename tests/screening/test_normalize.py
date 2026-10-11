"""AC1-AC4 for specs/screening-normalize-score.md: name normalisation and the order-free key."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aml.common.db import DuckDb

from .helpers import mod, norm


def test_ac1_basic_normalisation(cfg: Any) -> None:
    assert norm("  Nguyễn   Thị  Hương ", cfg) == "NGUYEN THI HUONG"
    assert norm("Đặng Văn Đức", cfg) == "DANG VAN DUC"
    assert norm("nguyễn thị hương", cfg) == "NGUYEN THI HUONG"
    assert norm("NGUYEN THI HUONG", cfg) == "NGUYEN THI HUONG"
    assert norm(norm("Nguyễn Thị Hương", cfg), cfg) == "NGUYEN THI HUONG"


def test_ac1_nfc_and_nfd_give_same_result(cfg: Any) -> None:
    nfc = unicodedata.normalize("NFC", "Nguyễn")
    nfd = unicodedata.normalize("NFD", "Nguyễn")
    assert nfc != nfd
    assert norm(nfc, cfg) == "NGUYEN"
    assert norm(nfd, cfg) == "NGUYEN"


def test_ac1_punctuation_and_digits_become_spaces(cfg: Any) -> None:
    assert norm("O'Brien-Smith 3rd", cfg) == "O BRIEN SMITH RD"


def test_ac1_strip_diacritics_maps_d_stroke() -> None:
    strip = mod("aml.screening.normalize").strip_diacritics
    assert strip("Đặng đức") == "Dang duc"


def test_ac2_legal_terms_are_removed(cfg: Any) -> None:
    assert norm("CÔNG TY TNHH MTV Thương Mại Hoà Bình", cfg) == "THUONG MAI HOA BINH"
    assert norm("Hoa Binh Trading Co., Ltd.", cfg) == "HOA BINH TRADING"
    assert norm("Công ty CP Sữa Việt Nam", cfg) == "SUA VIET NAM"
    assert norm("ABC JSC", cfg) == "ABC"


def test_ac2_person_names_are_not_cut(cfg: Any) -> None:
    assert norm("Nguyễn Công Tý", cfg) == "NGUYEN CONG TY"
    assert norm("Nguyễn Văn Cơ", cfg) == "NGUYEN VAN CO"
    assert norm("Nguyen Cong Minh", cfg) == "NGUYEN CONG MINH"


def test_ac2_weak_terms_kept_without_strong_term_and_never_empty(cfg: Any) -> None:
    assert norm("Công ty Hoà Bình", cfg) == "CONG TY HOA BINH"
    assert norm("Công ty TNHH", cfg) == "CONG TY TNHH"


@pytest.mark.parametrize("raw", [None, "", "   ", "123 !!!", float("nan"), "Иван Петров"])
def test_ac3_unusable_input_gives_empty_string(cfg: Any, raw: Any) -> None:
    assert norm(raw, cfg) == ""


def test_ac3_name_key_of_empty_is_empty() -> None:
    assert mod("aml.screening.normalize").name_key("") == ""


def test_ac4_name_key_is_order_free_and_keeps_duplicates(cfg: Any) -> None:
    key = mod("aml.screening.normalize").name_key
    for raw in ("Xuan Thang Huynh", "Huỳnh Xuân Thắng", "THANG HUYNH XUAN"):
        assert key(norm(raw, cfg)) == "HUYNH THANG XUAN"
    assert key(norm("Đặng Anh Anh", cfg)) == "ANH ANH DANG"


def _names(db: DuckDb, sql: str) -> list[str]:
    return [str(x) for x in db.query_df(sql).iloc[:, 0]]


@pytest.fixture
def tiny_db(tiny_parquet: Path, tmp_path: Path) -> Iterator[DuckDb]:
    db = DuckDb(tmp_path / "tiny.duckdb")
    mod("aml.datagen.load").load_parquet(db, tiny_parquet)
    yield db
    db.close()


def test_ac4_tiny_watchlist_names_are_already_normalised(cfg: Any, tiny_db: DuckDb) -> None:
    names = _names(tiny_db, "SELECT primary_name FROM watchlist") + _names(
        tiny_db, "SELECT alias_name FROM watchlist_alias"
    )
    assert len(names) == 445
    for name in names:
        assert norm(name, cfg) == name


def test_ac4_tiny_customer_distinct_counts(cfg: Any, tiny_db: DuckDb) -> None:
    key = mod("aml.screening.normalize").name_key
    normed = [norm(n, cfg) for n in _names(tiny_db, "SELECT full_name FROM customers")]
    assert len(normed) == 300
    assert all(re.fullmatch(r"[A-Z]+( [A-Z]+)*", n) for n in normed)
    assert len(set(normed)) == 268
    assert len({key(n) for n in normed}) == 258


def test_ac4_tiny_ground_truth_pairs_match_by_name_key(cfg: Any, tiny_db: DuckDb) -> None:
    key = mod("aml.screening.normalize").name_key
    pairs = tiny_db.query_df(
        "SELECT s.entity_id AS cif, e.entity_id AS entry_id, c.full_name AS full_name "
        "FROM ground_truth s JOIN ground_truth e ON s.scenario_id = e.scenario_id "
        "JOIN customers c ON c.cif = s.entity_id "
        "WHERE s.typology IN ('sanctions_hit','pep_hit') "
        "AND s.role = 'subject' AND e.role = 'listed_entry'"
    )
    pairs.columns = [c.lower() for c in pairs.columns]
    assert len(pairs) == 5
    for row in pairs.itertuples():
        names = _names(
            tiny_db,
            f"SELECT primary_name FROM watchlist WHERE entry_id = '{row.entry_id}' "
            f"UNION ALL SELECT alias_name FROM watchlist_alias WHERE entry_id = '{row.entry_id}'",
        )
        keys = {key(norm(n, cfg)) for n in names}
        assert key(norm(row.full_name, cfg)) in keys, (row.cif, row.entry_id)
