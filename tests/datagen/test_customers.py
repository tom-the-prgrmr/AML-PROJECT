"""Acceptance tests for specs/datagen-customers.md (AC1-AC11)."""

from __future__ import annotations

import importlib
import ipaddress
import re
import unicodedata
import uuid
from datetime import date
from itertools import combinations

import pandas as pd
import pytest

from aml.common.config import load_settings

cust_mod = importlib.import_module("aml.datagen.customers")
CustomerTables = cust_mod.CustomerTables
generate_customers = cust_mod.generate_customers

REF = date(2026, 6, 30)
P_STD = {
    "n_customers": 2000,
    "seed": 7,
    "duplicate_person_rate": 0.08,
    "dq_defect_rate": 0.02,
    "reference_date": REF,
}
COLUMNS = [
    "cif",
    "full_name",
    "gender",
    "dob",
    "nationality",
    "occupation",
    "kyc_risk",
    "id_type",
    "id_number",
    "phone",
    "email",
    "device_id",
    "ip",
    "address_format",
    "street",
    "ward",
    "district",
    "province",
    "address",
]
VARIATION_CODES = [
    "TYPO",
    "NO_DIACRITICS",
    "NAME_ORDER",
    "CMND_VS_CCCD",
    "PHONE_FORMAT",
    "OLD_VS_NEW_ADDRESS",
]


def norm_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    return "0" + digits[2:] if digits.startswith("84") else digits


