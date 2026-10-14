---
doc_number: KB-TYP-004
title: Chuyển tiền vòng tròn (round tripping)
doc_type: TYPOLOGY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Typology, id: round_tripping, name: Chuyển tiền vòng tròn}
  - {label: RedFlag, id: RF-011, name: Tiền rời tài khoản rồi quay lại qua các khách hàng khác trong vài ngày}
  - {label: RedFlag, id: RF-012, name: Chuỗi chuyển khoản khép kín với số tiền gần bằng nhau}
  - {label: RedFlag, id: RF-013, name: Giao dịch qua lại không có mục đích kinh tế}
relations:
  - {from: round_tripping, type: HAS_RED_FLAG, to: RF-011}
  - {from: round_tripping, type: HAS_RED_FLAG, to: RF-012}
  - {from: round_tripping, type: HAS_RED_FLAG, to: RF-013}
  - {from: round_tripping, type: INVESTIGATED_BY, to: PROC-001}
  - {from: round_tripping, type: INVESTIGATED_BY, to: PROC-003}
  - {from: round_tripping, type: INVESTIGATED_BY, to: PROC-004}
  - {from: round_tripping, type: GOVERNED_BY, to: REG-002}
---
# Chuyển tiền vòng tròn (round tripping)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Tài liệu mô tả kiểu chuyển tiền vòng tròn (round tripping): tiền đi một vòng qua các bên khác rồi quay về nơi xuất phát.

## Mô tả {round_tripping}

Round tripping là khi tiền rời một tài khoản, đi qua một hoặc nhiều tài khoản của khách hàng khác, rồi quay lại chính tài khoản đầu trong thời gian ngắn. Số tiền sau mỗi chặng thường chỉ giảm nhẹ.

Mục đích có thể là tạo doanh thu hoặc giao dịch giả để hợp thức hoá nguồn tiền, tăng khối lượng giao dịch bề ngoài, hoặc làm khó việc truy vết nguồn gốc ban đầu.

## Cách hệ thống phát hiện {round_tripping}

Luật mạng NET_CYCLE (rule_id) tìm chu trình trong đồ thị chuyển khoản giữa các tài khoản. Chu trình phải có độ dài trong khoảng network.cycles.min_length đến network.cycles.max_length, hop cuối nằm trong cửa sổ giờ network.cycles.window_hours kể từ hop đầu, mỗi khoản không nhỏ hơn network.cycles.min_amount_vnd, và tỷ lệ khoản nhỏ nhất trên khoản lớn nhất không dưới network.cycles.min_amount_ratio.

Phép tìm kiếm có giới hạn số bước (network.cycles.max_search_steps); vượt giới hạn là lỗi rõ ràng chứ không cắt im lặng. Luật NET_CYCLE gắn với typology round_tripping. Tài liệu không chép con số; xem config.yaml.

## Dấu hiệu nhận biết {RF-011 RF-012 RF-013 round_tripping}

Dấu hiệu RF-011: tiền rời tài khoản rồi quay lại qua các khách hàng khác trong vài ngày.

Dấu hiệu RF-012: chuỗi chuyển khoản khép kín với số tiền gần bằng nhau ở mọi chặng.

Dấu hiệu RF-013: giao dịch qua lại giữa các bên mà không có hàng hoá, dịch vụ hay mục đích kinh tế giải thích được.

Các bên trong vòng thường có liên hệ với nhau (chung địa chỉ, thiết bị hoặc người đại diện), nên nên kiểm tra cả quan hệ mạng.

## Hướng điều tra {PROC-001 PROC-003 PROC-004 round_tripping}

Phân loại cảnh báo theo PROC-001; cảnh báo NET_CYCLE thường xuất hiện cùng lúc cho mọi khách hàng trong vòng, nên hệ thống gộp chúng vào hồ sơ tương ứng.

Dùng PROC-003 để dựng lại từng chặng: thời điểm, số tiền, bên gửi và bên nhận, rồi xác định ai hưởng lợi cuối cùng.

Dùng PROC-004 để yêu cầu chứng từ giải thích từng giao dịch trong vòng, chẳng hạn hợp đồng, hoá đơn hay giấy vay.

## Trường hợp lành tính dễ nhầm {round_tripping}

Hoàn tiền sau khi huỷ giao dịch, trả nợ lẫn nhau giữa người thân hoặc đối tác thân thiết, và chuyển tiền qua lại của các công ty cùng tập đoàn có thể tạo chu trình nhìn như round tripping.

Điểm phân biệt: có chứng từ giải thích từng chặng, số tiền khác nhau theo bản chất giao dịch thay vì gần bằng nhau, và không lặp lại một cách đều đặn.
