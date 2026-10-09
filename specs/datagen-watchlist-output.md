---
id: datagen-watchlist-output
status: approved
approved_by: pthieu
---

# Phase 1c — Watchlist, size profiles, orchestration, Parquet output và loaders

## Bối cảnh
Phase 1 (PROJECT_BRIEF.md mục 2) chia thành: 1a `specs/datagen-customers.md` (APPROVED), 1b-i
`specs/datagen-transactions.md` (accounts/transactions/dq_labels), 1b-ii `specs/datagen-typologies.md`
(ground_truth + typologies) và spec này (1c). 1c sinh watchlist ~2k entry (sanctions/PEP, aliases,
transliteration variants, DOB đôi khi chỉ có năm, trap entries) cho Phase 3 (screening), ghép các
generator thành một pipeline tất định theo seed, chọn size profile qua config/env, ghi Parquet (mỗi
bảng một file) và nạp vào DuckDB/Oracle qua `aml data` / `aml load` (Makefile và `tasks.ps1` đã gọi sẵn).

### Interface upstream dùng lại (đã chốt / đang draft)
- 1a: `generate_customers_from_settings(settings) -> CustomerTables(customers, customer_person, dq_defects, admin_unit_mapping)`.
  `person_id` chỉ có trong `customer_person` (`cif, person_id, is_primary, variations`); `dq_defects` = `(cif, defect_type)`;
  `nationality` ISO-2; `data.reference_date: 2026-06-30`.
- 1b: `generate_activity(customers, TxnGenParams.from_settings(settings), seed) -> ActivityData(customers, accounts, transactions, ground_truth, dq_labels)`.
  `ActivityData.customers` là **bản sao đã sửa** (mule ring dùng chung device/phone/address). Cửa sổ giao dịch
  `data.start_date: 2026-01-01` đến `2026-06-30`.
- `ground_truth` (schema 1b): `scenario_id, typology, is_suspicious, entity_type, entity_id, role, start_ts, end_ts, reason`;
  typology `sanctions_hit` / `pep_hit` và `entity_type = 'watchlist_entry'` để dành cho 1c sinh.
- `dq_labels` (schema 1b): `entity_type, entity_id, defect_type, detail`.
- Seed: mỗi bảng có sub-stream riêng `np.random.SeedSequence([seed, stable_hash(<tên bảng>)])` (quy ước của 1a).
  1c dùng tên `"watchlist"` và `"watchlist_alias"`.

### Thiết kế đề xuất cho 1c (xác nhận ở Câu hỏi mở)
- `src/aml/datagen/watchlist.py`:
  `generate_watchlist(customers, customer_person, dq_defects, ground_truth, cfg: WatchlistConfig, seed: int) -> WatchlistResult(watchlist, watchlist_alias, ground_truth_rows)`.
  `customers` là `ActivityData.customers`; `ground_truth` là ground truth của 1b (để không chọn trùng entity).
- `src/aml/datagen/pipeline.py`: `run_pipeline(settings, out_dir) -> Manifest`: 1a (`CustomerTables`)
  -> 1b (`generate_activity(tables, ...)`) -> 1c -> ghi Parquet + `manifest.json`.
- `src/aml/datagen/load.py`: `load_parquet(db: Database, src_dir: Path) -> dict[str, int]` (tên bảng -> số dòng).
- Config mới: `data.watchlist: {entries: 2000, true_hits: 20, traps: 30, year_only_dob_rate: 0.30, unknown_dob_rate: 0.05}`
  (model `WatchlistConfig` trong `DataConfig`; override bằng env, ví dụ `AML__DATA__WATCHLIST__ENTRIES=200`).
- Bảng `watchlist`: `entry_id` (`WL000001`...), `list_type` (`SANCTIONS` | `PEP`), `primary_name` (Latin uppercase ASCII),
  `name_origin` (`vi` | `ru` | `ar` | `zh` | `other`), `dob` (DATE, NULL khi không đủ ngày), `dob_year` (INT, NULL khi không rõ),
  `dob_precision` (`DAY` | `YEAR` | `NONE`), `nationality` (ISO-2 hoặc NULL), `program`, `listed_date` (DATE, < `data.start_date`).
