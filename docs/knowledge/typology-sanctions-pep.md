---
doc_number: KB-TYP-005
title: Khớp danh sách trừng phạt và người có ảnh hưởng chính trị (sanctions và PEP)
doc_type: TYPOLOGY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Typology, id: sanctions_hit, name: Khớp danh sách trừng phạt}
  - {label: Typology, id: pep_hit, name: Khớp danh sách người có ảnh hưởng chính trị}
  - {label: RedFlag, id: RF-014, name: Tên khách hàng khớp mạnh với một mục trong danh sách trừng phạt}
  - {label: RedFlag, id: RF-015, name: Tên khách hàng khớp một người có ảnh hưởng chính trị}
  - {label: RedFlag, id: RF-016, name: Thông tin nhận dạng chỉ khớp một phần cần rà soát thủ công}
relations:
  - {from: sanctions_hit, type: HAS_RED_FLAG, to: RF-014}
  - {from: sanctions_hit, type: HAS_RED_FLAG, to: RF-016}
  - {from: sanctions_hit, type: INVESTIGATED_BY, to: PROC-001}
  - {from: sanctions_hit, type: INVESTIGATED_BY, to: PROC-005}
  - {from: sanctions_hit, type: GOVERNED_BY, to: REG-003}
  - {from: pep_hit, type: HAS_RED_FLAG, to: RF-015}
  - {from: pep_hit, type: HAS_RED_FLAG, to: RF-016}
  - {from: pep_hit, type: INVESTIGATED_BY, to: PROC-002}
  - {from: pep_hit, type: INVESTIGATED_BY, to: PROC-005}
  - {from: pep_hit, type: GOVERNED_BY, to: REG-001}
  - {from: pep_hit, type: GOVERNED_BY, to: REG-003}
---
# Khớp danh sách trừng phạt và người có ảnh hưởng chính trị (sanctions và PEP)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Danh sách trừng phạt và danh sách PEP trong dự án là dữ liệu giả lập. Tài liệu mô tả hai typology sanctions_hit và pep_hit sinh ra từ việc rà soát tên khách hàng.

## Mô tả {sanctions_hit pep_hit}

Rà soát tên (name screening) so tên khách hàng với một danh sách theo dõi. Khi danh sách là danh sách trừng phạt, một khớp đúng nghĩa là khách hàng có thể là đối tượng bị trừng phạt (typology sanctions_hit). Khi danh sách là PEP, khớp nghĩa là khách hàng có thể là người có ảnh hưởng chính trị hoặc người thân, cần thẩm định tăng cường (typology pep_hit).

Tên tiếng Việt có ít âm tiết và nhiều tên trùng nhau, nên phần lớn các khớp là khớp giả và cần phân biệt bằng ngày sinh, quốc tịch, giới tính hoặc số giấy tờ.

## Cách hệ thống phát hiện {sanctions_hit pep_hit}

Hệ thống rà soát hai tầng. Tầng một tính điểm tên mờ (fuzzy) giữa tên đã chuẩn hoá của khách hàng và mục trong danh sách. Tầng hai điều chỉnh điểm bằng ngày sinh, quốc tịch và giới tính rồi ra quyết định ALERT, REVIEW hoặc AUTO_CLEARED.

Khi đưa vào hồ sơ, quyết định ALERT trở thành cảnh báo có rule_id SCREENING_ALERT, quyết định REVIEW trở thành cảnh báo có rule_id SCREENING_REVIEW. Cảnh báo mang list_type SANCTIONS dẫn tới typology sanctions_hit, list_type PEP dẫn tới pep_hit.

Các khoá cấu hình liên quan: screening.alert_threshold, screening.review_threshold, screening.dob_tolerance_years, screening.dob_clear_years và các khoản giảm điểm do lệch thông tin (screening.dob_gap_discount, screening.nationality_mismatch_discount, screening.gender_mismatch_discount). Tài liệu không chép con số.

## Dấu hiệu nhận biết {RF-014 RF-015 RF-016 sanctions_hit pep_hit}

Dấu hiệu RF-014: tên khách hàng khớp mạnh với một mục trong danh sách trừng phạt, kèm ngày sinh và các thông tin nhận dạng phù hợp.

Dấu hiệu RF-015: tên khách hàng khớp một người có ảnh hưởng chính trị, cần thẩm định tăng cường và phê duyệt của cấp quản lý.

Dấu hiệu RF-016: thông tin nhận dạng chỉ khớp một phần, ví dụ tên giống nhưng ngày sinh lệch nhẹ hoặc thiếu; trường hợp này cần rà soát thủ công thay vì tự kết luận.

## Hướng điều tra {PROC-001 PROC-002 PROC-005 sanctions_hit pep_hit}

Phân loại cảnh báo theo PROC-001. Rà soát danh sách theo PROC-005: so sánh từng thông tin nhận dạng của khách hàng với mục danh sách và ghi lại lý do chấp nhận hay loại khớp.

Với PEP, thực hiện thêm xác minh danh tính và chủ sở hữu hưởng lợi theo PROC-002, và xác định nguồn tài sản.

Quyết định cuối cùng thuộc về điều tra viên hoặc cấp có thẩm quyền; hệ thống không tự đóng cảnh báo screening có khớp thật.

## Trường hợp lành tính dễ nhầm {sanctions_hit pep_hit}

Hai người khác nhau trùng tên là nguyên nhân phổ biến nhất của khớp giả. Tên phổ biến, tên công ty có các từ chung như loại hình doanh nghiệp, hoặc tên khớp với mục danh sách đã được loại trừ trước đó cũng không phải khớp thật.

Dấu hiệu loại trừ: chênh lệch ngày sinh lớn, quốc tịch hoặc giới tính khác nhau, số giấy tờ khác nhau. Ghi lý do loại trừ để lần sau không phải rà lại từ đầu.
