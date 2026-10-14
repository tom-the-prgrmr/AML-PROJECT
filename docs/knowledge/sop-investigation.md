---
doc_number: KB-SOP-001
title: Quy trình điều tra cảnh báo AML (SOP)
doc_type: SOP
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Procedure, id: PROC-001, name: Tiếp nhận và phân loại cảnh báo}
  - {label: Procedure, id: PROC-002, name: Xác minh danh tính và chủ sở hữu hưởng lợi}
  - {label: Procedure, id: PROC-003, name: Phân tích dòng tiền và đối tác}
  - {label: Procedure, id: PROC-004, name: Xác minh nguồn tiền}
  - {label: Procedure, id: PROC-005, name: Rà soát danh sách trừng phạt và PEP}
  - {label: Procedure, id: PROC-006, name: Ghi nhận kết luận và chuyển cấp xử lý}
relations:
  - {from: PROC-001, type: REQUIRED_BY, to: REG-002}
  - {from: PROC-002, type: REQUIRED_BY, to: REG-001}
  - {from: PROC-003, type: REQUIRED_BY, to: REG-002}
  - {from: PROC-004, type: REQUIRED_BY, to: REG-001}
  - {from: PROC-005, type: REQUIRED_BY, to: REG-003}
  - {from: PROC-006, type: REQUIRED_BY, to: REG-002}
---
# Quy trình điều tra cảnh báo AML (SOP)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Đây là quy trình điều tra mẫu gồm sáu bước, dùng chung cho các typology. Mỗi bước có mã PROC để các tài liệu khác và trợ lý dẫn tới.

## Nguyên tắc chung

Hệ thống giám sát tạo cảnh báo (alert) và gộp chúng thành hồ sơ (case) theo khách hàng. Mô hình chỉ xếp hạng thứ tự xem xét; nó không đóng hồ sơ. Mọi quyết định đóng, mở lại hay chuyển cấp là của người có thẩm quyền và được ghi vào audit_log cùng lý do.

Trợ lý chỉ tìm và trích dẫn bằng chứng. Nó không bao giờ xoá, đóng hay nộp bất cứ thứ gì thay điều tra viên.

## Tiếp nhận và phân loại cảnh báo {PROC-001}

Đọc hồ sơ và danh sách cảnh báo kèm rule_id, thời điểm và lý do của từng cảnh báo. Xác định typology tương ứng, kiểm tra các cảnh báo khác của cùng khách hàng và mức ưu tiên mô hình đã xếp.

Loại ngay các cảnh báo trùng lặp hoặc đã được xử lý trước đó (danh sách good guy, ngủ đông cảnh báo lặp). Ghi lại cảnh báo nào sẽ điều tra tiếp và vì sao.

## Xác minh danh tính và chủ sở hữu hưởng lợi {PROC-002}

Đối chiếu hồ sơ KYC với giấy tờ: họ tên, ngày sinh, số giấy tờ, địa chỉ, thiết bị và số điện thoại. Với khách hàng là tổ chức, xác định người đại diện và chủ sở hữu hưởng lợi cuối cùng.

Kiểm tra các điểm chung với khách hàng khác (cùng thiết bị, điện thoại, địa chỉ) và ghi lại quan hệ đã xác minh được. Với PEP, bước này gồm cả thẩm định tăng cường.

## Phân tích dòng tiền và đối tác {PROC-003}

Dựng lại chuỗi giao dịch quanh cảnh báo: tiền vào từ đâu, ra đi đâu, qua mấy chặng, trong bao lâu. Dùng truy vết dòng tiền và truy vấn đồ thị để xem mạng quan hệ của tài khoản.

So sánh với hành vi thường ngày của khách hàng. Chú ý đối tác mới, đối tác lặp lại, vòng khép kín và đầu mối gom tiền. Mọi kết luận phải dẫn tới mã giao dịch bằng chứng cụ thể.

## Xác minh nguồn tiền {PROC-004}

Yêu cầu khách hàng giải trình mục đích và nguồn gốc các khoản tiền đáng chú ý, kèm chứng từ như hợp đồng, hoá đơn, sao kê hay giấy tờ tài sản.

Đánh giá giải trình có hợp lý với nghề nghiệp, thu nhập và quy mô kinh doanh đã khai không. Giải trình thiếu hoặc mâu thuẫn là dấu hiệu cần chuyển cấp.

## Rà soát danh sách trừng phạt và PEP {PROC-005}

Với cảnh báo screening, so sánh từng thông tin nhận dạng (ngày sinh, quốc tịch, giới tính, số giấy tờ) giữa khách hàng và mục danh sách. Ghi rõ vì sao chấp nhận khớp hoặc loại trừ.

Khớp thật với danh sách trừng phạt phải được chuyển cấp ngay. Khớp PEP cần phê duyệt của cấp quản lý và thẩm định tăng cường.

## Ghi nhận kết luận và chuyển cấp xử lý {PROC-006}

Điều tra viên ghi kết luận (ví dụ báo cáo giao dịch đáng ngờ, đóng vì dương tính giả, hoặc tiếp tục theo dõi) kèm lý do bằng văn bản. Kết luận được lưu và ghi vào audit_log.

Các trường hợp cần báo cáo hay chuyển cấp do người có thẩm quyền thực hiện theo quy định nội bộ. Hệ thống và trợ lý không tự nộp báo cáo.
