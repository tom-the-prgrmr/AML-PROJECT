---
id: dba-runbook-tuning
status: approved
approved_by: pthieu
---

# Phase 2d — DBA runbook (`dba/RUNBOOK.md`) và tuning một query chậm có before/after

## Bối cảnh
Phase 2 (PROJECT_BRIEF.md mục 3, bullet "DBA runbook") yêu cầu `dba/RUNBOOK.md` gồm ghi chú thực hành + script cho
RMAN backup/restore, đọc AWR/ASH và `DBMS_XPLAN`, và tuning **một** query chậm từng bước có plan + timing trước/sau.
2d cũng nhận 3 việc 2a hoãn lại: `DBMS_XPLAN.DISPLAY_CURSOR` với `ALLSTATS LAST` (2a Q12), ghi chú MV log / fast
refresh cho `acct_edge_daily` (2a Q9), và ghi chú `DROP PARTITION ... UPDATE GLOBAL INDEXES` (2a Q4). Vì phần lớn là
tài liệu, spec này chốt **phần nào kiểm chứng tự động được**: cấu trúc runbook, script được tham chiếu có thật và đúng
quy ước `/`, lệnh `aml tune-demo` sinh bằng chứng thật vào `results/phase2/`, và số liệu trong runbook phải trùng file
bằng chứng (quy tắc "Never fabricate results" của CLAUDE.md).

### Hiện trạng môi trường (đo ngày 2026-10-10 trên container `aml-toolkit-oracle-1`, phải ghi trung thực vào runbook)
- Image `gvenzl/oracle-free:23-slim`, banner `Oracle AI Database 26ai Free Release 23.26.3.0.0`.
- **Không có binary `rman`** trong `$ORACLE_HOME/bin` của image slim (chỉ có `sqlplus`, `expdp`, `impdp`); database ở
  `NOARCHIVELOG`, `db_recovery_file_dest` rỗng. Vậy RMAN chỉ trình bày được ở mức khái niệm + script tham khảo;
  thứ chạy được thật trong container này là backup logic bằng Data Pump (`expdp`/`impdp`) và backup volume `oradata`.
- `control_management_pack_access = DIAGNOSTIC+TUNING`; `DBA_HIST_SNAPSHOT` có 8 snapshot (interval 1 giờ, retention
  8 ngày), `V$ACTIVE_SESSION_HISTORY` có dữ liệu; `awrrpt.sql`, `ashrpt.sql`, `spcreate.sql` (Statspack) đều có trong
  `$ORACLE_HOME/rdbms/admin`. Tức là AWR/ASH **truy vấn được về mặt kỹ thuật** khi kết nối SYS; quyền sử dụng theo
  license là câu hỏi riêng (Q3).
- User `aml_owner` chỉ có `DB_DEVELOPER_ROLE`: `SELECT` trên `V$SQL`, `V$SQL_PLAN_STATISTICS_ALL`,
  `V$ACTIVE_SESSION_HISTORY`, `V$DATABASE`, `DBA_HIST_SNAPSHOT` đều trả **ORA-00942**. `DISPLAY_CURSOR` vì thế cần
  một bước cấp quyền bằng SYS (Q2). `user_mview_logs` rỗng (chưa có MV log).
- Oracle hiện đang chứa fixture TINY (5100 giao dịch, 7 partition); đã thử bằng `EXPLAIN PLAN`: query "before" dưới đây
  cho `PARTITION RANGE ALL` (plan hash 935595979), query "after" cho `PARTITION RANGE SINGLE` (plan hash 3905367866),
  hai query trả cùng 4 dòng.