- Bảng `watchlist_alias`: `alias_id`, `entry_id`, `alias_name` (Latin uppercase ASCII), `alias_type` (`AKA` | `TRANSLITERATION` | `REORDERED`).
- Dòng `ground_truth` của 1c:
  - true hit: `scenario_id` `GT-SAN-0001` / `GT-PEP-0001`, `typology` = `sanctions_hit` nếu entry là `SANCTIONS`, `pep_hit` nếu `PEP`;
    `is_suspicious = True`; 1 dòng `entity_type='watchlist_entry'`, `role='listed_entry'` + 1 dòng `entity_type='customer'`,
    `role='subject'` cho **mỗi** CIF cùng `person_id` (kể cả CIF trùng của 1a); `start_ts` = `listed_date` 00:00, `end_ts` NULL;
    `reason` = câu tiếng Anh, ví dụ "Customer CIF00001234 is listed as WL000045 (sanctions); name, DOB year and nationality match".
  - trap: `scenario_id` `GT-TRAP-0001`, `typology='screening_trap'`, `is_suspicious = False`, 1 dòng `entity_type='watchlist_entry'`,
    `role='trap_entry'`.
- Output trong `data.output_dir` (mặc định `data/parquet`): mỗi bảng một file `<table>.parquet` cho đúng 9 bảng
  `customers, customer_person, admin_unit_mapping, accounts, transactions, ground_truth, dq_labels, watchlist, watchlist_alias`,
  cộng `manifest.json` = `{seed, profile, profile_params, start_date, reference_date, tables: {<table>: <rows>}}` (không timestamp).
  - `customers.parquet` = `ActivityData.customers` (của 1b, không phải 1a); không có cột `person_id` (chỉ nằm trong `customer_person`), để ER không đọc được đáp án.
  - `dq_labels.parquet` = `ActivityData.dq_labels` cộng các dòng 1a `dq_defects` đổi thành
    `entity_type='customer', entity_id=cif, defect_type=<giữ nguyên mã 1a>, detail=NULL`.
- CLI: `aml data [--profile small|dense|large] [--seed N] [--out DIR]`; `aml load [--backend duckdb|oracle] [--src DIR]`.
- DDL nạp dữ liệu: `sql/duckdb/ddl/010_datagen.sql` và `sql/oracle/ddl/010_datagen.sql` (bảng đơn giản, chỉ có PK;
  chuỗi Oracle dùng `VARCHAR2(n CHAR)`).

## Tiêu chí nghiệm thu
<!-- WL_IN = đầu vào watchlist: customers + customer_person + dq_defects của 1a với n_customers=300, seed=42,
     duplicate_person_rate=0.08, dq_defect_rate=0.02, reference_date=2026-06-30; ground_truth rỗng (đúng schema 1b);
     cfg entries=200, true_hits=5, traps=6, year_only_dob_rate=0.30, unknown_dob_rate=0.05; seed=42.
     TINY = fixture `tiny_settings` (tests/conftest.py): load_settings(environ=...) với profile customers=300,
     transactions=5000, months=6, số case typology tối thiểu theo config của 1b-ii, watchlist entries=200,
     true_hits=5, traps=6, output_dir/duckdb_path trỏ vào tmp_path. Mọi AC trừ AC11 không cần Oracle. -->