def osa_distance(a: str, b: str) -> int:
    """Optimal string alignment distance (substitute/delete/insert/adjacent swap)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def age_on(dob: date, ref: date) -> int:
    return ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))


@pytest.fixture(scope="module")
def tables() -> CustomerTables:
    return generate_customers(**P_STD)


@pytest.fixture(scope="module")
def cust(tables: CustomerTables) -> pd.DataFrame:
    return tables.customers


@pytest.fixture(scope="module")
def clean(tables: CustomerTables) -> pd.DataFrame:
    bad = set(tables.dq_defects["cif"])
    return tables.customers[~tables.customers["cif"].isin(bad)]


@pytest.fixture(scope="module")
def joined(tables: CustomerTables) -> pd.DataFrame:
    return tables.customers.merge(tables.customer_person, on="cif", how="inner")


def test_ac1_shape_columns_and_keys(tables: CustomerTables) -> None:
    c, p = tables.customers, tables.customer_person
    assert len(c) == 2000
    assert list(c.columns) == COLUMNS
    assert c["cif"].is_unique
    assert c["cif"].map(lambda x: re.fullmatch(r"CIF\d{8}", x) is not None).all()
    assert len(p) == 2000
    assert set(p["cif"]) == set(c["cif"])
    primaries = p[p["is_primary"]].groupby("person_id").size()
    assert set(primaries.index) == set(p["person_id"])
    assert (primaries == 1).all()
    assert len(tables.admin_unit_mapping) >= 1
    assert all(isinstance(d, date) for d in c["dob"])
    assert all(isinstance(x, str) for x in c["id_number"])
    assert all(isinstance(x, str) for x in c["phone"])


def test_ac2_deterministic_and_seed_sensitive(tables: CustomerTables) -> None:
    again = generate_customers(**P_STD)
    for name in ("customers", "customer_person", "dq_defects", "admin_unit_mapping"):
        pd.testing.assert_frame_equal(getattr(tables, name), getattr(again, name))
    other = generate_customers(**{**P_STD, "seed": 8})
    differs = tables.customers["full_name"].to_numpy() != other.customers["full_name"].to_numpy()
    assert differs.mean() >= 0.5


def test_ac3_vietnamese_names(joined: pd.DataFrame) -> None:
    vn = joined[joined["is_primary"] & (joined["nationality"] == "VN")]
    tokens = vn["full_name"].str.split()
    share = tokens.str[0].value_counts(normalize=True)
    assert 0.35 <= share["Nguyễn"] <= 0.41
    assert share["Nguyễn"] > share["Trần"] > share["Lê"] > share["Phạm"]
    assert tokens.map(lambda t: 2 <= len(t) <= 4).all()
    assert vn["full_name"].map(lambda s: unicodedata.is_normalized("NFC", s)).all()
    male = tokens[vn["gender"] == "M"]
    assert not male.map(lambda t: "Thị" in t).any()
    female = tokens[vn["gender"] == "F"]
    assert female.map(lambda t: len(t) > 1 and t[1] == "Thị").mean() >= 0.40


def test_ac4_demographics(clean: pd.DataFrame) -> None:
    ages = clean["dob"].map(lambda d: age_on(d, REF))
    assert ages.between(18, 80).all()
    assert 0.45 <= (clean["gender"] == "F").mean() <= 0.55
    assert 0.95 <= (clean["nationality"] == "VN").mean() <= 0.99
    kyc = clean["kyc_risk"].value_counts(normalize=True)
    assert 0.65 <= kyc["LOW"] <= 0.75
    assert 0.20 <= kyc["MEDIUM"] <= 0.30
    assert 0.03 <= kyc["HIGH"] <= 0.07
    assert clean["occupation"].isin(cust_mod.OCCUPATIONS).all()


def test_ac5_identity_documents(clean: pd.DataFrame) -> None:
    vn = clean[clean["nationality"] == "VN"]
    cccd = vn[vn["id_type"] == "CCCD"]
    cmnd = vn[vn["id_type"] == "CMND"]
    assert len(cccd) + len(cmnd) == len(vn)
    assert cccd["id_number"].map(lambda x: re.fullmatch(r"\d{12}", x) is not None).all()
    assert cmnd["id_number"].map(lambda x: re.fullmatch(r"\d{9}", x) is not None).all()
    assert 0.10 <= len(cmnd) / len(vn) <= 0.20
    foreign = clean[clean["nationality"] != "VN"]
    assert len(foreign) > 0
    assert (foreign["id_type"] == "PASSPORT").all()
    assert foreign["id_number"].map(lambda x: re.fullmatch(r"[A-Z0-9]{8,9}", x) is not None).all()
    for row in cccd.itertuples():
        century_base = 0 if row.dob.year < 2000 else 2
        expected = century_base + (0 if row.gender == "M" else 1)
        assert int(row.id_number[3]) == expected
        assert row.id_number[4:6] == f"{row.dob.year % 100:02d}"


def test_ac6_contact_and_device_fields(cust: pd.DataFrame) -> None:
    normalized = cust["phone"].map(norm_phone)
    assert normalized.str.fullmatch(r"0[35789]\d{8}").all()
    patterns = [
        r"0\d{9}",
        r"\+84 \d{2} \d{3} \d{4}",
        r"0\d{2} \d{3} \d{4}",
        r"0\d{2}\.\d{3}\.\d{4}",
    ]
    matches = pd.DataFrame({i: cust["phone"].str.fullmatch(p) for i, p in enumerate(patterns)})
    assert (matches.sum(axis=1) == 1).all()
    assert (matches.mean() >= 0.10).all()
    email_re = re.compile(r"[a-z0-9._]+@[a-z0-9.-]+\.[a-z]{2,}")
    assert cust["email"].map(lambda e: email_re.fullmatch(e) is not None and e.isascii()).all()
    for dev in cust["device_id"]:
        uuid.UUID(dev)
    for ip in cust["ip"]:
        addr = ipaddress.IPv4Address(ip)
        assert not addr.is_private
        assert not addr.is_reserved


def test_ac7_addresses_and_admin_mapping(tables: CustomerTables) -> None:
    c, m = tables.customers, tables.admin_unit_mapping
    mapping_cols = {"old_ward", "old_district", "old_province", "new_ward", "new_province"}
    assert mapping_cols <= set(m.columns)
    assert 0.40 <= (c["address_format"] == "OLD").mean() <= 0.60
    old = c[c["address_format"] == "OLD"]
    new = c[c["address_format"] == "NEW"]
    assert len(old) + len(new) == len(c)
    assert old["district"].notna().all()
    assert new["district"].isna().all()
    counts = m.groupby(["old_ward", "old_district", "old_province"]).size()
    for key in old[["ward", "district", "province"]].drop_duplicates().itertuples(index=False):
        assert counts.get(tuple(key), 0) == 1
    new_pairs = set(zip(m["new_ward"], m["new_province"], strict=True))
    for pair in new[["ward", "province"]].drop_duplicates().itertuples(index=False):
        assert tuple(pair) in new_pairs
    assert m["new_province"].nunique() < m["old_province"].nunique()
    for ward, prov, addr in zip(c["ward"], c["province"], c["address"], strict=True):
        assert ward in addr
        assert prov in addr


def test_ac8_duplicate_persons_and_variations(joined: pd.DataFrame) -> None:
    per_person = joined.groupby("person_id").size()
    assert 0.07 <= (per_person >= 2).mean() <= 0.09
    assert per_person[per_person >= 2].isin([2, 3]).all()

    primaries = joined[joined["is_primary"]].set_index("person_id")
    secondaries = joined[~joined["is_primary"]]
    assert len(secondaries) > 0
    assert (secondaries["variations"] != "").all()
    assert (primaries["variations"] == "").all()

    seen = dict.fromkeys(VARIATION_CODES, 0)
    for row in secondaries.itertuples():
        codes = row.variations.split(",")
        assert codes == sorted(codes)
        assert set(codes) <= set(VARIATION_CODES)
        prim = primaries.loc[row.person_id]
        for code in codes:
            seen[code] += 1
            if code == "NO_DIACRITICS":
                assert row.full_name.isascii()
                assert row.full_name != prim["full_name"]
            elif code == "CMND_VS_CCCD":
                assert row.id_type != prim["id_type"]
            elif code == "OLD_VS_NEW_ADDRESS":
                assert row.address_format != prim["address_format"]
            elif code == "PHONE_FORMAT":
                assert row.phone != prim["phone"]
                assert norm_phone(row.phone) == norm_phone(prim["phone"])
            elif code in ("TYPO", "NAME_ORDER"):
                assert row.full_name != prim["full_name"]
        if row.variations == "TYPO":
            assert osa_distance(row.full_name, prim["full_name"]) == 1
        if row.variations == "NAME_ORDER":
            t = prim["full_name"].split()
            assert row.full_name == " ".join(t[1:] + t[:1])
    for code, n in seen.items():
        assert n / len(secondaries) >= 0.05, code

    multi = joined[joined["person_id"].isin(per_person[per_person >= 2].index)]
    adjacent = total = 0
    for _, grp in multi.groupby("person_id"):
        nums = [int(c[3:]) for c in grp["cif"]]
        for a, b in combinations(nums, 2):
            total += 1
            adjacent += abs(a - b) == 1
    assert total > 0
    assert adjacent / total < 0.05


def test_ac9_dq_defects(tables: CustomerTables) -> None:
    c = tables.customers.set_index("cif")
    d = tables.dq_defects
    assert round(0.02 * 2000) == 40
    assert set(d["defect_type"]) == {
        "MISSING_OCCUPATION",
        "MISSING_NATIONALITY",
        "INVALID_ID_LENGTH",
        "FUTURE_DOB",
    }
    for t, n in d["defect_type"].value_counts().items():
        assert n == 40, t
    rows = {t: c.loc[g["cif"]] for t, g in d.groupby("defect_type")}
    assert rows["MISSING_OCCUPATION"]["occupation"].isna().all()
    assert rows["MISSING_NATIONALITY"]["nationality"].isna().all()
    inv = rows["INVALID_ID_LENGTH"]
    assert (~inv["id_number"].str.len().isin([9, 12])).all()
    assert (inv["id_type"] != "PASSPORT").all()
    assert rows["FUTURE_DOB"]["dob"].map(lambda x: x > REF).all()
    ok = c[~c.index.isin(set(d["cif"]))]
    assert ok["occupation"].notna().all()
    assert ok["nationality"].notna().all()
    assert ok["dob"].map(lambda x: x <= REF).all()


def test_ac10_zero_rates_and_validation() -> None:
    t = generate_customers(**{**P_STD, "duplicate_person_rate": 0.0, "dq_defect_rate": 0.0})
    assert t.customer_person["person_id"].nunique() == 2000
    assert t.customer_person["is_primary"].all()
    assert len(t.dq_defects) == 0

    bad_cases = [
        ({"n_customers": 0}, "n_customers"),
        ({"duplicate_person_rate": -0.1}, "duplicate_person_rate"),
        ({"duplicate_person_rate": 1.5}, "duplicate_person_rate"),
        ({"dq_defect_rate": -0.1}, "dq_defect_rate"),
        ({"dq_defect_rate": 1.5}, "dq_defect_rate"),
    ]
    for override, name in bad_cases:
        with pytest.raises(ValueError, match=name):
            generate_customers(**{**P_STD, **override})


def test_ac11_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(environ={})
    got = cust_mod.generate_customers_from_settings(settings)
    assert len(got.customers) == 5000
    expected = generate_customers(5000, 42, 0.08, 0.02, date(2026, 6, 30))
    pd.testing.assert_frame_equal(got.customers, expected.customers)

    captured: dict[str, object] = {}

    def fake(
        n_customers: int,
        seed: int,
        duplicate_person_rate: float,
        dq_defect_rate: float,
        reference_date: date,
    ) -> str:
        captured["n_customers"] = n_customers
        return "sentinel"

    monkeypatch.setattr(cust_mod, "generate_customers", fake)
    large = load_settings(environ={"AML__DATA__PROFILE": "large"})
    assert cust_mod.generate_customers_from_settings(large) == "sentinel"
    assert captured["n_customers"] == 50000
