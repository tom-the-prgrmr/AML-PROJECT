# 06 — Memo classification (Phase 8d)

Phân loại nội dung chuyển khoản (`transactions.memo`) vào 6 nhóm đóng bằng rule trước, LLM cục bộ (Ollama) sau.
Nhãn memo chỉ là **feature xếp hạng**; không bảng nào ở đây tạo alert hay đổi trạng thái case. Mỗi memo được phân
loại một lần theo khóa chuẩn hóa (`memo_key`), không theo từng giao dịch. Nguồn: `190_memo_analysis.sql`.

```mermaid
erDiagram
    memo_runs {
        bigint run_id PK
        timestamp run_ts
        varchar memo_version "normalisation + rules + prompt + schema"
        varchar llm_model
        bigint transactions
        bigint with_memo
        bigint distinct_memos
        bigint memo_keys
        bigint reused
        bigint by_rule
        bigint by_llm
        bigint fallback
        bigint llm_calls
        bigint keys_left "> 0: run dung som"
        double seconds
        varchar actor
    }
    memo_classifications {
        bigint run_id PK, FK
        varchar memo_key PK "sha256(memo_norm)[0:32]"
        varchar memo_version PK
        varchar llm_model PK
        varchar memo_norm "van ban khong tin cay, chi de nguoi doc"
        varchar category "1 trong 6 nhom dong"
        varchar method "RULE | LLM | FALLBACK"
        integer attempts
        integer pattern
        bigint transactions
        varchar reason "tu template, khong tu memo hay model"
        timestamp classified_ts
    }
    memo_overrides {
        bigint override_id PK
        varchar memo_key FK
        varchar memo_version
        varchar llm_model
        varchar category
        varchar previous_category
        varchar previous_method
        varchar reason "loi cua nguoi, luu nhu du lieu"
        varchar actor
        timestamp decided_ts
    }
    case_memo_features {
        bigint run_id PK, FK
        varchar case_id PK, FK
        varchar memo_version PK
        varchar llm_model PK
        bigint labels_rev PK "override_id moi nhat luc ghi"
        varchar feature PK
        double value
    }
    transactions {
        varchar txn_id PK
        varchar memo
    }
    cases {
        bigint run_id PK
        varchar case_id PK
    }

    memo_runs ||..o{ memo_classifications : "run_id"
    transactions }o..|| memo_classifications : "memo_key = hash(normalise(memo))"
    memo_classifications ||..o{ memo_overrides : "memo_key (nguoi sua nhan)"
    cases ||..o{ case_memo_features : "run_id, case_id"
    memo_overrides ||..o{ case_memo_features : "labels_rev (phien ban nhan)"
```

## Ghi chú

| Đối tượng | Ghi chú |
|---|---|
| `memo_classifications` | Một dòng mỗi câu trả lời của rule hoặc model cho một khóa. View `memo_classifications_current` đọc run mới nhất theo `(memo_key, memo_version, llm_model)`. `memo_norm` được coi là dữ liệu không tin cậy: không bao giờ đưa vào `reason` hay `audit_log`. |
| `memo_overrides` | Nhãn của người. Đổi ý là thêm dòng mới; dòng của model không bị sửa. View `memo_labels_current` cho nhãn đang hiệu lực, người thắng model (`method = HUMAN`). |
| `case_memo_features` | Sáu đếm theo nhóm cho mỗi case, tách khỏi `case_features` để feature set Phase 7c giữ nguyên. `labels_rev` ghi lại phiên bản nhãn đã dùng, nên điểm số truy vết được về đúng tập nhãn. |
