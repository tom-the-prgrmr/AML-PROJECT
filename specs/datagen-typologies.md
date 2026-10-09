---
id: datagen-typologies
status: approved
approved_by: pthieu
---

# Phase 1b-ii — Cài cắm typology và bảng `ground_truth` (`aml.datagen.typologies`)

## Bối cảnh
Monitoring (Phase 5), network detection, prioritization (Phase 7) và GraphRAG (Phase 8) cần nhãn đúng để
đo recall và false positive. Spec này cài cắm vào dữ liệu nền của 1b-i (`datagen-transactions`) các
typology structuring, rapid movement, mule ring, round-tripping, các mẫu lành tính giống-đáng-ngờ
(payroll, merchant) và ghi nhãn `ground_truth` (kể cả các memo prompt-injection). Phụ thuộc 1b-i: dùng
lại `TxnGenParams`, `ActivityData`, `generate_activity`, schema `ground_truth`, `INJECTION_PHRASES`.

### Interface
- `generate_activity(tables, params, seed)` của 1b-i, khi `params.typology_counts` > 0, gọi
  `inject_typologies(...)` trong `src/aml/datagen/typologies.py` (sub-stream `"ground_truth"`).
- Khoá `params.typology_counts`: `structuring`, `rapid_movement`, `mule_ring`, `round_tripping`,
  `benign_payroll`, `benign_merchant`.
- `scenario_id` khớp `^GT-[A-Z]{3,4}-\d{4}$` (vd `GT-STR-0001`).
- Role theo typology: structuring `subject`; rapid_movement `subject`, `source`, `destination`;
  mule_ring `member`, `collector`, `source`, `destination`; round_tripping `hop`; benign_payroll
  `employer`, `employee`; benign_merchant `merchant`, `payer`; mọi giao dịch của scenario `evidence`;
  prompt_injection `memo`.

## Tiêu chí nghiệm thu
<!-- Fixture G = fixture F của 1b-i (tables 1a 300 customers seed 7; n_transactions=5000, months=6,
counterparties=(3, 12), start_date=2026-01-01, large_cash_vnd=400_000_000, structuring_band_pct=0.10,
duplicate_rate=0.02, injection_memos=6, seed=42) nhưng typology_counts={structuring:2, rapid_movement:2,
mule_ring:1, round_tripping:2, benign_payroll:1, benign_merchant:1}. -->
- AC1: Given fixture G, When gọi `generate_activity`, Then `ground_truth` có cột bằng `GROUND_TRUTH_COLUMNS`, số `scenario_id` phân biệt theo typology = {structuring:2, rapid_movement:2, mule_ring:1, round_tripping:2, benign_payroll:1, benign_merchant:1, prompt_injection:6}, `is_suspicious` = False đúng với `benign_payroll`, `benign_merchant`, `prompt_injection` và True với 4 typology còn lại, mọi `entity_id` loại account/transaction/customer tồn tại trong bảng tương ứng, mọi `reason` khác rỗng, và không account nào thuộc hai scenario khác nhau.
- AC2: Given fixture G, When gọi `generate_activity`, Then 6 giao dịch có memo chứa cụm trong `INJECTION_PHRASES` đúng bằng tập `entity_id` của các dòng `typology = "prompt_injection"` (`entity_type = "transaction"`), và ít nhất 1 trong số đó cũng là `evidence` của một scenario `is_suspicious = True`.
- AC3: Given fixture G, When gọi `generate_activity`, Then mỗi scenario `structuring` có 4–8 giao dịch evidence đều `CASH` nạp vào cùng một account `subject`, mỗi `amount_vnd` trong [360_000_000, 400_000_000), tổng ≥ 400_000_000, trải trên ≥ 3 ngày lịch và ≥ 2 `branch_id` khác nhau trong ≤ 14 ngày; không giao dịch `CASH` nào ngoài evidence structuring có `amount_vnd` trong [360_000_000, 400_000_000); và khi đổi `large_cash_vnd=100_000_000` thì mọi amount evidence structuring trong [90_000_000, 100_000_000).
- AC4: Given fixture G, When gọi `generate_activity`, Then mỗi scenario `rapid_movement` có một account `subject` nhận vào tổng X với X trong [200_000_000, 2_000_000_000] và chuyển ra ≥ 2 account `destination` khác nhau tổng trong [0.95·X, 0.99·X], mọi giao dịch ra có `txn_ts` trong (ts giao dịch vào cuối cùng, ts giao dịch vào đầu tiên + 24 giờ].
- AC5: Given fixture G, When gọi `generate_activity`, Then scenario `mule_ring` có 5–30 account `member` (gồm `collector`) thuộc các `person_id` khác nhau (theo `customer_person`); đồ thị nối hai member khi customer của chúng trùng chính xác `device_id`, `phone` hoặc `address` trong `ActivityData.customers` là liên thông; mỗi member nhận ≥ 3 giao dịch từ ≥ 3 account `source` không phải member; `collector` chuyển tới ≥ 3 account `destination` không phải member; và `tables.customers` đầu vào bằng bản chụp trước khi gọi.
- AC6: Given fixture G, When gọi `generate_activity`, Then mỗi scenario `round_tripping` là chu trình 3 hoặc 4 account nội bộ thuộc các `person_id` khác nhau (A→B→C→A hoặc A→B→C→D→A), `txn_ts` các bước tăng nghiêm ngặt, bước cuối trừ bước đầu ≤ 168 giờ, bước đầu ≥ 100_000_000 VND và mỗi bước sau có amount trong [0.90, 1.00] × bước trước.
- AC7: Given fixture G, When gọi `generate_activity`, Then scenario `benign_payroll` có 1 account `employer` trả cho ≥ 20 account `employee` khác nhau, mỗi employee đúng 6 giao dịch, mỗi tháng lịch 2026-01 tới 2026-06 một giao dịch, memo chứa "lương" (không phân biệt hoa thường); scenario `benign_merchant` có 1 account `merchant` nhận từ ≥ 30 account `payer` khác nhau với mỗi amount trong [50_000, 5_000_000].
- AC8: Given fixture G, When gọi `generate_activity`, Then các bất biến của 1b-i vẫn giữ: số giao dịch không có trong `dq_labels` = 5000; không `detail` nào trong `dq_labels` là giao dịch thuộc `ground_truth`; mọi account `CURRENT` không xuất hiện trong `ground_truth` có số counterparty phân biệt trong [3, 12]; và hai lần chạy seed=42 cho `ground_truth` bằng nhau (`assert_frame_equal`).
- AC9: Given fixture G nhưng tables chỉ có 40 customers, hoặc n_transactions=200, When gọi `generate_activity`, Then raise `ValueError` với thông điệp lần lượt chứa "not enough accounts" và "n_transactions".

