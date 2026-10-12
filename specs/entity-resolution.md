---
id: entity-resolution
status: approved
approved_by: pthieu
---

# Phase 4 — Entity resolution: Splink trên DuckDB, `golden_customer_id`, match weights có giải thích, `aml er`

## Bối cảnh
Phase 4 của PROJECT_BRIEF.md (mục 5). Một người thật có thể có 2–3 CIF với biến thể về tên, giấy tờ, định dạng điện
thoại, địa chỉ cũ/mới. Phase này gom các CIF của cùng một người về một `golden_customer_id` bằng Splink (backend
DuckDB): chuẩn hoá bản ghi, blocking, chấm điểm theo mô hình Fellegi-Sunter, gom cụm, ghi kết quả về DB đang dùng
(Oracle hoặc DuckDB) qua abstraction `Database`, lưu match weight của từng cặp để giải thích từng cụm, ghi
`audit_log`, và báo precision/recall theo cặp và theo cụm so với ground truth của Phase 1. Lệnh `aml er` thay stub
trong `src/aml/cli.py`. Người dùng: analyst cần nhìn "một khách hàng" thay vì nhiều CIF (Phase 6 chiếu node
`Customer (golden)`, Phase 7 gộp case theo golden customer); người phỏng vấn xem số liệu và cách giải thích.
Hệ thống chỉ gắn nhãn liên kết: không sửa, không xoá, không gộp dòng nào trong `customers`.

### Hiện trạng đã kiểm trên dữ liệu Phase 1 (seed 42)
- **Ground truth** là bảng `customer_person(cif, person_id, is_primary, variations)` (không phải `ground_truth`).
  TINY: 300 CIF = 273 người; 251 người có 1 CIF, 17 người có 2, 5 người có 3 → 27 CIF phụ, **32 cặp trùng**, 22
  người nhiều CIF (49 CIF). `small`: 5000 CIF = 4545 người (4181 / 273 / 91), 455 CIF phụ, **546 cặp**, 364 người
  nhiều CIF (819 CIF). Biến thể trên CIF phụ của TINY: `NAME_ORDER` 11, `OLD_VS_NEW_ADDRESS` 8, `TYPO` 8,
  `CMND_VS_CCCD` 7, `PHONE_FORMAT` 7, `NO_DIACRITICS` 6 (một CIF có thể mang nhiều biến thể).
- **Cái gì KHÔNG đổi giữa các CIF của một người** (`src/aml/datagen/customers.py`): 10 chữ số điện thoại (chỉ đổi
  định dạng hiển thị), ngày sinh, số nhà + đường, vị trí hành chính (chỉ đổi cách viết cũ/mới). Email giữ nguyên
  với xác suất 0,5. Vì vậy dữ liệu tổng hợp **dễ hơn thực tế**: chỉ riêng blocking theo điện thoại đã phủ 32/32 cặp
  TINY và 546/546 cặp `small`.
- **CMND ↔ CCCD không có liên hệ nào trong dữ liệu**: `_id_numbers` sinh CCCD 12 số (mã tỉnh + giới tính/thế kỷ +
  2 số năm sinh + 6 số ngẫu nhiên) và CMND là 9 số ngẫu nhiên độc lập; biến thể `CMND_VS_CCCD` chỉ đổi loại giấy tờ
  được ghi trên CIF phụ. Không thể suy CMND từ CCCD hay ngược lại → blocking theo số giấy tờ chỉ bắt được cặp
  **trùng khít** (TINY 23/32 cặp, `small` 348/546) (Q6).
- **Nhiễu thật là mule ring, không phải người trùng tên**: `link_members` (typology `mule_ring`) chép nguyên điện
  thoại **hoặc** địa chỉ của thành viên đầu sang các thành viên khác. TINY: 53 cặp trùng điện thoại, chỉ 32 là cùng
  người (21 cặp là thành viên ring); 63 cặp trùng địa chỉ chuẩn hoá, 32 cùng người. `small`: 665 cặp trùng điện
  thoại (546 đúng), 1021 cặp trùng địa chỉ (542 đúng — 4 cặp trùng thật bị ring ghi đè địa chỉ). Không có cặp
  khác người nào trùng cả tên lẫn ngày sinh (TINY 21 cặp trùng tên + ngày sinh, `small` 342, đều là cùng người).
- **Lỗi DQ rơi vào cặp trùng** (TINY): `CIF00000277` có `dob = 2030-11-28` (`FUTURE_DOB`; CIF kia của người này là
  1960-01-13), `CIF00000150` có `id_number = '8087041'` (`INVALID_ID_LENGTH`). Toàn TINY: 6 CIF có `dob` sau
  `reference_date`, 6 CIF có số giấy tờ sai độ dài; `small`: 100 và 100.
- **`admin_unit_mapping`** (`old_ward, old_district, old_province → new_ward, new_province`; 288 dòng, mỗi bộ ba cũ
  xuất hiện đúng một lần, gộp nhiều-về-một): địa chỉ `OLD` có `district`, địa chỉ `NEW` có `district` null và đã mang
  tên phường/tỉnh mới. Sau khi ánh xạ cũ→mới TINY và `small` đều còn 8 tỉnh.
- **Splink chưa có trong `pyproject.toml` / `uv.lock`** → cần thêm dependency (Q2). Bản PyPI mới nhất khi viết spec
  là **Splink 5.0.0** (kéo thêm `sqlglot`; `duckdb` 1.5.6 và `pyarrow` 26.0.0 đang khoá đã thoả yêu cầu). API của 5.0
  khác 3.x/4.x: `Linker(db_api.register(df), settings)`, các bước nằm dưới `linker.training` / `linker.inference` /
  `linker.clustering`; kết quả `predict()` có `match_weight`, `match_probability`, `cif_l`, `cif_r` và một cột
  `mw_<comparison>` cho mỗi comparison (khi `retain_intermediate_calculation_columns=True`), **không có** cột `gamma_*`.
