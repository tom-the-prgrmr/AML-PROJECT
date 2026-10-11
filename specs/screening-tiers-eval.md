---
id: screening-tiers-eval
status: approved
approved_by: pthieu
---

# Phase 3b — Screening hai tầng: blocking, định danh phụ, quyết định có lý do, `aml screen`, đánh giá so baseline

## Bối cảnh
Phần giữa của Phase 3 (PROJECT_BRIEF.md mục 4, "Two-tier logic" và "Evaluation"); dùng `normalize_name`,
`TokenStats`, `tokens_match`, `score_names` của 3a (`specs/screening-normalize-score.md`). 3b sàng lọc toàn bộ
`customers` với `watchlist` + `watchlist_alias`: Tier 1 sinh ứng viên bằng blocking, Tier 2 dùng định danh phụ
(ngày sinh, quốc tịch, giới tính, số giấy tờ) để giảm điểm hoặc tự loại, ra quyết định `ALERT` / `REVIEW` /
`AUTO_CLEARED` kèm `reason`, lưu kết quả và ghi `audit_log`; rồi so với hai baseline ngây thơ trên ground truth
Phase 1. Hệ thống chỉ phân loại: `AUTO_CLEARED` vẫn được lưu và audit, không xoá, không đóng hồ sơ. Lệnh
`aml screen` thay stub trong `src/aml/cli.py`. Người dùng: analyst xử lý cảnh báo; người phỏng vấn xem số liệu.

### Hiện trạng đã kiểm trên dữ liệu Phase 1 (seed 42)
- **Định danh phụ có ở hai phía**: `customers` có `dob` (DATE), `nationality`, `gender`, `id_type`, `id_number`;
  `watchlist` chỉ có `dob`/`dob_year`/`dob_precision` và `nationality` — **không có `gender`, không có số giấy tờ**
  (Q1). `watchlist.dob_precision`: TINY 130 `DAY` / 60 `YEAR` / 10 `NONE`; `small` 1300 / 600 / 100;
  `watchlist.nationality` null: TINY 7, `small` 66.
- Phía khách hàng: `nationality` null TINY 6, `small` 100 (defect `MISSING_NATIONALITY`); `dob` sau
  `reference_date` 2026-06-30: TINY 6, `small` 100 (defect `FUTURE_DOB`); `dob`, `gender`, `id_number` không null.
- **Ground truth** (`ground_truth`, `typology` ∈ {`sanctions_hit`, `pep_hit`}): mỗi `scenario_id` có 1 dòng
  `entity_type='watchlist_entry'`, `role='listed_entry'` và 1 dòng `entity_type='customer'`, `role='subject'` cho
  **mỗi CIF** của người đó. TINY: 5 case = 5 cặp (CIF, entry); `small`: 20 case = 25 cặp (3 người có 2–3 CIF, kèm
  biến thể `NAME_ORDER`, `NO_DIACRITICS`, `TYPO`). Cách cài: tên y nguyên, tên xoay vòng + alias `REORDERED`, hoặc
  tên chính là tên người khác và tên thật chỉ nằm ở alias `AKA`. DOB của entry true hit lấy từ khách hàng nhưng
  `dob_precision` ngẫu nhiên (TINY: 2 `DAY`, 1 `YEAR`, 2 `NONE`); quốc tịch luôn trùng; không CIF true hit nào có
  defect DQ.
- **Trap** (`typology='screening_trap'`, chỉ có dòng `watchlist_entry`): TINY 6, `small` 30; tên = 2–3 token phổ
  biến + 1 token không khách hàng nào có (`NGUYEN THANH VAN BASHIROV`), quốc tịch `VN`, không alias.
- **Nguồn false positive thật là người trùng tên**: trên `small`, so chuỗi chuẩn hoá bằng nhau cho 137 cặp nhưng
  chỉ 24 là true hit — 113 cặp còn lại là khách hàng khác trùng họ tên với entry true hit (`Nguyễn Thị Linh`,
  `Nguyễn Vân`...) hoặc trùng tên chính ngẫu nhiên của entry kiểu "chỉ khớp qua alias". Chỉ định danh phụ mới
  phân biệt được. Trên TINY so chuỗi bằng nhau cho đúng 5 cặp, cả 5 là true hit (baseline exact hoàn hảo trên TINY).
- Baseline đo trực tiếp (ngưỡng 90, `rapidfuzz` 3.14.6): TINY — exact 5 cặp (5 TP), `token_set_ratio ≥ 90` 55 cặp
  (5 TP, 50 FP); `small` — exact 137 cặp (24 TP, recall 0,96: sót `Trầ Hữu Long`), fuzzy 4436 cặp (25 TP, 4411 FP,
  trong đó 386 cặp thuộc 19 trap entry).
- **Prototype** của thiết kế dưới đây (script tạm, không nằm trong repo): TINY — 262 cặp ứng viên trên 60 000 cặp
  (CIF × entry) có thể, 55 cặp được ghi nhận: 5 `ALERT` (đúng 5 true hit, điểm 100.0), 0 `REVIEW`, 50
  `AUTO_CLEARED` (21 "only common tokens", 28 "weak name match", 1 "DOB mismatch"); `small` — 26 676 ứng viên trên
  10 triệu cặp, 6280 cặp ghi nhận: 41 `ALERT` + 31 `REVIEW` chứa đủ 25 true hit (precision 0,347, recall 1,0; chỉ
  tính `ALERT`: precision 0,610), 6208 `AUTO_CLEARED` (356 do DOB), 446 cặp của trap đều `AUTO_CLEARED`; chạy ~2 giây.
  Prototype không cài luật giới tính / số giấy tờ (watchlist không có dữ liệu, Q1): các giá trị của AC5 suy ra từ
  luật bằng số học, không phải từ lần chạy.