### Query được tuning (xác nhận ở Q1)
"Tài khoản có tổng tiền chuyển ra trong cửa sổ 30 ngày ≥ ngưỡng `thresholds.large_cash_vnd`" — dạng aggregate
30 ngày theo tài khoản mà rule monitoring Phase 5 sẽ dùng. Cửa sổ = 30 ngày bắt đầu từ ngày đầu tháng thứ 3 của
`data.start_date` (mặc định `2026-03-01` … `2026-03-30`), nằm gọn trong một partition tháng.
- **before** (anti-pattern hay gặp: bọc hàm lên cột partition key nên mất pruning và mất khả năng dùng index):
  `SELECT from_account_id, COUNT(*) AS txn_count, SUM(amount_vnd) AS total_out FROM transactions
  WHERE TRUNC(txn_ts) BETWEEN DATE '2026-03-01' AND DATE '2026-03-30' AND from_account_id IS NOT NULL
  GROUP BY from_account_id HAVING SUM(amount_vnd) >= 400000000`
- **after** (viết lại predicate dạng khoảng nửa mở, sargable): thay điều kiện thời gian bằng
  `txn_ts >= TIMESTAMP '2026-03-01 00:00:00' AND txn_ts < TIMESTAMP '2026-03-31 00:00:00'`, phần còn lại giữ nguyên.
- Thay đổi duy nhất là viết lại SQL: **không** tạo/xoá/ẩn index, không đổi schema, không gather stats — nên
  `aml tune-demo` chạy lại bao nhiêu lần cũng không để lại trạng thái.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/dba/tuning.py
@dataclass(frozen=True)
class TuningStep:
    name: str  # "before" | "after"
    sql: str  # predicate literal, không bind; không chứa hint
    change: str  # một câu mô tả thay đổi so với bước trước ("" cho before)


@dataclass(frozen=True)
class TuningResult:
    step: TuningStep
    plan: str  # output DBMS_XPLAN.DISPLAY_CURSOR(format => 'ALLSTATS LAST')
    plan_hash_value: int
    buffer_gets: int  # cột Buffers của dòng Id 0/1 ở lần chạy cuối
    elapsed_ms: tuple[float, ...]  # mỗi phần tử = 1 lần chạy, fetch hết dòng
    rows: int


def tuning_steps(settings: Settings) -> list[TuningStep]: ...
def has_cursor_stats_access(db: Database) -> bool: ...  # SELECT được V$SQL_PLAN_STATISTICS_ALL?
def run_tuning(
    db: Database, settings: Settings, runs: int = 5
) -> list[TuningResult]: ...  # Oracle only, nếu không raise NotImplementedError
```
- `run_tuning`: với mỗi step chạy 1 lần warm-up (không tính), rồi `runs` lần đo bằng `time.perf_counter`; SQL thực thi
  = `step.sql` chèn hint `/*+ GATHER_PLAN_STATISTICS */` và comment tag `/* aml-tune-demo:<name> */` để tìm `sql_id`
  trong `V$SQL`; plan lấy bằng `DBMS_XPLAN.DISPLAY_CURSOR(sql_id, child, 'ALLSTATS LAST')` sau lần chạy cuối.
- CLI mới `aml tune-demo [--out PATH] [--runs N]` (mặc định `results/phase2/tune_demo.txt`, `runs=5`).

### Bố cục thư mục `dba/` (thư mục con quyết định trạng thái kiểm chứng của script)
- `dba/RUNBOOK.md` — viết bằng tiếng Anh (Q8), có đúng 7 heading cấp 2 theo thứ tự:
  `## 1. Environment and limits`, `## 2. Backup and restore`, `## 3. Reading AWR, ASH and Statspack`,
  `## 4. Reading DBMS_XPLAN output`, `## 5. Materialized view refresh`, `## 6. Partition maintenance`,
  `## 7. Tuning walkthrough`, và một bảng `## Script index` ở cuối (cột `Script | Runs as | Status | Purpose`).
- `dba/scripts/owner/*.sql` — chạy được bằng `aml_owner`, không bind, chỉ đọc; **Status `verified`** (test chạy thật).
  Tối thiểu: `xplan_display_cursor_last.sql` (plan `ALLSTATS LAST` của các cursor có tag `aml-tune-demo`),
  `xplan_explain_typical.sql`, `partition_and_index_status.sql` (`user_tab_partitions`, `user_indexes.status`).
