# 01 — Core data (Phase 1, 2a, 2b, 5b)

Dữ liệu tổng hợp do `aml datagen` sinh ra, nạp từ Parquet bằng `aml load`. Đây là các bảng duy nhất chứa PII.
Nguồn: `010_datagen.sql`, `030_constraints_indexes.sql`, `040_acct_edge_daily.sql`, `050_customers_masked.sql`,
`120_property_graph.sql` (Oracle).

```mermaid
erDiagram
    customers {
        varchar cif PK
        varchar full_name
        varchar gender
        date dob
        varchar nationality
        varchar occupation
        varchar kyc_risk
        varchar id_type
        varchar id_number
        varchar phone
        varchar email
        varchar device_id
        varchar ip
        varchar address_format
        varchar street
        varchar ward
        varchar district
        varchar province
        varchar address
    }
    customer_person {
        varchar cif PK, FK
        varchar person_id PK "nguoi that dung sau 1..n cif (nhan ER)"
        boolean is_primary
        varchar variations
    }
    accounts {
        varchar account_id PK
        varchar cif FK
        varchar account_type
        varchar branch_id
        date open_date
        varchar currency
    }
    transactions {
        varchar txn_id PK
        timestamp txn_ts "Oracle: partition key, interval 1 thang"
        varchar from_account_id "co the la EXT-*"
        varchar to_account_id "co the la EXT-*"
        bigint amount_vnd "CHECK > 0"
        varchar channel "CHECK in 5 kenh"
        varchar branch_id
        varchar device_id
        varchar ip
        varchar counterparty_bank
        varchar counterparty_name
        varchar memo
    }
    watchlist {
        varchar entry_id PK
        varchar list_type "SANCTIONS | PEP | ..."
        varchar primary_name
        varchar name_origin
        date dob
        integer dob_year
        varchar dob_precision
        varchar nationality
        varchar program
        date listed_date
    }
    watchlist_alias {
        varchar alias_id PK
        varchar entry_id FK
        varchar alias_name
        varchar alias_type "AKA | TRANSLITERATION | REORDERED"
    }
    admin_unit_mapping {
        varchar old_ward
        varchar old_district
        varchar old_province
        varchar new_ward
        varchar new_province
    }
    ground_truth {
        varchar scenario_id
        varchar typology
        boolean is_suspicious
        varchar entity_type
        varchar entity_id
        varchar role
        timestamp start_ts
        timestamp end_ts
        varchar reason
    }
    dq_labels {
        varchar entity_type
        varchar entity_id
        varchar defect_type
        varchar detail
    }
    acct_edge_daily {
        varchar src_acct PK "Oracle: MV; DuckDB: bang"
        varchar dst_acct PK
        date day PK
        bigint txn_count
        bigint total_amount
    }
    acct_node {
        varchar account_id PK "Oracle MV, vertex cua aml_fund_flow"
    }

    customers ||--o{ accounts : "fk_accounts_customer"
    customers ||--o{ customer_person : "fk_cp_customer"
    watchlist ||--o{ watchlist_alias : "fk_wla_watchlist"
    accounts |o..o{ transactions : "from_account_id (khong FK, EXT-*)"
    accounts |o..o{ transactions : "to_account_id (khong FK, EXT-*)"
    transactions ||..o{ acct_edge_daily : "GROUP BY src, dst, day"
    acct_edge_daily ||..o{ acct_node : "UNION src, dst"
    customers ||..o{ ground_truth : "entity_id khi entity_type = customer"
    accounts ||..o{ ground_truth : "entity_id khi entity_type = account"
    customers ||..o{ dq_labels : "entity_id (defect da gieo)"
    customers }o..o| admin_unit_mapping : "ward, district, province (dia gioi cu)"
```

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `customers` | Bảng PII duy nhất của khách hàng. Analyst đọc qua view `customers_masked` (giữ họ và chữ cái đầu, 4 ký tự cuối giấy tờ, 3 số cuối điện thoại, 1 ký tự email, `birth_year` thay `dob`). |
| `customer_person` | Nhãn sinh ra cùng dữ liệu: nhiều `cif` của cùng một người thật. Là ground truth cho entity resolution, không dùng ở runtime. |
| `transactions` | Không có FK về `accounts` vì `from/to_account_id` có thể là tài khoản ngoài hệ thống (`EXT-*`) và defect DQ được gieo có chủ đích. Oracle: `CHECK (amount_vnd > 0)`, `CHECK channel`, `CHECK (from IS NOT NULL OR to IS NOT NULL)`. |
| `acct_edge_daily` | Cạnh tài khoản → tài khoản gộp theo ngày, dùng cho SQL trace (CTE đệ quy) và benchmark SQL-vs-graph. |
| `acct_node` + `aml_fund_flow` | Chỉ Oracle 23ai. Property graph: vertex `account` (từ `acct_node`), edge `transfer` (từ `transactions`, `SOURCE from_account_id`, `DESTINATION to_account_id`, properties `txn_id, txn_ts, amount_vnd, channel`). Truy vấn bằng `GRAPH_TABLE ... MATCH`. |
| `ground_truth`, `dq_labels`, `admin_unit_mapping` | Bảng tham chiếu không khóa. `ground_truth` đánh giá rules/prioritization; `dq_labels` đánh giá DQ framework; `admin_unit_mapping` ánh xạ địa giới hành chính cũ sang mới cho chuẩn hóa địa chỉ. |
