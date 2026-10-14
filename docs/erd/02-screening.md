# 02 — Screening (Phase 3b, 3c)

Sàng lọc tên khách hàng (tiếng Việt, có dấu/không dấu, đảo thứ tự) với watchlist. Kết quả theo cặp
`(cif, entry_id)`, versioned theo `run_id`; dòng cũ không xóa mà đánh dấu `superseded_by`.
Nguồn: `080_screening.sql`, `090_screening_state.sql`.

```mermaid
erDiagram
    screening_runs {
        bigint run_id PK
        timestamp run_ts
        varchar mode "FULL | INCREMENTAL"
        date as_of
        bigint customers_screened
        bigint entries_screened
        bigint candidate_pairs
        bigint recorded
        bigint alerts
        bigint reviews
        bigint auto_cleared
        bigint superseded
        varchar version
        varchar config_hash
    }
    screening_results {
        bigint run_id PK, FK
        varchar cif PK
        varchar entry_id PK
        varchar list_type
        varchar matched_name
        varchar matched_name_type "PRIMARY | AKA | TRANSLITERATION | REORDERED"
        double token_set
        double jaro_winkler
        double fuzzy_score
        double coverage
        double name_score
        double final_score
        integer dob_gap_years
        varchar decision "ALERT | REVIEW | AUTO_CLEARED"
        varchar reason
        bigint superseded_by "NULL = dong hien hanh"
    }
    screening_customer_name {
        varchar cif PK
        varchar name_norm
        varchar name_key "token da sort"
    }
    screening_list_name {
        varchar entry_id PK
        varchar name_norm PK
        varchar name_type
        varchar name_key
    }
    screening_state {
        varchar entity_type PK "customer | watchlist_entry"
        varchar entity_id PK
        varchar fingerprint "SHA-256"
        bigint run_id FK
    }
    screening_token_stats {
        varchar token PK
        bigint doc_freq
        bigint n_names
        bigint run_id FK "IDF dong bang o FULL run cuoi"
    }
    customers {
        varchar cif PK
    }
    watchlist {
        varchar entry_id PK
    }
    watchlist_alias {
        varchar alias_id PK
        varchar entry_id FK
    }

    screening_runs ||..o{ screening_results : "run_id"
    screening_runs ||..o{ screening_results : "superseded_by (run moi hon)"
    screening_runs ||..o{ screening_state : "run_id"
    screening_runs ||..o{ screening_token_stats : "run_id"
    customers ||..o{ screening_results : "cif (khong FK, khong PII)"
    watchlist ||..o{ screening_results : "entry_id"
    customers ||..|| screening_customer_name : "cif (ten chuan hoa)"
    watchlist ||..o{ screening_list_name : "entry_id (primary + alias)"
    watchlist_alias ||..o| screening_list_name : "alias_name chuan hoa"
    customers ||..o| screening_state : "entity_id khi entity_type = customer"
    watchlist ||..o| screening_state : "entity_id khi entity_type = watchlist_entry"
```

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `screening_results` | Mỗi dòng là một quyết định có `reason`. View `screening_current` = `superseded_by IS NULL`. Chỉ lưu `cif`, không lưu tên khách hàng; `matched_name` là tên trong watchlist. |
| `screening_customer_name`, `screening_list_name` | Tên đã chuẩn hóa để screen bằng SQL (blocking theo `name_key`). Được rebuild từ `customers`, `watchlist`, `watchlist_alias`. |
| `screening_state` | Fingerprint lần screen gần nhất của từng entity. Chế độ INCREMENTAL chỉ screen entity có fingerprint thay đổi. `good_guy_list` (file 05) lưu lại fingerprint này để biết khi nào clearance hết hiệu lực. |
| `screening_token_stats` | IDF theo token, đóng băng ở FULL run gần nhất để điểm số của run INCREMENTAL so sánh được. |
