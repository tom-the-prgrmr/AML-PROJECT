# 05 — Cases, suppression và prioritization (Phase 7a, 7b-supp, 7c)

Gom alert từ ba nguồn (RULE, NETWORK, SCREENING) thành một case mỗi golden customer mỗi cửa sổ trượt, kèm
enrichment và quyết định của người. Mô hình chỉ **xếp hạng** case: không bảng nào ở đây để mô hình đóng case.
Append-only theo `run_id`. Nguồn: `160_cases.sql`, `170_case_suppression.sql`, `180_case_prioritization.sql`.

```mermaid
erDiagram
    case_runs {
        bigint run_id PK
        timestamp run_ts
        date as_of
        integer window_days
        bigint items
        bigint alerts
        bigint suppressed
        bigint active
        bigint cases
        bigint opened
        bigint reopened
        bigint closed
        varchar graph_source "gds | networkx | none"
        varchar version
        varchar config_hash
    }
    cases {
        bigint run_id PK, FK
        varchar case_id PK
        varchar golden_customer_id FK
        timestamp window_start
        timestamp first_alert_ts
        timestamp last_alert_ts
        bigint alerts
        bigint rule_alerts
        bigint network_alerts
        bigint screening_alerts
        varchar sources "RULE+NETWORK+SCREENING"
        varchar status "OPEN | REOPENED | CLOSED"
        varchar reason
    }
    case_alerts {
        bigint run_id PK, FK
        varchar item_key PK
        varchar golden_customer_id PK
        varchar case_id FK "NULL khi SUPPRESSED"
        varchar source "RULE | NETWORK | SCREENING"
        varchar rule_id
        varchar alert_ref "alert_id hoac run:cif:entry_id"
        varchar cif
        varchar entry_id
        timestamp event_ts
        timestamp end_ts
        bigint amount_vnd
        bigint txn_count
        varchar status "ACTIVE | SUPPRESSED"
        varchar suppression_rule
        varchar suppression_reason
        smallint retriggered
        varchar reason
        json details
    }
    case_enrichment {
        bigint run_id PK, FK
        varchar case_id PK, FK
        varchar section PK "kyc | linked_cifs | dq_issues | ..."
        json content
    }
    case_dispositions {
        bigint disposition_id PK
        varchar case_id FK
        bigint run_id FK
        varchar disposition "SUSPICIOUS | FALSE_POSITIVE"
        varchar reason
        varchar actor
        varchar origin "HUMAN | SIMULATED"
        date decided_on
        timestamp decided_ts
    }
    good_guy_list {
        bigint entry_no PK
        varchar cif
        varchar entry_id
        varchar case_id FK
        bigint disposition_id FK
        date cleared_on
        date expires_on
        varchar customer_fingerprint "tu screening_state"
        varchar entry_fingerprint
        varchar actor
        timestamp created_ts
    }
    case_features {
        bigint run_id PK, FK
        varchar case_id PK, FK
        varchar feature PK
        double value
    }
    case_models {
        bigint model_id PK
        varchar kind "logreg | lightgbm"
        varchar version
        varchar feature_version
        timestamp trained_ts
        date as_of
        bigint seed
        bigint cases
        bigint suspicious
        bigint false_positive
        json features
        json params
        json metrics
        varchar artifact "he so / model text, khong luu file"
        varchar data_hash
        varchar actor
    }
    case_scores {
        bigint score_run_id PK
        varchar case_id PK, FK
        bigint run_id FK
        bigint model_id FK
        varchar model_version
        double score
        integer queue_rank "NULL khi CLOSED"
        json top_features
        timestamp scored_ts
    }
    er_golden {
        varchar golden_customer_id
    }
    alerts {
        bigint alert_id PK
    }
    screening_results {
        bigint run_id PK
        varchar cif PK
        varchar entry_id PK
    }

    case_runs ||..o{ cases : "run_id"
    case_runs ||..o{ case_alerts : "run_id"
    case_runs ||..o{ case_enrichment : "run_id"
    cases ||..o{ case_alerts : "run_id, case_id (ACTIVE)"
    cases ||..o{ case_enrichment : "run_id, case_id"
    cases ||..o{ case_dispositions : "case_id (quyet dinh cua nguoi)"
    cases ||..o{ case_features : "run_id, case_id"
    cases ||..o{ case_scores : "run_id, case_id"
    case_models ||..o{ case_scores : "model_id"
    case_dispositions ||..o| good_guy_list : "disposition_id (FALSE_POSITIVE)"
    er_golden ||..o{ cases : "golden_customer_id"
    alerts ||..o{ case_alerts : "alert_ref (RULE, NETWORK)"
    screening_results ||..o{ case_alerts : "alert_ref (SCREENING)"
    screening_results ||..o{ good_guy_list : "cif, entry_id"
```

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `cases` | Khóa nghiệp vụ `case_id` ổn định qua các run; mỗi run ghi lại trạng thái mới (OPEN → REOPENED khi alert lặp sau CLOSED). View `cases_current` đọc run mới nhất. |
| `case_alerts` | Mỗi item là một `(alert, golden customer)`. Item bị suppress vẫn được lưu với `suppression_rule`, `suppression_reason` và `case_id = NULL`, nên mọi suppression đều truy vết được. |
| `case_dispositions` | Bảng duy nhất ghi quyết định đóng/mở, và chỉ do người (`origin = HUMAN`) hoặc mô phỏng demo (`SIMULATED`). View `case_dispositions_current` lấy quyết định mới nhất mỗi case. |
| `good_guy_list` | Cặp `(cif, entry_id)` đã được clear là false positive. Hết hiệu lực khi quá `expires_on` hoặc fingerprint của khách hàng/entry trong `screening_state` thay đổi. Hibernation không có bảng riêng, tính lại mỗi run từ dispositions. |
| `case_features` | Lưu dạng dài `(case, feature, value)`: thêm feature là thêm dòng, không đổi schema. Feature memo của Phase 8d nằm riêng ở `case_memo_features` (file 06). |
| `case_models` | Mô hình lưu trọn trong DB (hệ số, danh sách feature, params, metrics, `data_hash` của tập train). View `case_model_active` = model mới nhất. |
| `case_scores` | Một dòng mỗi case mỗi lần chấm; `top_features` giải thích điểm. View `case_queue` join `cases_current` với điểm mới nhất, chỉ case OPEN/REOPENED. |
