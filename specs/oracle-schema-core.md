---
id: oracle-schema-core
status: approved
approved_by: pthieu
---

# Phase 2a — Schema lõi Oracle: partitioning, index/constraint, DBMS_STATS, `acct_edge_daily`

## Bối cảnh
Phase 2 (PROJECT_BRIEF.md mục 3) được tách thành 4 spec: **2a (spec này)** schema lõi; 2b `oracle-security`
(roles, least privilege, masking view, unified auditing, audit_log append-only); 2c `oracle-retention-dq`
(purge/archive partition theo retention, DQ framework); 2d `dba-runbook-tuning` (`dba/RUNBOOK.md`, tuning
before/after). 2a nâng schema Phase 1 (`sql/oracle/ddl/010_datagen.sql`, bảng heap, chỉ có PK) lên mức
production: `transactions` interval-partition theo tháng với local index và bằng chứng partition pruning,
constraint + index cho FK, thống kê `DBMS_STATS`, và bảng cạnh `acct_edge_daily` cho graph trace (Phase 5/6) —
là materialized view trên Oracle và bảng thường trên DuckDB để chế độ DuckDB-only vẫn chạy được trace.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/dba/schema.py
SCHEMA_SCRIPTS: dict[str, tuple[str, ...]] = {
    "oracle": (
        "ddl/000_audit_log.sql",
        "ddl/010_datagen.sql",
        "ddl/020_transactions_partitioning.sql",
        "ddl/030_constraints_indexes.sql",
        "ddl/040_acct_edge_daily.sql",
    ),
    "duckdb": ("ddl/000_audit_log.sql", "ddl/010_datagen.sql", "ddl/040_acct_edge_daily.sql"),
}


def apply_schema(db: Database) -> dict[str, int]: ...  # script -> số statement; idempotent


# src/aml/dba/edges.py
def refresh_acct_edge_daily(db: Database) -> int: ...  # trả số dòng acct_edge_daily


# src/aml/dba/stats.py
def gather_stats(db: Database) -> list[str]: ...  # Oracle: bảng đã gather; DuckDB: []


# src/aml/dba/plans.py
@dataclass(frozen=True)
class PruningQuery:
    name: str  # "single" | "iterator" | "all"
    sql: str  # predicate dạng literal TIMESTAMP, không bind
    expected_op: str  # "PARTITION RANGE SINGLE" | "... ITERATOR" | "... ALL"