- **Prototype** của thiết kế dưới đây (script tạm ngoài repo, chạy bằng `uv run --with splink`; Splink 5.0.0,
  DuckDB 1.5.6, đọc dữ liệu qua `DuckDb` + `load_parquet`):
  - Bản ghi chuẩn hoá TINY: 6 `dob` null, 6 `id_norm` null, loại giấy tờ `CCCD` 237 / `CMND` 47 / `PASSPORT` 10.
  - Blocking TINY — điện thoại 53 cặp, số giấy tờ 23, tỉnh mới + ngày sinh 31, **hợp 53 cặp** trên 44 850 cặp có thể,
    đủ 32/32 cặp trùng; `small` — 665 / 348 / 582, hợp **736 cặp** trên 12 497 500, đủ 546/546. Nếu chặn theo
    **tỉnh đơn thuần**: TINY 6247 cặp (hợp 6266), `small` 1 782 980 cặp (hợp 1 783 094, chấm mất ~2,2 giây) (Q8).
  - Kết quả ở ngưỡng 0,95: TINY 32 cặp `MATCH`, 0 `REVIEW`, 21 cặp bị loại (xác suất cao nhất 0,0017), 273 cụm
    (22 cụm nhiều CIF) — precision = recall = 1,0 theo cặp và theo cụm; `small` 546 `MATCH`, 0 `REVIEW`, 190 cặp bị
    loại (cao nhất 0,0625), 4545 cụm (364 cụm nhiều CIF) — precision = recall = 1,0; mọi ngưỡng từ 0,5 đến 0,99 cho
    cùng kết quả. Phần Splink chạy ~0,5 giây (TINY) và ~1 giây (`small`).
  - **Huấn luyện bằng EM bị suy biến** trên dữ liệu này: vì các cặp trùng luôn khớp ngày sinh/điện thoại, EM cho
    `m = 1,0 / 0,0` (TINY: mức "khác ngày sinh" nhận weight −165, "khác điện thoại" −71) — một cặp trùng thật đổi
    số điện thoại sẽ không bao giờ được nối. Vì vậy thiết kế cố định `m` trong cấu hình và chỉ ước lượng `u` (Q3).
  - Tất định: chạy lại, đổi số luồng DuckDB (mặc định / 1 / 4) cho kết quả giống hệt. Trên TINY đổi seed cũng không
    đổi gì (44 850 cặp < `u_max_pairs` nên `u` tính trên toàn bộ cặp); trên `small` seed khác làm `u` khác (lệch
    weight tối đa 2,14 giữa seed 42 và 7) nhưng tập cụm vẫn giống hệt.
  - Bỏ comparison số giấy tờ: tập cụm TINY và `small` không đổi; khác biệt chỉ lộ ra ở kịch bản MUT (Q7).
  - Đọc `customers` + `admin_unit_mapping` từ **Oracle** (TINY đang nạp sẵn, chỉ `SELECT`) cho bản ghi chuẩn hoá, tập
    cặp và tập cụm trùng khít bản DuckDB; `dob` đọc về là `Timestamp` ở cả hai backend. **Chưa kiểm**: DDL và ghi kết
    quả xuống Oracle.
- `SCHEMA_SCRIPTS` đã dùng `000`–`080`; `090` thuộc spec 3c (`screening-oracle-incremental`, đang được hiện thực
  song song). Phase 4 dùng **`100`** và không phụ thuộc 3c. Trên Oracle `050_security_objects.sql` phải chạy cuối.
  `LEVEL`, `PRIOR`, `MODE` là từ khoá Oracle — tên cột dưới đây tránh các từ này.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class EntityResolutionConfig(BaseModel):
    match_threshold: float  # match_probability >= ngưỡng này -> MATCH (được gom cụm)
    review_threshold: float  # >= ngưỡng này và < match_threshold -> REVIEW (lưu, không gom cụm)
    name_jw_thresholds: tuple[float, float]  # hai mức Jaro-Winkler trên name_key, giảm dần
    deterministic_recall: (
        float  # recall giả định của luật tất định khi ước lượng xác suất tiên nghiệm
    )
    u_max_pairs: int  # số cặp ngẫu nhiên tối đa để ước lượng u
    m_probabilities: dict[
        str, list[float]
    ]  # comparison -> m theo từng mức (không kể mức null), tổng = 1.0


class Settings(BaseModel):
    ...
    entity_resolution: EntityResolutionConfig


# src/aml/entity_resolution/normalize.py
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


def normalize_phone(raw: str | None) -> str | None: ...  # 10 chữ số bắt đầu bằng 0, hoặc None
def normalize_id(
    id_type: str | None, id_number: str | None
) -> tuple[str, str] | None: ...  # (loại, số)
def to_new_admin_unit(
    ward: str | None, district: str | None, province: str | None, mapping: pd.DataFrame
) -> tuple[str | None, str | None]: ...  # (phường mới, tỉnh mới)
def prepare_records(
    customers: pd.DataFrame, mapping: pd.DataFrame, settings: Settings, *, as_of: date
) -> pd.DataFrame: ...  # cột = RECORD_COLUMNS, sắp theo cif


# src/aml/entity_resolution/model.py
COMPARISONS = ("name", "dob", "phone", "email", "address", "id")
BLOCKING_RULES = {
    "phone": ("phone_norm",),
    "id": ("id_norm",),
    "province_dob": ("province_new", "dob"),
}


def count_blocked_pairs(records: pd.DataFrame) -> dict[str, int]: ...


# khoá: "phone", "id", "province_dob" (đếm độc lập từng luật) và "total" (hợp, không trùng lặp)


# src/aml/entity_resolution/runner.py
ER_VERSION = "er/v1"
MATCH, REVIEW = "MATCH", "REVIEW"


class ErError(RuntimeError): ...


@dataclass(frozen=True)
class ErRun:
    run_id: int
    as_of: date
    customers_resolved: int
    blocked_pairs: int  # số cặp được Splink chấm điểm (= count_blocked_pairs(...)["total"])
    match_pairs: int
    review_pairs: int
    clusters: int  # số golden_customer_id khác nhau (kể cả cụm 1 CIF)
    merged_clusters: int  # số cụm có từ 2 CIF
    merged_cifs: int  # số CIF nằm trong các cụm đó


def run_er(db: Database, settings: Settings, *, as_of: date | None = None) -> ErRun: ...
def explain_cluster(db: Database, golden_customer_id: str) -> pd.DataFrame: ...


# các dòng er_pairs (MATCH) của lần chạy hiện hành có cả hai CIF thuộc cụm, sắp theo (cif_l, cif_r)


# src/aml/entity_resolution/evaluate.py
def evaluate_er(db: Database) -> pd.DataFrame: ...


