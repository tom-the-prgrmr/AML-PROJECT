"""Static reference data for synthetic Vietnamese customers (all values are synthetic)."""

from __future__ import annotations

import unicodedata

import pandas as pd

# Surname -> weight (sums to 100), roughly matching real-world frequency.
SURNAME_WEIGHTS: dict[str, int] = {
    "Nguyễn": 38,
    "Trần": 11,
    "Lê": 9,
    "Phạm": 6,
    "Hoàng": 5,
    "Huỳnh": 4,
    "Phan": 4,
    "Vũ": 3,
    "Võ": 3,
    "Đặng": 3,
    "Bùi": 3,
    "Đỗ": 3,
    "Hồ": 2,
    "Ngô": 2,
    "Dương": 2,
    "Lý": 2,
}

FEMALE_MARKER = "Thị"  # female-only middle name
MALE_MIDDLE = ["Văn", "Hữu", "Đức", "Minh", "Quốc", "Ngọc", "Thanh", "Công", "Xuân", "Anh"]
FEMALE_MIDDLE = ["Ngọc", "Thanh", "Kim", "Mai", "Thu", "Phương", "Bích", "Hồng"]
MALE_GIVEN = [
    "Anh", "Bình", "Cường", "Dũng", "Hải", "Hùng", "Khánh", "Long", "Minh", "Nam",
    "Phúc", "Quang", "Sơn", "Tài", "Thắng", "Tuấn", "Việt", "Hiếu", "Đạt", "Trung",
]  # fmt: skip
FEMALE_GIVEN = [
    "Anh", "Chi", "Dung", "Hà", "Hạnh", "Hoa", "Hương", "Lan", "Linh", "Mai",
    "Ngân", "Nhung", "Phương", "Thảo", "Trang", "Trinh", "Vân", "Yến", "Quỳnh", "Huyền",
]  # fmt: skip

# nationality -> (surnames, male given names, female given names); latin script only.
FOREIGN_NAMES: dict[str, tuple[list[str], list[str], list[str]]] = {
    "CN": (["Zhang", "Wang", "Li", "Chen"], ["Wei", "Jun", "Hao"], ["Mei", "Xiu", "Lan"]),
    "KR": (["Kim", "Park", "Lee", "Choi"], ["Minjun", "Jiho", "Seojun"], ["Jiwoo", "Soyeon"]),
    "JP": (["Sato", "Suzuki", "Tanaka"], ["Haruto", "Ren", "Sota"], ["Yui", "Hana", "Aoi"]),
    "US": (["Smith", "Johnson", "Brown"], ["James", "John", "Robert"], ["Mary", "Linda"]),
    "RU": (["Ivanov", "Petrov", "Smirnov"], ["Ivan", "Dmitri", "Sergei"], ["Olga", "Anna"]),
}

OCCUPATIONS: list[str] = [
    "Nhân viên văn phòng",
    "Kinh doanh tự do",
    "Giáo viên",
    "Kỹ sư",
    "Bác sĩ",
    "Công nhân",
    "Nông dân",
    "Lái xe",
    "Kế toán",
    "Sinh viên",
    "Nội trợ",
    "Nhân viên ngân hàng",
]

STREETS = [
    "Lê Lợi",
    "Nguyễn Trãi",
    "Trần Hưng Đạo",
    "Hai Bà Trưng",
    "Lý Thường Kiệt",
    "Quang Trung",
]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com"]

# new (post-2025 merger) province -> old provinces merged into it.
PROVINCE_MERGERS: dict[str, list[str]] = {
    "TP. Hồ Chí Minh": ["TP. Hồ Chí Minh", "Bình Dương", "Bà Rịa - Vũng Tàu"],
    "Hải Phòng": ["Hải Phòng", "Hải Dương"],
    "Đà Nẵng": ["Đà Nẵng", "Quảng Nam"],
    "Cần Thơ": ["Cần Thơ", "Sóc Trăng", "Hậu Giang"],
    "Đồng Nai": ["Đồng Nai", "Bình Phước"],
    "Khánh Hòa": ["Khánh Hòa", "Ninh Thuận"],
    "Hà Nội": ["Hà Nội"],
    "Huế": ["Huế"],
}

# Synthetic units: 3 districts x 6 wards per old province; wards merge in pairs (many-to-one).
_DISTRICT_STEMS = ["Hòa Bình", "Tân Phú", "Long Thành"]
_WARD_STEMS = ["An Phú", "Bình Thạnh", "Phước Long", "Tân Hưng", "Hiệp Thành", "Thới An"]


def build_admin_unit_mapping() -> pd.DataFrame:
    """Return the old -> new administrative unit mapping (deterministic, no randomness).

    Each old ``(ward, district, province)`` tuple appears exactly once; merging is
    many-to-one on the new side (old wards ``2i`` and ``2i+1`` become one new ward,
    and several old provinces become one new province).
    """
    rows = []
    for new_province, old_provinces in PROVINCE_MERGERS.items():
        for old_province in old_provinces:
            for district in _DISTRICT_STEMS:
                for i, ward in enumerate(_WARD_STEMS):
                    rows.append(
                        {
                            "old_ward": f"Phường {ward}",
                            "old_district": f"Quận {district}",
                            "old_province": old_province,
                            "new_ward": f"Phường {_WARD_STEMS[i - i % 2]}",
                            "new_province": new_province,
                        }
                    )
    mapping = pd.DataFrame(rows)
    for col in mapping.columns:
        mapping[col] = mapping[col].map(lambda s: unicodedata.normalize("NFC", s))
    return mapping
