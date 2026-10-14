---
doc_number: KB-POL-001
title: Quy định nội bộ về phòng chống rửa tiền (tổng hợp)
doc_type: POLICY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Regulation, id: REG-001, name: Quy định nội bộ về nhận biết và thẩm định khách hàng}
  - {label: Regulation, id: REG-002, name: Quy định nội bộ về giám sát giao dịch và báo cáo giao dịch giá trị lớn}
  - {label: Regulation, id: REG-003, name: Quy định nội bộ về rà soát danh sách trừng phạt và PEP}
---
# Quy định nội bộ về phòng chống rửa tiền (tổng hợp)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo. Đây là quy định nội bộ giả lập của một ngân hàng hư cấu, không phải văn bản pháp lý và không dẫn số hiệu hay điều khoản của luật thật. Ba quy định REG-001 đến REG-003 là căn cứ để các typology và quy trình điều tra dẫn tới.

## Nhận biết và thẩm định khách hàng {REG-001}

Quy định này yêu cầu ngân hàng nhận biết khách hàng khi mở tài khoản và cập nhật định kỳ: họ tên, ngày sinh, giấy tờ, địa chỉ, nghề nghiệp và mục đích quan hệ. Với tổ chức, phải xác định chủ sở hữu hưởng lợi.

Khách hàng rủi ro cao, bao gồm người có ảnh hưởng chính trị (PEP), cần thẩm định tăng cường: xác định nguồn tài sản, nguồn tiền và có phê duyệt của cấp quản lý trước khi tiếp tục quan hệ.

Khi nghi ngờ thông tin khách hàng không đúng hoặc nhiều khách hàng có thông tin chung bất thường, ngân hàng phải xác minh lại.

## Giám sát giao dịch và báo cáo giao dịch giá trị lớn {REG-002}

Quy định này yêu cầu giám sát liên tục giao dịch theo các luật có tên và có phiên bản (rule_id, rule_version), mỗi cảnh báo phải có lý do giải thích được và dấu vết kiểm toán.

Giao dịch tiền mặt từ ngưỡng giá trị lớn phải được báo cáo. Ngưỡng này là tham số cấu hình của hệ thống (thresholds.large_cash_vnd); văn bản này không nhắc lại con số. Việc cố ý chia nhỏ giao dịch để né ngưỡng là dấu hiệu đáng ngờ và được giám sát riêng.

Cảnh báo phải được xem xét, ghi kết luận và lưu hồ sơ trong thời hạn lưu trữ tối thiểu theo cấu hình retention. Khi đủ cơ sở nghi ngờ, người có thẩm quyền quyết định báo cáo giao dịch đáng ngờ.

## Rà soát danh sách trừng phạt và PEP {REG-003}

Quy định này yêu cầu rà soát tên khách hàng và bên liên quan với danh sách trừng phạt và danh sách PEP khi mở tài khoản và định kỳ khi danh sách thay đổi.

Mỗi khớp phải được xử lý theo mức độ: khớp mạnh phải được xem xét ngay, khớp một phần cần rà soát thủ công, khớp yếu có thể được loại trừ nhưng phải ghi lý do.

Khớp thật với danh sách trừng phạt phải được chuyển cấp có thẩm quyền ngay lập tức. Mọi quyết định loại trừ được lưu để áp dụng cho lần rà soát sau.