- `SCHEMA_SCRIPTS` đã dùng các số `000`–`070`; trên Oracle `050_security_objects.sql` phải chạy cuối. `audit_log`
  trên Oracle có trigger append-only (2b) — screening chỉ INSERT vào đó. `ROLE_GRANTS` (2b) chưa cấp quyền cho bảng
  nào của các phase sau (`dq_*` cũng chưa).

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py — thêm vào ScreeningConfig của 3a
    alert_threshold: float  # final_score >= ngưỡng này -> ALERT
    review_threshold: float  # final_score >= ngưỡng này -> REVIEW; cũng là ngưỡng ghi nhận ứng viên
    dob_tolerance_years: int  # lệch năm sinh <= giá trị này coi là khớp
    dob_clear_years: int  # lệch năm sinh > giá trị này -> AUTO_CLEARED
    dob_gap_discount: float  # trừ điểm khi lệch năm sinh nằm trong (tolerance, clear]
    nationality_mismatch_discount: float
    gender_mismatch_discount: float


# src/aml/screening/candidates.py
def candidate_name_pairs(
    customer_norms: Iterable[str], list_norms: Iterable[str], stats: TokenStats, cfg: ScreeningConfig
) -> set[tuple[str, str]]: ...  # (tên khách hàng chuẩn hoá, tên danh sách chuẩn hoá)


# src/aml/screening/decision.py
ALERT, REVIEW, AUTO_CLEARED = "ALERT", "REVIEW", "AUTO_CLEARED"


@dataclass(frozen=True)
class Identifiers:
    dob: date | None = None
    dob_year: int | None = None  # khách hàng: năm của dob; watchlist: cột dob_year
    nationality: str | None = None
    gender: str | None = None  # watchlist Phase 1 không có -> luôn None
    id_number: str | None = None  # watchlist Phase 1 không có -> luôn None


@dataclass(frozen=True)
class Decision:
    decision: str  # ALERT | REVIEW | AUTO_CLEARED
    reason: str  # câu tiếng Anh, bắt đầu bằng một trong các cụm cố định ở mục Thiết kế
    final_score: float  # name score sau khi trừ điểm định danh phụ, làm tròn 2
    dob_gap_years: int | None  # None khi một trong hai phía không có năm sinh dùng được


def decide(
    name: NameScore, customer: Identifiers, entry: Identifiers, cfg: ScreeningConfig, *, as_of: date
) -> Decision | None: ...  # None = không ghi nhận


# src/aml/screening/runner.py
SCREENING_VERSION = "screening/v1"


class ScreeningError(RuntimeError): ...


@dataclass(frozen=True)
class ScreeningRun:
    run_id: int
    mode: str  # "FULL" (3c thêm "INCREMENTAL")
    as_of: date
    customers_screened: int
    entries_screened: int
    candidate_pairs: int  # số cặp (cif, entry_id) khác nhau có ít nhất một cặp tên ứng viên
    recorded: int  # số dòng ghi vào screening_results trong lần chạy này
    alerts: int
    reviews: int
    auto_cleared: int
    superseded: int  # số dòng của các lần chạy trước bị thay thế


def run_screening(
    db: Database,
    settings: Settings,
    *,
    as_of: date | None = None,  # mặc định settings.data.reference_date
    token_stats: TokenStats | None = None,  # None = tính từ customers hiện tại (3c truyền bản đóng băng)
) -> ScreeningRun: ...