- `dba/scripts/sys/*.sql` — cần SYS/DBA; **Status `manual`**: người làm chạy tay một lần qua
  `docker compose exec -T oracle sqlplus -s / as sysdba` và lưu output vào `results/phase2/runbook/<tên-file>.txt`.
  Tối thiểu: `010_grant_tuning_views.sql` (đổi container sang `FREEPDB1`, `GRANT SELECT ON V_$SQL, V_$SQL_PLAN,
  V_$SQL_PLAN_STATISTICS_ALL, V_$SESSION TO aml_owner`), `environment_facts.sql` (log mode, FRA, pack parameter, số
  snapshot AWR), `ash_top_sql.sql`, `awr_snapshots.sql`.
- `dba/scripts/reference/*` — **không chạy được/không chạy trong môi trường này; Status `reference`**, runbook nêu rõ lý do.
  Tối thiểu: `rman_backup_full.rman`, `rman_restore_pitr.rman`, `enable_archivelog.sql`, `expdp_schema.par`,
  `mv_log_fast_refresh.sql` (MV log `WITH ROWID, SEQUENCE (...) INCLUDING NEW VALUES` + MV `REFRESH FAST` có
  `COUNT(*)`/`COUNT(amount_vnd)`), `drop_partition_update_global_indexes.sql`, `statspack_install.sql`.
- Mọi file `.sql` dưới `dba/scripts/` theo quy ước Oracle của repo: mỗi statement kết thúc bằng dòng chỉ có `/`, không
  dùng lệnh riêng của SQL*Plus (`SET`, `SPOOL`, `PROMPT`, `EXIT`, `@`) để `split_oracle_script` và `sqlplus` đều chạy được.