- AC1: Given WL_IN, When gọi `generate_watchlist`, Then `watchlist` có đúng 200 dòng, `entry_id` duy nhất khớp `^WL\d{6}$`, `list_type` chỉ thuộc {`SANCTIONS`, `PEP`} và có cả hai giá trị, mọi `primary_name` khớp `^[A-Z]+( [A-Z]+)*$`, `nationality` khớp `^[A-Z]{2}$` hoặc NULL, mọi `listed_date` < 2026-01-01, và mỗi dòng thỏa: `dob_precision='DAY'` thì `dob` khác NULL và `dob_year = year(dob)`; `'YEAR'` thì `dob` NULL và `dob_year` khác NULL; `'NONE'` thì cả hai NULL.
- AC2: Given WL_IN nhưng `entries=2000`, When gọi `generate_watchlist`, Then tỉ lệ `dob_precision='YEAR'` nằm trong [0.25, 0.35], tỉ lệ `'NONE'` trong [0.02, 0.08], mỗi `name_origin` trong {`ru`, `ar`, `zh`} chiếm ít nhất 10% số entry, mỗi entry có `name_origin` thuộc {`ru`, `ar`, `zh`} có ít nhất 1 alias `alias_type='TRANSLITERATION'` với `alias_name != primary_name` (ví dụ `MUHAMMAD`/`MOHAMMED`, `ALEKSANDR`/`ALEXANDER`, `ZHANG`/`CHANG`), mọi `alias_name` khớp `^[A-Z]+( [A-Z]+)*$`, và không entry nào có quá 5 alias.
- AC3: Given WL_IN (`true_hits=5`), When gọi `generate_watchlist`, Then `ground_truth_rows` có đúng 5 `scenario_id` khác nhau với `typology` thuộc {`sanctions_hit`, `pep_hit`}, `is_suspicious = True`; mỗi case có đúng 1 dòng `entity_type='watchlist_entry'` và `typology` khớp `list_type` của entry đó (`SANCTIONS` -> `sanctions_hit`, `PEP` -> `pep_hit`); tập CIF `entity_type='customer'` của case bằng đúng tập CIF cùng `person_id` trong `customer_person`; với CIF chính (`is_primary=True`), tập token tên (unidecode, uppercase, không phân biệt thứ tự) bằng tập token của `primary_name` hoặc của ít nhất một alias, `dob_year` bằng năm sinh hoặc NULL, `nationality` bằng nationality của customer; không CIF nào của case có trong `dq_defects`; mọi `reason` khác rỗng.
- AC4: Given WL_IN (`traps=6`) nhưng `ground_truth` đầu vào có sẵn 1 case `mule_ring` chứa 10 CIF, When gọi `generate_watchlist`, Then có đúng 6 `scenario_id` `typology='screening_trap'`, `is_suspicious = False`, mỗi case 1 dòng `entity_type='watchlist_entry'`; mỗi trap có ít nhất 2 token thuộc 10 token tên phổ biến nhất của customers (sau unidecode + uppercase), chung ít nhất 2 token với ít nhất 5% customers (≥ 15 trên 300), và không customer nào có tập token tên chứa toàn bộ token của trap; đồng thời không true hit nào chọn trúng 10 CIF của case `mule_ring` đó.
- AC5: Given TINY với seed 42, When gọi `run_pipeline`, Then thư mục output có đúng 9 file `<table>.parquet` đã liệt kê trong Thiết kế cùng `manifest.json`; `customers.parquet` không có cột `person_id` và bằng (`assert_frame_equal`) `ActivityData.customers` khi gọi 1a + 1b trực tiếp với cùng settings; `dq_labels.parquet` có số dòng = số dòng `ActivityData.dq_labels` + số dòng `dq_defects` của 1a, và mỗi dòng `dq_defects (cif, defect_type)` xuất hiện đúng 1 lần dưới dạng `entity_type='customer', entity_id=cif, defect_type` giữ nguyên mã 1a (ví dụ `FUTURE_DOB`); `ground_truth.parquet` chứa cả dòng của 1b và các dòng `sanctions_hit`/`pep_hit`/`screening_trap` của 1c, với `scenario_id` duy nhất theo từng case.
- AC6: Given TINY với seed 42, When gọi `run_pipeline` hai lần vào hai thư mục khác nhau, Then mọi cặp bảng cùng tên bằng nhau theo `pandas.testing.assert_frame_equal` và hai `manifest.json` giống hệt nhau từng byte; And khi đổi seed sang 43 thì bảng `watchlist` khác lần seed 42.
- AC7: Given TINY với seed 42, When chạy `run_pipeline` một lần với `AML__DATA__WATCHLIST__ENTRIES=200` và một lần với `=300`, Then `customers`, `customer_person`, `accounts`, `transactions` của hai lần bằng nhau theo `assert_frame_equal` (mỗi bảng dùng sub-stream `SeedSequence([seed, stable_hash(<tên bảng>)])`, nên đổi kích thước watchlist không làm lệch bảng khác).
- AC8: Given env `AML__DATA__PROFILE=dense` và TINY, When chạy `aml data --out <tmp>` qua `typer.testing.CliRunner`, Then exit code = 0, `manifest.json` có `profile = "dense"`, `profile_params.counterparties = [50, 100]`, `seed = 42`, và `tables[t]` bằng số dòng của `<t>.parquet` với mọi bảng t; And khi chạy `aml data --profile huge --out <tmp2>` thì exit code ≠ 0, thông báo lỗi chứa cả `small`, `dense`, `large`, và `<tmp2>` không có file nào.
- AC9: Given thư mục Parquet sinh từ TINY và một DuckDB rỗng ở tmp_path, When chạy `aml load --backend duckdb` hai lần liên tiếp, Then sau mỗi lần số dòng của từng bảng trong DuckDB bằng `manifest.json.tables[t]` (lần hai không nhân đôi), một `full_name` có dấu (ví dụ chứa `Nguyễn`) đọc lại giống hệt Parquet, và `audit_log` có thêm đúng 1 dòng mỗi lần với `module='datagen'`, `entity_type='dataset'`, `decision='LOADED'`, `reason` chứa `duckdb` và tổng số dòng, `details` chứa số dòng theo bảng.
- AC10: Given thư mục nguồn không có `manifest.json`, hoặc thiếu một file `<table>.parquet` được liệt kê trong manifest, When chạy `aml load --src <dir>`, Then exit code = 1, stderr chứa `run \`aml data\` first` và tên file thiếu, và không bảng dữ liệu nào trong DB bị tạo hay thay đổi.
- AC11: [pytest marker `oracle`] Given Oracle đang chạy và thư mục Parquet từ TINY, When chạy `load_parquet` với `OracleDb` hai lần, Then sau mỗi lần `SELECT COUNT(*)` của từng bảng bằng `manifest.json.tables[t]`, và một customer có `full_name` chứa dấu tiếng Việt (ví dụ `Nguyễn Thị Hương`) đọc lại từ Oracle giống hệt giá trị trong Parquet.

