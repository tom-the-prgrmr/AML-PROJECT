---
id: datagen-customers
status: approved
approved_by: pthieu
---

# Phase 1a — Sinh dữ liệu khách hàng tổng hợp (`aml.datagen.customers`)

## Bối cảnh
Phase 3 (screening) và Phase 4 (entity resolution) cần một tập khách hàng Việt Nam tổng hợp, có dấu,
có tần suất họ thực tế, có bản ghi trùng người (nhiều CIF) kèm nhãn ground-truth và có lỗi chất lượng dữ liệu
được cấy có kiểm soát. Spec này chỉ làm phần khách hàng; 1b (accounts/transactions/typologies) và 1c
(watchlist, Parquet, loaders, CLI `aml data`) xây trên interface thuần (hàm trả DataFrame) định nghĩa ở đây.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/datagen/customers.py
@dataclass(frozen=True)
class CustomerTables:
    customers: pd.DataFrame  # 1 dòng / CIF
    customer_person: pd.DataFrame  # ground truth ER: cif, person_id, is_primary, variations
    dq_defects: pd.DataFrame  # ground truth DQ: cif, defect_type
    admin_unit_mapping: pd.DataFrame  # old -> new đơn vị hành chính


def generate_customers(
    n_customers: int,
    seed: int,
    duplicate_person_rate: float,
    dq_defect_rate: float,
    reference_date: date,
) -> CustomerTables: ...


