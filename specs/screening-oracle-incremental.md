---
id: screening-oracle-incremental
status: approved
approved_by: pthieu
---

# Phase 3c — Bản SQL `UTL_MATCH` so với Python, và incremental screening

## Bối cảnh
Phần cuối của Phase 3 (PROJECT_BRIEF.md mục 4, "Oracle comparison" và "Incremental screening"), dựng trên 3a
(`specs/screening-normalize-score.md`) và 3b (`specs/screening-tiers-eval.md`). Gồm hai việc độc lập:
(1) một bản sàng lọc **viết bằng SQL** chạy trong DB, dùng `UTL_MATCH.JARO_WINKLER_SIMILARITY` trên Oracle, và một
phép so sánh có số liệu giữa kết quả SQL với kết quả hai tầng của Python; (2) **incremental screening**: sau lần
chạy đầy đủ, chỉ sàng lại phần watchlist và khách hàng đã thay đổi, kèm tài liệu giải thích vì sao điều này quan
trọng ở quy mô production. Người dùng: DBA/analyst so sánh hai cách làm; người vận hành chạy sàng lọc hằng ngày.

### Hiện trạng đã kiểm (Oracle 23.26.3 tại localhost:1521/FREEPDB1 — chỉ `SELECT ... FROM dual`; TINY seed 42)
- `UTL_MATCH.JARO_WINKLER_SIMILARITY(a, b)` trả số nguyên 0–100 = **phần nguyên** của `100 × UTL_MATCH.JARO_WINKLER`
  (`HUU LONG TRA` / `HUU LONG TRAN` → 98 với giá trị thực 0,9846; `TRA`/`TRAN` → 94; `AN`/`ANH` → 91).
- `UTL_MATCH` **không trùng** `rapidfuzz.distance.JaroWinkler`: trên 611 cặp khoá tên thử, 311 cặp lệch (tối đa 0,15),
  chủ yếu ở vùng điểm thấp và trung bình (`HA`/`HOA`: Oracle 64, rapidfuzz 61; `NGUYEN VAN` /
  `BASHIROV NGUYEN THANH VAN`: Oracle 63, rapidfuzz 66); ở ngưỡng ≥ 85 hai bên cho cùng tập cặp trên mẫu 611 cặp
  này, nhưng trên toàn bộ 4367 cặp khoá khác nhau sau khi chặn của TINY thì chỉ 454 cặp có điểm nguyên bằng nhau và
  13/114 cặp đạt ≥ 85 ở ít nhất một bên bị lệch (`DO HUYEN THI` / `DO HA THI`: Oracle 88, rapidfuzz 91).
- DuckDB có sẵn `jaro_winkler_similarity(a, b)` (0–1) và **trùng khít** rapidfuzz trên cả 611 cặp (lệch tối đa 0,0).
- Bản SQL dự kiến (Jaro-Winkler trên khoá tên không phụ thuộc thứ tự, chặn theo chữ cái đầu + lệch độ dài ≤ 3,
  ngưỡng 90) trên TINY: 5797 phép so trên 133 500 cặp (300 khách hàng × 445 tên); DuckDB cho **32** cặp
  (cif, entry_id), Oracle cho **30** cặp (tập con của 32; lệch 2 cặp do khác biệt nêu trên); cả hai chứa đủ 5 cặp
  ground truth. Trên `small` (DuckDB): 996 973 phép so trên 22,97 triệu, 4737 cặp, đủ 25 true hit, precision 0,005
  — tức Jaro-Winkler thuần trong SQL có recall tốt nhưng nhiễu ngang baseline fuzzy; so với 72 cặp
  `ALERT`+`REVIEW` của prototype hai tầng: 58 cặp chung, 4679 cặp chỉ SQL có, 14 cặp chỉ Python có.
- Không bảng nào của Phase 1 có cột thời điểm cập nhật; `aml load` luôn full refresh (xoá sạch rồi chèn) và phần
  "watchlist delta/versioning" đã được 1c ghi là việc của Phase 3 → delta phải tự phát hiện bằng so sánh nội dung.