## Ngoài phạm vi
- Logic sinh customers/customer_person/dq_defects/admin_unit_mapping (1a), accounts/transactions/dq_labels (1b-i), typologies và các dòng `ground_truth` khác `sanctions_hit`/`pep_hit`/`screening_trap` (1b-ii). 1c chỉ gọi, ghép và ghi ra; bất biến "50–100 counterparties" của `dense` do 1b-i kiểm (AC6 của 1b-i).
- Tên trong chữ viết gốc (Cyrillic, Arabic, Hán tự); watchlist chỉ có tên Latin.
- Dữ liệu sanctions/PEP thật hoặc bất kỳ lời gọi API bên ngoài nào.
- Watchlist delta/versioning cho incremental screening (Phase 3).
- Schema Oracle "production": partitioning, local index, FK, grants, masking view (Phase 2). Loader 1c chỉ tạo bảng đơn giản có PK.
- Nạp vào Neo4j (Phase 6); nạp incremental/append (`aml load` luôn full refresh).
- Chạy profile `small`/`large` kích thước thật trong test (chỉ dùng TINY).

## Giả định
- 1a đã duyệt; tên cột/hàm lấy từ `specs/datagen-customers.md`. `stable_hash` là helper dùng chung do 1a định nghĩa.
- 1b-i/1b-ii giữ nguyên schema `ground_truth` / `dq_labels` / `ActivityData` như coordinator đã chốt; 1b nhận nguyên `CustomerTables` của 1a (đọc `person_id` từ `customer_person`), pipeline không ghép cột.
- Không generator nào dùng giờ hệ thống; mốc thời gian lấy từ `data.start_date` (2026-01-01) và `data.reference_date` (2026-06-30).
- `get_settings()` đang `lru_cache`; test CLI gọi `get_settings.cache_clear()` (hoặc CLI đọc settings qua hàm patch được) để env override có hiệu lực.
- Watchlist cố định 2000 entry, 20 true hit, 30 trap cho mọi profile (override bằng env); alias ở bảng `watchlist_alias`; DOB 3 cột `dob`/`dob_year`/`dob_precision` (Q1, Q2, Q4, Q10).
- `aml load` nạp vào `DB_BACKEND` (`--backend` override), full refresh; Oracle down -> fallback DuckDB nếu `fallback_to_duckdb`, ngược lại exit 1; ghi 1 sự kiện `audit_log` mỗi lần load (Q12–Q14).
- `aml data` có `--profile/--seed/--out` (CLI > env > config.yaml), ghi qua thư mục tạm rồi thay file (Q11, Q16).
- TINY cho profile `dense` dùng 20000 giao dịch (không phải 5000): 300 account × ≥ 50 counterparty cần ≥ 7500 giao dịch hai phía. Người dùng duyệt sửa fixture khi chạy loop 1c.

