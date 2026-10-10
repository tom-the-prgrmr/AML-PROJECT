---
id: oracle-retention
status: approved
approved_by: pthieu
---

# Phase 2c-i — Retention: archive + drop partition `transactions`, partition hoá `audit_log`

## Bối cảnh
Spec 2c (`oracle-retention-dq` theo kế hoạch ở 2a) cần hơn 10 AC nên được tách đôi: **2c-i (spec này)** retention và
**2c-ii `dq-framework`** (DQ rules/runner/results/trend). 2c-i hiện thực gạch đầu dòng "Retention" của
PROJECT_BRIEF.md mục 3: thủ tục purge/archive drop các partition tháng của `transactions` cũ hơn một thời hạn lưu
trữ cấu hình được, có dry-run, có sàn pháp lý, ghi audit từng lần drop; đồng thời làm phần hoãn từ 2a Q14:
partition hoá `audit_log` theo tháng và **loại `audit_log` khỏi purge tự động**.

**Ghi chú pháp lý (đưa nguyên văn vào docstring module và `dba/RUNBOOK.md` ở 2d):** Luật Phòng, chống rửa tiền
2022 (số 14/2022/QH15), quy định về lưu giữ hồ sơ, yêu cầu đối tượng báo cáo lưu hồ sơ giao dịch **ít nhất 5 năm**
kể từ ngày phát sinh giao dịch (hồ sơ nhận biết khách hàng: 5 năm kể từ ngày kết thúc giao dịch/đóng tài khoản).
Vì vậy sàn cứng là **60 tháng**; cấu hình thấp hơn bị từ chối. Đây là demo dữ liệu tổng hợp, không phải tư vấn
pháp lý; số điều khoản cụ thể cần người dùng xác nhận (Q2).

### Hiện trạng đã kiểm trên Oracle đang chạy (localhost:1521/FREEPDB1, chỉ đọc)
- `TRANSACTIONS`: RANGE + `INTERVAL NUMTOYMINTERVAL(1,'MONTH')`, 7 partition (`P_BEFORE_2000` rỗng + 2026-01..06).
- PK `transactions` là index global không partition; `IX_TXN_FROM_TS`, `IX_TXN_TO_TS` là LOCAL.
- `AUDIT_LOG` chưa partition (heap, PK identity, cột `details` kiểu JSON); chưa có procedure/trigger nào.
- `user_tab_partitions.high_value_json` có sẵn (vd `{"high_value": "2026-02-01T00:00:00"}`) — dùng cột này,
  không parse cột `HIGH_VALUE` kiểu LONG.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class RetentionConfig(BaseModel):
    transactions_months: int  # số tháng giữ lại trong bảng nóng; phải >= LEGAL_MIN_MONTHS
    archive_dir: str  # thư mục gốc của file Parquet lưu trữ


# src/aml/dba/retention.py
LEGAL_MIN_MONTHS = 60  # Luật Phòng, chống rửa tiền 14/2022/QH15: lưu hồ sơ giao dịch >= 5 năm
ANCHOR_PARTITION = "P_BEFORE_2000"  # partition range neo của interval table, không bao giờ drop
PURGEABLE_TABLES = ("transactions",)  # audit_log cố ý không có mặt


class RetentionError(ValueError): ...


@dataclass(frozen=True)
class PartitionAction:
    partition: str  # tên partition Oracle, vd "SYS_P801"
    month: str  # "YYYY-MM" = tháng dữ liệu của partition (high_value trừ 1 tháng)
    rows: int  # COUNT(*) thực tế của partition tại thời điểm lập kế hoạch
    archive_path: Path  # <archive_dir>/transactions/transactions_<month>.parquet


@dataclass(frozen=True)
class PurgePlan:
    table: str
    as_of: date
    retention_months: int
    cutoff: datetime  # 00:00 ngày đầu tháng của as_of, lùi retention_months tháng
    drop: tuple[PartitionAction, ...]  # sắp theo month tăng dần
    executed: bool  # False = dry-run