- **Prototype incremental** trên TINY (đóng băng IDF của lần chạy đầy đủ): sau 3 thay đổi của kịch bản DELTA bên
  dưới, sàng lại chỉ cần 7 cặp ứng viên (lần đầy đủ: 262), ghi 2 dòng mới, thay thế 2 dòng cũ, và tập kết quả hiện
  hành trùng khớp với một lần chạy đầy đủ trên dữ liệu đã đổi (55 dòng: 5 `ALERT`, 1 `REVIEW`, 49 `AUTO_CLEARED`).
- `SCHEMA_SCRIPTS`: 3b dùng `080`; số `090` còn trống. Trên Oracle `050_security_objects.sql` phải chạy cuối.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py — thêm vào ScreeningConfig
    sql_length_band: int  # bản SQL: lệch độ dài tối đa giữa hai khoá tên được đem so


# src/aml/screening/sql_compare.py
SQL_FUNCTIONS = {"oracle": "UTL_MATCH.JARO_WINKLER_SIMILARITY", "duckdb": "jaro_winkler_similarity"}


def sync_screening_names(db: Database, settings: Settings) -> dict[str, int]: ...
# ghi lại toàn bộ screening_customer_name và screening_list_name; trả {tên bảng: số dòng}


def sql_screen(db: Database, settings: Settings) -> pd.DataFrame: ...  # cột: cif, entry_id, jw_score (int)


@dataclass(frozen=True)
class SqlComparison:
    backend: str
    function: str  # SQL_FUNCTIONS[backend]
    threshold: int  # = screening.alert_threshold
    sql_pairs: int  # số cặp (cif, entry_id) bản SQL trả về
    python_pairs: int  # số cặp ALERT + REVIEW trong screening_current
    both: int
    sql_only: int
    python_only: int
    truth: int  # số cặp ground truth
    sql_tp: int
    python_tp: int
    sql_seconds: float  # thời gian chạy câu SQL


def compare_sql_python(db: Database, settings: Settings) -> SqlComparison: ...


# src/aml/screening/incremental.py
@dataclass(frozen=True)
class Delta:
    customers_changed: frozenset[str]  # CIF mới hoặc đổi dấu vân tay
    customers_removed: frozenset[str]
    entries_changed: frozenset[str]  # entry_id mới hoặc đổi dấu vân tay
    entries_removed: frozenset[str]


