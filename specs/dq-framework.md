---
id: dq-framework
status: approved
approved_by: pthieu
---

# Phase 2c-ii — Data quality framework: `dq_rules`, runner, `dq_results`, trend view

## Bối cảnh
Nửa sau của 2c (nửa đầu là 2c-i `oracle-retention`). Hiện thực gạch đầu dòng "Data quality framework" của
PROJECT_BRIEF.md mục 3: bảng `dq_rules` + runner kiểm 5 chiều chất lượng (completeness, validity, uniqueness,
consistency, timeliness) trên dữ liệu KYC (`customers`) và `transactions`, ghi kết quả vào `dq_results`, có view xu
hướng `dq_trend`. Chạy trên **cả DuckDB và Oracle** qua `Database` abstraction, SQL kiểm tra nằm trong file `.sql`.
Framework được kiểm chứng bằng ground truth Phase 1: `dq_labels` chứa đúng các defect đã cài (2a cố ý không đặt
constraint chặn chúng). Người dùng: analyst/DBA xem chất lượng dữ liệu trước khi tin vào screening/monitoring.

### Hiện trạng đã kiểm trên dữ liệu Phase 1
- `dq_labels(entity_type, entity_id, defect_type, detail)`: `customer` × {`MISSING_OCCUPATION`, `MISSING_NATIONALITY`,
  `INVALID_ID_LENGTH`, `FUTURE_DOB`} và `transaction` × `DUPLICATE_TRANSACTION` (`detail` = `txn_id` gốc). Một CIF có
  thể mang nhiều defect.
- Profile `small` seed 42: 100 CIF mỗi loại defect KYC, 6000 giao dịch trùng. TINY (300 customers, 5000 txns):
  6 CIF mỗi loại, 100 giao dịch trùng, `transactions` = 5100 dòng.
- Bản sao trùng giống bản gốc ở mọi cột trừ `txn_id` và luôn có `txn_id` lớn hơn bản gốc; không có va chạm tự
  nhiên trên khoá (`from_account_id, to_account_id, txn_ts, amount_vnd, channel`) ở cả `small` lẫn TINY.
- ID hợp lệ theo generator: CCCD 12 chữ số (chữ số thứ 4 = thế kỷ + giới tính, chữ số 5–6 = 2 số cuối năm sinh),
  CMND 9 chữ số, PASSPORT 1 chữ cái hoa + 7 chữ số. Defect `INVALID_ID_LENGTH` chỉ cài lên CCCD/CMND.
- `customers` **không có cột ngày** nào về KYC (ngày rà soát/cập nhật) — xem Q5.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class DqConfig(BaseModel):
    max_feed_lag_days: int  # TXN_FEED_STALE: trễ tối đa của giao dịch mới nhất so với as_of
    sample_size: int  # số entity_id lỗi (sắp tăng dần) lưu vào dq_results.sample_ids


# src/aml/dq/rules.py
DIMENSIONS = ("COMPLETENESS", "VALIDITY", "UNIQUENESS", "CONSISTENCY", "TIMELINESS")


@dataclass(frozen=True)
class DqRule:
    rule_id: str
    table_name: str  # "customers" | "transactions"
    dimension: str  # một trong DIMENSIONS
    scope: str  # "ROW" (mẫu số = số dòng của bảng) | "TABLE" (mẫu số = 1)
    description: str
    check_sql: str  # tên file dưới sql/, vd "dq/kyc_id_format.sql"
    label_defect_type: str | None  # defect_type tương ứng trong dq_labels, nếu có
    max_fail_rate: float = 0.0
    enabled: bool = True


RULES: tuple[DqRule, ...] = ...  # 10 rule bên dưới


def sync_rules(db: Database) -> int: ...  # chèn rule còn thiếu vào dq_rules; trả số dòng mới chèn


# src/aml/dq/runner.py
@dataclass(frozen=True)
class DqRuleResult:
    rule_id: str
    total_rows: int
    failed_rows: int
    fail_rate: float | None  # round(failed_rows / total_rows, 6); None khi NO_DATA
    status: str  # "PASS" | "FAIL" | "NO_DATA"
    failed_ids: frozenset[str]  # toàn bộ entity_id lỗi (không ghi hết xuống DB)


@dataclass(frozen=True)
class DqRun:
    run_id: int
    as_of: date
    results: tuple[DqRuleResult, ...]  # theo thứ tự RULES