# src/aml/screening/evaluate.py
def truth_pairs(db: Database) -> frozenset[tuple[str, str]]: ...  # (cif, entry_id) từ ground_truth
def evaluate(db: Database, settings: Settings) -> pd.DataFrame: ...
# cột: method, flagged, tp, fp, fn, precision, recall, fp_reduction_pct
# dòng (đúng thứ tự): "exact", "fuzzy", "two_tier_alert", "two_tier"
```
- `config.yaml`, mục `screening` thêm:
  ```yaml
    alert_threshold: 90
    review_threshold: 75
    dob_tolerance_years: 1
    dob_clear_years: 5
    dob_gap_discount: 15
    nationality_mismatch_discount: 15
    gender_mismatch_discount: 15
  ```
- DDL `sql/duckdb/ddl/080_screening.sql` và `sql/oracle/ddl/080_screening.sql`, thêm vào `SCHEMA_SCRIPTS` của cả hai
  backend (Oracle: đứng trước `ddl/050_security_objects.sql`; DuckDB: đứng trước `ddl/050_customers_masked.sql` —
  quy ước hiện có "security objects are applied last").
- CLI: `aml screen [--as-of YYYY-MM-DD] [--eval-out PATH]` thay stub "arrives in Phase 3".

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Bảng** (cùng tên cột trên hai backend; không lưu tên khách hàng, chỉ `cif`):
  - `screening_runs(run_id PK, run_ts, mode, as_of, customers_screened, entries_screened, candidate_pairs, recorded,
    alerts, reviews, auto_cleared, superseded, version, config_hash)`; `run_ts` UTC; `version` =
    `SCREENING_VERSION`; `config_hash` = 16 ký tự hex đầu của SHA-256 trên JSON (khoá đã sắp xếp) của
    `settings.screening` — 3c dùng để từ chối chạy incremental khi cấu hình đã đổi.
  - `screening_results(run_id, cif, entry_id, list_type, matched_name, matched_name_type, token_set, jaro_winkler,
    fuzzy_score, coverage, name_score, final_score, dob_gap_years, decision, reason, superseded_by)`, PK
    `(run_id, cif, entry_id)`; `matched_name_type` ∈ {`PRIMARY`, `AKA`, `TRANSLITERATION`, `REORDERED`};
    `superseded_by` null = dòng hiện hành, khác null = `run_id` của lần chạy đã thay nó. Dòng không bao giờ bị DELETE.
  - View `screening_current` = `screening_results WHERE superseded_by IS NULL`.
- **Tier 1 — `candidate_name_pairs`**: làm việc trên tên chuẩn hoá **khác nhau** (khử trùng trước), dùng chỉ mục
  đảo token → tên khách hàng. Mỗi token danh sách chỉ được so với các token của **từ vựng khách hàng** cùng chữ
  cái đầu và lệch độ dài ≤ `token_length_band` (`tokens_match` của 3a). Cặp (C, W) là ứng viên khi có ít nhất một
  cặp token khớp **và** một trong ba điều kiện: (a) có token khách hàng khớp là token hiếm
  (`stats.is_rare(u, rare_token_max_df_rate)`); (b) mọi token của W đều có token khớp trong C; (c) mọi token của C
  đều có token khớp trong W. (b)/(c) giữ lại các tên chỉ gồm token phổ biến (`NGUYEN VAN`) để chúng được chấm
  điểm và loại có lý do.
- **Ghép về (cif, entry_id)**: tên của một entry = `primary_name` (loại `PRIMARY`) + mọi alias (loại =
  `alias_type`). Với mỗi cặp (cif, entry), trong các tên ứng viên có `fuzzy >= review_threshold` chọn tên tốt nhất
  theo (`score` giảm, `fuzzy` giảm, `PRIMARY` trước, tên tăng dần). Không có tên nào đạt → cặp **không được ghi
  nhận** (chỉ tính vào `candidate_pairs`).
- **Tier 2 — `decide`**, áp dụng theo thứ tự, dừng ở luật đầu tiên khớp (cụm in đậm là phần đầu cố định của `reason`):
  1. `name.fuzzy < review_threshold` → `None`.
  2. Số giấy tờ hai phía đều khác null và bằng nhau sau khi viết hoa, bỏ ký tự không phải chữ/số → `ALERT`,
     **`ID number match`**, `final_score = 100.0`.
  3. `name.score < review_threshold` → `AUTO_CLEARED`; **`only common tokens matched`** nếu `name.common_only`,
     ngược lại **`weak name match`**; `final_score = name.score`.
  4. Năm sinh: phía khách hàng dùng được khi `dob` khác null và `dob <= as_of`; phía danh sách khi `dob_year` khác
     null. Cả hai dùng được → `gap = |năm sinh khách hàng − dob_year|`, ngược lại `gap = None`.
     `gap > dob_clear_years` → `AUTO_CLEARED`, **`DOB mismatch > {dob_clear_years}y`**, `final_score = name.score`.
  5. `final = name.score` trừ `dob_gap_discount` nếu `gap > dob_tolerance_years`, trừ
     `nationality_mismatch_discount` nếu quốc tịch hai phía đều khác null và khác nhau, trừ
     `gender_mismatch_discount` nếu giới tính hai phía đều khác null và khác nhau.
  6. `final >= alert_threshold` → `ALERT`, **`strong name match`**; `final >= review_threshold` → `REVIEW`,
     **`possible name match`**; còn lại → `AUTO_CLEARED`, **`discounted below review threshold`**.
  Sau cụm cố định, `reason` ghi thêm trong ngoặc: name score, final score, trạng thái DOB (`DOB unknown` /
  `DOB gap 2y`), và các định danh lệch (vd `nationality VN vs RU`).
- **`run_screening`**: đọc `customers`, `watchlist`, `watchlist_alias` qua `Database.query_df`; một trong ba bảng
  này rỗng hoặc chưa có → raise `ScreeningError` chứa ``run `aml load` first``, không ghi gì. `run_id` =
  `COALESCE(MAX(run_id), 0) + 1` trên `screening_runs`. Thứ tự ghi: đánh dấu mọi dòng hiện hành
  `superseded_by = run_id` → `insert_df` kết quả mới → 1 dòng `screening_runs` → `audit_many`.
- **Audit**: mỗi dòng ghi nhận một sự kiện `module='screening'`, `entity_type='screening_match'`,
  `entity_id='<cif>:<entry_id>'`, `decision` và `reason` như trong bảng, `version=SCREENING_VERSION`,
  `details = {run_id, name_score, final_score, matched_name, list_type}`; thêm 1 sự kiện mỗi lần chạy:
  `entity_type='screening_run'`, `entity_id=str(run_id)`, `decision='SCREENING_RUN_COMPLETED'`,
  `details = {mode, as_of, customers, entries, candidate_pairs, recorded, alerts, reviews, auto_cleared, superseded}`.
- **Đánh giá** (mức cặp (cif, entry_id); ground truth = `truth_pairs`):
  - `exact`: `normalize_name(full_name)` bằng đúng chuỗi một tên của entry (có phân biệt thứ tự token).
  - `fuzzy`: `rapidfuzz.fuzz.token_set_ratio(normalize_name(full_name), tên) >= alert_threshold` với ít nhất một
    tên của entry; không IDF, không blocking, không Tier 2.
  - `two_tier_alert`: `screening_current.decision = 'ALERT'`; `two_tier`: `decision IN ('ALERT', 'REVIEW')`.
  - `precision = tp / flagged` (1.0 khi `flagged = 0`), `recall = tp / số cặp ground truth` (1.0 khi không có),
    làm tròn 4; `fp_reduction_pct = round(100 * (1 − fp / fp của fuzzy), 2)`, `None` khi fuzzy có `fp = 0`.

## Tiêu chí nghiệm thu
<!-- cfg = settings.screening mặc định (3a + các khoá ở mục Interface); as_of = date(2026, 6, 30).
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` (300 customers, 200 watchlist, 245 alias, seed 42).
BASE = 8 tên của spec 3a ("Nguyễn Văn An", "Nguyễn Văn Bình", "Nguyễn Thị Hoa", "Trần Văn Long", "Trần Hữu Long",
"Lê Thị Hoa", "Phạm Quốc Bảo", "Đỗ Xuân Sơn"), STATS = build_token_stats của BASE đã chuẩn hoá.
N(fuzzy, score, common_only=False) = NameScore(token_set=fuzzy, jaro_winkler=fuzzy, fuzzy=fuzzy,
coverage=round(score / fuzzy, 4), score=score, matched=("X",), common_only=common_only).
C = Identifiers(dob=date(1971, 2, 15), dob_year=1971, nationality="VN"); E(year) = Identifiers(dob_year=year,
nationality="VN"). TRAPS = 6 entry_id có typology 'screening_trap' trong ground_truth của TINY.
Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given `config.yaml` và thư mục `sql/` của repo cùng DuckDB rỗng (`duck`), When `load_settings(environ={})` và gọi `apply_schema(duck)` hai lần, Then `settings.screening` có `alert_threshold == 90`, `review_threshold == 75`, `dob_tolerance_years == 1`, `dob_clear_years == 5`, `dob_gap_discount == 15`, `nationality_mismatch_discount == 15`, `gender_mismatch_discount == 15`; `ddl/080_screening.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]` (ở Oracle đứng trước `ddl/050_security_objects.sql`) và resolve qua `sql_file` về đúng `sql/<backend>/`; `apply_schema` không raise; `SELECT COUNT(*)` trên `screening_runs`, `screening_results`, `screening_current` đều trả 0; và `load_settings(environ={"AML__SCREENING__REVIEW_THRESHOLD": "95"})` raise `pydantic.ValidationError` chứa `review_threshold must not exceed alert_threshold`.
- AC2: Given `STATS` của BASE, `cfg` với `rare_token_max_df_rate = 0.25` và danh sách tên `["TRAN HUU LONG", "NGUYEN VAN BASHIROV", "NGUYEN VAN", "SON DO XUAN", "MUHAMMAD AL RASHID"]`, When gọi `candidate_name_pairs` với 8 tên BASE đã chuẩn hoá, Then kết quả là đúng 5 cặp: (`TRAN VAN LONG`, `TRAN HUU LONG`), (`TRAN HUU LONG`, `TRAN HUU LONG`), (`NGUYEN VAN AN`, `NGUYEN VAN`), (`NGUYEN VAN BINH`, `NGUYEN VAN`), (`DO XUAN SON`, `SON DO XUAN`) — `NGUYEN VAN BASHIROV` và `MUHAMMAD AL RASHID` không có ứng viên nào; và Given TINY với `cfg` mặc định và `customer_token_stats`, When gọi `candidate_name_pairs` cho mọi tên khách hàng × mọi tên watchlist/alias, Then với cả 5 cặp ground truth tồn tại một cặp ứng viên (tên của CIF, một tên của entry), và số cặp (cif, entry_id) khác nhau suy ra từ kết quả không vượt quá 600 (1% của 300 × 200 = 60 000).
- AC3: Given `cfg` mặc định, `C` và `E(1971)`, When gọi `decide(name, C, E(1971), cfg, as_of=as_of)`, Then `N(74.88, 44.45)` trả `None`; `N(97.08, 45.14, common_only=True)` trả `AUTO_CLEARED` với `reason` bắt đầu bằng `only common tokens matched` và `final_score = 45.14`; `N(97.08, 45.14)` trả `AUTO_CLEARED` với `reason` bắt đầu bằng `weak name match`; `N(75.0, 75.0)` và `N(95.0, 89.99)` trả `REVIEW` với `reason` bắt đầu bằng `possible name match`; `N(90.0, 90.0)` và `N(100.0, 100.0)` trả `ALERT` với `reason` bắt đầu bằng `strong name match`, `final_score` lần lượt 90.0 và 100.0, `dob_gap_years = 0`.
- AC4: Given `cfg` mặc định và `name = N(100.0, 100.0)`, When gọi `decide(name, customer, entry, cfg, as_of=as_of)`, Then với `customer = C`: `E(1972)` → `ALERT`, `final_score = 100.0`, `dob_gap_years = 1`; `E(1973)` → `REVIEW`, `final_score = 85.0`, `dob_gap_years = 2`; `E(1976)` → `REVIEW`, `final_score = 85.0`, `dob_gap_years = 5`; `E(1977)` → `AUTO_CLEARED`, `reason` bắt đầu bằng `DOB mismatch > 5y`, `final_score = 100.0`, `dob_gap_years = 6`; `E(None)` (entry không có năm sinh) → `ALERT`, `dob_gap_years is None`; `Identifiers(dob=date(1971, 8, 30), dob_year=1971, nationality="VN")` (đủ ngày, cùng năm khác ngày) → `ALERT`, `dob_gap_years = 0`; và với khách hàng có `dob = date(2033, 1, 20)` (sau `as_of`) hoặc `dob = None`, `E(1951)` → `ALERT`, `final_score = 100.0`, `dob_gap_years is None`.
- AC5: Given `cfg` mặc định, `name = N(100.0, 100.0)` và `C`, When gọi `decide`, Then entry `Identifiers(dob_year=1971, nationality="RU")` → `REVIEW`, `final_score = 85.0`, `reason` chứa `nationality VN vs RU`; entry `Identifiers(dob_year=1973, nationality="RU")` → `AUTO_CLEARED`, `final_score = 70.0`, `reason` bắt đầu bằng `discounted below review threshold`; khách hàng có `nationality = None` với entry `nationality="RU"`, `dob_year=1971` → `ALERT`, `final_score = 100.0`; khách hàng `gender="M"` với entry `gender="F"`, `dob_year=1971`, `nationality="VN"` → `REVIEW`, `final_score = 85.0`, còn entry `gender=None` → `ALERT`; và với `name = N(80.0, 60.0)`, khách hàng `id_number="B1234567"`, entry `Identifiers(dob_year=1991, nationality="RU", id_number="b-1234567")` → `ALERT`, `reason` bắt đầu bằng `ID number match`, `final_score = 100.0`, còn entry `id_number="C7654321"` → `AUTO_CLEARED` với `reason` bắt đầu bằng `weak name match`.
- AC6: Given TINY trong DuckDB, When gọi `run_screening(duck, settings)` lần đầu, Then `run.run_id = 1`, `run.mode = "FULL"`, `run.as_of = date(2026, 6, 30)`, `run.customers_screened = 300`, `run.entries_screened = 200`, `run.alerts = 5`, `run.reviews = 0`, `run.auto_cleared >= 1`, `run.superseded = 0`, `run.recorded = run.alerts + run.reviews + run.auto_cleared` = `COUNT(*)` của `screening_results`, `run.recorded <= run.candidate_pairs <= 600`; các dòng `decision = 'ALERT'` là đúng 5 cặp (`CIF00000032`, `WL000084`), (`CIF00000041`, `WL000199`), (`CIF00000057`, `WL000013`), (`CIF00000069`, `WL000117`), (`CIF00000104`, `WL000158`) (= `truth_pairs(duck)`), mỗi dòng `name_score = 100.0`, `final_score = 100.0`; dòng (`CIF00000032`, `WL000084`) có `matched_name = 'DANG ANH ANH'`, `matched_name_type = 'AKA'`, dòng (`CIF00000104`, `WL000158`) có `matched_name = 'HUYNH XUAN SON'`, `matched_name_type = 'PRIMARY'`, `dob_gap_years` null; dòng (`CIF00000214`, `WL000099`) có `decision = 'AUTO_CLEARED'`, `reason` bắt đầu bằng `DOB mismatch > 5y`, `matched_name = 'LE THI NHUNG'`, `fuzzy_score = 96.66`, `name_score = 78.09`, `dob_gap_years = 38`; không dòng nào có `entry_id` thuộc TRAPS mà `decision` là `ALERT` hoặc `REVIEW`; mọi dòng có `reason` khác rỗng, `fuzzy_score >= 75` và `superseded_by` null; `screening_runs` có đúng 1 dòng khớp các trường của `run`, với `version = 'screening/v1'` và `config_hash` dài 16 ký tự hex.
- AC7: Given cùng lần chạy đầu trên TINY ở AC6, When đọc `audit_log` rồi gọi `run_screening(duck, settings)` lần hai, Then sau lần đầu `audit_log` có đúng `run.recorded` dòng `module='screening'`, `entity_type='screening_match'`, số dòng theo từng `decision` bằng `run.alerts` / `run.reviews` / `run.auto_cleared`; dòng `entity_id='CIF00000104:WL000158'` có `decision='ALERT'`, `version='screening/v1'`, `details.run_id = 1`, `details.name_score = 100.0`, `details.matched_name = "HUYNH XUAN SON"`; dòng `entity_id='CIF00000214:WL000099'` có `decision='AUTO_CLEARED'` và `reason` bằng đúng `reason` trong `screening_results`; có đúng 1 dòng `entity_type='screening_run'`, `entity_id='1'`, `decision='SCREENING_RUN_COMPLETED'` với `details.mode = "FULL"`, `details.alerts = 5`, `details.reviews = 0`; lần hai trả `run_id = 2`, `superseded = recorded` của lần đầu, mọi dòng `run_id = 1` có `superseded_by = 2` (không dòng nào bị xoá), `screening_current` chỉ gồm dòng `run_id = 2`, tập (`cif`, `entry_id`, `decision`, `reason`, `name_score`, `final_score`) của hai lần chạy bằng nhau, và `audit_log` có thêm đúng `recorded + 1` dòng `module='screening'`.
- AC8: Given TINY đã chạy `run_screening` một lần, When gọi `evaluate(duck, settings)`, Then kết quả có đúng 4 dòng theo thứ tự `exact`, `fuzzy`, `two_tier_alert`, `two_tier` với (`flagged`, `tp`, `fp`, `fn`, `precision`, `recall`, `fp_reduction_pct`) lần lượt là (5, 5, 0, 0, 1.0, 1.0, 100.0), (55, 5, 50, 0, 0.0909, 1.0, 0.0), (5, 5, 0, 0, 1.0, 1.0, 100.0), (5, 5, 0, 0, 1.0, 1.0, 100.0); và Given thêm hai thay đổi trên bảng `customers` — `full_name` của `CIF00000104` đổi thành `'Huỳn Xuân Sơn'` (lỗi gõ), chèn khách hàng `CIF90000001` tên `'Bùi Thanh Ngọc Chi'`, `gender 'F'`, `dob 1990-01-01`, `nationality 'VN'` (trùng tên entry `WL000199` sinh năm 1962) — When gọi `run_screening` rồi `evaluate`, Then dòng `exact` là (5, 4, 1, 1, 0.8, 0.8, 98.04), dòng `fuzzy` là (56, 5, 51, 0, 0.0893, 1.0, 0.0), dòng `two_tier` và `two_tier_alert` đều là (5, 5, 0, 0, 1.0, 1.0, 100.0); trong `screening_current` dòng (`CIF00000104`, `WL000158`) có `decision = 'ALERT'`, `name_score = 97.44` và dòng (`CIF90000001`, `WL000199`) có `decision = 'AUTO_CLEARED'`, `name_score = 100.0`, `reason` bắt đầu bằng `DOB mismatch > 5y`.
- AC9: Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), When chạy `aml screen --eval-out <tmp>/eval.csv`, Then exit code 0; stdout có một dòng tổng kết chứa `run_id=1`, `mode=FULL`, `customers=300`, `entries=200`, `ALERT=5`, `REVIEW=0`; có 4 dòng đánh giá bắt đầu lần lượt bằng `exact`, `fuzzy`, `two_tier_alert`, `two_tier`, dòng `fuzzy` chứa `flagged=55` và `precision=0.09`, dòng `two_tier` chứa `precision=1.00 recall=1.00` và `fp_reduction=100.00%`; file `eval.csv` có dòng tiêu đề `method,flagged,tp,fp,fn,precision,recall,fp_reduction_pct` và 4 dòng dữ liệu; When chạy `aml screen --as-of 2026-13-01`, Then exit code 2 và `screening_runs` không thêm dòng; và Given DuckDB chỉ mới `apply_schema` (chưa `aml load`), When chạy `aml screen`, Then exit code 1, stderr chứa ``run `aml load` first``, `screening_runs` và `audit_log` không có dòng `screening` nào.
- AC10: [oracle] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, When gọi `run_screening` với cùng `as_of = 2026-06-30` trên hai backend, Then `alerts`, `reviews`, `auto_cleared`, `recorded`, `candidate_pairs` của hai `ScreeningRun` bằng nhau; tập (`cif`, `entry_id`, `matched_name`, `decision`, `reason`, `name_score`, `final_score`) đọc từ `screening_current` (điểm làm tròn 2) bằng nhau giữa hai backend; trên Oracle `user_tables` có `SCREENING_RUNS`, `SCREENING_RESULTS`, `user_views` có `SCREENING_CURRENT`; số dòng `audit_log` `module='screening'` của lần chạy trên Oracle (lọc theo `details.run_id` hoặc `entity_id` của run) = `recorded + 1`; và `evaluate` trên Oracle trả đúng 4 dòng như phần đầu AC8.