def pruning_queries(settings: Settings) -> list[PruningQuery]: ...
def explain_plan(
    db: Database, sql: str
) -> str: ...  # Oracle only, nếu không raise NotImplementedError
```
- `load_parquet` (Phase 1c) thay `DDL_SCRIPTS` bằng `apply_schema(db)`, xoá dữ liệu theo **thứ tự ngược**
  `TABLES` (con trước cha, vì có FK), nạp như cũ, rồi gọi `refresh_acct_edge_daily(db)` và `gather_stats(db)`.
- `aml init-db` gọi `apply_schema(db)` (toàn bộ schema, không cần dữ liệu).
- CLI mới `aml explain-pruning [--out PATH]` (mặc định `results/phase2/partition_pruning.txt`).

### Thiết kế schema Oracle (xác nhận ở Câu hỏi mở)
- `020_transactions_partitioning.sql`: `txn_ts` NOT NULL; nếu `TRANSACTIONS` chưa có trong `user_part_tables` thì
  `ALTER TABLE transactions MODIFY PARTITION BY RANGE (txn_ts) INTERVAL (NUMTOYMINTERVAL(1,'MONTH'))
  (PARTITION p_before_2000 VALUES LESS THAN (TIMESTAMP '2000-01-01 00:00:00')) ONLINE UPDATE INDEXES (...)`.
  Đã partition thì không làm gì.
- Index: PK `txn_id` giữ nguyên (global, non-partitioned); local `IX_TXN_FROM_TS(from_account_id, txn_ts)`,
  `IX_TXN_TO_TS(to_account_id, txn_ts)`; index cho FK `IX_ACCOUNTS_CIF(cif)`, `IX_WLA_ENTRY(entry_id)`,
  `IX_CP_PERSON(person_id)` (tra cứu ER Phase 4).
- Constraint (đặt tên, ENABLE VALIDATE): `FK_ACCOUNTS_CUSTOMER` (accounts.cif → customers),
  `FK_CP_CUSTOMER` (customer_person.cif → customers), `FK_WLA_WATCHLIST` (watchlist_alias.entry_id → watchlist),
  `CK_TXN_AMOUNT_POS` (`amount_vnd > 0`), `CK_TXN_CHANNEL` (5 channel của 1b-i),
  `CK_TXN_HAS_PARTY` (`from_account_id IS NOT NULL OR to_account_id IS NOT NULL`). Không FK từ `transactions`
  sang `accounts` (account `EXT-`); không constraint nào chặn defect DQ đã cài (DOB tương lai, ID sai độ dài,
  thiếu occupation, giao dịch trùng) — việc đó thuộc DQ framework 2c.
- `acct_edge_daily(src_acct, dst_acct, day, txn_count, total_amount)` = `SELECT from_account_id, to_account_id,
  TRUNC(txn_ts), COUNT(*), SUM(amount_vnd) FROM transactions WHERE from_account_id IS NOT NULL AND to_account_id
  IS NOT NULL GROUP BY 1,2,3`. Oracle: `MATERIALIZED VIEW ... BUILD IMMEDIATE REFRESH COMPLETE ON DEMAND`, refresh
  bằng `DBMS_MVIEW.REFRESH('ACCT_EDGE_DAILY','C', atomic_refresh => FALSE)`, index `IX_AED_SRC_DAY(src_acct, day)`,
  `IX_AED_DST_DAY(dst_acct, day)`. DuckDB: `CREATE OR REPLACE TABLE acct_edge_daily AS SELECT ... CAST(txn_ts AS DATE)`.
- Mọi lệnh DDL Oracle nằm trong khối PL/SQL `EXECUTE IMMEDIATE`, nuốt đúng mã lỗi "đã tồn tại" (ORA-00955,
  ORA-01442, ORA-02260, ORA-02261, ORA-02264, ORA-02275, ORA-01408), mỗi statement kết thúc bằng dòng `/`.

## Tiêu chí nghiệm thu
<!-- Fixture TINY = `tiny_parquet` của tests/datagen/conftest.py (300 customers, 5000 txns, 6 tháng từ 2026-01-01, seed 42).
Test có nhãn [oracle] dùng @pytest.mark.oracle và tự skip khi Oracle không chạy; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given thư mục `sql/oracle/` của repo, When duyệt mọi file `*.sql` (không cần Oracle), Then `split_oracle_script` tách mỗi file không lỗi và ra ≥ 1 statement, không statement nào (bỏ dòng comment) bắt đầu bằng `CREATE`/`ALTER`/`DROP` (DDL phải nằm trong khối `BEGIN`/`DECLARE`), và mọi tên trong `SCHEMA_SCRIPTS["oracle"]` và `SCHEMA_SCRIPTS["duckdb"]` resolve được qua `sql_file` về đúng thư mục `sql/<backend>/`.
- AC2: Given DuckDB rỗng (`duck`) sau `apply_schema` và 5 giao dịch T1 `A1→A2` 2026-02-01 09:00:00 100000, T2 `A1→A2` 2026-02-01 23:59:59 50000, T3 `A1→A2` 2026-02-02 00:00:00 70000, T4 `CASH` null→`A1` 2026-02-01 10:00:00 400000, T5 `A1→EXT-X` 2026-02-01 11:00:00 30000, When gọi `refresh_acct_edge_daily` hai lần, Then mỗi lần trả 3 và bảng có đúng 3 dòng (`A1,A2,2026-02-01,2,150000`), (`A1,A2,2026-02-02,1,70000`), (`A1,EXT-X,2026-02-01,1,30000`), và `audit_log` có đúng 2 dòng `module='dba'`, `entity_id='acct_edge_daily'`, `decision='REFRESHED'`, `details.rows = 3`.
- AC3: Given DuckDB rỗng và fixture TINY, When gọi `load_parquet` hai lần, Then sau mỗi lần số dòng 9 bảng bằng manifest, `acct_edge_daily` không có `src_acct`/`dst_acct` null, `SUM(txn_count)` = số giao dịch có cả hai phía khác null và `SUM(total_amount)` = tổng `amount_vnd` của chúng (tính bằng pandas trên `transactions.parquet`), và `gather_stats` trả `[]` trên DuckDB.
- AC4: [oracle] Given `transactions` bị drop rồi tạo lại bằng `010_datagen.sql` (heap như Phase 1) và có 3 giao dịch ở 2026-01-15, 2026-02-15, 2026-03-15, When gọi `apply_schema` hai lần, Then `user_part_tables` cho `TRANSACTIONS` có `partitioning_type='RANGE'`, `interval` (bỏ khoảng trắng) = `NUMTOYMINTERVAL(1,'MONTH')`, `user_part_key_columns` = [`TXN_TS`], `user_tab_cols.nullable` của `TXN_TS` = `N`, `COUNT(*)` vẫn = 3, lần 2 không raise, và `audit_log` có đúng 1 dòng mới `module='dba'`, `entity_id='transactions'`, `decision='PARTITIONED'`.
- AC5: [oracle] Given schema sau `apply_schema`, When đọc data dictionary, Then `IX_TXN_FROM_TS`, `IX_TXN_TO_TS` có `user_part_indexes.locality='LOCAL'` với cột đúng thứ tự như thiết kế; index của PK `transactions` có `user_indexes.partitioned='NO'`; `IX_ACCOUNTS_CIF`, `IX_WLA_ENTRY`, `IX_CP_PERSON`, `IX_AED_SRC_DAY`, `IX_AED_DST_DAY` tồn tại; và 6 constraint `FK_ACCOUNTS_CUSTOMER`, `FK_CP_CUSTOMER`, `FK_WLA_WATCHLIST`, `CK_TXN_AMOUNT_POS`, `CK_TXN_CHANNEL`, `CK_TXN_HAS_PARTY` có `status='ENABLED'`, `validated='VALIDATED'`.
- AC6: [oracle] Given fixture TINY, When gọi `load_parquet` hai lần liên tiếp, Then không lỗi ORA-02292, số dòng 9 bảng bằng manifest, 6 constraint của AC5 vẫn `VALIDATED`; và sau đó INSERT một giao dịch `amount_vnd = 0` raise lỗi chứa `ORA-02290`, INSERT một account `cif='C_NOT_EXIST'` raise lỗi chứa `ORA-02291`.
- AC7: [oracle] Given fixture TINY vừa nạp bằng `load_parquet`, When đọc thống kê, Then `user_tab_statistics.last_analyzed` khác null cho 9 bảng dữ liệu và `ACCT_EDGE_DAILY`, `num_rows` của `TRANSACTIONS` = số dòng manifest, `DBMS_STATS.GET_PREFS('INCREMENTAL', USER, 'TRANSACTIONS')='TRUE'`, đúng 6 partition của `TRANSACTIONS` có `num_rows > 0` (2026-01 … 2026-06), và `audit_log` có 1 dòng mới `module='dba'`, `decision='STATS_GATHERED'` với `details.tables` gồm 10 tên bảng.
- AC8: [oracle] Given fixture TINY nạp vào cả Oracle và một DuckDB tạm, When đọc `acct_edge_daily` ở hai backend, Then `user_mviews` có `ACCT_EDGE_DAILY` với `refresh_method='COMPLETE'`, và hai DataFrame (sắp theo `src_acct, dst_acct, day`; `day` về `date`, số về `int64`) bằng nhau theo `pd.testing.assert_frame_equal`.
- AC9: [oracle] Given fixture TINY đã nạp và `pruning_queries(settings)` với `data.start_date=2026-01-01`, When gọi `explain_plan` cho từng query, Then query `single` (`txn_ts` trong [2026-02-01, 2026-03-01)) cho plan chứa `PARTITION RANGE SINGLE` với Pstart = Pstop là số nguyên; query `iterator` ([2026-02-01, 2026-04-01)) chứa `PARTITION RANGE ITERATOR` với Pstop − Pstart = 1; query `all` (không predicate `txn_ts`) chứa `PARTITION RANGE ALL`; trên DuckDB `explain_plan` raise `NotImplementedError` với thông điệp chứa "Oracle only".
- AC10: Given `DB_BACKEND=duckdb` (hoặc Oracle down và fallback sang DuckDB), When chạy `aml explain-pruning --out <tmp>/p.txt`, Then exit code 2, stderr chứa "Oracle only" và không tạo file; [oracle] với `DB_BACKEND=oracle` thì exit 0, file có 3 khối (mỗi khối gồm tên query, SQL, output `DBMS_XPLAN`) và `audit_log` có 1 dòng `module='dba'`, `decision='EVIDENCE_CAPTURED'`, `details.path` = đường dẫn file.

## Ngoài phạm vi
- Roles/grants, least privilege, masking view PII, unified auditing, trigger chặn UPDATE/DELETE trên `audit_log` (2b).
- Partition hoá `audit_log`, thủ tục purge/archive theo retention, ghi chú thời hạn lưu trữ theo luật (2c).
- DQ framework `dq_rules`/runner/`dq_results`/trend view (2c); constraint chặn defect DQ.
- `dba/RUNBOOK.md`, RMAN/AWR/ASH, `DBMS_XPLAN.DISPLAY_CURSOR` với runtime stats, tuning before/after có timing (2d).
- Fast refresh / MV log / refresh theo lịch `DBMS_SCHEDULER` cho `acct_edge_daily`; SQL property graph (Phase 5).
- Constraint và index trên DuckDB; partition trên DuckDB.
- Đo hiệu năng profile `large` trong test; TRUNCATE thay DELETE khi nạp lại.

## Giả định
- Oracle 23ai Free (image đã pin trong docker-compose) hỗ trợ `ALTER TABLE ... MODIFY PARTITION BY ... ONLINE`, interval partitioning và `PLAN_TABLE` dùng chung; user `aml_owner` (APP_USER của gvenzl) có quyền tạo bảng/MV/index và gọi `DBMS_STATS`, `DBMS_MVIEW` trên schema của mình.
- Test [oracle] ghi đè dữ liệu trong schema `aml_owner` (giống AC11 của 1c) — chấp nhận được vì dữ liệu chỉ là tổng hợp và tái tạo được bằng `aml load`.
- Dữ liệu Phase 1 thoả các constraint: `txn_ts` không null, `amount_vnd > 0`, channel thuộc 5 giá trị, mọi `accounts.cif` có trong `customers`, mọi `watchlist_alias.entry_id` có trong `watchlist`.
- `day` = ngày theo giờ địa phương Việt Nam của `txn_ts` naive (quy ước 1b-i).
- 2a không thêm key mới vào `config.yaml`: biên partition neo `2000-01-01` là cấu trúc, không phải ngưỡng nghiệp vụ; cửa sổ query pruning suy ra từ `data.start_date` (tháng thứ 2 và tháng 2–3 của cửa sổ).
- Audit: chỉ ghi khi có hành động thật — `PARTITIONED` (chỉ lúc chuyển đổi), `REFRESHED`, `STATS_GATHERED` (Oracle), `EVIDENCE_CAPTURED`; `version` = tên script/hàm.

- Mọi câu hỏi mở Q1–Q14 đã chốt theo đề xuất mặc định (2026-10-10); thiết kế trong mục "Thiết kế schema Oracle" là giả định đã xác nhận.

## Câu hỏi mở
- [x] Q1. Cách tách Phase 2? — đề xuất mặc định: 4 spec 2a/2b/2c/2d như mục Bối cảnh; file này là 2a. Lý do: mỗi spec ≤ 10 AC, 2b cần quyền SYS (init script) nên tách riêng. — Trả lời: theo đề xuất (người dùng chọn qua câu hỏi).
- [x] Q2. Bảng `transactions` heap của Phase 1 đã tồn tại trong volume Oracle (DDL idempotent nuốt ORA-00955 nên sẽ âm thầm không partition) — chuyển đổi thế nào? — đề xuất mặc định: script 020 tự kiểm `user_part_tables` và `ALTER TABLE ... MODIFY PARTITION BY ... ONLINE UPDATE INDEXES`, 010 giữ nguyên. Lý do: một đường code cho cả cài mới lẫn nâng cấp, và là kỹ thuật DBA đáng trình bày. — Trả lời: theo đề xuất (người dùng chọn qua câu hỏi).
- [x] Q3. Partition neo (range partition bắt buộc của interval)? — đề xuất mặc định: `p_before_2000` < `2000-01-01`, luôn rỗng. Lý do: interval table không drop được partition range cuối cùng (ORA-14758), neo rỗng để 2c purge tự do. — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q4. PK `txn_id` là global index hay đổi thành local unique `(txn_id, txn_ts)`? — đề xuất mặc định: giữ global non-partitioned PK. Lý do: không đổi contract 1c, tra cứu theo id; cái giá là 2c phải `DROP PARTITION ... UPDATE GLOBAL INDEXES` (ghi trong RUNBOOK). — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q5. Có FK từ `transactions` sang `accounts` không? — đề xuất mặc định: không (account `EXT-` không có trong `accounts`; CASH/CARD có một phía null); chỉ CHECK `CK_TXN_*`. Constraint không chặn defect DQ đã cài. — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q6. Constraint/index có áp lên DuckDB không? — đề xuất mặc định: không, DuckDB chỉ thêm `acct_edge_daily`. Lý do: `CREATE TABLE IF NOT EXISTS` không sửa file DuckDB cũ, và FK DuckDB chặn `DELETE` khi nạp lại. — Trả lời: theo đề xuất (người dùng chọn qua câu hỏi).
- [x] Q7. Nạp lại khi đã có FK? — đề xuất mặc định: `load_parquet` DELETE theo thứ tự ngược `TABLES`, INSERT theo thứ tự xuôi (đã đúng cha trước con). Lý do: tránh ORA-02292 mà không phải disable constraint. — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q8. Nội dung `acct_edge_daily`? — đề xuất mặc định: chỉ giao dịch có cả hai phía khác null, **có** cạnh tới/từ `EXT-`, **có** giao dịch trùng (DQ) như dữ liệu thô, giữ self-transfer nếu có, `day` theo giờ VN. Lý do: MV phản ánh trung thực bảng nguồn; trace cần thấy tiền ra ngoài ngân hàng. — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q9. Kiểu refresh MV? — đề xuất mặc định: `REFRESH COMPLETE ON DEMAND`, gọi ở cuối `load_parquet` với `atomic_refresh => FALSE`. Lý do: nạp là bulk replace; fast refresh cần MV log và hạn chế aggregate — để RUNBOOK 2d bàn. — Trả lời: theo đề xuất (người dùng chọn qua câu hỏi).
- [x] Q10. DuckDB `acct_edge_daily`: bảng hay view? — đề xuất mặc định: bảng thật dựng lại bằng `CREATE OR REPLACE TABLE ... AS`, cùng tên/cột với Oracle. Lý do: trace Phase 5/6 dùng chung SQL và có dữ liệu đã tổng hợp sẵn. — Trả lời: theo đề xuất (người dùng chọn qua câu hỏi).
- [x] Q11. Gather stats thế nào? — đề xuất mặc định: `GATHER_TABLE_STATS` cho 10 bảng cố định (không `GATHER_SCHEMA_STATS`), `INCREMENTAL=TRUE` cho `TRANSACTIONS`, `method_opt` mặc định; chạy sau mỗi `load_parquet`; DuckDB no-op trả `[]`, không ghi audit. — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q12. Bằng chứng pruning lấy thế nào? — đề xuất mặc định: `EXPLAIN PLAN` + `DBMS_XPLAN.DISPLAY(format=>'TYPICAL')` với predicate literal (bind cho Pstart/Pstop = `KEY`), không dùng `DISPLAY_CURSOR` (cần quyền V$, thuộc 2d); ghi `results/phase2/partition_pruning.txt` và commit file đó làm bằng chứng cho README. — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q13. Code đặt ở đâu và CLI? — đề xuất mặc định: package `src/aml/dba/` (`schema.py`, `edges.py`, `stats.py`, `plans.py`); `aml init-db` gọi `apply_schema`; lệnh mới `aml explain-pruning`, trên DuckDB exit 2 (lỗi dùng sai backend, giống profile không hợp lệ ở `aml data`). — Trả lời: theo đề xuất (người dùng giữ mặc định).
- [x] Q14. Comment trong `000_audit_log.sql` hứa partition + trigger + grants cho `audit_log` ở Phase 2 — thuộc spec nào? — đề xuất mặc định: trigger append-only + grants ở 2b; partition `audit_log` ở 2c và **loại khỏi** purge tự động. — Trả lời: theo đề xuất (người dùng giữ mặc định).
