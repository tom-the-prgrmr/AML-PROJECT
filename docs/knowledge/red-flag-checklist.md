---
doc_number: KB-RFC-001
title: Danh mục dấu hiệu đáng ngờ (red flag checklist)
doc_type: CHECKLIST
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: RedFlag, id: RF-017, name: Tài khoản ngủ đông hoạt động lại với số tiền lớn}
  - {label: RedFlag, id: RF-018, name: Tần suất giao dịch cao bất thường với đối tác mới}
---
# Danh mục dấu hiệu đáng ngờ (red flag checklist)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Danh mục liệt kê mười tám dấu hiệu đáng ngờ (red flag) từ RF-001 đến RF-018 để điều tra viên đối chiếu nhanh. Mỗi dấu hiệu được mô tả đầy đủ ở tài liệu typology tương ứng; một dấu hiệu đơn lẻ chưa đủ để kết luận.

## Nhóm chia nhỏ giao dịch tiền mặt {RF-001 RF-002 RF-003 structuring}

RF-001: nhiều lần nộp tiền mặt ngay dưới ngưỡng báo cáo. RF-002: nhiều khoản nộp tiền mặt dồn vào một cửa sổ thời gian ngắn. RF-003: khoản nộp tiền mặt không phù hợp hồ sơ thu nhập của khách hàng.

Luật giám sát liên quan là STRUCTURING; chi tiết xem tài liệu KB-TYP-001.

## Nhóm chuyển tiền nhanh {RF-004 RF-005 RF-006 rapid_movement}

RF-004: tiền vào lớn bị chuyển ra gần hết trong vài giờ. RF-005: số dư cuối ngày gần bằng không dù dòng tiền lớn. RF-006: tài khoản chỉ làm trạm trung chuyển, không có mục đích kinh tế rõ ràng.

Luật giám sát liên quan là RAPID_MOVEMENT; chi tiết xem tài liệu KB-TYP-002.

## Nhóm mạng lưới tài khoản trung gian {RF-007 RF-008 RF-009 RF-010 mule_ring}

RF-007: nhiều người gửi mới cùng chuyển tiền vào một tài khoản. RF-008: một tài khoản chuyển tiền cho nhiều người nhận mới. RF-009: nhiều khách hàng dùng chung thiết bị, số điện thoại hoặc địa chỉ. RF-010: tài khoản gom dòng tiền từ nhiều khách hàng khác.

Các luật liên quan là FAN_IN, FAN_OUT, NET_SHARED_ATTRIBUTE và NET_HUB; chi tiết xem tài liệu KB-TYP-003.

## Nhóm chuyển tiền vòng tròn {RF-011 RF-012 RF-013 round_tripping}

RF-011: tiền rời tài khoản rồi quay lại qua các khách hàng khác trong vài ngày. RF-012: chuỗi chuyển khoản khép kín với số tiền gần bằng nhau. RF-013: giao dịch qua lại không có mục đích kinh tế.

Luật liên quan là NET_CYCLE; chi tiết xem tài liệu KB-TYP-004.

## Nhóm khớp danh sách trừng phạt và PEP {RF-014 RF-015 RF-016 sanctions_hit pep_hit}

RF-014: tên khớp mạnh với danh sách trừng phạt. RF-015: tên khớp một người có ảnh hưởng chính trị. RF-016: thông tin nhận dạng chỉ khớp một phần, cần rà soát thủ công.

Các cảnh báo liên quan có rule_id SCREENING_ALERT và SCREENING_REVIEW; chi tiết xem tài liệu KB-TYP-005.

## Tài khoản ngủ đông hoạt động lại {RF-017}

RF-017: tài khoản không hoạt động trong thời gian dài bỗng nhận hoặc chuyển một khoản tiền lớn. Luật giám sát liên quan là DORMANT_REACTIVATION; khoá cấu hình nằm dưới monitoring.dormant_reactivation (số ngày ngủ đông, cửa sổ giờ và số tiền tối thiểu).

Dấu hiệu này không thuộc typology nào trong bộ tài liệu này; nó thường là tín hiệu đi kèm, ví dụ tài khoản bị chiếm quyền hoặc được kích hoạt lại để làm trung gian. Hãy xem tài khoản có đổi thiết bị, số điện thoại hoặc người đại diện gần đây không.

## Tần suất giao dịch cao bất thường {RF-018}

RF-018: số lượng giao dịch với đối tác mới tăng vọt trong một cửa sổ ngắn. Luật giám sát liên quan là HIGH_VELOCITY; khoá cấu hình nằm dưới monitoring.high_velocity (cửa sổ giờ, số giao dịch tối thiểu và tổng tiền tối thiểu).

Dấu hiệu này cũng không thuộc typology nào; nhiều trường hợp lành tính như đợt bán hàng hay trả lương hàng loạt. Điều tra viên chỉ xem đây là tín hiệu bổ sung khi nó xuất hiện cùng các dấu hiệu khác.
