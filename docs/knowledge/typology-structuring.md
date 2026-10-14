---
doc_number: KB-TYP-001
title: Chia nhỏ giao dịch tiền mặt (structuring)
doc_type: TYPOLOGY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Typology, id: structuring, name: Chia nhỏ giao dịch tiền mặt}
  - {label: RedFlag, id: RF-001, name: Nhiều lần nộp tiền mặt ngay dưới ngưỡng báo cáo}
  - {label: RedFlag, id: RF-002, name: Nhiều khoản nộp tiền mặt dồn vào một cửa sổ thời gian ngắn}
  - {label: RedFlag, id: RF-003, name: Khoản nộp tiền mặt không phù hợp hồ sơ thu nhập của khách hàng}
relations:
  - {from: structuring, type: HAS_RED_FLAG, to: RF-001}
  - {from: structuring, type: HAS_RED_FLAG, to: RF-002}
  - {from: structuring, type: HAS_RED_FLAG, to: RF-003}
  - {from: structuring, type: INVESTIGATED_BY, to: PROC-001}
  - {from: structuring, type: INVESTIGATED_BY, to: PROC-003}
  - {from: structuring, type: INVESTIGATED_BY, to: PROC-004}
  - {from: structuring, type: GOVERNED_BY, to: REG-002}
---
# Chia nhỏ giao dịch tiền mặt (structuring)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Tài liệu mô tả kiểu hành vi chia nhỏ giao dịch tiền mặt (structuring), cách hệ thống phát hiện nó và hướng điều tra. Dữ liệu của dự án hoàn toàn là dữ liệu giả lập.

## Mô tả {structuring}

Chia nhỏ giao dịch (structuring, còn gọi là smurfing) là việc nộp tiền mặt thành nhiều khoản, mỗi khoản được giữ ngay dưới ngưỡng phải báo cáo giao dịch tiền mặt giá trị lớn, nhằm tránh bị báo cáo và tránh bị chú ý. Tổng các khoản có thể lớn hơn nhiều so với ngưỡng, nhưng từng khoản riêng lẻ trông bình thường.

Mục đích điển hình là đưa tiền mặt không rõ nguồn gốc vào hệ thống ngân hàng (giai đoạn placement của rửa tiền). Hành vi thường lặp lại trên cùng một tài khoản, đôi khi ở nhiều chi nhánh khác nhau để khó bị nhận ra.

## Cách hệ thống phát hiện {structuring}

Luật giám sát STRUCTURING (rule_id) tìm các khoản nộp tiền mặt vào tài khoản có số tiền nằm trong một dải ngay dưới ngưỡng báo cáo tiền mặt lớn. Ngưỡng nằm ở khoá cấu hình thresholds.large_cash_vnd; độ rộng của dải "ngay dưới" nằm ở thresholds.structuring_band_pct.

Một cảnh báo được tạo khi cùng một tài khoản có đủ số khoản nộp tối thiểu (monitoring.structuring.min_deposits) trong cửa sổ ngày (monitoring.structuring.window_days). Các giá trị cụ thể luôn đọc từ config.yaml; tài liệu này cố ý không chép con số để khỏi lệch với cấu hình.

Mỗi cảnh báo mang theo các giao dịch bằng chứng (alert_evidence) và một lý do (reason) dạng văn bản để điều tra viên đọc lại. Luật STRUCTURING gắn với typology structuring; hệ thống chỉ xếp hạng cảnh báo, không tự đóng.

## Dấu hiệu nhận biết {RF-001 RF-002 RF-003 structuring}

Dấu hiệu RF-001: nhiều lần nộp tiền mặt ngay dưới ngưỡng báo cáo, các số tiền gần như bằng nhau hoặc cùng một dải.

Dấu hiệu RF-002: các khoản nộp dồn vào một cửa sổ thời gian ngắn trên cùng một tài khoản, đôi khi tại nhiều chi nhánh.

Dấu hiệu RF-003: tổng tiền mặt nộp vào không phù hợp với nghề nghiệp, thu nhập hoặc mục đích mở tài khoản đã khai trong hồ sơ KYC.

Một dấu hiệu đơn lẻ chưa đủ kết luận; điều tra viên đánh giá sự kết hợp của các dấu hiệu cùng bối cảnh khách hàng.

## Hướng điều tra {PROC-001 PROC-003 PROC-004 structuring}

Bắt đầu bằng quy trình tiếp nhận và phân loại cảnh báo (PROC-001) để xác định cảnh báo thuộc loại nào và mức ưu tiên.

Sau đó phân tích dòng tiền và đối tác của tài khoản (PROC-003): tiền mặt nộp vào đi đâu, có được chuyển ra nhanh không, các khoản nộp có chung chi nhánh hoặc người nộp không.

Cuối cùng xác minh nguồn tiền (PROC-004): yêu cầu khách hàng giải trình và so sánh với hồ sơ thu nhập. Kết quả và quyết định do điều tra viên ghi nhận; trợ lý không đóng hay nộp hồ sơ thay con người.

## Trường hợp lành tính dễ nhầm {structuring}

Một số hoạt động hợp lệ có hình dạng giống structuring: cửa hàng bán lẻ nộp doanh thu tiền mặt hằng ngày, người buôn bán nhỏ có doanh thu đều đặn, hoặc hộ kinh doanh nộp tiền theo mùa vụ. Điểm khác biệt là doanh thu có nguồn gốc giải thích được, số tiền thay đổi tự nhiên và phù hợp quy mô kinh doanh đã đăng ký.

Khi nghi ngờ, so sánh với lịch sử nộp tiền cũ của chính khách hàng thay vì chỉ nhìn vào dải số tiền.