# cột: level, predicted, truth, tp, fp, fn, precision, recall; dòng (đúng thứ tự): "pairwise", "cluster"
```
- `pyproject.toml`: thêm `splink>=5.0,<6` vào `dependencies` (và cập nhật `uv.lock`).
- `config.yaml`, mục mới `entity_resolution`:
  ```yaml
  entity_resolution:
    match_threshold: 0.95
    review_threshold: 0.50
    name_jw_thresholds: [0.92, 0.80]
    deterministic_recall: 0.9
    u_max_pairs: 1000000
    m_probabilities:
      name: [0.60, 0.25, 0.10, 0.05]     # trùng khoá tên | JW >= 0.92 | JW >= 0.80 | khác
      dob: [0.97, 0.03]                  # trùng | khác
      phone: [0.90, 0.10]                # trùng | khác
      email: [0.45, 0.55]                # trùng | khác
      address: [0.85, 0.10, 0.05]        # trùng địa chỉ chuẩn hoá | cùng tỉnh mới | khác
      id: [0.98, 0.02]                   # cùng loại và trùng số | cùng loại, khác số
  ```
- DDL `sql/duckdb/ddl/100_entity_resolution.sql` và `sql/oracle/ddl/100_entity_resolution.sql`, thêm vào
  `SCHEMA_SCRIPTS` của cả hai backend (Oracle: trước `ddl/050_security_objects.sql`; DuckDB: trước
  `ddl/050_customers_masked.sql`).
- CLI: `aml er [--as-of YYYY-MM-DD] [--eval-out PATH] [--explain GOLDEN_ID]` thay stub "arrives in Phase 4".

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Luồng `run_er`**: đọc `customers` và `admin_unit_mapping` bằng `Database.query_df` → `prepare_records` (Python)
  → Splink trên một kết nối **DuckDB in-memory riêng** (kể cả khi backend là Oracle) → ghi kết quả về `db` bằng
  `insert_df` → `audit_many`. `customers` rỗng hoặc chưa có → raise `ErError` chứa ``run `aml load` first``, không ghi
  gì. `as_of` mặc định `settings.data.reference_date`.
- **Chuẩn hoá** (`prepare_records`, một dòng cho mỗi CIF; giá trị không dùng được → `None`):
  - `name_key` = `name_key(normalize_name(full_name, settings.screening))` của Phase 3a (bỏ dấu, viết hoa, sắp token).
  - `dob` = chuỗi `YYYY-MM-DD`; `None` khi null hoặc sau `as_of`.
  - `phone_norm` = `normalize_phone(phone)`: giữ chữ số, bỏ `00` đầu, `84` + 9 số → `0` + 9 số; hợp lệ khi đúng 10
    chữ số bắt đầu bằng `0`.
  - `(id_kind, id_norm)` = `normalize_id(id_type, id_number)`: viết hoa, bỏ ký tự không phải chữ/số; hợp lệ khi
    `CCCD` có đúng 12 chữ số, `CMND` đúng 9 chữ số, `PASSPORT` từ 6 ký tự; còn lại → cả hai `None`.
  - `email_norm` = bỏ khoảng trắng hai đầu, viết thường.
  - `(phường mới, tỉnh mới)` = `to_new_admin_unit`: khi `district` khác null và bộ ba (`ward`, `district`,
    `province`) có trong `admin_unit_mapping` thì lấy (`new_ward`, `new_province`), ngược lại giữ nguyên.
    `province_new` = tỉnh mới đã bỏ dấu, viết hoa, gộp khoảng trắng; `addr_key` = `street|phường mới|tỉnh mới` (ba
    phần cùng cách chuẩn hoá đó), `None` khi `street` rỗng.
- **Blocking** (ba luật, lấy hợp; giá trị null không tạo cặp): trùng `phone_norm`; trùng `id_norm`; trùng
  (`province_new`, `dob`).
- **Comparisons** (mức đầu tiên khớp được chọn; mức null có weight 0):
  | comparison | mức null | các mức còn lại (theo thứ tự) |
  |---|---|---|
  | `name` | một phía thiếu `name_key` | trùng `name_key`; Jaro-Winkler ≥ 0,92; ≥ 0,80; khác |
  | `dob` | một phía thiếu | trùng; khác |
  | `phone` | một phía thiếu | trùng `phone_norm`; khác |
  | `email` | một phía thiếu | trùng `email_norm`; khác |
  | `address` | một phía thiếu `addr_key` | trùng `addr_key`; trùng `province_new`; khác |
  | `id` | một phía thiếu **hoặc hai phía khác `id_kind`** | trùng `id_norm`; khác |
- **Tham số mô hình**: `m` lấy từ `m_probabilities` (cố định); `u` do Splink ước lượng bằng
  `estimate_u_using_random_sampling(max_pairs=u_max_pairs, seed=settings.seed)`; xác suất tiên nghiệm bằng
  `estimate_probability_two_random_records_match` với hai luật tất định (trùng `phone_norm` + `dob`; trùng `id_norm`)
  và `recall = deterministic_recall`. Không chạy EM. Ground truth **không** tham gia bất kỳ bước nào ngoài đánh giá.
- **Quyết định theo cặp**: `match_probability >= match_threshold` → `MATCH`; `>= review_threshold` → `REVIEW`;
  thấp hơn → không ghi nhận (chỉ đếm trong `blocked_pairs`). `reason` = `match probability {p:.4f} >= {match_threshold}`
  (hoặc `< {match_threshold}` với `REVIEW`) + ` (weight {w:.2f}: prior {..:+.2f}, name {..:+.2f}, dob {..:+.2f}, phone
  {..:+.2f}, email {..:+.2f}, address {..:+.2f}, id {..:+.2f})`.
- **Gom cụm**: thành phần liên thông trên các cặp `MATCH` (`cluster_pairwise_predictions_at_threshold`); cặp `REVIEW`
  không nối cụm. `golden_customer_id` = `'G-'` + CIF nhỏ nhất (thứ tự chuỗi) của cụm; CIF không có cặp `MATCH` nào
  là cụm một phần tử (`G-<chính nó>`).
- **Bảng** (cùng tên cột trên hai backend; chỉ lưu `cif`, không lưu tên/điện thoại/số giấy tờ; không bao giờ DELETE):
  - `er_runs(run_id PK, run_ts, as_of, customers_resolved, blocked_pairs, match_pairs, review_pairs, clusters,
    merged_clusters, merged_cifs, match_threshold, review_threshold, prior_probability, version, splink_version,
    config_hash)`; `run_ts` UTC; `version = ER_VERSION`; `config_hash` = 16 ký tự hex đầu của SHA-256 trên JSON (khoá
    đã sắp xếp) của `settings.entity_resolution`. `run_id` = `MAX + 1` (tính cả trên `er_golden`, như `run_screening`).
  - `er_model(run_id, comparison, level_no, label, is_null_level, m_probability, u_probability, match_weight)`, PK
    `(run_id, comparison, level_no)`: bảng tham số đã dùng; `level_no` 0 là mức null (`m`, `u`, weight null);
    `match_weight = log2(m / u)`.
  - `er_pairs(run_id, cif_l, cif_r, match_weight, match_probability, mw_prior, mw_name, mw_dob, mw_phone, mw_email,
    mw_address, mw_id, decision, reason)`, PK `(run_id, cif_l, cif_r)`, `cif_l < cif_r`; `match_weight` =
    `mw_prior` + tổng sáu `mw_*`; weight làm tròn 4, xác suất làm tròn 6.
  - `er_golden(run_id, cif, golden_customer_id, cluster_size)`, PK `(run_id, cif)`: một dòng cho **mọi** CIF.
  - View `customer_golden` = dòng `er_golden` của lần chạy hiện hành (`run_id = MAX(run_id)` trong `er_runs`).
  - View `er_cluster_weights(golden_customer_id, cluster_size, pairs, min_match_weight, avg_match_weight, avg_mw_name,
    avg_mw_dob, avg_mw_phone, avg_mw_email, avg_mw_address, avg_mw_id)`: mỗi cụm nhiều CIF của lần chạy hiện hành một
    dòng, tổng hợp các cặp `MATCH` nằm trong cụm (làm tròn 2).
  - Thứ tự ghi: `er_model` → `er_pairs` → `er_golden` → 1 dòng `er_runs` (ghi cuối để hai view chỉ chuyển sang lần
    chạy mới khi dữ liệu đã đủ) → audit.
- **Audit** (`module='entity_resolution'`, `version=ER_VERSION`):
  - mỗi cụm nhiều CIF: `entity_type='golden_customer'`, `entity_id=<golden_customer_id>`, `decision='MERGED'`,
    `reason` = `linked {n} CIFs ({danh sách}) by {k} MATCH pair(s); weakest link {cif_l}-{cif_r} weight {w:.2f}`
    (cặp `MATCH` có weight nhỏ nhất trong cụm; hoà thì lấy cặp đứng trước theo (`cif_l`, `cif_r`)),
    `details = {run_id, cifs, pairs, min_match_weight}`;
  - mỗi cặp `REVIEW`: `entity_type='er_pair'`, `entity_id='<cif_l>:<cif_r>'`, `decision='REVIEW'`, `reason` như trong
    `er_pairs`, `details = {run_id, match_weight, match_probability}`;
  - mỗi lần chạy: `entity_type='er_run'`, `entity_id=str(run_id)`, `decision='ER_RUN_COMPLETED'`, `details` = các
    trường của `ErRun` (trừ `run_id`).
- **Đánh giá** (`evaluate_er`, trên `customer_golden` và `customer_person`; CIF không có dòng `customer_person` được
  coi là một người riêng): `pairwise` — cặp dự đoán = mọi cặp CIF cùng `golden_customer_id`, cặp thật = mọi cặp CIF
  cùng `person_id`; `cluster` — cụm dự đoán = các cụm có từ 2 CIF, cụm thật = các người có từ 2 CIF, đúng khi **tập
  CIF trùng khít**. `precision = tp / predicted` (1.0 khi `predicted = 0`), `recall = tp / truth` (1.0 khi
  `truth = 0`), làm tròn 4. Chưa có lần chạy nào → `ErError` chứa ``run `aml er` first``.

## Tiêu chí nghiệm thu
<!-- cfg = settings.entity_resolution mặc định; as_of = date(2026, 6, 30); Splink 5.0.x, DuckDB 1.5.x.
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` (300 customers, 273 người, 32 cặp trùng, seed 42).
So sánh số thực: weight làm tròn 2 chữ số, xác suất làm tròn 4.
MUT = bốn thay đổi áp lên DB (TINY) theo thứ tự:
  M1: UPDATE customers SET phone = '0901234567' WHERE cif = 'CIF00000186'
      (CIF trùng của CIF00000233 'Trần Hồng Phương', cùng số CCCD);
  M2: INSERT customers CIF90000001: full_name 'Lý Minh Long', gender 'M', dob 1978-09-21, nationality 'VN',
      id_type 'CCCD', id_number '001078000001', phone '0912345678', email 'lml@example.com', address_format 'NEW',
      street '5 Lê Lợi', ward 'Phường An Phú', district NULL, province 'Hà Nội', address '5 Lê Lợi, Phường An Phú,
      Hà Nội' (các cột còn lại của M2/M3 tuỳ ý, ER không đọc); customer_person
      (CIF90000001, P9000001) — người khác trùng tên + ngày sinh với CIF00000253 (CCCD) / CIF00000095 (CMND, tên
      lỗi gõ 'Ly Uinh Long');
  M3: INSERT customers CIF90000002: full_name 'Ngô Thị Lam', gender 'F', dob 1999-03-03, nationality 'VN',
      id_type 'CMND', id_number '123456789', email 'lam@example.com', còn phone, address_format, street, ward,
      district, province, address chép từ CIF00000002 ('Ngô Thị Lan', sinh 2003-10-31, CCCD); customer_person
      (CIF90000002, P9000002) — người nhà dùng chung điện thoại và địa chỉ;
  M4: UPDATE customers SET phone = '0934567890', address_format = 'NEW', ward = 'Phường An Phú', district = NULL,
      province = 'Huế', address = '205 Lê Lợi, Phường An Phú, Huế' WHERE cif = 'CIF00000006'
      (CIF trùng của CIF00000119 'Lê Ngọc Chi'; một bên CCCD, một bên CMND).
Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given `config.yaml`, `pyproject.toml` và thư mục `sql/` của repo cùng DuckDB rỗng (`duck`), When `load_settings(environ={})` và gọi `apply_schema(duck)` hai lần, Then `settings.entity_resolution` có `match_threshold == 0.95`, `review_threshold == 0.5`, `name_jw_thresholds == (0.92, 0.8)`, `deterministic_recall == 0.9`, `u_max_pairs == 1000000`, `m_probabilities == {"name": [0.6, 0.25, 0.1, 0.05], "dob": [0.97, 0.03], "phone": [0.9, 0.1], "email": [0.45, 0.55], "address": [0.85, 0.1, 0.05], "id": [0.98, 0.02]}`; `import splink` thành công với `splink.__version__` bắt đầu bằng `5.`; `ddl/100_entity_resolution.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]` (ở Oracle đứng trước `ddl/050_security_objects.sql`, ở DuckDB đứng trước `ddl/050_customers_masked.sql`) và resolve qua `sql_file` về đúng `sql/<backend>/`; `apply_schema` không raise; `SELECT COUNT(*)` trên `er_runs`, `er_model`, `er_pairs`, `er_golden`, `customer_golden`, `er_cluster_weights` đều trả 0; `load_settings(environ={"AML__ENTITY_RESOLUTION__REVIEW_THRESHOLD": "0.99"})` raise `pydantic.ValidationError` chứa `review_threshold must not exceed match_threshold`; và `load_settings(environ={"AML__ENTITY_RESOLUTION__M_PROBABILITIES__DOB": "[0.9, 0.2]"})` raise `pydantic.ValidationError` chứa `m_probabilities.dob must sum to 1.0`.
- AC2: Given các hàm của `aml.entity_resolution.normalize` và `mapping = build_admin_unit_mapping()` (288 dòng), When gọi từng hàm, Then `normalize_phone` trả `'0907547759'` cho cả `'+84 90 754 7759'`, `'0084 90 754 7759'`, `'84907547759'` và `'090.754.7759'`, trả `'0711155033'` cho `'071 115 5033'`, trả `None` cho `'12345'`, `''` và `None`; `normalize_id("CCCD", "063078358317") == ("CCCD", "063078358317")`, `normalize_id("CMND", "597312816") == ("CMND", "597312816")`, `normalize_id("PASSPORT", "y-5707628") == ("PASSPORT", "Y5707628")`, còn `normalize_id("CCCD", "8087041")`, `normalize_id("CMND", "063078358317")`, `normalize_id("CCCD", None)` và `normalize_id(None, "597312816")` đều trả `None`; `to_new_admin_unit("Phường Bình Thạnh", "Quận Tân Phú", "Bà Rịa - Vũng Tàu", mapping) == ("Phường An Phú", "TP. Hồ Chí Minh")`, `to_new_admin_unit("Phường Thới An", "Quận Hòa Bình", "Hậu Giang", mapping) == ("Phường Hiệp Thành", "Cần Thơ")`, `to_new_admin_unit("Phường An Phú", None, "Hà Nội", mapping) == ("Phường An Phú", "Hà Nội")` (địa chỉ định dạng mới giữ nguyên), và `to_new_admin_unit("Phường X", "Quận Y", "Tỉnh Z", mapping) == ("Phường X", "Tỉnh Z")` (bộ ba không có trong bảng giữ nguyên).
- AC3: Given TINY trong DuckDB, When gọi `prepare_records(customers, mapping, settings, as_of=as_of)` với hai DataFrame đọc bằng `duck.query_df` rồi `count_blocked_pairs(records)`, Then kết quả có đúng 300 dòng, cột bằng `RECORD_COLUMNS`, `cif` tăng dần không trùng; 6 dòng `dob` null (trong đó `CIF00000277`, `dob` gốc 2030-11-28), 6 dòng `id_norm` null (trong đó `CIF00000150`), `id_kind` có 237 `CCCD`, 47 `CMND`, 10 `PASSPORT`; `province_new` có đúng 8 giá trị `CAN THO`, `DA NANG`, `DONG NAI`, `HA NOI`, `HAI PHONG`, `HUE`, `KHANH HOA`, `TP. HO CHI MINH`; dòng `CIF00000095` có `name_key = 'LONG LY UINH'`, `dob = '1978-09-21'`, `phone_norm = '0510946265'`, `id_kind = 'CMND'`, `id_norm = '597312816'`, `email_norm = 'longl7198@gmail.com'`, `addr_key = '167 HAI BA TRUNG|PHUONG PHUOC LONG|HA NOI'`; hai dòng `CIF00000091` (địa chỉ cũ ở Bà Rịa - Vũng Tàu) và `CIF00000163` (địa chỉ mới) có cùng `addr_key = '220 LY THUONG KIET|PHUONG AN PHU|TP. HO CHI MINH'` và cùng `phone_norm = '0907547759'`; `count_blocked_pairs` trả `{"phone": 53, "id": 23, "province_dob": 31, "total": 53}`; và cả 32 cặp CIF cùng `person_id` trong `customer_person` đều có `phone_norm` bằng nhau.
- AC4: Given TINY trong DuckDB, When gọi `run_er(duck, settings)` lần đầu, Then `run.run_id = 1`, `run.as_of = date(2026, 6, 30)`, `run.customers_resolved = 300`, `run.blocked_pairs = 53`, `run.match_pairs = 32`, `run.review_pairs = 0`, `run.clusters = 273`, `run.merged_clusters = 22`, `run.merged_cifs = 49`; `er_runs` có đúng 1 dòng khớp các trường của `run`, với `version = 'er/v1'`, `match_threshold = 0.95`, `review_threshold = 0.5`, `prior_probability` làm tròn 6 bằng `0.000793`, `splink_version` bắt đầu bằng `5.`, `config_hash` dài 16 ký tự hex; `er_golden` có 300 dòng `run_id = 1` với 273 `golden_customer_id` khác nhau, 251 dòng `cluster_size = 1`, 34 dòng `cluster_size = 2`, 15 dòng `cluster_size = 3`; ba CIF `CIF00000047`, `CIF00000138`, `CIF00000268` cùng `golden_customer_id = 'G-CIF00000047'`, `CIF00000095` và `CIF00000253` cùng `'G-CIF00000095'`, `CIF00000001` có `'G-CIF00000001'` với `cluster_size = 1`; view `customer_golden` trả đúng 300 dòng đó; `er_pairs` có đúng 32 dòng, tất cả `decision = 'MATCH'`, `cif_l < cif_r`, `match_probability >= 0.9999`, và tập (`cif_l`, `cif_r`) bằng đúng tập 32 cặp CIF cùng `person_id` (không cặp nào trong 21 cặp mule ring trùng điện thoại được ghi nhận).
- AC5: Given TINY đã chạy `run_er` một lần (AC4), When đọc `er_pairs`, `er_model`, `er_cluster_weights` và gọi `explain_cluster`, Then dòng (`CIF00000095`, `CIF00000253`) có `match_weight = 24.36`, `mw_prior = -10.30`, `mw_name = 6.40`, `mw_dob = 10.31`, `mw_phone = 9.57`, `mw_email = -0.86`, `mw_address = 9.24`, `mw_id = 0.00` (CMND so với CCCD: không tính) và `reason` bằng đúng `match probability 1.0000 >= 0.95 (weight 24.36: prior -10.30, name +6.40, dob +10.31, phone +9.57, email -0.86, address +9.24, id +0.00)`; dòng (`CIF00000134`, `CIF00000277`) có `mw_dob = 0.00` (ngày sinh tương lai coi là thiếu), `mw_id = 10.28`, `match_weight = 26.69`; dòng (`CIF00000005`, `CIF00000285`) có `match_weight = 48.46`, `mw_email = 10.60`; dòng (`CIF00000110`, `CIF00000244`) có `mw_name = 1.59`, `match_weight = 29.82`; với mọi dòng, `mw_prior` cộng sáu cột `mw_*` lệch `match_weight` không quá 0.001; `er_model` có 21 dòng `run_id = 1` (`name` 5, `address` 4, bốn comparison còn lại mỗi cái 3), 6 dòng `level_no = 0` có `is_null_level` đúng và `match_weight` null, dòng (`dob`, 1) có `m_probability = 0.97`, `u_probability` làm tròn 6 bằng `0.000766`, `match_weight = 10.31`, dòng (`dob`, 2) có `match_weight = -5.06`, dòng (`id`, 2) có `match_weight = -5.64`; `er_cluster_weights` có 22 dòng, dòng `G-CIF00000047` có `cluster_size = 3`, `pairs = 3`, `min_match_weight = 37.00`, `avg_match_weight = 40.82`, `avg_mw_email = 2.96`, `avg_mw_id = 10.28`; `explain_cluster(duck, "G-CIF00000047")` trả 3 dòng theo thứ tự (`CIF00000047`, `CIF00000138`), (`CIF00000047`, `CIF00000268`), (`CIF00000138`, `CIF00000268`) với `match_weight` lần lượt 37.00, 48.46, 37.00; `explain_cluster(duck, "G-CIF00000001")` trả 0 dòng; và `explain_cluster(duck, "G-NOPE")` raise `ErError` chứa `unknown golden_customer_id`.
- AC6: Given TINY đã chạy `run_er` một lần (AC4), When đọc `audit_log`, gọi `run_er(duck, settings)` lần hai, rồi gọi lần ba với `settings` có `seed = 7`, Then sau lần đầu `audit_log` có đúng 23 dòng `module='entity_resolution'`: 22 dòng `entity_type='golden_customer'`, `decision='MERGED'`, `version='er/v1'` và 1 dòng `entity_type='er_run'`, `entity_id='1'`, `decision='ER_RUN_COMPLETED'` với `details.match_pairs = 32`, `details.review_pairs = 0`, `details.clusters = 273`, `details.merged_clusters = 22`; dòng `entity_id='G-CIF00000047'` có `reason` bằng đúng `linked 3 CIFs (CIF00000047, CIF00000138, CIF00000268) by 3 MATCH pair(s); weakest link CIF00000047-CIF00000138 weight 37.00`, `details.run_id = 1`, `details.cifs = ["CIF00000047", "CIF00000138", "CIF00000268"]`, `details.pairs = 3`; không có dòng audit nào cho cụm một CIF; lần hai trả `run_id = 2` và lần ba `run_id = 3`, cả hai có các trường còn lại bằng lần đầu; `er_golden`, `er_pairs`, `er_model` giữ đủ dòng của cả ba lần (300 / 32 / 21 dòng mỗi `run_id`, không dòng nào bị xoá hay sửa); tập (`cif`, `golden_customer_id`, `cluster_size`) và tập (`cif_l`, `cif_r`, `match_weight`, `match_probability`, `decision`, `reason`) của ba lần bằng nhau; `customer_golden` chỉ gồm 300 dòng `run_id = 3`; và mỗi lần chạy sau thêm đúng 23 dòng audit `module='entity_resolution'`.
- AC7: Given TINY đã chạy `run_er` (run 1) rồi áp MUT, When gọi `run_er(duck, settings)` lần hai, Then trả `run_id = 2`, `customers_resolved = 302`, `blocked_pairs = 55`, `match_pairs = 32`, `review_pairs = 1`, `clusters = 275`, `merged_clusters = 22`; trong `er_pairs` của `run_id = 2`: (`CIF00000186`, `CIF00000233`) vẫn `MATCH` dù khác điện thoại, với `mw_phone = -3.32`, `mw_id = 10.29`, `match_weight = 24.00`; (`CIF00000095`, `CIF90000001`) là `REVIEW` với `match_probability` trong [0.75, 0.77], `match_weight = 1.64`, `mw_id = 0.00`, `reason` bắt đầu bằng `match probability 0.75` và chứa `< 0.95`; không có dòng nào cho (`CIF00000253`, `CIF90000001`) (cùng loại CCCD, khác số → dưới ngưỡng `REVIEW`) và không có dòng nào cho (`CIF00000006`, `CIF00000119`) (không luật blocking nào bắt được); (`CIF00000002`, `CIF90000002`) là `MATCH` với `match_probability` làm tròn 3 bằng `0.998`, `match_weight = 8.99`, `mw_dob = -5.06`, `mw_id = 0.00`; trong `customer_golden`: `CIF90000001` có `'G-CIF90000001'` (`cluster_size = 1`), `CIF00000095` và `CIF00000253` vẫn cùng `'G-CIF00000095'` (`cluster_size = 2` — cặp `REVIEW` không nối cụm), `CIF00000002` và `CIF90000002` cùng `'G-CIF00000002'`, `CIF00000006` có `'G-CIF00000006'` và `CIF00000119` có `'G-CIF00000119'` (đều `cluster_size = 1`); `audit_log` thêm đúng 24 dòng `module='entity_resolution'` cho lần chạy này: 22 `MERGED`, 1 dòng `entity_type='er_pair'`, `entity_id='CIF00000095:CIF90000001'`, `decision='REVIEW'` có `reason` bằng đúng `reason` trong `er_pairs`, và 1 `ER_RUN_COMPLETED` (`entity_id='2'`); các dòng `run_id = 1` của `er_golden` (300) và `er_pairs` (32) không đổi.
- AC8: Given TINY đã chạy `run_er` một lần, When gọi `evaluate_er(duck)`, Then kết quả có đúng 2 dòng theo thứ tự `pairwise`, `cluster` với (`predicted`, `truth`, `tp`, `fp`, `fn`, `precision`, `recall`) lần lượt là (32, 32, 32, 0, 0, 1.0, 1.0) và (22, 22, 22, 0, 0, 1.0, 1.0); Given tiếp tục áp MUT rồi `run_er` lần hai, When gọi `evaluate_er(duck)`, Then dòng `pairwise` là (32, 32, 31, 1, 1, 0.9688, 0.9688) (sai: cặp gộp nhầm `CIF00000002`–`CIF90000002`; sót: `CIF00000006`–`CIF00000119`) và dòng `cluster` là (22, 22, 21, 1, 1, 0.9545, 0.9545); và Given DuckDB có TINY nhưng chưa chạy `run_er`, When gọi `evaluate_er`, Then raise `ErError` chứa ``run `aml er` first``.
- AC9: Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), When chạy `aml er --eval-out <tmp>/er_eval.csv`, Then exit code 0; stdout có một dòng tổng kết chứa `run_id=1`, `customers=300`, `blocked_pairs=53`, `MATCH=32`, `REVIEW=0`, `clusters=273`, `merged_clusters=22`; có 2 dòng đánh giá bắt đầu lần lượt bằng `pairwise` và `cluster`, dòng `pairwise` chứa `predicted=32`, `truth=32`, `precision=1.00 recall=1.00`, dòng `cluster` chứa `predicted=22`, `truth=22`, `precision=1.00 recall=1.00`; file `er_eval.csv` có dòng tiêu đề `level,predicted,truth,tp,fp,fn,precision,recall` và 2 dòng dữ liệu; When chạy tiếp `aml er --explain G-CIF00000047`, Then exit code 0, stdout có một dòng chứa `G-CIF00000047`, `cluster_size=3`, `min_match_weight=37.00` và 3 dòng cặp, dòng của `CIF00000047` `CIF00000268` chứa `weight=48.46`, `name=+8.76`, `email=+10.60`; `er_runs` vẫn chỉ có 1 dòng (`--explain` không chạy lại); When chạy `aml er --explain G-NOPE`, Then exit code 1 và stderr chứa `unknown golden_customer_id`; When chạy `aml er --as-of 2026-13-01`, Then exit code 2 và `er_runs` không thêm dòng; và Given DuckDB chỉ mới `apply_schema` (chưa `aml load`), When chạy `aml er`, Then exit code 1, stderr chứa ``run `aml load` first``, `er_runs` rỗng và `audit_log` không có dòng `entity_resolution` nào.
- AC10: [oracle] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, When gọi `run_er` với cùng `as_of = 2026-06-30` trên hai backend rồi `evaluate_er` trên Oracle, Then `customers_resolved`, `blocked_pairs`, `match_pairs`, `review_pairs`, `clusters`, `merged_clusters`, `merged_cifs` của hai `ErRun` bằng nhau (300, 53, 32, 0, 273, 22, 49); tập (`cif`, `golden_customer_id`, `cluster_size`) đọc từ `customer_golden` và tập (`cif_l`, `cif_r`, `decision`, `reason`, `match_weight` làm tròn 2) đọc từ `er_pairs` của lần chạy đó bằng nhau giữa hai backend; trên Oracle `user_tables` có `ER_RUNS`, `ER_MODEL`, `ER_PAIRS`, `ER_GOLDEN`, `user_views` có `CUSTOMER_GOLDEN`, `ER_CLUSTER_WEIGHTS`; `ER_CLUSTER_WEIGHTS` có 22 dòng và dòng `G-CIF00000047` có `min_match_weight = 37.00`, `avg_match_weight = 40.82`; số dòng `audit_log` `module='entity_resolution'` của lần chạy trên Oracle (lọc theo `details.run_id` hoặc `entity_id` của run) = 23; `evaluate_er` trên Oracle trả đúng 2 dòng như phần đầu AC8; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- Sửa, gộp hay xoá dòng trong `customers` / `accounts`; chọn "bản ghi vàng" (survivorship: tên, địa chỉ nào là chuẩn). Phase 4 chỉ gắn `golden_customer_id` cho từng CIF.
- Analyst duyệt cặp `REVIEW`, tách cụm gộp nhầm, ghi đè thủ công; hàng đợi và UI — Phase 7/9. Cặp `REVIEW` chỉ được lưu và audit.
- Dùng `golden_customer_id` ở nơi khác: gộp cảnh báo screening theo golden customer, case theo golden customer (Phase 7), node `Customer (golden)` trên Neo4j (Phase 6).
- ER tăng dần (chỉ chấm CIF mới/đổi), giữ ổn định `golden_customer_id` khi cụm đổi thành viên giữa các lần chạy; mỗi lần `aml er` là chạy lại toàn bộ.
- Huấn luyện `m` bằng EM, term-frequency adjustment cho tên phổ biến, học từ nhãn của analyst; tự tinh chỉnh ngưỡng.
- Đối chiếu CMND ↔ CCCD bằng dữ liệu ngoài (số CMND cũ in trên CCCD / mã QR), kiểm tra chéo năm sinh–giới tính mã hoá trong CCCD với `dob`/`gender`.
- Blocking và comparison theo `device_id` / `ip`; phát hiện cụm dùng chung thiết bị/điện thoại/địa chỉ (mule ring) — Phase 5.
- Chạy Splink ngay trong Oracle hoặc bản SQL/PL-SQL tương đương; biểu đồ Splink (waterfall, cluster studio).
- Kiểm soát nối bắc cầu (A–B, B–C nhưng A–C điểm thấp): cụm là thành phần liên thông đơn thuần.
- Quyền Oracle (`ROLE_GRANTS`, `020_grants.sql`) trên các bảng/view `er_*`, `customer_golden` (Q16); purge/retention cho `er_pairs`.
- Đo hiệu năng trên profile `large`; ghi số liệu vào README (làm ở bước demo từ lần chạy thật trên `small`).