def retention_cutoff(as_of: date, retention_months: int) -> datetime: ...
def purge_transactions(
    db: Database,
    settings: Settings,
    *,
    as_of: date | None = None,  # mặc định settings.data.reference_date
    dry_run: bool = True,
    table: str = "transactions",
) -> PurgePlan: ...
```
- `config.yaml` thêm:
  ```yaml
  retention:
    transactions_months: 60      # >= 60 (sàn pháp lý 5 năm, Luật PCRT 2022)
    archive_dir: data/archive    # git-ignored (nằm trong data/)
  ```
- CLI mới `aml retention [--as-of YYYY-MM-DD] [--execute]`; không có `--execute` thì là dry-run.
- `SCHEMA_SCRIPTS["oracle"]` thêm `ddl/070_audit_log_partitioning.sql` (sau `040`; số `050` đã được bản nháp 2b dùng, `060` là DQ của 2c-ii); DuckDB không có script tương ứng.

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Điều kiện drop**: partition bị drop khi và chỉ khi `high_value <= cutoff` (mọi dòng của nó cũ hơn cutoff) và
  tên khác `P_BEFORE_2000`. Ví dụ `as_of=2026-06-30`, 60 tháng: cutoff = `2021-06-01 00:00:00`; partition tháng
  2021-05 (high_value `2021-06-01`) bị drop, partition tháng 2021-06 được giữ.
- **Thứ tự cho từng partition** (dừng ngay ở lỗi đầu tiên, các partition đã xử lý xong giữ nguyên kết quả):
  1. `SELECT * FROM transactions PARTITION (<tên>)` ghi ra Parquet (ghi file tạm rồi rename);
  2. đọc lại file, so số dòng với `COUNT(*)` của partition — lệch thì raise, **không drop**;
  3. `ALTER TABLE transactions DROP PARTITION <tên> UPDATE GLOBAL INDEXES`;
  4. ghi 1 dòng `audit_log` `decision='PARTITION_DROPPED'`.
  Partition rỗng: bỏ bước 1–2 (không tạo file), vẫn drop và audit với `details.rows = 0`, `archive_path = null`.
- Sau khi drop ít nhất 1 partition: gọi `refresh_acct_edge_daily(db)` một lần (MV đã stale).
- Kiểm sàn pháp lý (`transactions_months < 60`) và kiểm `table` thuộc `PURGEABLE_TABLES` chạy **trước** mọi truy
  vấn DB, kể cả ở dry-run.
- `070_audit_log_partitioning.sql`: nếu `AUDIT_LOG` chưa có trong `user_part_tables` thì
  `ALTER TABLE audit_log MODIFY PARTITION BY RANGE (event_ts) INTERVAL (NUMTOYMINTERVAL(1,'MONTH'))
  (PARTITION p_before_2000 VALUES LESS THAN (TIMESTAMP '2000-01-01 00:00:00')) ONLINE UPDATE INDEXES`; PK identity
  giữ global. Cùng quy ước PL/SQL `EXECUTE IMMEDIATE` + dòng `/` như 2a; `apply_schema` ghi audit `PARTITIONED`
  (`entity_id='audit_log'`) chỉ khi thực sự chuyển đổi.

## Tiêu chí nghiệm thu
<!-- Test [oracle] dùng @pytest.mark.oracle, tự skip khi Oracle không chạy. Dữ liệu test retention: 3 giao dịch
RT1 (2019-03-15 10:00:00), RT2 (2019-04-15 10:00:00), RT3 (2026-02-15 10:00:00), mỗi dòng from_account_id='A1',
to_account_id='A2', amount_vnd=100000, channel='INTERNAL_TRANSFER'; as_of=2026-06-30, transactions_months=60
=> cutoff 2021-06-01. archive_dir = tmp_path. Test tự dọn RT* và các partition 2019 khi kết thúc để không ảnh hưởng
AC7 của 2a (đúng 6 partition có dữ liệu). -->
- AC1: Given không cần DB, When gọi `retention_cutoff`, Then `(2026-06-30, 60)` trả `datetime(2021, 6, 1, 0, 0)`, `(2026-01-01, 60)` trả `datetime(2021, 1, 1, 0, 0)`, `(2026-03-31, 61)` trả `datetime(2021, 2, 1, 0, 0)`, và `(2026-06-30, 59)` raise `RetentionError` với thông điệp chứa `legal minimum of 60 months`.
- AC2: Given `config.yaml` của repo, When `load_settings(environ={})`, Then `settings.retention.transactions_months == 60` và `settings.retention.archive_dir == "data/archive"`; và Given `environ={"AML__RETENTION__TRANSACTIONS_MONTHS": "59"}` cùng DuckDB rỗng (`duck`) sau `apply_schema`, When gọi `purge_transactions(duck, settings, dry_run=True)`, Then raise `RetentionError` chứa `legal minimum of 60 months` và `audit_log` không có dòng nào `module='dba'` với `decision` bắt đầu bằng `RETENTION` hoặc `PARTITION_DROPPED`.
- AC3: Given thư mục `sql/` của repo (không cần Oracle), When đọc `SCHEMA_SCRIPTS`, Then `SCHEMA_SCRIPTS["oracle"]` chứa `ddl/070_audit_log_partitioning.sql` ở vị trí sau `ddl/040_acct_edge_daily.sql`, file đó resolve qua `sql_file` về `sql/oracle/`, `split_oracle_script` tách ra >= 1 statement và không statement nào (bỏ dòng comment) bắt đầu bằng `CREATE`/`ALTER`/`DROP`; `SCHEMA_SCRIPTS["duckdb"]` không chứa script nào có tên chứa `audit_log_partitioning` và `apply_schema(duck)` hai lần không raise.
- AC4: [oracle] Given `audit_log` bị drop rồi tạo lại bằng `ddl/000_audit_log.sql` (heap như Phase 0) và có 3 sự kiện audit `module='test'` với `event_ts` 2026-01-15, 2026-02-15, 2026-03-15 (UTC), When gọi `apply_schema` hai lần, Then `user_part_tables` cho `AUDIT_LOG` có `partitioning_type='RANGE'`, `interval` (bỏ khoảng trắng) = `NUMTOYMINTERVAL(1,'MONTH')`, `user_part_key_columns` = [`EVENT_TS`], tồn tại partition `P_BEFORE_2000`, index của PK `audit_log` có `user_indexes.partitioned='NO'` và `status='VALID'`, `COUNT(*)` các dòng `module='test'` vẫn = 3, lần 2 không raise, và `audit_log` có đúng 1 dòng `module='dba'`, `entity_type='table'`, `entity_id='audit_log'`, `decision='PARTITIONED'`.
- AC5: [oracle] Given schema sau `apply_schema` và 3 giao dịch RT1, RT2, RT3, When gọi `purge_transactions(db, settings, as_of=date(2026, 6, 30), dry_run=True)`, Then `plan.executed is False`, `plan.cutoff == datetime(2021, 6, 1)`, `[a.month for a in plan.drop] == ["2019-03", "2019-04"]`, `[a.rows for a in plan.drop] == [1, 1]`, không phần tử nào có `partition == "P_BEFORE_2000"`, số dòng `user_tab_partitions` của `TRANSACTIONS` không đổi, RT1 và RT2 vẫn truy vấn được, thư mục `archive_dir` không có file `.parquet` nào, và `audit_log` có đúng 1 dòng mới `module='dba'`, `entity_type='table'`, `entity_id='transactions'`, `decision='RETENTION_DRY_RUN'` với `details.months = ["2019-03", "2019-04"]`, `details.cutoff = "2021-06-01"`, `details.retention_months = 60`.
- AC6: [oracle] Given cùng trạng thái AC5, When gọi `purge_transactions(db, settings, as_of=date(2026, 6, 30), dry_run=False)`, Then `plan.executed is True`; file `<archive_dir>/transactions/transactions_2019-03.parquet` có đúng 1 dòng `txn_id='RT1'` và `transactions_2019-04.parquet` có đúng 1 dòng `txn_id='RT2'`, cả hai có đủ 12 cột của `transactions` đúng thứ tự `TRANSACTION_COLUMNS` (tên cột chữ thường); `SELECT COUNT(*) FROM transactions WHERE txn_id IN ('RT1','RT2')` = 0; không còn partition nào có `high_value_json.high_value` thuộc {`2019-04-01T00:00:00`, `2019-05-01T00:00:00`}; partition `P_BEFORE_2000` vẫn tồn tại; `SELECT COUNT(*) FROM transactions WHERE txn_id = 'RT3'` = 1; index của PK `transactions` có `status='VALID'`.
- AC7: [oracle] Given cùng lần chạy thật ở AC6, When đọc `audit_log`, Then có đúng 2 dòng mới `module='dba'`, `entity_type='partition'`, `decision='PARTITION_DROPPED'` với `entity_id` lần lượt `transactions:2019-03`, `transactions:2019-04`, mỗi dòng `details.rows = 1`, `details.archive_path` = đường dẫn file tương ứng, `details.cutoff = "2021-06-01"`, `details.retention_months = 60`, `reason` chứa `UPDATE GLOBAL INDEXES`; có đúng 1 dòng mới `entity_id='acct_edge_daily'`, `decision='REFRESHED'`; và gọi lại `purge_transactions(db, settings, as_of=date(2026, 6, 30), dry_run=False)` lần hai trả `plan.drop == ()` và không thêm dòng `PARTITION_DROPPED` hay `REFRESHED` nào.
- AC8: [oracle] Given RT1, RT2, RT3 như AC5 và bước ghi Parquet bị monkeypatch để raise `OSError("disk full")` khi ghi file của tháng `2019-04`, When gọi `purge_transactions(db, settings, as_of=date(2026, 6, 30), dry_run=False)`, Then `OSError` lan ra ngoài; partition tháng 2019-03 đã bị drop và có 1 dòng `PARTITION_DROPPED` cho `transactions:2019-03`; RT2 vẫn còn trong `transactions` (`COUNT(*)` theo `txn_id='RT2'` = 1), không có dòng `PARTITION_DROPPED` cho `transactions:2019-04` và không có file `transactions_2019-04.parquet`.
- AC9: [oracle] Given `audit_log` đã partition (AC4) và 1 sự kiện audit ghi bằng `audit_many` với `event_ts = 2019-03-10 08:00:00 UTC`, `module='test'`, `entity_id='RETENTION-AUDIT'`, cùng RT1 trong `transactions`, When gọi `purge_transactions(db, settings, as_of=date(2026, 6, 30), dry_run=False)` rồi gọi `purge_transactions(db, settings, table="audit_log")`, Then lần gọi đầu drop partition 2019-03 của `transactions` nhưng dòng `entity_id='RETENTION-AUDIT'` vẫn còn (`COUNT(*)` = 1) và partition của `AUDIT_LOG` có `high_value` `2019-04-01T00:00:00` vẫn tồn tại; lần gọi thứ hai raise `RetentionError` với thông điệp chứa `audit_log is excluded from purge` và không drop gì.
- AC10: Given `DB_BACKEND=duckdb` (hoặc Oracle down và fallback sang DuckDB), When chạy `aml retention --execute`, Then exit code 2, stderr chứa `Oracle only`, không tạo file nào trong `archive_dir`; Given `AML__RETENTION__TRANSACTIONS_MONTHS=59`, When chạy `aml retention`, Then exit code 2 và stderr chứa `legal minimum of 60 months`; Given `--as-of 2026-13-01`, Then exit code 2; [oracle] Given `DB_BACKEND=oracle` và RT1, RT2, RT3, When chạy `aml retention --as-of 2026-06-30` (không `--execute`), Then exit 0, stdout chứa `DRY RUN`, `cutoff=2021-06-01`, `2019-03`, `2019-04` và RT1 vẫn còn trong `transactions`.

## Ngoài phạm vi
- DQ framework (`dq_rules`, runner, `dq_results`, trend view, `aml dq run`) — spec 2c-ii `dq-framework`.
- Purge/archive cho mọi bảng khác `transactions` (`audit_log`, `customers`, `accounts`, `dq_results`, watchlist...); xoá hồ sơ KYC sau khi đóng tài khoản.
- Retention trên DuckDB (không có partition): CLI thoát mã 2, không có đường `DELETE` thay thế.
- Khôi phục từ file archive về bảng (`restore`), nén/mã hoá/checksum file archive, đẩy archive lên object storage, `EXCHANGE PARTITION` sang bảng archive, tablespace riêng / ILM / ADO.
- Legal hold: giữ lại partition có giao dịch đang bị cảnh báo/thuộc case điều tra (alert/case chỉ có từ Phase 5–7).
- Lịch chạy tự động (`DBMS_SCHEDULER`), thủ tục PL/SQL lưu trong DB, roles/grants và trigger append-only cho `audit_log` (2b), nội dung `dba/RUNBOOK.md` (2d).
- Xử lý dữ liệu nằm trong `P_BEFORE_2000` (giả định luôn rỗng), `gather_stats` sau purge.

## Giả định
- Oracle 23ai Free hỗ trợ `ALTER TABLE audit_log MODIFY PARTITION BY ... ONLINE` cho bảng có cột identity và cột JSON; nếu `ONLINE` không được phép với cột JSON thì script dùng chuyển đổi offline (bỏ `ONLINE`), kết quả AC4 không đổi.
- `DROP PARTITION ... UPDATE GLOBAL INDEXES` giữ index PK `VALID` (bảo trì index global bất đồng bộ từ 12c: có thể còn `orphaned_entries='YES'`, được dọn bởi job hệ thống — ghi chú trong RUNBOOK 2d, không kiểm trong test).
- `audit_log` hiện chưa có trigger append-only; bản nháp 2b (`oracle-security`) thêm trigger chặn UPDATE/DELETE/TRUNCATE trên `audit_log`. Purge chỉ INSERT vào `audit_log` và chỉ DDL trên `transactions` nên không xung đột; hệ quả: sau khi 2b được hiện thực, test không xoá được dòng audit mình tạo (dòng `RETENTION-AUDIT` năm 2019 của AC9 ở lại vĩnh viễn — vô hại), và chuyển đổi partition của `audit_log` phải chạy được khi bảng đã có trigger.
- Dữ liệu Phase 1 (2026-01..06) không bao giờ đủ tuổi để bị purge với `as_of = data.reference_date`; hành vi drop chỉ thấy được qua dữ liệu test cài tay (RT1–RT3) hoặc `--as-of` xa trong tương lai.
- Thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có; `event_ts` audit là UTC, `txn_ts` là giờ địa phương naive (quy ước 1b-i) — cutoff so trực tiếp với `txn_ts`/`high_value` naive.
- Test [oracle] ghi/xoá dữ liệu trong schema `aml_owner` (như 2a), tự dọn dữ liệu RT* của mình; test AC4 drop và tạo lại `audit_log` (mất lịch sử audit của schema dev — chấp nhận được vì dữ liệu tổng hợp, giống cách AC4 của 2a drop `transactions`).

## Câu hỏi mở
- [x] Q1. Tách 2c thành hai spec? — đề xuất mặc định: có, 2c-i `oracle-retention` (file này, 10 AC) và 2c-ii `dq-framework` (10 AC); không tạo file `oracle-retention-dq.md`. Lý do: gộp lại là 20 AC, vượt giới hạn ~10 AC/spec. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q2. Sàn pháp lý là bao nhiêu và trích dẫn thế nào? — đề xuất mặc định: 60 tháng, trích "Luật Phòng, chống rửa tiền 2022 (14/2022/QH15) — lưu giữ hồ sơ giao dịch ít nhất 5 năm kể từ ngày phát sinh giao dịch", không ghi số điều cho tới khi người dùng xác nhận. Lý do: tránh trích sai điều khoản trong tài liệu phỏng vấn. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q3. Sàn 60 tháng đặt ở đâu? — đề xuất mặc định: hằng số code `LEGAL_MIN_MONTHS = 60` (không nằm trong `config.yaml`), chỉ `retention.transactions_months` là cấu hình được. Lý do: sàn luật không phải ngưỡng nghiệp vụ tinh chỉnh được; để trong config thì một biến môi trường là vô hiệu hoá được. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q4. Giá trị mặc định của `retention.transactions_months`? — đề xuất mặc định: 60 (đúng bằng sàn). Lý do: đơn giản, dễ giải thích; ngân hàng thật thường giữ dài hơn (vd 84–120 tháng) vì thời hạn tính từ lúc đóng tài khoản — ghi chú trong RUNBOOK. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q5. "Cũ hơn retention" tính từ mốc nào? — đề xuất mặc định: `as_of` = `settings.data.reference_date` (ghi đè bằng `--as-of`), cutoff = đầu tháng của `as_of` lùi `transactions_months` tháng; drop khi `high_value <= cutoff`. Lý do: tái lập được như mọi phần khác của demo (không phụ thuộc đồng hồ máy), và bảo đảm mọi dòng bị drop đều cũ hơn đủ số tháng. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q6. Archive đi đâu trước khi drop? — đề xuất mặc định: Parquet `<archive_dir>/transactions/transactions_<YYYY-MM>.parquet`, kiểm số dòng đọc lại rồi mới drop. Lý do: cùng định dạng với Phase 1 (`data/parquet`), đọc được bằng DuckDB, không cần tablespace/bảng archive; phương án thay thế là `EXCHANGE PARTITION` sang bảng `transactions_archive` (để RUNBOOK 2d bàn). — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q7. File archive của tháng đó đã tồn tại thì sao (chạy lại sau sự cố, hoặc dữ liệu cũ nạp muộn)? — đề xuất mặc định: raise `RetentionError` chứa `archive already exists`, không ghi đè, không drop partition đó. Lý do: không bao giờ làm mất bản archive trước; người vận hành tự xử lý file. (Chưa có AC riêng — nếu đồng ý sẽ gộp vào AC8.) — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q8. Mặc định là dry-run hay chạy thật? — đề xuất mặc định: dry-run là mặc định ở cả hàm (`dry_run=True`) và CLI; phải có `--execute` mới drop. Lý do: thao tác phá huỷ không hoàn tác được nên phải chủ động yêu cầu. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q9. Dry-run có ghi `audit_log` không? — đề xuất mặc định: có, đúng 1 dòng `RETENTION_DRY_RUN` liệt kê các tháng sẽ drop (kể cả khi danh sách rỗng); không ghi file, không DDL. Lý do: để lại dấu vết ai đã xem kế hoạch purge; phương án thay thế là dry-run hoàn toàn không ghi gì. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q10. Retention có chạy trên DuckDB không? — đề xuất mặc định: không, `aml retention` thoát mã 2 với "Oracle only" (giống `aml explain-pruning`); riêng kiểm sàn pháp lý và `retention_cutoff` chạy được không cần Oracle. Lý do: drop partition là tính năng riêng của Oracle; `DELETE` theo tháng trên DuckDB là một đường code khác, không chứng minh được gì về partition. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q11. Thủ tục là PL/SQL lưu trong DB hay Python điều phối? — đề xuất mặc định: Python (`aml.dba.retention`) điều phối, phát lệnh `ALTER TABLE ... DROP PARTITION ... UPDATE GLOBAL INDEXES`. Lý do: bước archive ra Parquet và ghi `audit_log` qua `aml.common.audit` nằm ngoài DB; brief gọi là "procedure" nhưng không bắt buộc PL/SQL. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q12. Sau khi drop có refresh `acct_edge_daily` và gather stats không? — đề xuất mặc định: refresh `acct_edge_daily` một lần nếu có ít nhất 1 partition bị drop; không gather stats (`INCREMENTAL=TRUE` của 2a tự xử lý ở lần `aml load` kế tiếp). Lý do: MV phải khớp bảng nguồn cho graph trace. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q13. Partition rỗng đủ tuổi (không có dòng nào)? — đề xuất mặc định: vẫn drop và audit với `rows = 0`, không tạo file archive. Lý do: dọn metadata, không có gì để lưu. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q14. `audit_log`: partition thế nào và giữ bao lâu? — đề xuất mặc định: interval theo tháng trên `event_ts`, neo `p_before_2000`, PK identity giữ global; **không bao giờ** bị purge tự động (không nằm trong `PURGEABLE_TABLES`, gọi với `table="audit_log"` thì raise). Lý do: nhật ký kiểm toán là bằng chứng tuân thủ, việc xoá phải là quyết định thủ công có phê duyệt; partition chỉ để truy vấn theo thời gian và sẵn sàng cho archive thủ công về sau. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q15. Giao dịch đang thuộc cảnh báo/case điều tra (legal hold) có được miễn purge không? — đề xuất mặc định: ngoài phạm vi 2c-i (chưa có bảng alert/case), ghi thành hạn chế đã biết trong RUNBOOK và xem lại ở Phase 7. Lý do: hồ sơ đang điều tra thường phải giữ quá 5 năm, nhưng hiện chưa có dữ liệu để kiểm. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