## Tiêu chí nghiệm thu
<!-- Fixture TINY = `tiny_parquet` của tests/datagen/conftest.py (300 customers, 5000 txns + typology, 6 tháng từ 2026-01-01, seed 42).
Test có nhãn [oracle] dùng @pytest.mark.oracle và tự skip khi Oracle không chạy; AC6, AC9 còn skip (kèm thông điệp trỏ tới
dba/scripts/sys/010_grant_tuning_views.sql) khi `has_cursor_stats_access` trả False. Các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given file `dba/RUNBOOK.md` của repo, When đọc các heading cấp 2 (không cần Oracle), Then danh sách heading bằng đúng 8 chuỗi theo thứ tự `1. Environment and limits`, `2. Backup and restore`, `3. Reading AWR, ASH and Statspack`, `4. Reading DBMS_XPLAN output`, `5. Materialized view refresh`, `6. Partition maintenance`, `7. Tuning walkthrough`, `Script index`, và mỗi mục 1–7 có ít nhất 1 đoạn văn khác rỗng.
- AC2: Given `dba/RUNBOOK.md`, When tìm từ khoá theo từng mục (không phân biệt hoa thường), Then mục 1 chứa `gvenzl/oracle-free`, `NOARCHIVELOG` và `control_management_pack_access`; mục 2 chứa `RMAN`, `expdp`, `impdp` và câu khẳng định image slim không có binary `rman` (chứa cả `rman` và `not available`); mục 3 chứa `AWR`, `ASH`, `Statspack`, `spcreate.sql` và `Diagnostics Pack`; mục 4 chứa `DISPLAY_CURSOR`, `ALLSTATS LAST`, `GATHER_PLAN_STATISTICS`, `E-Rows`, `A-Rows`, `Buffers`, `Pstart`; mục 5 chứa `MATERIALIZED VIEW LOG`, `INCLUDING NEW VALUES`, `DBMS_MVIEW.EXPLAIN_MVIEW`, `REFRESH COMPLETE` và `acct_edge_daily`; mục 6 chứa `UPDATE GLOBAL INDEXES`, `p_before_2000` và `ORA-14758`.
- AC3: Given `dba/RUNBOOK.md` và cây thư mục repo, When trích mọi đường dẫn file bắt đầu bằng `dba/scripts/`, `results/phase2/` hoặc `sql/oracle/` trong runbook, Then mọi đường dẫn đó tồn tại trên đĩa; ngược lại mọi file dưới `dba/scripts/` xuất hiện đúng 1 dòng trong bảng `Script index` với `Status` = `verified` nếu nằm trong `owner/`, `manual` nếu nằm trong `sys/`, `reference` nếu nằm trong `reference/` (không file nào nằm ngoài 3 thư mục con này); cả 2 file `*.rman` có Status `reference`; và 14 file tối thiểu liệt kê ở mục "Bố cục thư mục" đều có mặt.
- AC4: Given mọi file `*.sql` dưới `dba/scripts/` (không cần Oracle), When tách bằng `split_oracle_script`, Then mỗi file tách không lỗi và ra ≥ 1 statement, không dòng nào (bỏ comment `--`) bắt đầu bằng `SET `, `SPOOL`, `PROMPT`, `EXIT` hoặc `@`; và mỗi file `dba/scripts/sys/<tên>.sql` có file `results/phase2/runbook/<tên>.txt` tương ứng với kích thước > 0 byte.
- AC5: Given `load_settings` với `data.start_date=2026-01-01`, `thresholds.large_cash_vnd=400000000`, When gọi `tuning_steps(settings)` (không cần DB), Then trả đúng 2 step tên `before`, `after` theo thứ tự; SQL `before` chứa `TRUNC(txn_ts) BETWEEN DATE '2026-03-01' AND DATE '2026-03-30'`; SQL `after` chứa `txn_ts >= TIMESTAMP '2026-03-01 00:00:00' AND txn_ts < TIMESTAMP '2026-03-31 00:00:00'` và không chứa `TRUNC(`; cả hai chứa `HAVING SUM(amount_vnd) >= 400000000` và không chứa `/*+`; `before.change == ""`, `after.change` khác rỗng; với `AML__THRESHOLDS__LARGE_CASH_VND=300000000` và `AML__DATA__START_DATE=2026-02-01` thì cả hai SQL chứa `>= 300000000` và cửa sổ đổi thành `2026-04-01` … `2026-04-30` / `< TIMESTAMP '2026-05-01 00:00:00'`.
- AC6: [oracle] Given fixture TINY vừa nạp bằng `load_parquet` và `has_cursor_stats_access(db)` là True, When gọi `run_tuning(db, settings, runs=3)`, Then trả 2 `TuningResult` (`before`, `after`); plan `before` chứa `PARTITION RANGE ALL`; plan `after` chứa `PARTITION RANGE SINGLE` và không chứa `PARTITION RANGE ALL`; cả hai plan chứa các cột `A-Rows` và `Buffers` (bằng chứng lấy từ cursor thật, không phải `EXPLAIN PLAN`); `before.plan_hash_value != after.plan_hash_value`; `after.buffer_gets < before.buffer_gets`; mỗi `elapsed_ms` có đúng 3 phần tử đều > 0; `before.rows == after.rows >= 1` và hai tập kết quả (sắp theo `from_account_id`) bằng nhau.
- AC7: Given DuckDB (`duck`), When gọi `run_tuning(duck, settings)`, Then raise `NotImplementedError` với thông điệp chứa "Oracle only"; và Given `DB_BACKEND=duckdb` (hoặc Oracle down và fallback sang DuckDB), When chạy `aml tune-demo --out <tmp>/t.txt`, Then exit code 2, stderr chứa "Oracle only" và không tạo file.
- AC8: Given backend Oracle giả lập mà `has_cursor_stats_access` trả False (monkeypatch, không cần Oracle thật), When chạy `aml tune-demo --out <tmp>/t.txt`, Then exit code 1, stderr chứa `dba/scripts/sys/010_grant_tuning_views.sql`, không tạo file và không ghi dòng `audit_log` nào.
- AC9: [oracle] Given fixture TINY đã nạp, `DB_BACKEND=oracle` và có quyền V$, When chạy `aml tune-demo --out <tmp>/t.txt --runs 3`, Then exit 0; file có dòng đầu dạng `# aml tune-demo` kèm các dòng `transactions_rows: 5100`, `runs: 3`, `oracle_version: <banner>`; có đúng 2 khối `== before ==` và `== after ==`, mỗi khối gồm SQL, đúng 1 dòng `plan_hash_value: <int>`, `buffer_gets: <int>`, `elapsed_ms: <3 số>`, `elapsed_ms_median: <số>`, `rows: <int>` và output `DISPLAY_CURSOR`; dòng cuối dạng `summary: buffer_gets <b> -> <a>, elapsed_ms_median <x> -> <y>`; và `audit_log` có đúng 1 dòng mới `module='dba'`, `entity_type='query'`, `entity_id='outflow_30d'`, `decision='TUNING_CAPTURED'` với `details.path` = đường dẫn file, `details.before.plan_hash_value` và `details.after.plan_hash_value` trùng số trong file.
- AC10: Given file bằng chứng đã commit `results/phase2/tune_demo.txt` và `dba/RUNBOOK.md` (không cần Oracle), When so mục `7. Tuning walkthrough` với file, Then mục 7 chứa lệnh `uv run aml tune-demo`, đường dẫn `results/phase2/tune_demo.txt`, cả hai giá trị `plan_hash_value`, cả hai giá trị `buffer_gets` và cả hai giá trị `elapsed_ms_median` đúng như trong file (so khớp chuỗi số), cùng giá trị `transactions_rows` của lần chạy đó; file có `plan_hash_value` của `before` khác `after`.

