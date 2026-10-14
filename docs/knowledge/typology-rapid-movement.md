---
doc_number: KB-TYP-002
title: Chuyển tiền nhanh qua tài khoản (rapid movement)
doc_type: TYPOLOGY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Typology, id: rapid_movement, name: Chuyển tiền nhanh qua tài khoản}
  - {label: RedFlag, id: RF-004, name: Tiền vào lớn bị chuyển ra gần hết trong vài giờ}
  - {label: RedFlag, id: RF-005, name: Số dư cuối ngày gần bằng không dù dòng tiền lớn}
  - {label: RedFlag, id: RF-006, name: Tài khoản chỉ làm trạm trung chuyển không có mục đích kinh tế rõ ràng}
relations:
  - {from: rapid_movement, type: HAS_RED_FLAG, to: RF-004}
  - {from: rapid_movement, type: HAS_RED_FLAG, to: RF-005}
  - {from: rapid_movement, type: HAS_RED_FLAG, to: RF-006}
  - {from: rapid_movement, type: INVESTIGATED_BY, to: PROC-001}
  - {from: rapid_movement, type: INVESTIGATED_BY, to: PROC-003}
  - {from: rapid_movement, type: GOVERNED_BY, to: REG-002}
---
# Chuyển tiền nhanh qua tài khoản (rapid movement)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Tài liệu mô tả kiểu hành vi chuyển tiền nhanh (rapid movement): tiền vào một tài khoản rồi bị chuyển đi gần hết trong thời gian rất ngắn.

## Mô tả {rapid_movement}

Chuyển tiền nhanh là khi một khoản tiền lớn vào tài khoản rồi được chuyển ra ngay, thường trong vài giờ, với tỷ lệ gần bằng số tiền đã vào. Tài khoản đóng vai trò trạm trung chuyển thay vì nơi giữ tiền hoặc chi tiêu thật.

Hành vi này thuộc giai đoạn layering của rửa tiền: tạo thêm lớp trung gian để làm đứt dấu vết dòng tiền giữa nguồn và đích cuối.

## Cách hệ thống phát hiện {rapid_movement}

Luật giám sát RAPID_MOVEMENT (rule_id) cộng tổng tiền vào trong một cửa sổ giờ (monitoring.rapid_movement.window_hours) và so với tổng tiền ra sau đó trong cùng cửa sổ.

Cảnh báo được tạo khi tổng tiền vào đạt mức tối thiểu (monitoring.rapid_movement.min_inflow_vnd) và tiền ra chiếm ít nhất một tỷ lệ của tiền vào (monitoring.rapid_movement.min_pass_through_pct). Các giá trị cụ thể nằm trong config.yaml; tài liệu này không chép con số.

Cảnh báo ghi lại tổng tiền vào, tổng tiền ra và các giao dịch bằng chứng. Luật RAPID_MOVEMENT gắn với typology rapid_movement. Hệ thống chỉ xếp hạng cảnh báo, không tự đóng.

## Dấu hiệu nhận biết {RF-004 RF-005 RF-006 rapid_movement}

Dấu hiệu RF-004: một khoản tiền vào lớn bị chuyển ra gần hết trong vài giờ.

Dấu hiệu RF-005: số dư cuối ngày gần bằng không dù dòng tiền qua tài khoản rất lớn.

Dấu hiệu RF-006: tài khoản chỉ làm trạm trung chuyển, không có mục đích kinh tế rõ ràng như chi tiêu, đầu tư hay thanh toán hàng hoá.

Khi các dấu hiệu lặp lại nhiều ngày với cùng nhóm đối tác, mức nghi ngờ tăng lên.

## Hướng điều tra {PROC-001 PROC-003 rapid_movement}

Phân loại cảnh báo theo PROC-001 để biết cảnh báo thuộc luật nào và có cảnh báo khác cùng khách hàng không.

Dùng PROC-003 để lần theo dòng tiền: ai là bên gửi, ai là bên nhận, tiền đi tiếp qua mấy chặng và có quay về nguồn không. Công cụ truy vết dòng tiền (aml trace) và phân tích mạng hỗ trợ bước này.

Ghi nhận kết luận bằng con người; trợ lý chỉ cung cấp bằng chứng và trích dẫn.

## Trường hợp lành tính dễ nhầm {rapid_movement}

Một số hoạt động hợp lệ trông giống chuyển tiền nhanh: công ty thanh toán hộ (nhận tiền khách rồi trả nhà cung cấp), dịch vụ thu hộ chi hộ, hoặc khách hàng nhận tiền bán tài sản rồi trả ngay khoản vay.

Điểm phân biệt là có hợp đồng, hoá đơn hoặc mục đích kinh tế giải thích được, và đối tác lặp lại ổn định thay vì thay đổi liên tục.
