"""AC2-AC3 for specs/entity-resolution.md: normalisation helpers, records and blocking."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from .helpers import AS_OF, duck_settings, load_tiny_duck, mod, query, truth_pairs

PHONE_907 = ["+84 90 754 7759", "0084 90 754 7759", "84907547759", "090.754.7759"]


@pytest.mark.parametrize("raw", PHONE_907)
def test_ac2_normalize_phone_variants(raw: str) -> None:
    assert mod("aml.entity_resolution.normalize").normalize_phone(raw) == "0907547759"


def test_ac2_normalize_phone_other_cases() -> None:
    normalize_phone = mod("aml.entity_resolution.normalize").normalize_phone
    assert normalize_phone("071 115 5033") == "0711155033"
    assert normalize_phone("12345") is None
    assert normalize_phone("") is None
    assert normalize_phone(None) is None


def test_ac2_normalize_id() -> None:
    normalize_id = mod("aml.entity_resolution.normalize").normalize_id
    assert normalize_id("CCCD", "063078358317") == ("CCCD", "063078358317")
    assert normalize_id("CMND", "597312816") == ("CMND", "597312816")
    assert normalize_id("PASSPORT", "y-5707628") == ("PASSPORT", "Y5707628")
    assert normalize_id("CCCD", "8087041") is None
    assert normalize_id("CMND", "063078358317") is None
    assert normalize_id("CCCD", None) is None
    assert normalize_id(None, "597312816") is None


def test_ac2_to_new_admin_unit() -> None:
    to_new = mod("aml.entity_resolution.normalize").to_new_admin_unit
    mapping = mod("aml.datagen.vn_reference").build_admin_unit_mapping()
    assert len(mapping) == 288
    assert to_new("Phường Bình Thạnh", "Quận Tân Phú", "Bà Rịa - Vũng Tàu", mapping) == (
        "Phường An Phú",
        "TP. Hồ Chí Minh",
    )
    assert to_new("Phường Thới An", "Quận Hòa Bình", "Hậu Giang", mapping) == (
        "Phường Hiệp Thành",
        "Cần Thơ",
    )
    assert to_new("Phường An Phú", None, "Hà Nội", mapping) == ("Phường An Phú", "Hà Nội")
    assert to_new("Phường X", "Quận Y", "Tỉnh Z", mapping) == ("Phường X", "Tỉnh Z")


@pytest.fixture(scope="module")
def tiny_records(
    tiny_parquet: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[tuple[Any, pd.DataFrame]]:
    db = load_tiny_duck(tiny_parquet, tmp_path_factory.mktemp("er_norm") / "tiny.duckdb")
    normalize = mod("aml.entity_resolution.normalize")
    customers = query(db, "SELECT * FROM customers")
    mapping = query(db, "SELECT * FROM admin_unit_mapping")
    records = normalize.prepare_records(customers, mapping, duck_settings(), as_of=AS_OF)
    yield db, records
    db.close()


def _rec(records: pd.DataFrame, cif: str) -> pd.Series:
    sel = records[records["cif"] == cif]
    assert len(sel) == 1, cif
    return sel.iloc[0]


def test_ac3_records_shape_and_quality_flags(tiny_records: tuple[Any, pd.DataFrame]) -> None:
    _, records = tiny_records
    assert list(records.columns) == mod("aml.entity_resolution.normalize").RECORD_COLUMNS
    assert len(records) == 300
    assert records["cif"].is_unique
    assert list(records["cif"]) == sorted(records["cif"])
    assert records["dob"].isna().sum() == 6
    assert pd.isna(_rec(records, "CIF00000277")["dob"])
    assert records["id_norm"].isna().sum() == 6
    assert pd.isna(_rec(records, "CIF00000150")["id_norm"])
    assert records["id_kind"].value_counts().to_dict() == {"CCCD": 237, "CMND": 47, "PASSPORT": 10}
    assert set(records["province_new"].dropna()) == {
        "CAN THO",
        "DA NANG",
        "DONG NAI",
        "HA NOI",
        "HAI PHONG",
        "HUE",
        "KHANH HOA",
        "TP. HO CHI MINH",
    }


def test_ac3_specific_records(tiny_records: tuple[Any, pd.DataFrame]) -> None:
    _, records = tiny_records
    r95 = _rec(records, "CIF00000095")
    assert r95["name_key"] == "LONG LY UINH"
    assert r95["dob"] == "1978-09-21"
    assert r95["phone_norm"] == "0510946265"
    assert r95["id_kind"] == "CMND"
    assert r95["id_norm"] == "597312816"
    assert r95["email_norm"] == "longl7198@gmail.com"
    assert r95["addr_key"] == "167 HAI BA TRUNG|PHUONG PHUOC LONG|HA NOI"
    for cif in ("CIF00000091", "CIF00000163"):
        r = _rec(records, cif)
        assert r["addr_key"] == "220 LY THUONG KIET|PHUONG AN PHU|TP. HO CHI MINH"
        assert r["phone_norm"] == "0907547759"


def test_ac3_blocked_pairs_and_truth_pairs_share_phone(
    tiny_records: tuple[Any, pd.DataFrame],
) -> None:
    db, records = tiny_records
    counts = mod("aml.entity_resolution.model").count_blocked_pairs(records)
    assert counts == {"phone": 53, "id": 23, "province_dob": 31, "total": 53}
    truth = truth_pairs(db)
    assert len(truth) == 32
    phone = records.set_index("cif")["phone_norm"]
    for a, b in truth:
        assert pd.notna(phone[a]) and phone[a] == phone[b], (a, b)
