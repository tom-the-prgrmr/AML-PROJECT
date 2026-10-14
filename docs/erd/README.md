# ERD — AML Investigation Toolkit

Sơ đồ quan hệ thực thể (ERD) của schema trong Oracle 23ai (system of record) và bản DuckDB tương đương.
Nguồn sự thật là DDL trong [sql/oracle/ddl/](../../sql/oracle/ddl/) và [sql/duckdb/ddl/](../../sql/duckdb/ddl/);
tài liệu này được trích từ đó, không thêm bảng nào ngoài DDL.

## Cách đọc

- Mỗi domain một file, theo thứ tự phase. Mỗi file có một `erDiagram` Mermaid (GitHub và VS Code render trực tiếp)
  và một bảng ghi chú ngắn.
- **Nét liền** (`||--o{`) là foreign key thật, khai báo trong `030_constraints_indexes.sql` trên Oracle.
  **Nét đứt** (`||..o{`) là liên kết logic: cùng khóa, join được, nhưng **cố ý không có FK**.
- `PK` / `FK` đánh dấu cột khóa. Với PK ghép, mọi cột thành phần đều mang `PK`.
- Kiểu dữ liệu viết gọn (`varchar`, `bigint`, `timestamp`, `date`, `double`, `json`, `smallint`, `integer`,
  `boolean`). Độ dài xem trong DDL.

## Vì sao hầu hết liên kết là nét đứt

Chỉ có 3 FK thật: `accounts → customers`, `customer_person → customers`, `watchlist_alias → watchlist`.
Phần còn lại của schema theo ba nguyên tắc trong PROJECT_BRIEF:

1. **Append-only, versioned theo `run_id`.** Mọi bảng kết quả (screening, ER, monitoring, cases, scoring, memo)
   không bao giờ UPDATE/DELETE. Mỗi lần chạy thêm dòng với `run_id` mới; view `*_current` đọc run mới nhất.
   FK cứng sẽ cản việc chạy lại và purge partition theo retention.
2. **Tách PII.** Bảng kết quả chỉ lưu `cif`, `account_id`, `entry_id`, không lưu tên, số giấy tờ, số điện thoại.
   DDL ghi rõ "there is no foreign key to customers" (`100_entity_resolution.sql`); kết quả chỉ nối về
   `customers` qua khóa, tách khỏi bảng PII mà analyst chỉ đọc được qua `customers_masked`.
3. **Dữ liệu bẩn có chủ đích.** `transactions` tham chiếu tài khoản ngoài hệ thống (`EXT-*`) và các defect DQ
   được gieo sẵn (`dq_labels`), nên không có FK `transactions → accounts`; DQ framework phát hiện thay vì chặn.

## Tổng quan theo domain

```mermaid
flowchart LR
    subgraph core["01 Core data (Phase 1-2)"]
        customers --> accounts --> transactions
        watchlist --> watchlist_alias
        transactions --> acct_edge_daily
    end
    subgraph scr["02 Screening (Phase 3)"]
        screening_runs --> screening_results
    end
    subgraph er["03 Entity resolution (Phase 4)"]
        er_runs --> er_golden
    end
    subgraph mon["04 Monitoring & network (Phase 5-6)"]
        monitoring_runs --> alerts
        graph_sync_runs --> gds_runs --> gds_account_features
        nx_account_features
    end
    subgraph cases["05 Cases & prioritization (Phase 7)"]
        case_runs --> cases --> case_dispositions
        case_models --> case_scores
        good_guy_list
    end
    subgraph memo["06 Memo (Phase 8d)"]
        memo_runs --> memo_classifications --> case_memo_features
    end
    subgraph gov["07 DQ & audit (Phase 2b-2c)"]
        dq_rules --> dq_results
        audit_log
    end
    customers -.cif.-> screening_results
    watchlist -.entry_id.-> screening_results
    customers -.cif.-> er_golden
    transactions -.txn_id.-> alerts
    er_golden -.golden_customer_id.-> cases
    alerts -.alert_ref.-> cases
    screening_results -.alert_ref.-> cases
    case_dispositions -.disposition_id.-> good_guy_list
    cases -.case_id.-> case_scores
    cases -.case_id.-> case_memo_features
    transactions -.memo.-> memo_classifications
    er_runs -.er_run_id.-> graph_sync_runs
```

## Danh sách file

| File | Bảng | Phase |
|---|---|---|
| [01-core-data.md](01-core-data.md) | `customers`, `customer_person`, `accounts`, `transactions`, `watchlist`, `watchlist_alias`, `admin_unit_mapping`, `ground_truth`, `dq_labels`, `acct_edge_daily`, `acct_node`, property graph `aml_fund_flow`, view `customers_masked` | 1, 2a, 2b, 5b |
| [02-screening.md](02-screening.md) | `screening_runs`, `screening_results`, `screening_customer_name`, `screening_list_name`, `screening_state`, `screening_token_stats` | 3b, 3c |
| [03-entity-resolution.md](03-entity-resolution.md) | `er_runs`, `er_model`, `er_pairs`, `er_golden` | 4 |
| [04-monitoring-network.md](04-monitoring-network.md) | `monitoring_runs`, `alerts`, `alert_accounts`, `alert_evidence`, `nx_account_features`, `graph_sync_runs`, `gds_runs`, `gds_account_features`, mô hình đồ thị Neo4j | 5a, 5c, 6a, 6b |
| [05-cases.md](05-cases.md) | `case_runs`, `cases`, `case_alerts`, `case_enrichment`, `case_dispositions`, `good_guy_list`, `case_features`, `case_models`, `case_scores` | 7a, 7b-supp, 7c |
| [06-memo.md](06-memo.md) | `memo_runs`, `memo_classifications`, `memo_overrides`, `case_memo_features` | 8d |
| [07-dq-audit.md](07-dq-audit.md) | `dq_rules`, `dq_results`, `audit_log` | 0, 2c |

## Khác biệt Oracle và DuckDB

| Điểm | Oracle | DuckDB |
|---|---|---|
| `transactions` | Interval partition theo tháng trên `txn_ts`, local index (`020_transactions_partitioning.sql`) | Bảng heap |
| FK và CHECK | Có, `ENABLE VALIDATE` (`030_constraints_indexes.sql`) | Chỉ có PK |
| `acct_edge_daily` | Materialized view, refresh complete | Bảng thường, rebuild bằng `refresh_acct_edge_daily()` |
| `acct_node`, `aml_fund_flow` | Có (SQL property graph, `GRAPH_TABLE ... MATCH`) | Không có; trace chạy bằng CTE đệ quy |
| `customers_masked` | View; role `aml_analyst` chỉ được grant view này, không được đọc `customers` (`sql/oracle/security/020_grants.sql`) | View thuần, không phân quyền |
| `audit_log` | Append-only bằng grant (`aml_app` chỉ có INSERT) và unified audit policy `aml_audit_log_tamper` ghi lại mọi UPDATE/DELETE | Append-only theo quy ước ứng dụng |

Cách tái tạo khi schema đổi: đọc lại DDL của phase vừa thêm, cập nhật file domain tương ứng và bảng danh sách ở trên.