def generate_customers_from_settings(settings: Settings) -> CustomerTables: ...
```
- `customers` có đúng các cột: `cif, full_name, gender, dob, nationality, occupation, kyc_risk, id_type,
  id_number, phone, email, device_id, ip, address_format, street, ward, district, province, address`.
- `gender` ∈ {`M`,`F`}; `nationality` là mã ISO-3166 alpha-2 (`VN`, `CN`, `KR`, `JP`, `US`, `RU`) hoặc null;
  `kyc_risk` ∈ {`LOW`,`MEDIUM`,`HIGH`}; `id_type` ∈ {`CCCD`,`CMND`,`PASSPORT`}; `address_format` ∈ {`OLD`,`NEW`};
  `dob` kiểu `date`; `id_number`, `phone` là chuỗi (giữ số 0 đầu).
- `customer_person.variations`: chuỗi các mã cách nhau dấu phẩy, sắp xếp ABC, rỗng với bản ghi chính.
  Mã: `TYPO`, `NO_DIACRITICS`, `NAME_ORDER`, `CMND_VS_CCCD`, `PHONE_FORMAT`, `OLD_VS_NEW_ADDRESS`.
- `dq_defects.defect_type` ∈ {`MISSING_OCCUPATION`, `MISSING_NATIONALITY`, `INVALID_ID_LENGTH`, `FUTURE_DOB`}.
- `admin_unit_mapping` có cột: `old_ward, old_district, old_province, new_ward, new_province`.
- "Chuẩn hoá phone" trong AC = bỏ mọi ký tự không phải số, rồi nếu bắt đầu bằng `84` thì thay bằng `0`.

Tham số chuẩn cho test (gọi là **P_STD**): `n_customers=2000, seed=7, duplicate_person_rate=0.08,
dq_defect_rate=0.02, reference_date=date(2026, 6, 30)`. "Dòng sạch" = CIF không có dòng nào trong `dq_defects`.

## Tiêu chí nghiệm thu
- AC1: Given P_STD, When gọi `generate_customers`, Then `customers` có đúng 2000 dòng, đúng 19 cột liệt kê ở trên, `cif` duy nhất và khớp regex `^CIF\d{8}$`; `customer_person` có đúng 2000 dòng với tập `cif` bằng tập `cif` của `customers`; mỗi `person_id` có đúng 1 dòng `is_primary = True`; `admin_unit_mapping` có ít nhất 1 dòng.
- AC2: Given P_STD, When gọi `generate_customers` hai lần, Then cả 4 DataFrame của hai lần bằng nhau theo `pd.testing.assert_frame_equal`; And khi đổi `seed=8` thì `customers` khác lần chạy `seed=7` ở ít nhất 50% số dòng của cột `full_name`.
- AC3: Given P_STD, When xét các dòng `is_primary = True` có `nationality = "VN"`, Then tỉ lệ họ (token đầu của `full_name`) `Nguyễn` nằm trong [0.35, 0.41], và tỉ lệ giảm dần theo thứ tự Nguyễn > Trần > Lê > Phạm; mọi `full_name` có 2–4 token và ở dạng Unicode NFC; không dòng `gender = "M"` nào có token `Thị`; tỉ lệ dòng `gender = "F"` có token thứ hai là `Thị` ≥ 0.40.
- AC4: Given P_STD, When xét các dòng sạch, Then tuổi tại `reference_date` nằm trong [18, 80]; tỉ lệ `gender = "F"` trong [0.45, 0.55]; tỉ lệ `nationality = "VN"` trong [0.95, 0.99]; tỉ lệ `kyc_risk` LOW trong [0.65, 0.75], MEDIUM trong [0.20, 0.30], HIGH trong [0.03, 0.07]; mọi `occupation` thuộc danh sách hằng `OCCUPATIONS` của module.
- AC5: Given P_STD, When xét các dòng sạch, Then mọi dòng `nationality = "VN"` có `id_type` là `CCCD` với `id_number` khớp `^\d{12}$` hoặc `CMND` với `^\d{9}$`, tỉ lệ `CMND` trong số đó nằm trong [0.10, 0.20]; mọi dòng nước ngoài có `id_type = "PASSPORT"` và `id_number` khớp `^[A-Z0-9]{8,9}$`; với mọi CCCD, chữ số thứ 4 bằng 0 (nam sinh 19xx), 1 (nữ 19xx), 2 (nam 20xx) hoặc 3 (nữ 20xx) khớp `gender`/`dob`, và chữ số 5–6 bằng 2 số cuối năm sinh.
- AC6: Given P_STD, When chuẩn hoá `phone` của mọi dòng, Then kết quả khớp `^0[35789]\d{8}$`; `phone` gốc thuộc đúng 1 trong 4 mẫu `^0\d{9}$`, `^\+84 \d{2} \d{3} \d{4}$`, `^0\d{2} \d{3} \d{4}$`, `^0\d{2}\.\d{3}\.\d{4}$` và mỗi mẫu chiếm ≥ 10% số dòng; `email` khớp `^[a-z0-9._]+@[a-z0-9.-]+\.[a-z]{2,}$` (ASCII); `device_id` parse được bằng `uuid.UUID`; `ip` parse được bằng `ipaddress.IPv4Address` và `is_private = False`, `is_reserved = False`.
- AC7: Given P_STD, When xét địa chỉ, Then tỉ lệ `address_format = "OLD"` trong [0.40, 0.60]; dòng `OLD` có `district` khác null, dòng `NEW` có `district` null; mỗi bộ `(ward, district, province)` của dòng `OLD` xuất hiện đúng 1 lần trong `admin_unit_mapping` dưới dạng `(old_ward, old_district, old_province)`; mỗi cặp `(ward, province)` của dòng `NEW` có trong `(new_ward, new_province)`; số `new_province` phân biệt nhỏ hơn số `old_province` phân biệt; `address` chứa nguyên văn `ward` và `province` của dòng đó.
- AC8: Given P_STD, When xét `customer_person`, Then tỉ lệ `person_id` có ≥ 2 CIF nằm trong [0.07, 0.09] tổng số người; mỗi người như vậy có 2 hoặc 3 CIF; mọi dòng `is_primary = False` có `variations` không rỗng và mỗi mã trong đó thể hiện ở dữ liệu (vd `NO_DIACRITICS` -> `full_name` là ASCII và khác `full_name` bản chính; `CMND_VS_CCCD` -> `id_type` khác bản chính; `OLD_VS_NEW_ADDRESS` -> `address_format` khác bản chính); mỗi trong 6 mã xuất hiện ở ≥ 5% số dòng phụ; < 5% cặp CIF cùng người có số CIF liền nhau.
- AC9: Given P_STD, When xét `dq_defects`, Then mỗi `defect_type` có đúng `round(0.02 * 2000) = 40` dòng và dữ liệu tương ứng mang lỗi: `MISSING_OCCUPATION` -> `occupation` null, `MISSING_NATIONALITY` -> `nationality` null, `INVALID_ID_LENGTH` -> độ dài `id_number` không thuộc {9, 12} và `id_type` ≠ `PASSPORT`, `FUTURE_DOB` -> `dob > reference_date`; And mọi dòng không có trong `dq_defects` có `occupation`, `nationality` khác null và `dob ≤ reference_date`.
- AC10: Given `duplicate_person_rate=0.0` và `dq_defect_rate=0.0` (còn lại như P_STD), When gọi `generate_customers`, Then số `person_id` phân biệt = 2000, mọi dòng `is_primary = True` và `dq_defects` có 0 dòng; And Given `n_customers=0` hoặc một rate bằng `-0.1` hoặc `1.5`, When gọi hàm, Then raise `ValueError` với thông điệp chứa tên tham số sai (`n_customers`, `duplicate_person_rate` hoặc `dq_defect_rate`).
- AC11: Given `load_settings(environ={})` (profile `small`, seed 42), When gọi `generate_customers_from_settings`, Then `customers` có đúng 5000 dòng và bằng kết quả `generate_customers(5000, 42, 0.08, 0.02, date(2026, 6, 30))`; And với `AML__DATA__PROFILE=large` thì `n_customers` truyền vào là 50000 (kiểm qua monkeypatch, không sinh thật).

## Ngoài phạm vi
- Accounts, transactions, typologies, bảng `ground_truth`, lỗi duplicate transactions (spec 1b).
- Watchlist, plumbing profile dense/large cho giao dịch, ghi Parquet, loader Oracle/DuckDB, lệnh `aml data` (spec 1c).
- Khách hàng doanh nghiệp (CÔNG TY, TNHH) — chỉ cá nhân trong 1a.
- Thiết bị/phone/địa chỉ dùng chung giữa những người khác nhau (mule ring thuộc 1b).
- Khớp đúng địa lý thực ở cấp phường/xã/quận; ghi `audit_log` (sinh dữ liệu không phải quyết định tự động).
- Hàm chuẩn hoá tên/ID/phone dùng cho screening/ER (Phase 3/4) — test ở đây chỉ dùng logic chuẩn hoá tối thiểu.

## Giả định
- Không thêm dependency mới: dùng `numpy.random.default_rng` (có sẵn qua pandas) và danh sách tên/nghề tự soạn trong module; bỏ dấu bằng `unicodedata` + thay `đ/Đ`.
- `n_customers` là số dòng CIF (không phải số người); số người được suy ra sao cho tổng CIF đúng bằng `n_customers`.
- Toàn bộ dữ liệu sinh ra là tổng hợp; không dùng dữ liệu cá nhân thật.
- Ngày tham chiếu: thêm `data.reference_date: 2026-06-30` vào `config.yaml` + `DataConfig`; không dùng `date.today()` (Q1).
- Seed: một seed gốc; mỗi bảng có sub-stream `np.random.SeedSequence([seed, hash ổn định của tên bảng])` (Q2).
- CMND và CCCD của cùng người là hai số độc lập, không suy ra được từ nhau (Q6).
- Lỗi DQ: mỗi loại đúng `round(rate * n)` CIF, các loại được chồng nhau và được rơi vào CIF phụ (Q4, Q5).
- Hằng số phân bố (nước ngoài 3%, CMND 15% khách VN, KYC 70/25/5, OLD/NEW 50/50, tuổi 18–80 đều) nằm trong module, không đưa vào config (Q8).
- `admin_unit_mapping`: tên tỉnh thật (~10 tỉnh sáp nhập 2025 + vài tỉnh giữ nguyên), quận/phường tổng hợp, có gộp nhiều-một (Q7).
- `occupation` tiếng Việt có dấu, `nationality` mã ISO alpha-2; chỉ khách hàng cá nhân (Q11, Q12).

## Câu hỏi mở
- [x] Q1. Ngày tham chiếu để tính tuổi / "DOB tương lai" lấy ở đâu? — đề xuất mặc định: thêm `data.reference_date: 2026-06-30` vào `config.yaml` + `DataConfig`; không bao giờ dùng `date.today()` (sẽ phá tính tất định). — Trả lời: theo đề xuất.
- [x] Q2. Seed: config chỉ có một `seed: 42`, brief nói "seeds". — đề xuất mặc định: giữ một seed gốc, mỗi bảng dùng sub-stream `np.random.SeedSequence([seed, hash ổn định của "customers"])` để 1b/1c thêm bảng không làm đổi dữ liệu khách hàng. — Trả lời: theo đề xuất.
- [x] Q3. `customers: 5000` trong profile là số CIF hay số người thật? — đề xuất mặc định: số CIF (dòng bảng `customers`), vì 1b sinh tài khoản theo CIF và test kích thước đơn giản hơn. — Trả lời: theo đề xuất.
- [x] Q4. `dq_defect_rate=0.02` áp cho từng loại lỗi hay tổng? Số lượng chính xác hay xác suất? — đề xuất mặc định: mỗi loại lỗi đúng `round(rate * n)` CIF (chọn ngẫu nhiên theo seed, các loại có thể chồng nhau trên cùng CIF), để test so khớp chính xác. — Trả lời: theo đề xuất.
- [x] Q5. Lỗi DQ có được rơi vào CIF trùng (dòng phụ) không? — đề xuất mặc định: có, chọn độc lập — giống thực tế và làm ER khó hơn một chút. — Trả lời: theo đề xuất.
- [x] Q6. Liên kết CMND ↔ CCCD cho ER: dòng phụ dùng CMND thì số CMND có suy ra được từ CCCD không? — đề xuất mặc định: không (thực tế cũng không suy ra được); mỗi người có cả CCCD và CMND cũ, CIF nào lưu loại nào là ngẫu nhiên; ER phải dựa vào tên/DOB/phone. — Trả lời: theo đề xuất.
- [x] Q7. Mức chính xác địa lý của `admin_unit_mapping`? — đề xuất mặc định: tên tỉnh cũ/mới thật cho khoảng 10 tỉnh/thành đã sáp nhập theo cải cách 2025 (vd Bình Dương + Bà Rịa–Vũng Tàu -> TP.HCM, Hải Dương -> Hải Phòng, Quảng Nam -> Đà Nẵng) và vài tỉnh giữ nguyên (Hà Nội, Huế); quận/phường là tên tổng hợp; một số phường cũ gộp vào cùng một phường mới (nhiều-một). — Trả lời: theo đề xuất.
- [x] Q8. Tỉ lệ nước ngoài, CMND, KYC, OLD/NEW, phân bố tuổi như AC3–AC7 có đúng ý không? — đề xuất mặc định: nước ngoài 3%, CMND 15% khách VN, KYC 70/25/5, OLD/NEW 50/50, tuổi 18–80 phân bố đều; đây là hằng số trong module, không đưa vào config. — Trả lời: theo đề xuất.
- [x] Q9. Biến thể "đảo thứ tự tên" trông thế nào? — đề xuất mặc định: đưa họ xuống cuối (`Nguyễn Văn An` -> `Văn An Nguyễn`), kiểu người nước ngoài nhập tên; `TYPO` = đúng 1 phép sửa ký tự (thay/xoá/hoán vị) trong tên. — Trả lời: theo đề xuất.
- [x] Q10. Các CIF của cùng một người có chung `device_id`/`email` không? — đề xuất mặc định: chung `device_id` với xác suất 0.7, chung `email` với xác suất 0.5, còn lại sinh mới — vừa có tín hiệu cho ER vừa không quá dễ. — Trả lời: theo đề xuất.
- [x] Q11. Chuỗi nghề nghiệp và tên quốc tịch nên bằng tiếng Việt hay tiếng Anh? — đề xuất mặc định: `occupation` tiếng Việt có dấu (vd "Nhân viên văn phòng", "Kinh doanh tự do"), `nationality` mã ISO alpha-2. — Trả lời: theo đề xuất.
- [x] Q12. Có cần khách hàng doanh nghiệp ngay trong 1a (cho benign look-alike "doanh nghiệp thu tiền" và test hậu tố CÔNG TY/TNHH ở Phase 3) không? — đề xuất mặc định: không, để 1b thêm khi cần; 1a chỉ cá nhân. — Trả lời: theo đề xuất.
- [x] Q13. Spec có 11 AC (vượt mức ~10). — đề xuất mặc định: giữ nguyên vì AC10/AC11 nhỏ; nếu muốn tách thì tách AC7 + Q7 (địa chỉ & `admin_unit_mapping`) thành spec 1a-2. — Trả lời: theo đề xuất.