## Ngoài phạm vi
- Chạy RMAN thật, bật `ARCHIVELOG`, cấu hình FRA, đổi sang image `gvenzl/oracle-free:23` (full) hay sửa `docker-compose.yml`; test restore/point-in-time recovery thật. Script RMAN chỉ ở mức `reference`.
- Cài Statspack (`spcreate.sql`) hay tạo AWR report (`awrrpt.sql`) trong container; chỉ ghi cách làm và script `reference`.
- Tạo MV log, đổi `acct_edge_daily` sang `REFRESH FAST`, hay lập lịch `DBMS_SCHEDULER` — chỉ ghi chú + script `reference`; MV vẫn `REFRESH COMPLETE ON DEMAND` như 2a.
- Thủ tục purge/archive partition theo retention và thực thi `DROP PARTITION` (2c) — 2d chỉ ghi chú cú pháp và lý do `UPDATE GLOBAL INDEXES`.
- Roles `app`/`analyst`/`readonly_graph_sync`/`auditor`, masking view, unified auditing (2b). 2d chỉ cấp 4 view `V_$` cho `aml_owner`.
- Tuning hơn một query; thay đổi index/schema/stats trong demo; SQL Plan Baseline, SQL Profile, SQL Tuning Advisor, hint ép plan.
- Test assert "after nhanh hơn before" theo thời gian (nhiễu trên TINY) — test chỉ assert `buffer_gets` giảm và timing được ghi; mức cải thiện thời gian do file bằng chứng của profile `small` chứng minh.
- `tune-demo`/`DISPLAY_CURSOR` trên DuckDB; thêm target `tune-demo` vào `Makefile`/`tasks.ps1` (gọi thẳng `uv run aml tune-demo`).
- Đưa `ORACLE_SYS_PASSWORD` vào `SECRET_ENV_MAP` hay cho code Python kết nối bằng SYS.

