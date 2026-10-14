# 07 — Data quality và audit (Phase 0, 2c)

Hai bảng xuyên suốt mọi module: `audit_log` nhận mọi quyết định tự động hoặc của người, `dq_rules`/`dq_results`
đo chất lượng dữ liệu đầu vào. Cả hai đều append-only. Nguồn: `000_audit_log.sql`, `060_dq.sql`.

```mermaid
erDiagram
    audit_log {
        bigint audit_id PK "sequence"
        timestamp event_ts "UTC"
        varchar module "screening | er | monitoring | cases | assistant | ui"
        varchar entity_type "screening_match | er_pair | alert | case | memo | query ..."
        varchar entity_id
        varchar decision "ALERT | REVIEW | AUTO_CLEARED | SUPPRESSED ..."
        varchar reason "nguoi doc duoc"
        varchar version "rule / model / prompt version"
        varchar actor "system hoac user id"
        json details "extras rieng tung module"
    }
    dq_rules {
        varchar rule_id PK
        varchar table_name
        varchar dimension "COMPLETENESS | VALIDITY | UNIQUENESS | CONSISTENCY | TIMELINESS"
        varchar scope "ROW | TABLE"
        varchar description
        varchar check_sql "file duoi sql/"
        varchar label_defect_type
        double max_fail_rate
        boolean enabled
    }
    dq_results {
        bigint run_id PK
        varchar rule_id PK, FK
        timestamp run_ts
        date as_of
        varchar table_name
        varchar dimension
        bigint total_rows
        bigint failed_rows
        double fail_rate "NULL khi NO_DATA"
        varchar status "PASS | FAIL | NO_DATA"
        json sample_ids
    }
    dq_labels {
        varchar entity_type
        varchar entity_id
        varchar defect_type
        varchar detail
    }
    screening_results {
        varchar decision
    }
    er_pairs {
        varchar decision
    }
    alerts {
        bigint alert_id PK
    }
    case_alerts {
        varchar status
    }
    case_dispositions {
        bigint disposition_id PK
    }
    memo_overrides {
        bigint override_id PK
    }

    dq_rules ||..o{ dq_results : "rule_id"
    dq_rules }o..o{ dq_labels : "label_defect_type = defect_type (danh gia recall)"
    screening_results ||..|| audit_log : "entity_type = screening_match"
    er_pairs ||..|| audit_log : "entity_type = er_pair"
    alerts ||..|| audit_log : "entity_type = alert"
    case_alerts ||..|| audit_log : "entity_type = alert_item (SUPPRESSED)"
    case_dispositions ||..|| audit_log : "entity_type = case, actor = nguoi"
    memo_overrides ||..|| audit_log : "entity_type = memo"
```

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `audit_log` | Quan hệ đa hình qua `(entity_type, entity_id)`, không FK. Mọi module ghi qua `aml.common.audit.audit()` / `audit_many()`; dòng dữ liệu và dòng audit nằm trong cùng `with db.transaction():`. Trên Oracle, role `aml_app` chỉ được grant INSERT, và unified audit policy `aml_audit_log_tamper` ghi lại mọi UPDATE/DELETE (`sql/oracle/security/`). Extras của từng module (câu hỏi assistant, Cypher sinh ra, ID đã truy xuất, feedback) đi vào `details` để schema lõi không đổi. |
| `dq_rules` | Catalogue rule DQ, mỗi rule trỏ tới một file SQL kiểm tra. `label_defect_type` nối với `dq_labels` để đo rule bắt được bao nhiêu defect đã gieo. |
| `dq_results` | Một dòng mỗi `(run, rule)`, insert-only. View `dq_trend` tính delta `failed_rows` giữa các run bằng `LAG`. `sample_ids` là các id lỗi nhỏ nhất để điều tra viên xem nhanh. |