## Ngoài phạm vi
- Chuẩn hoá tên, IDF, công thức điểm tên, ghi chú Soundex/Metaphone — spec 3a.
- Bản Oracle SQL `UTL_MATCH` và so sánh SQL với Python; incremental screening (delta watchlist/khách hàng, đóng băng IDF, `--incremental`) — spec 3c. Trong 3b mỗi lần `aml screen` là chạy lại toàn bộ.
- Thêm cột `gender` / số giấy tờ vào `watchlist` của Phase 1 (Q1): 3b chỉ hiện thực và unit-test luật, dữ liệu thật luôn cho "không rõ".
- Analyst xử lý cảnh báo (đóng, xác nhận true/false positive, ghi chú), hàng đợi, gộp cảnh báo, chấm ưu tiên — Phase 7; UI — Phase 9. Hệ thống không tự đóng hay tự gỡ bất cứ gì ngoài nhãn `AUTO_CLEARED` có lý do.
- Sàng lọc đối tác giao dịch (`transactions.counterparty_name`), sàng lọc thời gian thực khi mở tài khoản/chuyển tiền.
- Đối chiếu CMND ↔ CCCD, gộp nhiều CIF của một người thành một cảnh báo (entity resolution Phase 4): mỗi CIF là một cặp riêng.
- Mô hình ML xếp hạng/giảm false positive cho screening (Phase 7b `screening/ml/`), tự tinh chỉnh ngưỡng.
- Quyền Oracle (`ROLE_GRANTS`, `020_grants.sql`) trên các bảng `screening_*` (Q15); purge/retention cho `screening_results`.
- Đo hiệu năng trên profile `large`; chạy song song nhiều tiến trình.
- Ghi số liệu vào README (làm ở bước demo từ lần chạy thật trên `small`).