## Giả định
- Các số đo ở mục "Hiện trạng môi trường" đúng với image đã pin trong `docker-compose.yml`; nếu digest image đổi thì phải đo lại bằng `dba/scripts/sys/environment_facts.sql` và cập nhật runbook.
- Người làm có quyền `docker compose exec` vào container Oracle để chạy script `sys/` bằng `sqlplus / as sysdba` (xác thực OS, không cần mật khẩu SYS trong code); script `sys/` tự `ALTER SESSION SET CONTAINER = FREEPDB1`.
- Tên schema owner trong `010_grant_tuning_views.sql` viết cứng là `aml_owner` (mặc định của `ORACLE_APP_USER`); ai đổi user thì sửa script.
- Sau khi cấp `V_$SQL`, `V_$SQL_PLAN`, `V_$SQL_PLAN_STATISTICS_ALL`, `V_$SESSION`, `aml_owner` gọi được `DBMS_XPLAN.DISPLAY_CURSOR(..., 'ALLSTATS LAST')` cho cursor của chính mình; `statistics_level = TYPICAL` nên phải dùng hint `GATHER_PLAN_STATISTICS`.
- Oracle 23ai không prune partition khi partition key bị bọc `TRUNC()` (đã kiểm bằng `EXPLAIN PLAN` trên TINY ngày 2026-10-10); `TRUNC(txn_ts) BETWEEN d1 AND d2` tương đương `txn_ts >= d1 AND txn_ts < d2 + 1` vì `txn_ts` là timestamp naive, không null.
- File `results/phase2/tune_demo.txt` được commit là kết quả chạy thật trên profile `small` (300000 giao dịch) sau `aml data` + `aml load --backend oracle`; test [oracle] ghi đè dữ liệu bằng TINY nên phải nạp lại `small` trước khi sinh file commit.
- Thời gian đo là wall-clock phía client (gồm round-trip mạng tới container), buffer cache đã ấm nhờ lần warm-up; con số chỉ có ý nghĩa so sánh tương đối trên cùng máy.
- 2d không thêm key mới vào `config.yaml`: ngưỡng lấy từ `thresholds.large_cash_vnd`, cửa sổ suy ra từ `data.start_date`; `runs` là tham số CLI.
- Audit: `TUNING_CAPTURED` chỉ ghi khi file bằng chứng được viết thành công; `reason` là câu mô tả đọc được (thay đổi gì, buffer gets và median ms trước → sau).