## Giả định
- Dữ liệu Phase 1 giữ các tính chất ở mục "Hiện trạng" (seed 42); các AC trên TINY chỉ cam kết cho TINY seed 42 với Splink 5.0.x và DuckDB 1.5.x. Số liệu `small` trong mục Hiện trạng chỉ để định hướng, không phải cam kết.
- Mọi con số trong AC1–AC9 lấy từ prototype chạy thật (Splink 5.0.0); riêng số dòng `er_model` (21), số dòng audit (23 / 24) và các chuỗi `reason` của audit được suy ra từ thiết kế + số đo, vì prototype không ghi bảng. AC10 chưa chạy trên Oracle: mới kiểm phần **đọc** (bản ghi, cặp, cụm trùng khít DuckDB).
- `uv add "splink>=5.0,<6"` giải được với các phiên bản đang khoá (đã chạy thử bằng `uv run --with splink`, không sửa `pyproject.toml`); nếu bước hiện thực khoá ra bản Splink khác 5.0.x và số lệch, cập nhật spec chứ không sửa công thức.
- 3a đã hiện thực `normalize_name` / `name_key`; Phase 4 dùng lại cấu hình `settings.screening` cho phần chuẩn hoá tên. Phase 4 không phụ thuộc 3c.
- `as_of` mặc định là `settings.data.reference_date` (2026-06-30), không dùng đồng hồ máy ngoài `run_ts` / `event_ts` (UTC).
- `run_er` không chạy đồng thời từ hai tiến trình (`run_id` cấp bằng `MAX + 1`); `customers` vừa bộ nhớ một tiến trình (đúng với `small`; `large` 50 nghìn dòng vẫn vừa).
- Lệnh chạy dưới schema owner (`aml_owner`), đọc `customers` gốc (không qua view che PII) và đọc được `customer_person` để đánh giá; `evaluate_er` chỉ có ý nghĩa trên dữ liệu tổng hợp.
- `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có.
- Test [oracle] nạp lại TINY vào schema `aml_owner` và để lại dòng trong `er_*` / `audit_log` (bảng audit append-only nên không dọn được); vì vậy AC10 so theo `run_id` của lần chạy trong test, không giả định `run_id = 1`.

## Câu hỏi mở
- [x] Q1. Splink chạy ở đâu khi backend là Oracle? — đề xuất mặc định: luôn chạy trên một DuckDB in-memory riêng: đọc `customers` + `admin_unit_mapping` qua `Database.query_df`, chuẩn hoá bằng Python, chấm điểm trong DuckDB, rồi ghi kết quả về backend đang dùng bằng `insert_df`. Lý do: Splink không có backend Oracle; brief ghi rõ "splink (DuckDB backend)"; một đường code cho cả hai backend nên kết quả giống nhau (đã kiểm phần đọc từ Oracle). Hệ quả: PII của `customers` được kéo về bộ nhớ tiến trình Python trong lúc chạy (không ghi ra đĩa). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q2. Phiên bản Splink? — đề xuất mặc định: thêm `splink>=5.0,<6` vào `pyproject.toml` (5.0.0 là bản prototype đã chạy; kéo thêm `sqlglot`). Lý do: API 5.x khác 3.x/4.x (đăng ký bảng qua `db_api.register`, cột `mw_*` thay cho `bf_*`/`gamma_*`), nên phải chốt major; mọi số trong AC đo trên 5.0.0. Phương án thay thế: ghim 4.x nếu muốn bản đã có nhiều tài liệu hơn — khi đó phải đo lại số. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q3. Tham số mô hình lấy từ đâu? — đề xuất mặc định: `m` cố định trong `config.yaml` (bảng `m_probabilities`), `u` do Splink ước lượng từ cặp ngẫu nhiên, **không chạy EM**. Lý do: đã đo — EM trên dữ liệu này suy biến (`m` = 1,0 / 0,0, weight −165 cho "khác ngày sinh") vì cặp trùng tổng hợp không bao giờ lệch ngày sinh/điện thoại; mô hình như vậy sẽ không nối được cặp trùng thật vừa đổi số điện thoại (kịch bản M1 vẫn `MATCH` với `m` cố định). `m` cố định cũng tất định và dễ giải thích với người phỏng vấn. Các giá trị `m` đề xuất là đánh giá chuyên gia, cần người dùng chốt. Phương án thay thế: EM có chặn sàn cho `m` (thêm cấu hình và một spec nhỏ). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q4. Tính tất định và seed? — đề xuất mặc định: `estimate_u_using_random_sampling(max_pairs=u_max_pairs=1 000 000, seed=settings.seed)`; cam kết "cùng dữ liệu + cùng cấu hình + cùng seed → cùng kết quả". Lý do: đã đo chạy lại và đổi số luồng DuckDB đều cho kết quả giống hệt; trên TINY (44 850 cặp) `u` tính trên toàn bộ cặp nên không phụ thuộc seed (AC6), trên `small` (12,5 triệu cặp) seed khác cho weight lệch tới 2,14 nhưng cùng tập cụm. Phương án thay thế: nâng `u_max_pairs` để `small` cũng không phụ thuộc seed (chậm hơn chút; `large` vẫn phải lấy mẫu). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q5. Ngưỡng và vùng `REVIEW`? — đề xuất mặc định: `match_probability >= 0,95` → `MATCH` (được gom cụm); `[0,50; 0,95)` → `REVIEW` (lưu + audit, **không** gom cụm); dưới 0,50 không ghi nhận. Lý do: gộp nhầm hai người có hậu quả lớn hơn bỏ sót (Phase 7 gộp case theo golden customer) nên chỉ tự gộp khi rất chắc; trên TINY và `small` không cặp nào rơi vào vùng giữa (mọi ngưỡng 0,5–0,99 cho cùng kết quả) nên ngưỡng chỉ có tác dụng ở dữ liệu khó hơn — kịch bản M2 cho đúng 1 cặp `REVIEW` (0,76). Cần người dùng chốt khẩu vị rủi ro. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q6. "Xử lý CMND ↔ CCCD" nghĩa là gì khi dữ liệu không có liên hệ giữa hai số? — đề xuất mặc định: (a) blocking theo số giấy tờ chỉ bắt cặp trùng khít số đã chuẩn hoá; (b) khi so sánh, hai giấy tờ **khác loại** (CMND với CCCD) được coi là "không so được" (weight 0) thay vì bằng chứng chống; chỉ cùng loại mà khác số mới bị trừ điểm. Lý do: đã kiểm trong `customers.py` — CMND là 9 số ngẫu nhiên độc lập với CCCD; ngoài đời cũng không suy được số này từ số kia nếu không có trường "số CMND cũ". Hệ quả: 7 CIF `CMND_VS_CCCD` của TINY được nối nhờ điện thoại/tên/ngày sinh/địa chỉ, không nhờ giấy tờ. Phương án thay thế: sửa generator Phase 1 để CIF dùng CCCD mang thêm cột "số CMND cũ" (đổi contract 1a đã duyệt). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q7. Có thêm số giấy tờ làm comparison thứ sáu không (brief chỉ liệt kê name, DOB, phone, email, address)? — đề xuất mặc định: có, comparison `id` như Q6. Lý do: trùng số giấy tờ là bằng chứng mạnh nhất, và **khác số cùng loại** là thứ duy nhất phân biệt hai người trùng tên + ngày sinh: ở kịch bản M2, có `id` thì cặp (`CIF00000253`, `CIF90000001`) bị loại (0,24), không có `id` thì lên `REVIEW` 0,94 — sát ngưỡng gộp. Trên TINY/`small` gốc tập cụm không đổi dù có hay không. Phương án thay thế: theo đúng chữ của brief (5 comparison), số giấy tờ chỉ dùng để blocking. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q8. Luật blocking theo tỉnh? — đề xuất mặc định: tỉnh **sau ánh xạ cũ→mới** kết hợp ngày sinh (`province_new` + `dob`), bên cạnh hai luật điện thoại và số giấy tờ. Lý do: tỉnh đơn thuần chỉ có 8 giá trị nên sinh 6247 cặp trên TINY và 1,78 triệu cặp trên `small` (ước ~178 triệu trên `large`) mà không thêm cặp đúng nào; kèm ngày sinh còn 31 / 582 cặp. Luật này là lưới an toàn cho cặp đổi cả điện thoại lẫn loại giấy tờ (M2, M3 đi qua luật này/luật điện thoại). Hạn chế đã biết (M4): cặp trùng đổi điện thoại + khác loại giấy tờ + chuyển tỉnh thì không luật nào bắt được. Phương án thay thế: tỉnh đơn thuần đúng chữ brief (chấp nhận 1,78 triệu cặp, ~2 giây trên `small`). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q9. Các mức so sánh? — đề xuất mặc định: như bảng ở mục Thiết kế — tên so trên `name_key` của 3a (không phụ thuộc thứ tự, đã bỏ dấu) với hai mức Jaro-Winkler 0,92 / 0,80; ngày sinh, điện thoại, email chỉ có trùng / khác; địa chỉ có trùng địa chỉ chuẩn hoá / cùng tỉnh mới / khác. Lý do: tái dùng chuẩn hoá đã kiểm thử; `NAME_ORDER` và `NO_DIACRITICS` thành trùng khít, `TYPO` rơi vào mức JW (trên `small` EM ước 66% / 28% / 3% / 3% cặp trùng ở bốn mức tên); dữ liệu không có ngày sinh "gần đúng" nên thêm mức trung gian chỉ tạo tham số không có căn cứ. Hạn chế: lỗi gõ làm đổi vị trí token sau khi sắp xếp cho điểm JW thấp. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q10. Dữ liệu lỗi (ngày sinh tương lai, số giấy tờ sai độ dài, điện thoại không hợp lệ) xử lý thế nào? — đề xuất mặc định: coi là thiếu (`None`): không tạo cặp qua blocking và comparison tương ứng có weight 0. Lý do: nhất quán với 3b Q6 — dữ liệu KYC lỗi không được làm lệch quyết định; DQ framework đã báo riêng. Đã đo: cặp (`CIF00000134`, `CIF00000277`) vẫn `MATCH` (26,69) dù một bên có ngày sinh 2030. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q11. Định dạng `golden_customer_id`? — đề xuất mặc định: `'G-'` + CIF nhỏ nhất của cụm (vd `G-CIF00000047`); CIF đứng một mình cũng có (`G-CIF00000001`). Lý do: tất định, đọc được, không cần bảng cấp số, và thêm một CIF trùng mới (số lớn hơn) không làm đổi mã của cụm. Hạn chế: mã đổi khi CIF nhỏ nhất rời cụm hoặc hai cụm nhập làm một. Phương án thay thế: mã băm của tập CIF, hoặc số tuần tự. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q12. Lược đồ kết quả và lịch sử? — đề xuất mặc định: bốn bảng `er_runs`, `er_model`, `er_pairs`, `er_golden` (giữ mọi lần chạy theo `run_id`, không DELETE/UPDATE) và hai view `customer_golden` (lần chạy mới nhất — đây là thứ Phase 6/7 đọc) và `er_cluster_weights` (weight theo cụm). Lý do: không xoá bằng chứng của lần chạy trước; view theo `MAX(run_id)` đơn giản hơn cột `superseded_by` của screening vì ER luôn chạy lại toàn bộ; `er_model` cho phép truy ra `m`/`u` đã sinh ra từng weight. Hệ quả: mỗi lần chạy thêm 5000 dòng `er_golden` trên `small`. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q13. Cặp nào được lưu vào `er_pairs`? — đề xuất mặc định: chỉ cặp `MATCH` và `REVIEW`; cặp dưới `review_threshold` chỉ được đếm trong `blocked_pairs`. Lý do: giống 3b Q2; trên `small` là 546 trên 736 cặp. Không lưu tên/điện thoại/số giấy tờ trong bảng kết quả (như 3b Q14) — chỉ `cif` và weight. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q14. Định nghĩa precision/recall theo cặp và theo cụm? — đề xuất mặc định: theo cặp = trên mọi cặp CIF cùng `golden_customer_id` (đã tính bắc cầu) so với mọi cặp cùng `person_id`; theo cụm = **khớp chính xác tập CIF** trên các cụm có từ 2 CIF (cụm một CIF không tính). Lý do: đo đúng thứ các phase sau dùng (`golden_customer_id`); khớp chính xác dễ giải thích và nghiêm khắc nhất — ở kịch bản MUT một cụm gộp nhầm và một cụm sót cho 0,9545 trong khi B-cubed cho 0,9967. Phương án thay thế: thêm dòng `bcubed`. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q15. Mức chi tiết của audit? — đề xuất mặc định: một sự kiện `MERGED` cho mỗi cụm nhiều CIF, một sự kiện `REVIEW` cho mỗi cặp `REVIEW`, một sự kiện tổng kết mỗi lần chạy; **không** ghi sự kiện cho CIF đứng một mình và không ghi riêng từng cặp `MATCH` (đã nằm trong `er_pairs` kèm `reason`). Lý do: quyết định tự động ở đây là "gộp các CIF này thành một người"; TINY 23 dòng, `small` ~365 dòng mỗi lần chạy thay vì ~5000. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q16. Phạm vi Oracle? — đề xuất mặc định: DDL `100_entity_resolution.sql` cho cả hai backend, ghi kết quả qua `insert_df`, một AC [oracle] so khớp với DuckDB (AC10); **chưa** cấp quyền cho các role của 2b trên `er_*` / `customer_golden`. Lý do: cùng hướng với 3b Q15 (`aml er` chạy dưới owner; test 2b so `dba_tab_privs` với `ROLE_GRANTS`). Lưu ý: Phase 6 đồng bộ Neo4j qua user `readonly_graph_sync` sẽ cần `SELECT` trên `customer_golden` — bổ sung ở spec Phase 6. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q17. Hình dạng CLI? — đề xuất mặc định: `aml er` chạy toàn bộ và luôn in bảng đánh giá 2 dòng khi `customer_person` có dữ liệu; `--eval-out PATH` ghi CSV; `--explain GOLDEN_ID` chỉ đọc lần chạy hiện hành và in weight của cụm (không chạy lại). Lý do: `make er` / `tasks.ps1 er` giữ nguyên; giống `aml screen --eval-out`; "show the match weights per cluster" của brief có lệnh demo trực tiếp. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q18. Một spec hay tách 4a/4b? — đề xuất mặc định: một spec (10 AC). Lý do: chuẩn hoá, mô hình, ghi kết quả và đánh giá dùng chung một lần chạy trên TINY; tách ra sẽ lặp lại phần Hiện trạng và fixture. Nếu muốn giảm rủi ro: tách AC10 [oracle] + DDL Oracle thành 4b. — Trả lời: theo đề xuất mặc định (2026-10-11).
