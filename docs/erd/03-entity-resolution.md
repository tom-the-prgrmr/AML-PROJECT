# 03 — Entity resolution (Phase 4)

Gộp nhiều `cif` của cùng một người thật thành một `golden_customer_id` bằng Splink (Fellegi-Sunter).
Append-only theo `run_id`; view `customer_golden` đọc run mới nhất. Chỉ lưu `cif`, không FK về `customers`.
Nguồn: `100_entity_resolution.sql`.

```mermaid
erDiagram
    er_runs {
        bigint run_id PK
        timestamp run_ts
        date as_of
        bigint customers_resolved
        bigint blocked_pairs
        bigint match_pairs
        bigint review_pairs
        bigint clusters
        bigint merged_clusters
        bigint merged_cifs
        double match_threshold
        double review_threshold
        double prior_probability
        varchar version
        varchar splink_version
        varchar config_hash
    }
    er_model {
        bigint run_id PK, FK
        varchar comparison PK "name | dob | phone | email | address | id"
        integer level_no PK "0 = null level"
        varchar label
        integer is_null_level
        double m_probability
        double u_probability
        double match_weight "log2(m/u)"
    }
    er_pairs {
        bigint run_id PK, FK
        varchar cif_l PK "cif_l < cif_r"
        varchar cif_r PK
        double match_weight
        double match_probability
        double mw_prior
        double mw_name
        double mw_dob
        double mw_phone
        double mw_email
        double mw_address
        double mw_id
        varchar decision "MATCH | REVIEW"
        varchar reason
    }
    er_golden {
        bigint run_id PK, FK
        varchar cif PK
        varchar golden_customer_id
        integer cluster_size
    }
    customers {
        varchar cif PK
    }
    customer_person {
        varchar cif PK
        varchar person_id PK
    }

    er_runs ||..o{ er_model : "run_id (tham so m/u da hoc)"
    er_runs ||..o{ er_pairs : "run_id"
    er_runs ||..o{ er_golden : "run_id"
    customers ||..o{ er_pairs : "cif_l"
    customers ||..o{ er_pairs : "cif_r"
    customers ||..o{ er_golden : "cif (1 dong moi run)"
    customer_person ||..o{ er_golden : "cif (ground truth de danh gia)"
```

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `er_model` | Lưu nguyên tham số mô hình (m, u, match weight từng level) trong DB thay vì file, nên mỗi cặp trong `er_pairs` giải thích được bằng tổng các `mw_*`. |
| `er_pairs` | Một dòng mỗi cặp ứng viên qua blocking. `reason` là chuỗi người đọc được, liệt kê các trường đóng góp nhiều nhất. |
| `er_golden` | Ánh xạ `cif → golden_customer_id`. View `customer_golden` (run mới nhất) là khóa mà `cases` (file 05) và Neo4j node `Customer` (file 04) dùng. View `er_cluster_weights` tổng hợp theo cluster. |