## Ngoài phạm vi
- Accounts/transactions nền, memo, giao dịch trùng, profile dense (1b-i).
- Dòng `sanctions_hit` / `pep_hit` / `screening_trap` trong `ground_truth` (1c sinh; giá trị typology đã giữ chỗ ở schema 1b-i).
- Typology high velocity, dormant reactivation; nhãn cấp customer cho trùng người (đã có ở `customer_person` của 1a).
- Khách hàng doanh nghiệp riêng (xem N1); bảng số dư.

## Giả định
- Số scenario cho profile thật: `data.typologies` = {structuring: 20, rapid_movement: 20, mule_ring: 5, round_tripping: 15, benign_payroll: 5, benign_merchant: 5}; profile `large` nhân 10 qua khoá mới `typology_scale` trong `ProfileConfig` (mặc định 1, large = 10) (Q3).
- Mule ring: 1b trả về bản sao customers với `device_id` / `phone` / nhóm cột địa chỉ (`address_format, street, ward, district, province, address`) của member được ghi đè nguyên văn từ một member khác; không bao giờ sửa input (Q6).
- Dữ liệu nền không có giao dịch `CASH` nào trong dải structuring; false positive được kiểm bằng benign look-alike (Q7).
- Memo prompt-injection được gắn nhãn `prompt_injection`, `is_suspicious = False`; ít nhất 1 nằm trên giao dịch của scenario nghi ngờ (Q9).
- Tham số typology (cửa sổ structuring 14 ngày, round-trip 168 giờ, mule 5–30, retention 1–5%, rapid 200M–2B) là hằng có tên trong `typologies.py`; chỉ ngưỡng và band lấy từ `thresholds` (Q10).
- Typology giữ chỗ cho 1c: `sanctions_hit`, `pep_hit` (`is_suspicious = True`, entity gồm `customer` và `watchlist_entry`) và `screening_trap` (`is_suspicious = False`, entity `watchlist_entry`); 1b-ii không sinh dòng nào cho ba typology này.
- Mỗi account tham gia nhiều nhất một scenario (trừ giao dịch `prompt_injection`); mọi entity liên quan (source, destination, employee, payer) đều được ghi vào `ground_truth`.
- Giao dịch typology nằm trong n_transactions (nền = n_transactions − số giao dịch typology); giao dịch trùng DQ chỉ nhân bản giao dịch nền.

## Câu hỏi mở
- [x] Q3. Số scenario mỗi typology? — đề xuất mặc định: 20/20/5/15/5/5, large nhân 10. — Trả lời: theo đề xuất.
- [x] Q6. Thuộc tính dùng chung cho mule ring? — đề xuất mặc định: 1b trả bản sao customers đã ghi đè. — Trả lời: theo đề xuất, không bao giờ sửa input.
- [x] Q7. Nền có cash trong dải structuring? — đề xuất mặc định: không. — Trả lời: theo đề xuất.
- [x] Q9. Prompt-injection memo? — đề xuất mặc định: nhãn `prompt_injection`, ≥ 1 trên scenario nghi ngờ. — Trả lời: theo đề xuất.
- [x] Q10. Tham số typology vào config? — đề xuất mặc định: hằng số trong module. — Trả lời: theo đề xuất.
- [x] N1. 1a chỉ có khách cá nhân; employer/merchant của benign look-alike là ai? — đề xuất mặc định: account `CURRENT` của khách cá nhân sẵn có (mô hình hộ kinh doanh), không thêm khách doanh nghiệp; memo/`counterparty_name` thể hiện tính chất kinh doanh. — Trả lời: theo đề xuất (account CURRENT của khách cá nhân có sẵn, mô hình hộ kinh doanh).
- [x] N2. Cách đưa "large nhân 10" vào config? — đề xuất mặc định: thêm `typology_scale: int = 1` vào `ProfileConfig`, `large: typology_scale: 10`; tránh hệ số ẩn trong code. — Trả lời: theo đề xuất (`ProfileConfig.typology_scale`, large = 10).