## Câu hỏi mở
<!-- Phải trả lời hết ([x]) trước khi duyệt. -->
- [x] Q1. Lưu alias thế nào? — đề xuất mặc định: bảng riêng `watchlist_alias` (1 entry - n alias, `alias_type` AKA/TRANSLITERATION/REORDERED). Lý do: Phase 3 screen từng alias như một tên độc lập; cột list/JSON khó dùng ở cả Oracle lẫn DuckDB. — Trả lời: theo đề xuất.
- [x] Q2. Biểu diễn DOB chỉ có năm? — đề xuất mặc định: 3 cột `dob` (DATE, NULL), `dob_year` (INT), `dob_precision` (DAY/YEAR/NONE); tỉ lệ 65% DAY / 30% YEAR / 5% NONE. Lý do: DATE thuần ở cả hai backend, Tier 2 so năm trực tiếp. — Trả lời: theo đề xuất.
- [x] Q3. Tên watchlist viết thế nào? — đề xuất mặc định: Latin, uppercase, không dấu, chỉ chữ và khoảng trắng (kiểu OFAC/UN). Lý do: buộc Phase 3 normalize phía customer; không có chữ viết gốc. — Trả lời: theo đề xuất.
- [x] Q4. Số true hit, trap và tỉ lệ SANCTIONS/PEP? — đề xuất mặc định: `true_hits=20`, `traps=30`, cố định cho mọi profile; khoảng 60% SANCTIONS / 40% PEP trên toàn watchlist; true hit chia đều `sanctions_hit` / `pep_hit`. Lý do: đủ đo recall/precision ở Phase 3, không phụ thuộc kích thước profile. — Trả lời: theo đề xuất.
- [x] Q5. Cách tạo true hit? — đề xuất mặc định: chọn theo seed các `person_id` mà mọi CIF đều không có trong `dq_defects` và không xuất hiện trong `ground_truth` của 1b; tạo entry từ tên bỏ dấu của CIF chính; khoảng 1/3 đảo thứ tự tên hoặc chỉ khớp qua alias, khoảng 1/3 chỉ có năm sinh; customers không bị sửa; ground truth liệt kê mọi CIF của người đó. Lý do: nhãn sạch, giữ quy ước "mỗi entity thuộc tối đa một case" của 1b, và test ER + screening cùng lúc. — Trả lời: theo đề xuất.
- [x] Q6. Định nghĩa trap entry và cách gắn nhãn? — đề xuất mặc định: tên gồm 2–3 token phổ biến (NGUYEN, VAN, THI, TRAN) cộng 1 token phân biệt không có trong tên customer nào; ghi vào `ground_truth` với typology mới `screening_trap` (`is_suspicious=False`, `role='trap_entry'`). Cần 1b-ii thêm `screening_trap` vào danh sách typology. Lý do: đo được FP của screening trên đúng tập trap. — Trả lời: theo đề xuất.
- [x] Q7. `start_ts`/`end_ts`/`role` cho dòng sanctions/PEP trong `ground_truth`? — đề xuất mặc định: `start_ts` = `listed_date` 00:00, `end_ts` NULL; role `listed_entry` (watchlist entry) và `subject` (customer). Lý do: hit là trạng thái, không phải hoạt động trong một cửa sổ thời gian. — Trả lời: theo đề xuất.
- [x] Q8. Gộp `dq_defects` của 1a vào `dq_labels` thế nào? — đề xuất mặc định: `entity_type='customer'`, `entity_id=cif`, `defect_type` giữ nguyên mã 1a (UPPER_SNAKE, ví dụ `FUTURE_DOB`), `detail=NULL`; không ghi `dq_defects.parquet` riêng. 1b-i dùng `DUPLICATE_TRANSACTION` (đã đồng nhất). Lý do: một bảng nhãn DQ duy nhất cho Phase 2 so với `dq_results`. — Trả lời: theo đề xuất.
- [x] Q9. `customers.parquet` có chứa `person_id` không? — đề xuất mặc định: không; `person_id` chỉ nằm trong `customer_person.parquet` (đáp án ER). Lý do: Phase 4 không được đọc đáp án từ bảng đầu vào. — Trả lời: theo đề xuất.
- [x] Q10. Kích thước watchlist có đổi theo profile không? — đề xuất mặc định: không, `data.watchlist.entries=2000` cho mọi profile, override bằng env. — Trả lời: theo đề xuất.
- [x] Q11. Chạy lại `aml data` vào thư mục đã có dữ liệu? — đề xuất mặc định: ghi vào thư mục tạm cạnh đó rồi thay từng file `<table>.parquet` + `manifest.json`; file lạ trong thư mục được giữ nguyên. Lý do: không trộn bảng cũ/mới khi chạy dở, không xóa file của người dùng. — Trả lời: theo đề xuất.
- [x] Q12. `aml load` nạp vào đâu, xử lý dữ liệu cũ ra sao? — đề xuất mặc định: backend theo `DB_BACKEND` (override bằng `--backend`); full refresh (tạo bảng nếu chưa có qua `010_datagen.sql`, rồi xóa sạch và insert); cần cả hai backend thì chạy hai lần. Lý do: idempotent, khớp `get_db`. — Trả lời: theo đề xuất.
- [x] Q13. `aml load --backend oracle` khi Oracle down? — đề xuất mặc định: theo `get_db`: `fallback_to_duckdb=true` thì cảnh báo, nạp DuckDB và in rõ backend thực tế; `false` thì exit 1. Lý do: nhất quán với hành vi hiện có. — Trả lời: theo đề xuất.
- [x] Q14. Ghi `audit_log`? — đề xuất mặc định: `aml data` không ghi (không cần DB, giống 1a); `aml load` ghi 1 event mỗi lần (`module='datagen'`, `entity_type='dataset'`, `entity_id='<profile>-seed<seed>'`, `decision='LOADED'`, `details` = số dòng theo bảng). Lý do: biết dữ liệu trong DB đến từ đâu mà không làm loãng audit trail. — Trả lời: theo đề xuất.
- [x] Q15. DDL Phase 1 so với schema Phase 2? — đề xuất mặc định: bảng đơn giản chỉ có PK trong `ddl/010_datagen.sql`, chuỗi Oracle `VARCHAR2(n CHAR)`; Phase 2 thay bằng bản partitioned. PK của `transactions` là `txn_id` (bản trùng DQ của 1b có `txn_id` mới nên không vi phạm). Lý do: `aml load` chạy được ngay mà không đi trước thiết kế DBA của Phase 2. — Trả lời: theo đề xuất.
- [x] Q16. Option CLI của `aml data`? — đề xuất mặc định: có `--profile`, `--seed`, `--out`; ưu tiên CLI > env > config.yaml. Lý do: `make bench` cần sinh small và dense liền nhau mà không sửa file. — Trả lời: theo đề xuất.
- [x] Q17. Độ tất định so thế nào? — đề xuất mặc định: Parquet so nội dung (`assert_frame_equal`), `manifest.json` so từng byte; sub-stream `SeedSequence([seed, stable_hash(<tên bảng>)])` theo quy ước 1a. Lý do: metadata Parquet có thể chứa phiên bản thư viện. — Trả lời: theo đề xuất.
- [x] Q18. Spec có 11 AC (vượt mức ~10). — đề xuất mặc định: giữ nguyên; nếu muốn tách thì tách AC9–AC11 (loaders + `aml load`) thành spec 1d `datagen-load`. — Trả lời: theo đề xuất.