def detect_delta(db: Database, settings: Settings) -> Delta: ...
def run_incremental(db: Database, settings: Settings, *, as_of: date | None = None) -> ScreeningRun: ...
```
- `config.yaml`, mục `screening` thêm `sql_length_band: 3`.
- DDL `sql/duckdb/ddl/090_screening_state.sql` và `sql/oracle/ddl/090_screening_state.sql`, thêm vào
  `SCHEMA_SCRIPTS` của cả hai backend (Oracle: trước `ddl/050_security_objects.sql`; DuckDB: trước
  `ddl/050_customers_masked.sql` — quy ước hiện có "security objects are applied last").
- SQL sàng lọc: `sql/oracle/screening/jw_screen.sql` và `sql/duckdb/screening/jw_screen.sql`.
- CLI: `aml screen --incremental` (thêm cờ vào lệnh của 3b) và lệnh mới `aml screen-compare`.
- `docs/screening.md` thêm hai mục "Oracle UTL_MATCH vs Python" và "Incremental screening".

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Bảng** (cùng tên cột trên hai backend):
  - `screening_customer_name(cif PK, name_norm, name_key)` và
    `screening_list_name(entry_id, name_type, name_norm, name_key)` PK `(entry_id, name_norm)`: tên đã chuẩn hoá
    bằng `normalize_name`/`name_key` của 3a (Python là nơi duy nhất chuẩn hoá); `sync_screening_names` xoá sạch rồi
    chèn lại (idempotent), bỏ qua tên chuẩn hoá rỗng.
  - `screening_state(entity_type, entity_id, fingerprint, run_id)` PK `(entity_type, entity_id)`; `entity_type` ∈
    {`customer`, `watchlist_entry`}: dấu vân tay của lần sàng lọc gần nhất đã phủ thực thể đó.
  - `screening_token_stats(token PK, doc_freq, n_names, run_id)`: IDF đóng băng của lần chạy `FULL` gần nhất.
- **`jw_screen.sql`**: mỗi backend một file, chứa đúng một câu `SELECT` trả `cif, entry_id, jw_score`: nối
  `screening_customer_name` với `screening_list_name` theo điều kiện chặn `SUBSTR(name_key, 1, 1)` bằng nhau và
  `ABS(LENGTH(c.name_key) − LENGTH(w.name_key)) <= {length_band}`, tính điểm nguyên 0–100 trên `name_key`
  (Oracle: `UTL_MATCH.JARO_WINKLER_SIMILARITY`; DuckDB: `CAST(FLOOR(100 * jaro_winkler_similarity(...) + 1e-9) AS
  INTEGER)` — số bù `1e-9` chống sai số dấu phẩy động ngay tại ngưỡng, xem Q5), giữ cặp
  có điểm `>= {threshold}`, gộp theo (cif, entry_id) lấy `MAX`. Placeholder chỉ có `{threshold}` và `{length_band}`,
  được định dạng từ số nguyên (như các file rule của DQ); file Oracle kết thúc bằng dòng `/`.
- **`compare_sql_python`**: gọi `sync_screening_names`, chạy `sql_screen` (đo thời gian), so tập cặp với
  `screening_current` (`decision IN ('ALERT', 'REVIEW')`) và với `truth_pairs` của 3b; chưa có lần `run_screening`
  nào → raise `ScreeningError` chứa ``run `aml screen` first``. Ghi 1 dòng `audit_log` `module='screening'`,
  `entity_type='screening_compare'`, `entity_id=<backend>`, `decision='COMPARISON_CAPTURED'`, `details` = các
  trường của `SqlComparison`.
- **Dấu vân tay** (SHA-256 dạng hex của các trường nối bằng `|`, null → chuỗi rỗng):
  khách hàng = `normalize_name(full_name)`, `dob`, `nationality`, `gender`, `id_number`; watchlist entry =
  `list_type`, `dob`, `dob_year`, `dob_precision`, `nationality`, danh sách `name_type:name_norm` của tên chính và
  mọi alias (sắp tăng dần, nối bằng `;`). Cột khác (`phone`, `address`, `program`, `listed_date`...) không tham gia.
- **Lần chạy `FULL`** (`run_screening` của 3b, được mở rộng): sau khi ghi kết quả thì ghi lại toàn bộ
  `screening_state` (mọi khách hàng và entry hiện có) và `screening_token_stats` (từ `TokenStats` vừa dùng).
- **`run_incremental`**:
  1. `screening_state` rỗng → chạy `FULL` (trả `mode = "FULL"`).
  2. `config_hash` của cấu hình hiện tại khác `config_hash` của lần `FULL` gần nhất trong `screening_runs` → raise
     `ScreeningError` chứa `full screen required`.
  3. `delta = detect_delta(...)`: so dấu vân tay hiện tại với `screening_state`.
  4. Nạp `TokenStats` từ `screening_token_stats` (**không** tính lại IDF).
  5. `run_id` mới; đánh dấu `superseded_by = run_id` cho mọi dòng hiện hành có `cif` thuộc
     `customers_changed ∪ customers_removed` hoặc `entry_id` thuộc `entries_changed ∪ entries_removed`.
  6. Sàng (Tier 1 + Tier 2 của 3b) đúng các cặp có `cif ∈ customers_changed` **hoặc** `entry_id ∈ entries_changed`,
     đối chiếu với toàn bộ phía còn lại; chèn kết quả với `run_id` mới.
  7. Cập nhật `screening_state` (ghi dấu vân tay mới, xoá thực thể đã bị gỡ); ghi 1 dòng `screening_runs`
     `mode = 'INCREMENTAL'`, `customers_screened = |customers_changed|`, `entries_screened = |entries_changed|`.
  8. Audit: một sự kiện cho mỗi dòng mới (như 3b); một sự kiện `decision='WITHDRAWN'`
     (`entity_type='screening_match'`, `entity_id='<cif>:<entry_id>'`) cho mỗi dòng `ALERT`/`REVIEW` bị thay thế mà
     cặp đó không có dòng mới trong lần chạy này, `reason` nêu nguyên nhân (`watchlist entry removed`,
     `customer removed`, hoặc `no longer a recorded match after change`); và sự kiện tổng kết lần chạy với
     `details` có thêm `customers_changed`, `customers_removed`, `entries_changed`, `entries_removed` (số lượng).
- **Tài liệu** `docs/screening.md`: mục "Incremental screening" giải thích chi phí sàng đầy đủ tỉ lệ với
  (số khách hàng × số tên trong danh sách) trong khi delta hằng ngày chỉ là một phần rất nhỏ, yêu cầu phản ứng
  nhanh khi có entry mới bị liệt kê, vì sao đóng băng IDF và khi nào phải chạy lại đầy đủ; mục
  "Oracle UTL_MATCH vs Python" nêu khác biệt đo được giữa `UTL_MATCH` và rapidfuzz và đánh đổi SQL trong DB
  (không kéo PII ra ngoài, tận dụng DB) với Python (IDF, Tier 2, lý do từng quyết định). Số liệu thật do bước demo điền.

## Tiêu chí nghiệm thu
<!-- TINY = fixture `tiny_parquet` nạp bằng `load_parquet` (300 customers, 200 watchlist, 245 alias, seed 42);
cfg mặc định của 3a + 3b + `sql_length_band: 3`; as_of = 2026-06-30. "FULL-1" = lần `run_screening(db, settings)`
đầu tiên trên TINY (run_id = 1; theo 3b: 5 ALERT, 0 REVIEW; dòng (CIF00000214, WL000099) AUTO_CLEARED vì DOB).
DELTA = ba thay đổi áp lên DB sau FULL-1:
  D1: UPDATE customers SET dob = DATE '1950-03-01' WHERE cif = 'CIF00000214'   (tên 'Lê Nhung', dob cũ 1988-05-05);
  D2: INSERT watchlist (entry_id 'WL900001', list_type 'SANCTIONS', primary_name 'NGO THI LAN', name_origin 'vi',
      dob NULL, dob_year NULL, dob_precision 'NONE', nationality 'VN', program 'SDGT', listed_date 2025-12-01)
      — khách hàng CIF00000002 tên 'Ngô Thị Lan';
  D3: DELETE FROM watchlist WHERE entry_id = 'WL000158' (entry true hit của CIF00000104, không có alias).
Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given `config.yaml`, thư mục `sql/` và `docs/` của repo (không cần DB), When `load_settings(environ={})` và đọc `SCHEMA_SCRIPTS`, Then `settings.screening.sql_length_band == 3`; `ddl/090_screening_state.sql` có trong `SCHEMA_SCRIPTS` của cả hai backend (ở Oracle đứng trước `ddl/050_security_objects.sql`) và resolve về đúng `sql/<backend>/`; `screening/jw_screen.sql` resolve qua `sql_file` cho `"oracle"` về `sql/oracle/` và cho `"duckdb"` về `sql/duckdb/`; file Oracle chứa `UTL_MATCH.JARO_WINKLER_SIMILARITY`, qua `split_oracle_script` ra đúng 1 statement bắt đầu bằng `SELECT` hoặc `WITH`; file DuckDB chứa `jaro_winkler_similarity`; cả hai file chứa `{threshold}` và `{length_band}` và không chứa placeholder nào khác; `docs/screening.md` chứa hai tiêu đề `Oracle UTL_MATCH vs Python` và `Incremental screening`.
- AC2: Given TINY trong DuckDB, When gọi `sync_screening_names(duck, settings)` hai lần, Then cả hai lần trả `{"screening_customer_name": 300, "screening_list_name": 445}` và số dòng thực tế của hai bảng là 300 và 445 (không nhân đôi); dòng `cif = 'CIF00000104'` có `name_norm = 'HUYNH XUAN SON'`, `name_key = 'HUYNH SON XUAN'`; entry `WL000084` có đúng 3 dòng (`PRIMARY`, `NGUYEN ANH LONG`), (`AKA`, `DANG ANH ANH`), (`REORDERED`, `LONG NGUYEN ANH`), dòng `AKA` có `name_key = 'ANH ANH DANG'`.
- AC3: Given TINY trong DuckDB đã chạy FULL-1, When gọi `sql_screen(duck, settings)` rồi `compare_sql_python(duck, settings)`, Then `sql_screen` trả đúng 32 dòng, không trùng (cif, entry_id), mọi `jw_score` là số nguyên trong [90, 100], chứa đủ 5 cặp ground truth với `jw_score = 100`; `SqlComparison` có `backend = "duckdb"`, `function = "jaro_winkler_similarity"`, `threshold = 90`, `sql_pairs = 32`, `python_pairs = 5`, `both = 5`, `sql_only = 27`, `python_only = 0`, `truth = 5`, `sql_tp = 5`, `python_tp = 5`, `sql_seconds >= 0`; `audit_log` có đúng 1 dòng mới `entity_type='screening_compare'`, `decision='COMPARISON_CAPTURED'` với `details.sql_pairs = 32`; và Given DuckDB có TINY nhưng chưa chạy `run_screening`, When gọi `compare_sql_python`, Then raise `ScreeningError` chứa ``run `aml screen` first``.
- AC4: [oracle] Given Oracle đang chạy, When truy vấn `SELECT UTL_MATCH.JARO_WINKLER_SIMILARITY(:a, :b) FROM dual` qua `Database.query_df`, Then (`HUU LONG TRA`, `HUU LONG TRAN`) → 98, (`TRA`, `TRAN`) → 94, (`AN`, `ANH`) → 91, (`DO SON XUAN`, `DO SON XUAN`) → 100, (`HA`, `HOA`) → 64 (trong khi phần nguyên của `100 * rapidfuzz JaroWinkler.similarity` là 61); và Given TINY nạp vào cả Oracle và một DuckDB tạm, cả hai đã chạy FULL-1, When gọi `sql_screen` trên hai backend và `compare_sql_python` trên Oracle, Then Oracle trả 30 cặp, DuckDB trả 32 cặp, tập cặp của Oracle là tập con của DuckDB, cả hai chứa đủ 5 cặp ground truth; `SqlComparison` trên Oracle có `function = "UTL_MATCH.JARO_WINKLER_SIMILARITY"`, `sql_pairs = 30`, `both = 5`, `python_only = 0`, `sql_tp = 5`; `user_tables` có `SCREENING_CUSTOMER_NAME`, `SCREENING_LIST_NAME`, `SCREENING_STATE`, `SCREENING_TOKEN_STATS`.
- AC5: Given TINY trong DuckDB, When gọi `run_incremental(duck, settings)` khi chưa có lần chạy nào, rồi gọi lại lần hai không đổi dữ liệu, Then lần đầu trả `mode = "FULL"`, `run_id = 1`, `alerts = 5`; sau đó `screening_state` có 300 dòng `customer` và 200 dòng `watchlist_entry`, `screening_token_stats` có 85 dòng, mọi dòng `n_names = 300`, dòng `token = 'NGUYEN'` có `doc_freq = 115`; lần hai trả `mode = "INCREMENTAL"`, `run_id = 2`, `customers_screened = 0`, `entries_screened = 0`, `candidate_pairs = 0`, `recorded = 0`, `superseded = 0`; `screening_current` không đổi (cùng tập dòng, vẫn `run_id = 1`); `audit_log` chỉ thêm đúng 1 dòng (`entity_type='screening_run'`, `entity_id='2'`, `details.mode = "INCREMENTAL"`).
- AC6: Given TINY đã chạy FULL-1 rồi áp DELTA, cộng thêm `UPDATE customers SET phone = '0900000000' WHERE cif = 'CIF00000001'` và `UPDATE watchlist SET program = 'CYBER' WHERE entry_id = 'WL000001'`, When gọi `detect_delta(duck, settings)`, Then `customers_changed = {"CIF00000214"}`, `customers_removed = ∅`, `entries_changed = {"WL900001"}`, `entries_removed = {"WL000158"}` (đổi `phone`/`program` không tạo delta); và When chèn thêm alias (`alias_id 'WA9000001'`, `entry_id 'WL000001'`, `alias_name 'TEST ALIAS'`, `alias_type 'AKA'`) rồi gọi lại, Then `entries_changed = {"WL900001", "WL000001"}`; `detect_delta` không ghi gì vào DB.
- AC7: Given TINY đã chạy FULL-1 rồi áp DELTA, When gọi `run_incremental(duck, settings)`, Then trả `run_id = 2`, `mode = "INCREMENTAL"`, `customers_screened = 1`, `entries_screened = 1`, `recorded = 2`, `alerts = 1`, `reviews = 1`, `auto_cleared = 0`, `superseded = 2`, `candidate_pairs <= 20`; hai dòng mới (`run_id = 2`) là (`CIF00000214`, `WL000099`) với `decision = 'REVIEW'`, `name_score = 78.09`, `final_score = 78.09`, `dob_gap_years = 0`, và (`CIF00000002`, `WL900001`) với `decision = 'ALERT'`, `name_score = 100.0`, `matched_name = 'NGO THI LAN'`; hai dòng `run_id = 1` của (`CIF00000214`, `WL000099`) và (`CIF00000104`, `WL000158`) có `superseded_by = 2` và vẫn tồn tại; mọi dòng `run_id = 1` khác có `superseded_by` null; `screening_current` có 5 dòng `ALERT`, 1 dòng `REVIEW` và không có dòng nào của `WL000158`; `screening_state` không còn dòng `WL000158`, có dòng `WL900001`, và gọi `detect_delta` ngay sau đó trả bốn tập rỗng.
- AC8: Given hai DuckDB: A = TINY chạy FULL-1, áp DELTA, rồi `run_incremental`; B = DuckDB mới nạp TINY, áp DELTA trước, rồi `run_screening(B, settings, token_stats=<TokenStats đọc từ screening_token_stats của A>)`, When so `screening_current` của A và B, Then tập (`cif`, `entry_id`, `matched_name`, `decision`, `reason`, `name_score`, `final_score`) của hai bên bằng nhau, và lần chạy trên B có `candidate_pairs` lớn hơn ít nhất 10 lần `candidate_pairs` của lần incremental trên A.
- AC9: Given cùng lần `run_incremental` sau DELTA ở AC7, When đọc `audit_log`, Then lần chạy này thêm đúng 4 dòng `module='screening'`: 2 dòng `entity_type='screening_match'` cho `CIF00000214:WL000099` (`decision='REVIEW'`) và `CIF00000002:WL900001` (`decision='ALERT'`), cả hai `details.run_id = 2`; 1 dòng `entity_id='CIF00000104:WL000158'` với `decision='WITHDRAWN'`, `reason` chứa `watchlist entry removed`, `details.previous_decision = "ALERT"`; 1 dòng `entity_type='screening_run'`, `entity_id='2'` với `details.mode = "INCREMENTAL"`, `details.customers_changed = 1`, `details.entries_changed = 1`, `details.entries_removed = 1`, `details.customers_removed = 0`; không có dòng `WITHDRAWN` nào cho `CIF00000214:WL000099`; và Given `load_settings` với `AML__SCREENING__ALERT_THRESHOLD=85` trên cùng DB, When gọi `run_incremental`, Then raise `ScreeningError` chứa `full screen required` và không thêm dòng nào vào `screening_runs`, `screening_results`, `audit_log`.
- AC10: Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), When chạy lần lượt `aml screen`, `aml screen --incremental`, `aml screen-compare`, Then cả ba exit code 0; lệnh thứ hai in dòng tổng kết chứa `run_id=2`, `mode=INCREMENTAL`, `customers=0`, `entries=0`, `ALERT=0`; lệnh thứ ba in một dòng chứa `backend=duckdb`, `function=jaro_winkler_similarity`, `threshold=90`, `sql_pairs=32`, `python_pairs=5`, `both=5`, `sql_only=27`, `python_only=0`; và Given DuckDB có TINY nhưng chưa chạy `aml screen`, When chạy `aml screen-compare`, Then exit code 1 và stderr chứa ``run `aml screen` first``.

## Ngoài phạm vi
- Viết lại toàn bộ logic hai tầng (IDF, `token_set_ratio`, Tier 2, quyết định) bằng SQL/PL-SQL; bản SQL chỉ là so khớp Jaro-Winkler trên khoá tên với blocking (Q1).
- Chuẩn hoá tên bằng SQL trong Oracle (`TRANSLATE`/`CONVERT`); đối chiếu chéo chuẩn hoá Python ↔ SQL.
- Tối ưu hiệu năng phía Oracle: function-based index trên khoá chặn, chạy song song, materialized view cho `screening_customer_name`, `DBMS_SCHEDULER`; ghi kết quả bản SQL vào bảng (chỉ trả DataFrame và số liệu so sánh).
- Property graph / `GRAPH_TABLE` (Phase 5–6).
- Nguồn delta thật: nhận file cập nhật danh sách (OFAC/UN delta), versioning watchlist, CDC/trigger/`ORA_ROWSCN`, cột `updated_at`; delta ở đây suy ra từ so sánh dấu vân tay toàn bảng.
- Tự cập nhật IDF trong lần chạy incremental; tự quyết định khi nào cần chạy lại đầy đủ (ngoài kiểm tra `config_hash`).
- Mang quyết định của analyst (đã xử lý, ghi chú) sang dòng mới khi cặp được sàng lại — Phase 7.
- Incremental cho bản SQL; so sánh hiệu năng SQL ↔ Python trên profile `large`.
- Quyền Oracle trên bốn bảng mới cho các role của 2b (cùng hướng xử lý với 3b Q15).
- Ghi số liệu vào README; số liệu trong `docs/screening.md` do bước demo điền từ lần chạy thật.

## Giả định
- 3a và 3b đã được duyệt và hiện thực đúng interface; `screening_runs` của 3b có cột `config_hash` và `run_screening` nhận `token_stats`.
- Oracle 23ai Free cho schema owner quyền `EXECUTE` trên `UTL_MATCH` mặc định (đã kiểm: gọi được dưới `aml_owner`); số liệu Oracle trong AC4 đo trên bản 23.26.3 — bản vá khác có thể cho số khác, khi đó cập nhật spec chứ không sửa công thức.
- `jaro_winkler_similarity` của DuckDB trùng `rapidfuzz` (đã kiểm trên 611 cặp với DuckDB đang cài trong `.venv`).
- Dữ liệu thay đổi giữa hai lần sàng lọc bằng `UPDATE`/`INSERT`/`DELETE` trực tiếp hoặc `aml load` lại; không tiến trình nào sửa `customers`/`watchlist` trong lúc `run_incremental` đang chạy.
- Đóng băng IDF nghĩa là token mới của khách hàng mới được coi là "chưa thấy" (IDF cao nhất) cho tới lần chạy đầy đủ kế tiếp; chấp nhận sai lệch nhỏ này để kết quả incremental trùng khớp một lần chạy đầy đủ dùng cùng IDF (AC8).
- Test [oracle] nạp lại TINY vào schema `aml_owner` và để lại dòng trong các bảng `screening_*`/`audit_log`.
- Thông điệp và output CLI bằng tiếng Anh; không dùng đồng hồ máy ngoài `run_ts`/`event_ts` (UTC) và `sql_seconds`.

## Câu hỏi mở
- [x] Q1. "Bản Oracle SQL" phủ tới đâu? — đề xuất mặc định: một câu SQL so khớp tên bằng `UTL_MATCH.JARO_WINKLER_SIMILARITY` trên khoá tên không phụ thuộc thứ tự, có blocking (chữ cái đầu + dải độ dài) và ngưỡng; **không** có IDF, `token_set_ratio` hay Tier 2. Lý do: brief chỉ yêu cầu "an Oracle SQL version using UTL_MATCH... and compare"; phép so sánh khi đó cho thấy rõ Jaro-Winkler thuần trong DB được gì (recall đủ, chạy ngay cạnh dữ liệu) và mất gì (4737 cặp trên `small` so với 72 của bản hai tầng). Phương án thay thế: viết thêm Tier 2 (DOB/quốc tịch) bằng SQL để so sánh công bằng hơn — tốn thêm một spec. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q2. Tên chuẩn hoá cho bản SQL lấy từ đâu? — đề xuất mặc định: Python chuẩn hoá rồi ghi xuống hai bảng `screening_customer_name` / `screening_list_name`; SQL chỉ đọc. Lý do: một nguồn chuẩn hoá duy nhất (3a); viết lại bỏ dấu tiếng Việt bằng `TRANSLATE` trong SQL sẽ tạo hai bản dễ lệch nhau. Hệ quả: tên chuẩn hoá của khách hàng (PII đã bỏ dấu) được lưu thêm một bản trong schema owner. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q3. Có cần bản DuckDB của câu SQL không? — đề xuất mặc định: có, `sql/duckdb/screening/jw_screen.sql` dùng `jaro_winkler_similarity`; `aml screen-compare` chạy trên backend đang dùng. Lý do: giữ quy ước "mỗi câu SQL có bản cho từng backend" và cho phép kiểm thử ở chế độ DuckDB-only; đồng thời lộ ra khác biệt thú vị: DuckDB trùng rapidfuzz còn `UTL_MATCH` thì không. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q4. Ngưỡng và dải chặn của bản SQL? — đề xuất mặc định: ngưỡng = `screening.alert_threshold` (90), `sql_length_band = 3`. Lý do: "cùng ngưỡng" với Python; dải 3 ký tự giữ đủ 5/5 true hit TINY và 25/25 trên `small` trong khi chỉ so 4,3% số cặp. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q5. Điểm của bản DuckDB làm tròn thế nào để so được với Oracle? — đề xuất mặc định: lấy phần nguyên của `100 × similarity + 1e-9` (cắt bỏ phần thập phân như `UTL_MATCH.JARO_WINKLER_SIMILARITY`, đã đo). Lý do: hai backend cùng thang số nguyên 0–100, khác biệt còn lại là khác biệt thuật toán thật; số bù `1e-9` là cần thiết vì đã đo: trên TINY có hay không đều ra 32 cặp, nhưng trên `small` `FLOOR` thuần cho 4735 cặp còn có bù cho 4737 (2 cặp có điểm đúng bằng 90 bị tính thành 89,999...). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q6. Phát hiện delta bằng cách nào khi dữ liệu không có cột thời điểm cập nhật và `aml load` luôn full refresh? — đề xuất mặc định: so dấu vân tay SHA-256 của các trường có tham gia sàng lọc với bảng `screening_state`. Lý do: không phải đổi schema Phase 1, chạy được trên cả hai backend, và nạp lại y nguyên dữ liệu thì delta rỗng. Phương án thay thế (ghi trong docs): cột `updated_at`/CDC ở production. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q7. Trường nào tham gia dấu vân tay? — đề xuất mặc định: khách hàng: tên đã chuẩn hoá, `dob`, `nationality`, `gender`, `id_number`; entry: `list_type`, ba cột DOB, `nationality`, toàn bộ tên + alias đã chuẩn hoá. Lý do: đúng các đầu vào của Tier 1/Tier 2; đổi số điện thoại hay `program` không làm đổi quyết định nên không cần sàng lại. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q8. Lần chạy incremental dùng IDF nào? — đề xuất mặc định: IDF **đóng băng** từ lần chạy đầy đủ gần nhất (bảng `screening_token_stats`); chỉ lần chạy đầy đủ mới tính lại. Lý do: nếu tính lại IDF mỗi lần thì điểm của **mọi** cặp đều thay đổi chút ít và về nguyên tắc phải sàng lại tất cả — mất ý nghĩa incremental; đóng băng cho phép chứng minh "incremental = đầy đủ với cùng IDF" (AC8). Hệ quả: nên chạy đầy đủ định kỳ (vd hằng tuần) để làm mới IDF — ghi trong docs. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q9. Gọi `--incremental` khi chưa từng chạy đầy đủ, hoặc khi cấu hình sàng lọc đã đổi? — đề xuất mặc định: chưa có trạng thái → tự chạy đầy đủ; cấu hình (`config_hash`) khác lần đầy đủ gần nhất → báo lỗi `full screen required`, không tự chạy. Lý do: lần đầu thì chạy đầy đủ là điều duy nhất hợp lý; còn đổi ngưỡng là quyết định có chủ đích, trộn kết quả hai bộ ngưỡng trong `screening_current` là sai nên phải để người vận hành chủ động chạy lại. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q10. Cặp đang `ALERT`/`REVIEW` mà sau thay đổi không còn khớp (entry bị gỡ khỏi danh sách, khách hàng đổi tên) thì sao? — đề xuất mặc định: dòng cũ được đánh dấu `superseded_by`, không xoá; ghi thêm sự kiện audit `WITHDRAWN` kèm lý do; không tạo dòng kết quả mới. Lý do: analyst cần biết vì sao một cảnh báo biến mất khỏi danh sách hiện hành; việc đóng case tương ứng thuộc Phase 7. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q11. Lần chạy incremental không có thay đổi nào có ghi gì không? — đề xuất mặc định: có, 1 dòng `screening_runs` và 1 sự kiện audit tổng kết (0 thực thể thay đổi). Lý do: bằng chứng là sàng lọc hằng ngày đã chạy, kể cả khi không có gì mới. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q12. Hình dạng CLI? — đề xuất mặc định: cờ `--incremental` trên `aml screen`; lệnh riêng `aml screen-compare` (không tự chạy trong `aml screen`). Lý do: `make screen` / `tasks.ps1 screen` giữ nguyên nghĩa "chạy đầy đủ"; so sánh SQL là bước demo riêng, giống `explain-pruning` / `tune-demo`. — Trả lời: theo đề xuất mặc định (2026-10-11).
