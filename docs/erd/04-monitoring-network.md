# 04 — Monitoring, network và Neo4j projection (Phase 5a, 5c, 6a, 6b)

Rules giao dịch (`source = RULE`) và phân tích mạng lưới (`source = NETWORK`, NetworkX trên DuckDB/Oracle hoặc
GDS trên Neo4j) cùng ghi vào `alerts`. Append-only theo `run_id`; view `alerts_current` đọc run mới nhất của từng rule.
Nguồn: `110_monitoring.sql`, `130_network.sql`, `140_graph_sync.sql`, `150_gds.sql`.

```mermaid
erDiagram
    monitoring_runs {
        bigint run_id PK
        varchar rule_id PK
        timestamp run_ts
        date as_of
        varchar source "RULE | NETWORK"
        varchar rule_version
        json params "tham so da the vao rule"
        bigint alerts
        bigint evidence
    }
    alerts {
        bigint alert_id PK
        bigint run_id FK
        varchar alert_key "UNIQUE (run_id, alert_key), on dinh qua cac run"
        varchar source "RULE | NETWORK"
        varchar rule_id FK
        varchar rule_version
        varchar subject_type "ACCOUNT | ACCOUNT_GROUP"
        varchar subject_id
        timestamp window_start
        timestamp window_end
        bigint txn_count
        bigint amount_vnd
        varchar reason
        json details
    }
    alert_accounts {
        bigint alert_id PK, FK
        varchar account_id PK
        varchar cif
        varchar role
    }
    alert_evidence {
        bigint alert_id PK, FK
        varchar txn_id PK
    }
    nx_account_features {
        bigint run_id PK
        varchar account_id PK
        bigint in_degree
        bigint out_degree
        bigint in_vnd
        bigint out_vnd
        double pagerank
        double pagerank_ratio
        bigint cycle_alerts
        varchar shared_cluster_id
        bigint shared_cluster_size
        smallint is_hub
    }
    graph_sync_runs {
        bigint run_id PK
        timestamp run_ts
        varchar mode "FULL | INCREMENTAL"
        varchar source_backend
        varchar source_user
        timestamp since_ts
        timestamp watermark_from
        timestamp watermark_to
        bigint er_run_id FK
        bigint nodes_sent
        bigint rels_sent
        bigint pruned
        bigint swept
        bigint lag_before_seconds
        bigint lag_after_seconds
        double seconds
        smallint in_sync
        json details
    }
    gds_runs {
        bigint run_id PK
        timestamp run_ts
        date as_of
        varchar source_backend
        bigint sync_run_id FK
        timestamp txn_watermark
        varchar gds_version
        bigint accounts
        bigint active_accounts
        bigint wcc_components
        bigint louvain_communities
        bigint shared_clusters
        double seconds
        json params
    }
    gds_account_features {
        bigint run_id PK, FK
        varchar account_id PK
        bigint in_degree
        bigint out_degree
        bigint in_vnd
        bigint out_vnd
        double pagerank
        double pagerank_ratio
        varchar wcc_id
        bigint wcc_size
        varchar louvain_id
        bigint louvain_size
        varchar shared_cluster_id
        bigint shared_cluster_size
    }
    accounts {
        varchar account_id PK
        varchar cif FK
    }
    transactions {
        varchar txn_id PK
    }
    er_runs {
        bigint run_id PK
    }

    monitoring_runs ||..o{ alerts : "run_id, rule_id"
    alerts ||..o{ alert_accounts : "alert_id"
    alerts ||..o{ alert_evidence : "alert_id"
    accounts ||..o{ alert_accounts : "account_id"
    transactions ||..o{ alert_evidence : "txn_id (bang chung)"
    accounts ||..o{ nx_account_features : "account_id (1 dong moi run)"
    nx_account_features ||..o{ alerts : "NETWORK alerts (cycle, hub, shared)"
    er_runs ||..o{ graph_sync_runs : "er_run_id (golden id dua len Neo4j)"
    graph_sync_runs ||..o{ gds_runs : "sync_run_id (projection da tinh)"
    gds_runs ||..o{ gds_account_features : "run_id"
    accounts ||..o{ gds_account_features : "account_id"
```

## Mô hình đồ thị Neo4j (read-only projection)

Neo4j không nằm trong schema quan hệ nhưng là đích của `graph_sync_runs`. Mô hình được `aml graph sync` xây bằng
`MERGE` từ view `graph_customer_attrs`, `accounts`, `transactions` và `customer_golden`:

```mermaid
flowchart LR
    C((Customer<br/>golden_customer_id)) -- OWNS --> A((Account))
    A -- TRANSFERRED_TO<br/>txn_id, txn_ts, amount_vnd --> A2((Account))
    C -- USES_DEVICE --> D((Device<br/>sha256))
    C -- HAS_PHONE --> P((Phone<br/>sha256))
    C -- LIVES_AT --> L((Address<br/>sha256))
    S[SyncState<br/>watermark]
```

| Node / rel | Ghi chú |
|---|---|
| `Customer` | Một node mỗi `golden_customer_id` (sau ER), không phải mỗi `cif`. |
| `Device`, `Phone`, `Address` | Khóa bằng sha256 của giá trị chuẩn hóa; giá trị thô không rời Oracle. Dùng cho shared-attribute cluster. |
| `TRANSFERRED_TO` | Một rel mỗi giao dịch có cả hai đầu là tài khoản nội bộ. |
| `SyncState` | Watermark sync incremental; không có bảng tương ứng phía Oracle. |

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `alerts` | `alert_key` ổn định qua các run (cùng rule, cùng subject, cùng cửa sổ) để Phase 7 nhận ra alert lặp. `details` giữ số liệu riêng từng rule. |
| `alert_accounts.cif` | Denormalize `cif` tại thời điểm chạy để case consolidation không phải join lại `accounts`. |
| `nx_account_features` vs `gds_account_features` | Cùng ý nghĩa, hai nguồn tính (NetworkX trên system of record / GDS trên Neo4j). `case_runs.graph_source` ghi lại run case dùng nguồn nào. |
| `graph_sync_runs`, `gds_runs` | Nhật ký chạy, cho phép truy vết feature GDS về đúng bản projection và run ER đã dùng. |