## Giả định
- Dữ liệu Phase 1 giữ các tính chất ở mục "Hiện trạng" (seed 42); các AC trên TINY chỉ cam kết cho TINY seed 42. Các con số "prototype" trong mục Hiện trạng chỉ để định hướng, không phải cam kết — AC chỉ dùng số đo trực tiếp hoặc ràng buộc đã được prototype chứng minh là khả thi.
- 3a đã được duyệt và hiện thực đúng interface (`score_names`, `tokens_match`, `TokenStats`); số điểm đo bằng `rapidfuzz` 3.14.6.
- `as_of` mặc định là `settings.data.reference_date` (2026-06-30), không dùng đồng hồ máy — như DQ và retention; chỉ dùng để nhận ra ngày sinh ở tương lai.
- `run_screening` không chạy đồng thời từ hai tiến trình (`run_id` cấp bằng `MAX + 1`, như `run_dq`).
- Lệnh chạy dưới schema owner (`aml_owner`), đọc `customers` gốc (không qua view che PII) và đọc được `ground_truth` để đánh giá; `evaluate` chỉ có ý nghĩa trên dữ liệu tổng hợp.
- `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có; `run_ts` là UTC như `audit_log.event_ts`.
- Test [oracle] nạp lại TINY vào schema `aml_owner` (full refresh như các test Oracle hiện có) và để lại dòng trong `screening_*`/`audit_log` (bảng audit append-only nên không dọn được).

## Câu hỏi mở
- [x] Q1. `watchlist` Phase 1 không có giới tính và số giấy tờ, trong khi brief yêu cầu Tier 2 dùng cả hai. Làm thế nào? — đề xuất mặc định: hiện thực đủ luật trong `decide` (số giấy tờ trùng → `ALERT`; giới tính lệch → trừ 15 điểm) và kiểm bằng unit test (AC5), nhưng khi chạy trên dữ liệu thật hai trường phía watchlist luôn là "không rõ"; không sửa generator/schema Phase 1. Lý do: thêm cột vào `watchlist` là đổi contract 1c đã duyệt (9 bảng, DDL hai backend, test 1c); danh sách trừng phạt thật cũng thường thiếu hai trường này. Phương án thay thế: mở một spec nhỏ thêm `gender` và `id_number` cho một phần entry (kể cả true hit) để Tier 2 có tác dụng đo được. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q2. Cặp nào được lưu vào `screening_results` và audit? — đề xuất mặc định: chỉ các ứng viên có `fuzzy >= review_threshold` (điểm trước khi nhân IDF đạt 75), tức những cặp mà một bộ so khớp ngây thơ sẽ để ý; ứng viên dưới mức đó chỉ được đếm trong `candidate_pairs`. Lý do: trên `small` Tier 1 sinh ~26,7 nghìn ứng viên nhưng chỉ ~6,3 nghìn đạt mức này; lưu và audit cả 26,7 nghìn dòng mỗi lần chạy không thêm giá trị giải trình. Phương án thay thế: lưu mọi ứng viên. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q3. Ngưỡng `ALERT` / `REVIEW`? — đề xuất mặc định: 90 / 75 trên thang 0–100, nằm trong `config.yaml`. Lý do: với prototype trên `small`, 90/75 giữ recall 1,0 (true hit lỗi gõ đạt 97,23) và cho 41 `ALERT` + 31 `REVIEW`; đây là điểm khởi đầu, cần người dùng chốt khẩu vị rủi ro. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q4. Dung sai ngày sinh và cách so khi chỉ có năm? — đề xuất mặc định: luôn so theo **năm** (kể cả khi entry có đủ ngày); lệch ≤ 1 năm coi là khớp, lệch 2–5 năm trừ 15 điểm, lệch > 5 năm thì `AUTO_CLEARED` với lý do `DOB mismatch > 5y`. Lý do: 30% entry chỉ có năm; dung sai 1 năm chịu được lỗi nhập và lệch lịch; ví dụ lý do trong brief chính là "DOB mismatch > 5y". Hệ quả: người trùng tên sinh cùng năm (khác ngày) với entry có đủ ngày vẫn là `ALERT`. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q5. Có cho phép **tự loại** (`AUTO_CLEARED`) một cặp trùng tên hoàn toàn với entry `SANCTIONS` chỉ vì lệch năm sinh không? — đề xuất mặc định: có, áp dụng như nhau cho `SANCTIONS` và `PEP`, vì brief nêu rõ Tier 2 "can auto-discount or auto-clear"; dòng vẫn được lưu kèm lý do và audit, analyst vẫn xem lại được. Lý do: trên `small` luật này loại 356 cặp trùng tên/gần trùng tên, là nguồn giảm false positive chính. Phương án thận trọng hơn: với `SANCTIONS` chỉ hạ xuống `REVIEW`, không bao giờ tự loại. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q6. Ngày sinh khách hàng thiếu hoặc ở tương lai (defect `FUTURE_DOB`, 100 CIF trên `small`) xử lý thế nào? — đề xuất mặc định: coi là "không rõ" — không trừ điểm, không tự loại. Lý do: dữ liệu KYC lỗi không được phép làm biến mất một cảnh báo; DQ framework (2c-ii) đã báo riêng các CIF này. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q7. Lệch quốc tịch thì trừ điểm hay tự loại? — đề xuất mặc định: trừ 15 điểm (trùng tên hoàn toàn → `REVIEW`), không tự loại; thiếu quốc tịch ở một phía thì bỏ qua. Lý do: người bị liệt kê có thể có nhiều quốc tịch hoặc khai khác; cộng dồn với lệch DOB 2–5 năm thì rơi xuống `AUTO_CLEARED` có lý do. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q8. Luật cho giới tính và số giấy tờ (khi có dữ liệu)? — đề xuất mặc định: giới tính lệch trừ 15 điểm; số giấy tờ trùng → `ALERT` ngay với lý do `ID number match` (bỏ qua lệch DOB/quốc tịch); số giấy tờ khác nhau không có tác dụng gì. Lý do: một người có thể có nhiều giấy tờ (dữ liệu Phase 1 có cả CMND lẫn CCCD), nên khác số không chứng minh là khác người. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q9. Quy tắc blocking của Tier 1? — đề xuất mặc định: chỉ mục token; token được so trong dải cùng chữ cái đầu + lệch độ dài ≤ 1; cặp tên là ứng viên khi chung token hiếm (xuất hiện ở ≤ 2% khách hàng) hoặc một tên bị tên kia phủ hết. Lý do: đo được trên TINY 262/60 000 cặp (0,44%) mà không sót true hit nào; hạn chế đã biết là lỗi gõ ở chữ cái đầu của token và tên nước ngoài chuyển tự khác chữ đầu (`ZHANG`/`CHANG`) không thành ứng viên. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q10. Khi tính precision/recall, "bị gắn cờ" nghĩa là gì và đếm theo đơn vị nào? — đề xuất mặc định: `two_tier` = `ALERT` + `REVIEW` (cả hai đều cần người xem), báo thêm dòng `two_tier_alert`; đơn vị là cặp (cif, entry_id), mỗi CIF trùng của cùng một người là một cặp ground truth riêng. Lý do: khối lượng việc của analyst gồm cả `REVIEW`; entity resolution (Phase 4) chưa gộp CIF. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q11. Định nghĩa hai baseline? — đề xuất mặc định: `exact` = chuỗi tên đã chuẩn hoá bằng nhau (bỏ dấu, viết hoa, có phân biệt thứ tự); `fuzzy` = `token_set_ratio >= alert_threshold` trên tên đã chuẩn hoá, so vét cạn, không IDF, không Tier 2; `fp_reduction_pct` tính so với `fuzzy`. Lý do: nếu `exact` không bỏ dấu thì gần như không khớp gì (đo trên `small`: 5 cặp, 2 TP) — một baseline quá yếu làm kết quả vô nghĩa; "cùng ngưỡng" lấy ngưỡng `ALERT` (90) nên so sánh còn thiệt cho bản hai tầng. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q12. Mức chi tiết của audit? — đề xuất mặc định: một sự kiện cho mỗi cặp được ghi nhận (kể cả `AUTO_CLEARED`) và một sự kiện tổng kết cho mỗi lần chạy. Lý do: quy tắc dự án "mọi quyết định tự động đều ghi `reason` vào `audit_log`"; hệ quả: mỗi lần chạy trên `small` thêm khoảng 6,3 nghìn dòng audit. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q13. Chạy lại `aml screen` thì kết quả cũ ra sao? — đề xuất mặc định: giữ lại, đánh dấu `superseded_by = run_id mới`; view `screening_current` chỉ hiện lần mới nhất. Lý do: không xoá bằng chứng của lần chạy trước; 3c dùng đúng cột này cho incremental. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q14. Có lưu tên khách hàng trong `screening_results` không? — đề xuất mặc định: không; chỉ lưu `cif` và tên phía watchlist (`matched_name`). Lý do: tránh nhân bản PII ra ngoài `customers`/view che dữ liệu của 2b; UI sau này join theo `cif`. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q15. Cấp quyền Oracle trên `screening_runs` / `screening_results` / `screening_current` cho các role của 2b? — đề xuất mặc định: chưa làm trong Phase 3 (như `dq_*`); spec nào có người dùng chạy dưới role khác owner (Phase 7/9) thì bổ sung `SELECT` cho `aml_analyst`, `aml_app` vào `ROLE_GRANTS` và `020_grants.sql`. Lý do: `aml screen` chạy dưới owner; test 2b đang so `dba_tab_privs` với `ROLE_GRANTS` nên thêm quyền là thay đổi có kiểm thử riêng. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q16. Kết quả đánh giá xuất ra đâu? — đề xuất mặc định: `aml screen` luôn in bảng 4 dòng khi `ground_truth` có cặp sanctions/PEP; chỉ ghi file CSV khi có `--eval-out PATH` (bước demo dùng `results/phase3/screening_eval.csv`). Lý do: giống `aml dq run` in đối chiếu nhãn; không tự ghi vào repo khi chạy test. — Trả lời: theo đề xuất mặc định (2026-10-11).