def run_dq(db: Database, settings: Settings, *, as_of: date | None = None) -> DqRun: ...
def label_agreement(
    db: Database, run: DqRun
) -> pd.DataFrame: ...  # rule_id, defect_type, tp, fp, fn, precision, recall
```
- `config.yaml` thêm:
  ```yaml
  dq:
    max_feed_lag_days: 1
    sample_size: 20
  ```
- DDL: `sql/duckdb/ddl/060_dq.sql` và `sql/oracle/ddl/060_dq.sql`, thêm vào `SCHEMA_SCRIPTS` của cả hai backend (sau `040`; số `050` đã được bản nháp 2b dùng, `070` là partition `audit_log` của 2c-i).
- CLI mới: nhóm lệnh `aml dq` với lệnh con `run [--as-of YYYY-MM-DD]`.

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Bảng** (cùng tên cột trên hai backend):
  - `dq_rules(rule_id PK, table_name, dimension, scope, description, check_sql, label_defect_type, max_fail_rate, enabled)`.
  - `dq_results(run_id, rule_id, run_ts, as_of, table_name, dimension, total_rows, failed_rows, fail_rate, status, sample_ids)`,
    PK `(run_id, rule_id)`; `run_ts` UTC; `sample_ids` kiểu JSON (mảng chuỗi); bảng chỉ INSERT, không UPDATE/DELETE.
  - View `dq_trend(rule_id, table_name, dimension, run_id, run_ts, failed_rows, fail_rate, status, prev_failed_rows,
    delta_failed_rows)`: mỗi dòng `dq_results` kèm `LAG(failed_rows) OVER (PARTITION BY rule_id ORDER BY run_id)`.
- **File kiểm tra**: mỗi rule là một file chứa đúng **một** câu `SELECT` trả một cột `entity_id` (chuỗi) = các thực thể
  vi phạm. `sql_file` tìm `sql/<backend>/dq/<tên>` trước rồi `sql/common/dq/<tên>`. File dưới `sql/oracle/` kết thúc
  bằng dòng `/` (quy ước 2a, đọc qua `split_oracle_script`, phải ra đúng 1 statement); file `common`/`duckdb` có thể kết
  thúc bằng `;` (runner cắt bỏ). Placeholder duy nhất: `{as_of}` → literal `DATE 'YYYY-MM-DD'` và `{max_feed_lag_days}`
  → số nguyên, cả hai được định dạng từ giá trị đã ép kiểu (`date`, `int`), không nhận chuỗi tự do.
- **10 rule** (`as_of` mặc định = `settings.data.reference_date`):

  | rule_id | bảng | chiều | vi phạm khi | label |
  |---|---|---|---|---|
  | `KYC_OCCUPATION_MISSING` | customers | COMPLETENESS | `occupation IS NULL` | `MISSING_OCCUPATION` |
  | `KYC_NATIONALITY_MISSING` | customers | COMPLETENESS | `nationality IS NULL` | `MISSING_NATIONALITY` |
  | `KYC_ID_FORMAT` | customers | VALIDITY | `id_number` khác null và không khớp mẫu theo `id_type`: CCCD `^[0-9]{12}$`, CMND `^[0-9]{9}$`, PASSPORT `^[A-Z][0-9]{7}$`; `id_type` khác 3 loại này cũng là vi phạm | `INVALID_ID_LENGTH` |
  | `KYC_DOB_FUTURE` | customers | VALIDITY | `dob > as_of` | `FUTURE_DOB` |
  | `KYC_CCCD_DOB_MISMATCH` | customers | CONSISTENCY | CCCD 12 chữ số, `dob` và `gender` (M/F) khác null, mà chữ số 5–6 khác `năm sinh mod 100` hoặc chữ số 4 khác (0 nếu sinh trước 2000, 2 nếu từ 2000) + (0 nếu M, 1 nếu F) | — |
  | `TXN_DUPLICATE` | transactions | UNIQUENESS | cùng (`from_account_id, to_account_id, txn_ts, amount_vnd, channel`, null bằng null) với một dòng có `txn_id` nhỏ hơn (dòng `txn_id` nhỏ nhất của nhóm không bị gắn) | `DUPLICATE_TRANSACTION` |
  | `TXN_VALUE_INVALID` | transactions | VALIDITY | `amount_vnd` null hoặc `<= 0`, hoặc `channel` null/không thuộc 5 channel, hoặc `txn_ts` null | — |
  | `TXN_ACCOUNT_UNKNOWN` | transactions | CONSISTENCY | `from_account_id` hoặc `to_account_id` khác null, không bắt đầu bằng `EXT-`, và không có trong `accounts` | — |
  | `TXN_BEFORE_ACCOUNT_OPEN` | transactions | CONSISTENCY | ngày của `txn_ts` trước `accounts.open_date` của tài khoản nội bộ phía gửi hoặc nhận | — |
  | `TXN_FEED_STALE` | transactions | TIMELINESS (scope TABLE) | `MAX(txn_ts) < as_of − max_feed_lag_days ngày` (00:00); `entity_id` trả về là `transactions` | — |

- **Runner**: `run_id` = `COALESCE(MAX(run_id), 0) + 1` trên `dq_results`; gọi `sync_rules`; đọc rule `enabled` từ bảng
  `dq_rules` (bảng là nguồn điều khiển, không phải hằng `RULES`); với mỗi rule chạy file, tính
  `total_rows` (ROW: `COUNT(*)` của `table_name`; TABLE: 1), `fail_rate = round(failed_rows / total_rows, 6)`,
  `status = 'FAIL'` nếu `fail_rate > max_fail_rate`, ngược lại `'PASS'`; bảng rỗng → `NO_DATA` cho mọi rule của bảng
  đó (`total_rows = 0`, `failed_rows = 0`, `fail_rate` null). Ghi `dq_results` bằng `insert_df`, rồi 1 dòng `audit_log`.
- `sync_rules` chỉ INSERT rule chưa có `rule_id` trong bảng; **không ghi đè** dòng đã có (giữ chỉnh sửa
  `enabled`/`max_fail_rate` của người vận hành).
- `label_agreement`: với mỗi rule có `label_defect_type`, so `failed_ids` với tập `entity_id` trong `dq_labels` cùng
  `defect_type` (`entity_type` = `customer` cho bảng customers, `transaction` cho transactions).

## Tiêu chí nghiệm thu
<!-- TINY = fixture `tiny_parquet` (300 customers, 5000 txns + 100 bản trùng = 5100 dòng, seed 42, reference_date 2026-06-30).
MINI = dữ liệu cài tay trên DuckDB rỗng sau apply_schema, as_of = 2026-06-30 (các cột không nêu để null):
 customers: C1 (M, dob 1990-05-20, VN, occupation 'Teacher', CCCD '001090123456');
            C2 (F, dob 2026-07-01, nationality null, occupation null, CMND '12345678');
            C3 (M, dob 2026-06-30, US, 'Engineer', PASSPORT 'B1234567');
            C4 (M, dob 1990-05-20, VN, 'Teacher', CCCD '001190123456');
            C5 (M, dob 1990-05-20, VN, 'Teacher', CCCD '00109012345X');
            C6 (M, dob 1990-05-20, VN, 'Teacher', CCCD '001085123456').
 accounts:  A1 (cif C1, open_date 2026-01-10), A2 (cif C1, open_date 2025-01-01).
 transactions (txn_id: from -> to, txn_ts, amount_vnd, channel):
   T1: A1 -> A2,   2026-02-01 09:00:00, 100000, INTERNAL_TRANSFER;  T2, T3: giống hệt T1;
   T4: null -> A1, 2026-01-05 10:00:00, 500000, CASH;
   T5: A1 -> EXT-X, 2026-03-01 09:00:00, 200000, INTERBANK_TRANSFER;
   T6: A9 -> A2,   2026-03-02 09:00:00, 300000, EBANKING;
   T7: A1 -> A2,   2026-06-30 12:00:00, 0, WIRE;
   T8: null -> A2, 2026-02-01 09:00:00, 100000, CASH;  T9: giống hệt T8.
Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given hằng `RULES` và thư mục `sql/` của repo (không cần DB), When duyệt `RULES`, Then có đúng 10 rule với `rule_id` duy nhất đúng như bảng thiết kế; tập `dimension` = đủ 5 giá trị của `DIMENSIONS`; các rule của `customers` phủ đúng {COMPLETENESS, VALIDITY, CONSISTENCY} và các rule của `transactions` phủ đúng {UNIQUENESS, VALIDITY, CONSISTENCY, TIMELINESS}; mỗi `check_sql` resolve được qua `sql_file` cho cả `"duckdb"` lẫn `"oracle"`, nội dung chứa đúng 1 câu lệnh bắt đầu bằng `SELECT` hoặc `WITH`; `ddl/060_dq.sql` có trong cả `SCHEMA_SCRIPTS["duckdb"]` lẫn `SCHEMA_SCRIPTS["oracle"]` và resolve qua `sql_file` về đúng thư mục `sql/<backend>/`.
- AC2: Given DuckDB rỗng (`duck`), When gọi `apply_schema` hai lần rồi `sync_rules` hai lần, Then không raise; `sync_rules` trả 10 rồi 0; `dq_rules` có đúng 10 dòng; `SELECT COUNT(*)` chạy được trên `dq_results` và `dq_trend` (đều 0 dòng); và sau `UPDATE dq_rules SET enabled = FALSE WHERE rule_id = 'TXN_FEED_STALE'` rồi `sync_rules` lần nữa, dòng đó vẫn `enabled = FALSE` và `run_dq` trả đúng 9 kết quả, không có `TXN_FEED_STALE`.
- AC3: Given dữ liệu MINI, When gọi `run_dq(duck, settings, as_of=date(2026, 6, 30))`, Then `failed_ids` của 5 rule KYC lần lượt là `KYC_OCCUPATION_MISSING` = {C2}, `KYC_NATIONALITY_MISSING` = {C2}, `KYC_ID_FORMAT` = {C2, C5}, `KYC_DOB_FUTURE` = {C2} (C3 sinh đúng ngày `as_of` không bị gắn), `KYC_CCCD_DOB_MISMATCH` = {C4, C6}; mỗi rule có `total_rows = 6`; `KYC_ID_FORMAT` có `fail_rate = 0.333333` và `status = 'FAIL'`.
- AC4: Given dữ liệu MINI, When gọi `run_dq(duck, settings, as_of=date(2026, 6, 30))`, Then `failed_ids` của `TXN_DUPLICATE` = {T2, T3, T9}, `TXN_VALUE_INVALID` = {T7}, `TXN_ACCOUNT_UNKNOWN` = {T6} (T5 đi `EXT-X` không bị gắn), `TXN_BEFORE_ACCOUNT_OPEN` = {T4}; 4 rule này có `total_rows = 9`; `TXN_DUPLICATE` có `fail_rate = 0.333333`; `TXN_FEED_STALE` có `total_rows = 1`, `failed_rows = 0`, `status = 'PASS'`.
- AC5: Given `dq.max_feed_lag_days = 1`, `as_of = 2026-06-30` và `transactions` chỉ có 1 dòng, When `txn_ts` của dòng đó là `2026-06-28 23:59:59`, Then `TXN_FEED_STALE` có `failed_rows = 1`, `total_rows = 1`, `fail_rate = 1.0`, `status = 'FAIL'`, `failed_ids = {"transactions"}`; When `txn_ts` là `2026-06-29 00:00:00`, Then `status = 'PASS'`, `failed_rows = 0`; When `transactions` và `customers` rỗng, Then cả 10 rule có `status = 'NO_DATA'`, `total_rows = 0`, `failed_rows = 0`, `fail_rate is None`.
- AC6: Given DuckDB rỗng nạp TINY bằng `load_parquet`, When gọi `run_dq(duck, tiny_settings)` (as_of mặc định 2026-06-30) rồi `label_agreement`, Then với 4 rule `KYC_OCCUPATION_MISSING`, `KYC_NATIONALITY_MISSING`, `KYC_ID_FORMAT`, `KYC_DOB_FUTURE`: `failed_rows = 6`, `total_rows = 300`, `fail_rate = 0.02` và `failed_ids` bằng đúng tập `entity_id` của `dq_labels` cùng `defect_type`; `TXN_DUPLICATE`: `failed_rows = 100`, `total_rows = 5100`, `fail_rate = 0.019608`, `failed_ids` bằng đúng tập `entity_id` nhãn `DUPLICATE_TRANSACTION`; `label_agreement` có 5 dòng, mỗi dòng `fp = 0`, `fn = 0`, `precision = 1.0`, `recall = 1.0`; `KYC_CCCD_DOB_MISMATCH` có `failed_rows = 5` và `failed_ids` là tập con của các CIF nhãn `FUTURE_DOB`; 4 rule còn lại (`TXN_VALUE_INVALID`, `TXN_ACCOUNT_UNKNOWN`, `TXN_BEFORE_ACCOUNT_OPEN`, `TXN_FEED_STALE`) có `failed_rows = 0`, `status = 'PASS'`.
- AC7: Given cùng lần chạy đầu trên TINY ở AC6 (`run_id = 1`), When đọc `dq_results` và `audit_log`, Then `dq_results` có đúng 10 dòng `run_id = 1`, `as_of = 2026-06-30`, với (`total_rows`, `failed_rows`, `fail_rate`, `status`) khớp `DqRun.results`; dòng `KYC_OCCUPATION_MISSING` có `sample_ids` là mảng JSON 6 CIF sắp tăng dần; dòng `TXN_DUPLICATE` có `sample_ids` dài đúng 20 (= `dq.sample_size`) và là 20 `txn_id` nhỏ nhất trong `failed_ids`; `audit_log` có đúng 1 dòng mới `module='dq'`, `entity_type='dq_run'`, `entity_id='1'`, `decision='DQ_RUN_COMPLETED'` với `details.rules = 10`, `details.passed = 4`, `details.failed = 6`, `details.as_of = "2026-06-30"`, `details.failed_rules` gồm đúng 6 `rule_id` FAIL.
- AC8: Given TINY đã chạy `run_dq` lần 1, When cập nhật `occupation = 'Teacher'` cho 2 CIF nhỏ nhất đang thiếu occupation, gọi `run_dq` lần 2 rồi đọc `dq_trend`, Then lần 2 có `run_id = 2`; `dq_trend` có 20 dòng; dòng (`KYC_OCCUPATION_MISSING`, run 1) có `failed_rows = 6`, `prev_failed_rows` null, `delta_failed_rows` null; dòng (`KYC_OCCUPATION_MISSING`, run 2) có `failed_rows = 4`, `prev_failed_rows = 6`, `delta_failed_rows = -2`; dòng (`TXN_DUPLICATE`, run 2) có `failed_rows = 100`, `delta_failed_rows = 0`; và 10 dòng `run_id = 1` trong `dq_results` không đổi.
- AC9: [oracle] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, When gọi `run_dq` với cùng `as_of = 2026-06-30` trên hai backend, Then với cả 10 rule, (`total_rows`, `failed_rows`, `fail_rate`, `status`) và `failed_ids` bằng nhau giữa hai backend; trên Oracle `user_tables` có `DQ_RULES`, `DQ_RESULTS`, `user_views` có `DQ_TREND`, và `SELECT COUNT(*) FROM dq_trend WHERE run_id = <run_id vừa chạy>` = 10.
- AC10: Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), When chạy `aml dq run`, Then exit code 0 (dù có rule FAIL), stdout có 10 dòng kết quả mỗi dòng chứa `rule_id` và `PASS`/`FAIL`, có dòng tổng kết chứa `run_id=1`, `4 PASS`, `6 FAIL`, và 5 dòng đối chiếu nhãn mỗi dòng chứa `precision=1.00 recall=1.00`; When chạy `aml dq run --as-of 2026-13-01`, Then exit code 2 và `dq_results` không thêm dòng nào.

## Ngoài phạm vi
- Retention/purge, partition hoá `audit_log` (2c-i `oracle-retention`).
- Tự sửa dữ liệu, cách ly (quarantine) hay chặn nạp khi DQ FAIL; constraint DB chặn defect; exit code khác 0 khi có rule FAIL (cờ `--fail-on` để sau).
- Bảng chi tiết từng dòng vi phạm (`dq_exceptions`); chỉ lưu số đếm + mẫu `sample_ids`.
- Rule cho `accounts`, `watchlist`, `watchlist_alias`, `customer_person`, `acct_edge_daily`, `audit_log`; phát hiện trùng khách hàng (thuộc entity resolution Phase 4, không phải DQ uniqueness).
- Timeliness của KYC (ngày rà soát định kỳ): schema Phase 1 không có cột ngày tương ứng (Q5).
- Rule do người dùng tự viết SQL qua UI/CLI, DSL khai báo rule, lịch chạy (`DBMS_SCHEDULER`), cảnh báo/email, dashboard (Phase 9 có thể đọc `dq_trend`).
- Purge `dq_results` theo retention; đo hiệu năng trên profile `large`.
- Grants trên `dq_rules`/`dq_results`/`dq_trend` cho các role của 2b (Q16).
- Ghi số liệu DQ vào README (làm ở bước demo của phase, phải lấy từ lần chạy thật).

## Giả định
- Dữ liệu Phase 1 có các tính chất đã kiểm ở mục "Hiện trạng" (seed 42, `small` và TINY): không có null tự nhiên ở `occupation`/`nationality`/`id_number`/`dob`/`gender`, không có `dob` tương lai tự nhiên, không trùng khoá giao dịch tự nhiên, mọi tài khoản nội bộ trong `transactions` có trong `accounts`, không giao dịch nào trước `open_date`, giao dịch mới nhất của TINY là 2026-06-30. Nếu seed/profile khác phá các tính chất này thì AC6 chỉ cam kết cho TINY seed 42.
- `txn_ts` là giờ địa phương naive (quy ước 1b-i) và `as_of` là ngày theo cùng quy ước; `run_ts` là UTC như `audit_log.event_ts`.
- Mỗi lần chạy DQ là một "quyết định tự động" ở mức lần chạy: audit 1 dòng/lần chạy (không audit từng rule, từng dòng vi phạm); `reason` là câu tiếng Anh tóm tắt số PASS/FAIL.
- `run_dq` không chạy đồng thời từ hai tiến trình (cách cấp `run_id` bằng `MAX + 1` không an toàn khi song song).
- Trên Oracle `CK_TXN_AMOUNT_POS`/`CK_TXN_CHANNEL` (2a) đã bảo đảm `TXN_VALUE_INVALID` = 0; rule vẫn tồn tại vì DuckDB không có constraint.
- Thông điệp/CLI bằng tiếng Anh như các lệnh hiện có; `aml dq run` không cần Oracle.

## Câu hỏi mở
- [x] Q1. Bộ rule ban đầu gồm những gì? — đề xuất mặc định: đúng 10 rule trong bảng thiết kế (5 KYC, 5 transactions; đủ 5 chiều). Lý do: phủ cả 5 loại defect đã cài ở Phase 1 và thêm các kiểm tra "sạch" (kỳ vọng 0 vi phạm) để thấy rule PASS. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q2. Định nghĩa giao dịch trùng? — đề xuất mặc định: trùng cả 5 cột (`from_account_id, to_account_id, txn_ts, amount_vnd, channel`), null coi như bằng nhau; gắn mọi dòng trừ dòng `txn_id` nhỏ nhất của nhóm. Lý do: khớp cách Phase 1 cài (bản sao mang `txn_id` mới lớn hơn) nên đối chiếu nhãn được chính xác 100%; không dùng `memo`/`device_id` để khoá vẫn bắt được bản sao bị sửa trường phụ. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q3. Mẫu ID hợp lệ? — đề xuất mặc định: CCCD 12 chữ số, CMND 9 chữ số, PASSPORT 1 chữ cái hoa + 7 chữ số; `id_number` null không bị rule này gắn (đó là completeness, hiện không có rule). Lý do: đúng với generator Phase 1; hộ chiếu nước ngoài thật đa dạng hơn nhưng dữ liệu tổng hợp chỉ có một mẫu. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q4. Có thêm rule consistency CCCD ↔ ngày sinh/giới tính (`KYC_CCCD_DOB_MISMATCH`) dù Phase 1 không có nhãn riêng? — đề xuất mặc định: có; kỳ vọng mọi vi phạm đều là CIF mang nhãn `FUTURE_DOB` (TINY: 5 trên 6). Lý do: là kiểm tra chéo đặc thù Việt Nam, cho thấy một defect bị bắt bởi hai chiều khác nhau; không tính vào precision/recall. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q5. Timeliness cho KYC đo bằng gì khi `customers` không có cột ngày? — đề xuất mặc định: 2c-ii chỉ có timeliness cho `transactions` (`TXN_FEED_STALE`); timeliness KYC ghi là hạn chế đã biết. Lý do: thêm cột `kyc_review_date` là đổi contract Phase 1 (9 bảng, manifest, test 1a–1c) — nếu muốn, nên là một spec nhỏ riêng. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q6. `TXN_FEED_STALE` định nghĩa thế nào? — đề xuất mặc định: rule mức bảng, FAIL khi giao dịch mới nhất cũ hơn `as_of − dq.max_feed_lag_days` ngày (mặc định 1), mẫu số = 1. Lý do: timeliness là "dữ liệu về kịp chưa", không phải thuộc tính từng dòng; ngưỡng nằm trong `config.yaml`. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q7. `as_of` mặc định? — đề xuất mặc định: `settings.data.reference_date` (2026-06-30), ghi đè bằng `--as-of`; không dùng đồng hồ máy. Lý do: dữ liệu tổng hợp đóng băng tại reference_date; dùng ngày hôm nay thì `TXN_FEED_STALE` luôn FAIL và kết quả không tái lập được. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q8. Ngưỡng PASS/FAIL? — đề xuất mặc định: `max_fail_rate = 0.0` cho cả 10 rule (có bất kỳ vi phạm nào là FAIL), lưu theo từng rule trong `dq_rules` để người vận hành chỉnh. Lý do: đơn giản, minh bạch; ngưỡng dung sai theo rule là quyết định nghiệp vụ chưa có căn cứ. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q9. Danh mục rule lưu ở đâu và đồng bộ thế nào? — đề xuất mặc định: hằng Python `RULES` + file SQL cho từng rule; `sync_rules` chỉ chèn rule còn thiếu, không ghi đè dòng đã có; runner đọc từ bảng `dq_rules`. Lý do: bảng thật sự điều khiển runner (tắt rule bằng `UPDATE`), còn định nghĩa nằm trong git; hệ quả: sửa mô tả/ngưỡng trong code không tự cập nhật dòng đã có. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q10. Lưu kết quả chi tiết tới đâu? — đề xuất mặc định: `dq_results` chỉ có số đếm + `sample_ids` (tối đa `dq.sample_size` = 20 id nhỏ nhất); toàn bộ id vi phạm chỉ có trong đối tượng `DqRun` trả về. Lý do: profile `large` có ~100 nghìn giao dịch trùng mỗi lần chạy, lưu hết sẽ phình bảng; muốn truy vết đủ thì chạy lại file SQL của rule. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q11. Bảng rỗng xử lý thế nào? — đề xuất mặc định: `status = 'NO_DATA'`, `fail_rate` null cho mọi rule của bảng đó (kể cả `TXN_FEED_STALE`). Lý do: tránh chia cho 0 và tránh PASS giả khi chưa nạp dữ liệu; phương án thay thế là coi feed rỗng là FAIL. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q12. Hình dạng view xu hướng? — đề xuất mặc định: `dq_trend` = mỗi (rule, lần chạy) một dòng kèm `prev_failed_rows` và `delta_failed_rows` so với lần chạy liền trước của cùng rule. Lý do: một câu SQL dùng `LAG` chạy được trên cả hai backend; gộp theo ngày/tuần để UI làm sau. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q13. `aml dq run` trả exit code nào khi có rule FAIL? — đề xuất mặc định: 0 (lệnh chạy thành công; FAIL là kết quả đo, không phải lỗi), chỉ thoát 2 khi tham số sai. Lý do: dữ liệu Phase 1 cố ý có defect nên lệnh luôn có FAIL; chặn pipeline theo DQ là ngoài phạm vi. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q14. Code đặt ở đâu? — đề xuất mặc định: package mới `src/aml/dq/` (`rules.py`, `runner.py`), DDL `ddl/060_dq.sql` cho cả hai backend, SQL rule dưới `sql/common/dq/` (bản riêng theo backend chỉ khi cú pháp buộc phải khác, vd regex). Lý do: DQ không phải việc riêng của DBA Oracle nên không nằm trong `aml.dba`. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q15. Có in/ghi đối chiếu với `dq_labels` trong lệnh CLI không? — đề xuất mặc định: có, `aml dq run` in thêm precision/recall theo từng rule có nhãn khi `dq_labels` có dữ liệu; không ghi file kết quả. Lý do: là bằng chứng "framework bắt đúng defect đã cài" cho buổi demo; `dq_labels` là ground truth chỉ có ở dữ liệu tổng hợp. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q16. Role nào được đọc `dq_*` khi 2b (`oracle-security`) được hiện thực? — đề xuất mặc định: không làm trong 2c-ii; spec nào hiện thực sau thì bổ sung `SELECT` trên `dq_rules`, `dq_results`, `dq_trend` cho `aml_analyst` và `aml_auditor` vào `ROLE_GRANTS`/`020_grants.sql` (bản nháp 2b đã quy định "mỗi phase tự bổ sung"). Lý do: 2b còn là bản nháp, chưa có role nào tồn tại trên Oracle. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
