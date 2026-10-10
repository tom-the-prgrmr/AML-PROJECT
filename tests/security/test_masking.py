"""AC1-AC2 for specs/oracle-security.md (Python reference masking and the DuckDB view)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from aml.common.db import DuckDb

from .helpers import mod, normalise_masked

MASKED_COLUMNS = [
    "cif", "full_name", "gender", "birth_year", "nationality", "occupation", "kyc_risk",
    "id_type", "id_number", "phone", "email", "address_format", "ward", "district", "province",
]  # fmt: skip


def test_ac1_mask_name() -> None:
    m = mod("aml.dba.masking")
    assert m.mask_name("Nguyễn Thanh Đạt") == "Nguyễn T. Đ."
    assert m.mask_name("  Vũ Thị   Phương Anh ") == "Vũ T. P. A."
    assert m.mask_name("Madonna") == "M."


def test_ac1_mask_id() -> None:
    m = mod("aml.dba.masking")
    assert m.mask_id("032084621159") == "********1159"
    assert m.mask_id("486421276") == "*****1276"
    assert m.mask_id("1234") == "****"


def test_ac1_mask_phone() -> None:
    m = mod("aml.dba.masking")
    assert m.mask_phone("085.250.0337") == "*******337"
    assert m.mask_phone("+84 912 345 678") == "********678"
    assert m.mask_phone("12") == "**"
    assert m.mask_phone("n/a") is None


def test_ac1_mask_email() -> None:
    m = mod("aml.dba.masking")
    assert m.mask_email("datn5493@icloud.com") == "d***@icloud.com"
    assert m.mask_email("khong-co-a-cong") == "***"
    assert m.mask_email("@x.com") == "***"


@pytest.mark.parametrize("fn", ["mask_name", "mask_id", "mask_phone", "mask_email"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_ac1_empty_inputs_give_none(fn: str, value: str | None) -> None:
    assert getattr(mod("aml.dba.masking"), fn)(value) is None


def test_ac1_masked_columns_constant() -> None:
    assert list(mod("aml.dba.masking").MASKED_COLUMNS) == MASKED_COLUMNS


def test_ac2_duckdb_view_matches_python_reference(duck: DuckDb, tiny_parquet: Path) -> None:
    mod("aml.datagen.load").load_parquet(duck, tiny_parquet)
    view = normalise_masked(duck.query_df("SELECT * FROM customers_masked ORDER BY cif"))
    assert list(view.columns) == MASKED_COLUMNS
    assert len(view) == 300

    customers = pd.read_parquet(tiny_parquet / "customers.parquet")
    customers = customers.sort_values("cif").reset_index(drop=True)
    expected = normalise_masked(mod("aml.dba.masking").mask_customers(customers))
    assert list(expected.columns) == MASKED_COLUMNS
    pd.testing.assert_frame_equal(view, expected)

    for col in ("id_number", "phone"):
        original = set(customers[col].dropna())
        assert original
        assert not original & set(view[col].dropna()), col