## Câu hỏi mở
- [x] Q1. Tuning query nào và bằng thay đổi gì? — đề xuất mặc định: aggregate tiền ra 30 ngày theo tài khoản trên `transactions`, "before" dùng `TRUNC(txn_ts) BETWEEN ...` (mất pruning: `PARTITION RANGE ALL`), "after" viết lại predicate khoảng nửa mở (`PARTITION RANGE SINGLE`). Lý do: anti-pattern có thật, plan hash đổi chắc chắn, không sửa schema nên lặp lại được và không cần hoàn tác. Phương án khác: fund-flow 2 hop trên `acct_edge_daily` với `IX_AED_SRC_DAY` đặt `INVISIBLE`/`VISIBLE` (trực quan về index nhưng phải đổi rồi khôi phục trạng thái index, rủi ro để lại index ẩn khi lỗi giữa chừng). — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q2. `aml_owner` chưa đọc được `V$` (ORA-00942) — cấp quyền cho `DISPLAY_CURSOR` thế nào? — đề xuất mặc định: script `dba/scripts/sys/010_grant_tuning_views.sql` cấp trực tiếp 4 view cho `aml_owner`, chạy tay một lần qua `docker compose exec ... sqlplus / as sysdba`; `aml tune-demo` kiểm quyền trước, thiếu thì exit 1 và in đường dẫn script; test [oracle] liên quan skip kèm thông điệp. Lý do: không đưa mật khẩu SYS vào code; 2b sau này có thể chuyển grant sang role riêng. Phương án khác: cấp `SELECT_CATALOG_ROLE` (rộng hơn least privilege) hoặc fallback sang `EXPLAIN PLAN` (mất `A-Rows`/`Buffers`). — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q3. Runbook nói gì về license AWR/ASH trên bản Free? — đề xuất mặc định: ghi đúng điều đo được (tham số pack = `DIAGNOSTIC+TUNING`, có snapshot, ASH có dữ liệu), nói rõ ở Enterprise Edition AWR/ASH thuộc Diagnostics Pack tính phí riêng, và **không khẳng định** quyền dùng trên Free mà dẫn người đọc tới "Database Licensing Information User Manual" của đúng phiên bản; kèm Statspack (`spcreate.sql`, có sẵn trong image) làm phương án không cần pack. Lý do: tôi không xác minh được điều khoản license từ bên trong repo; cần người dùng xác nhận câu chữ nếu muốn khẳng định mạnh hơn. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q4. RMAN không có trong image slim — xử lý phần backup thế nào? — đề xuất mặc định: runbook giải thích khái niệm (ARCHIVELOG, backup set level 0/1, FRA, restore/recover PITR, backup PDB `FREEPDB1`, lưu ý partition + MV dựng lại bằng refresh) với script `.rman` trạng thái `reference`, và nêu phương án chạy được ở đây: `expdp schemas=aml_owner` + backup volume `oradata` khi container dừng. Không đổi image. Lý do: image đã pin, đổi sang bản full tăng dung lượng và ngoài phạm vi demo. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q5. Có chạy thật `expdp` để chuyển `expdp_schema.par` từ `reference` sang `manual` (kèm output trong `results/phase2/runbook/`)? — đề xuất mặc định: không, giữ `reference`. Lý do: cần cấp quyền trên `DATA_PUMP_DIR` và sinh file dump trong volume; giá trị trình bày thấp so với công. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q6. Ghi chú MV fast refresh: chỉ viết hay chứng minh bằng chạy thật? — đề xuất mặc định: chỉ ghi chú + `mv_log_fast_refresh.sql` trạng thái `reference`, nêu điều kiện (MV log `WITH ROWID, SEQUENCE, INCLUDING NEW VALUES`, MV phải có `COUNT(*)` và `COUNT(amount_vnd)`, kiểm bằng `DBMS_MVIEW.EXPLAIN_MVIEW`) và lý do 2a chọn `COMPLETE` (nạp kiểu bulk replace, MV log làm chậm DML). Lý do: tạo MV log trên `transactions` làm chậm `aml load` và nếu script lỗi giữa chừng sẽ để lại trạng thái. Phương án khác: script tự tạo rồi tự dọn một MV demo riêng, chuyển sang `verified`. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q7. Timing đo thế nào và test assert gì? — đề xuất mặc định: 1 warm-up + `runs` lần (mặc định 5), ghi từng lần và median (ms, 3 chữ số thập phân), kèm `buffer_gets` từ `ALLSTATS LAST`; test chỉ assert `buffer_gets` giảm, plan hash khác và timing > 0, **không** assert after nhanh hơn. Lý do: logical read gần như tất định, wall-clock trên 5100 dòng là nhiễu; mức tăng tốc lấy từ lần chạy `small` đã commit. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q8. Ngôn ngữ của `dba/RUNBOOK.md`? — đề xuất mặc định: tiếng Anh (giống README, CLAUDE.md, comment code; người phỏng vấn đọc trực tiếp), spec vẫn tiếng Việt. AC1/AC2 dùng heading và từ khoá tiếng Anh. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q9. File bằng chứng commit sinh từ profile nào? — đề xuất mặc định: `small` (300000 giao dịch), commit `results/phase2/tune_demo.txt`; README/runbook chỉ trích số từ file này kèm lệnh tái tạo. Lý do: TINY quá nhỏ để thấy chênh lệch thời gian, `large` (5 triệu dòng) nạp lâu trên máy demo. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q10. Phân loại trạng thái script theo thư mục (`owner`=verified, `sys`=manual có output lưu lại, `reference`=không chạy) có chấp nhận không? — đề xuất mặc định: có. Lý do: biến quy tắc "không bịa" thành thứ test kiểm được (AC3, AC4) và người đọc runbook biết ngay script nào đã chạy thật. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q11. Script `owner/` có cần một AC [oracle] chạy thật từng file không? — đề xuất mặc định: chưa (đã đủ 10 AC); `verified` được bảo chứng gián tiếp vì `run_tuning` dùng cùng câu lệnh `DISPLAY_CURSOR`. Nếu muốn chặt hơn, gộp vào AC6 một bước `db.run_script` cho mọi file `dba/scripts/owner/*.sql`. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
