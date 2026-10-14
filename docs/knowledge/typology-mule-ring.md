---
doc_number: KB-TYP-003
title: Mạng lưới tài khoản trung gian (mule ring)
doc_type: TYPOLOGY
version: "1.0"
effective_date: 2026-01-01
language: vi
defines:
  - {label: Typology, id: mule_ring, name: Mạng lưới tài khoản trung gian}
  - {label: RedFlag, id: RF-007, name: Nhiều người gửi mới cùng chuyển tiền vào một tài khoản}
  - {label: RedFlag, id: RF-008, name: Một tài khoản chuyển tiền cho nhiều người nhận mới}
  - {label: RedFlag, id: RF-009, name: Nhiều khách hàng dùng chung thiết bị hoặc số điện thoại hoặc địa chỉ}
  - {label: RedFlag, id: RF-010, name: Tài khoản gom dòng tiền từ nhiều khách hàng khác}
relations:
  - {from: mule_ring, type: HAS_RED_FLAG, to: RF-007}
  - {from: mule_ring, type: HAS_RED_FLAG, to: RF-008}
  - {from: mule_ring, type: HAS_RED_FLAG, to: RF-009}
  - {from: mule_ring, type: HAS_RED_FLAG, to: RF-010}
  - {from: mule_ring, type: INVESTIGATED_BY, to: PROC-001}
  - {from: mule_ring, type: INVESTIGATED_BY, to: PROC-002}
  - {from: mule_ring, type: INVESTIGATED_BY, to: PROC-003}
  - {from: mule_ring, type: GOVERNED_BY, to: REG-001}
  - {from: mule_ring, type: GOVERNED_BY, to: REG-002}
---
# Mạng lưới tài khoản trung gian (mule ring)

Tài liệu tổng hợp (synthetic) do nhóm dự án soạn cho bản demo, không phải văn bản pháp lý và không dẫn điều khoản của luật thật. Tài liệu mô tả mạng lưới tài khoản trung gian (mule ring) và bốn luật hệ thống dùng để phát hiện nó, hai luật theo giao dịch và hai luật theo quan hệ mạng.

## Mô tả {mule_ring}

Mule ring là một nhóm tài khoản (mule account) được dùng để nhận rồi chuyển tiền thay cho kẻ đứng sau. Chủ tài khoản có thể biết hoặc không biết mình đang bị lợi dụng. Dòng tiền thường tập trung từ nhiều nguồn về một vài tài khoản, hoặc phân tán từ một tài khoản ra nhiều nơi.

Các thành viên của nhóm hay có điểm chung trong hồ sơ như cùng thiết bị, cùng số điện thoại hoặc cùng địa chỉ, vì chúng được mở và điều khiển bởi cùng một nhóm người.

## Cách hệ thống phát hiện {mule_ring}

Hai luật giám sát giao dịch: FAN_IN phát hiện nhiều người gửi mới cùng chuyển tiền vào một tài khoản, và FAN_OUT phát hiện một tài khoản chuyển tiền cho nhiều người nhận mới. Cả hai đọc ngưỡng từ monitoring.fan_in_out (cửa sổ ngày, số đối tác tối thiểu, tổng tiền tối thiểu), và khái niệm "mới" theo monitoring.known_counterparty_days.

Hai luật mạng: NET_SHARED_ATTRIBUTE tìm cụm khách hàng cùng dùng chung thiết bị, số điện thoại hoặc địa chỉ (network.shared_attributes.min_customers và network.shared_attributes.max_customers_per_value để bỏ qua giá trị dùng chung quá phổ biến). NET_HUB tìm tài khoản gom tiền từ nhiều khách hàng khác với PageRank cao bất thường (các khoá network.hubs.min_in_degree, network.hubs.min_pagerank_ratio, network.hubs.min_inflow_vnd).

Cả bốn luật FAN_IN, FAN_OUT, NET_SHARED_ATTRIBUTE và NET_HUB gắn với typology mule_ring. Tài liệu không chép con số ngưỡng; hãy xem config.yaml.

## Dấu hiệu nhận biết {RF-007 RF-008 RF-009 RF-010 mule_ring}

Dấu hiệu RF-007: nhiều người gửi mới cùng chuyển tiền vào một tài khoản trong thời gian ngắn.

Dấu hiệu RF-008: một tài khoản chuyển tiền cho nhiều người nhận mới trong thời gian ngắn.

Dấu hiệu RF-009: nhiều khách hàng dùng chung thiết bị, số điện thoại hoặc địa chỉ mà không có quan hệ gia đình hay công việc giải thích được.

Dấu hiệu RF-010: một tài khoản gom dòng tiền từ nhiều khách hàng khác, đóng vai trò đầu mối (hub) của mạng.

## Hướng điều tra {PROC-001 PROC-002 PROC-003 mule_ring}

Phân loại cảnh báo theo PROC-001 và gộp các cảnh báo cùng khách hàng thành một hồ sơ.

Xác minh danh tính và các thông tin liên hệ chung theo PROC-002: ai là chủ thật của tài khoản, các khách hàng chung thiết bị hay địa chỉ có quan hệ gì với nhau.

Phân tích dòng tiền và mạng quan hệ theo PROC-003: tiền đi từ đâu đến đâu, đầu mối nằm ở đâu, nhóm có khép kín hay không. Truy vấn đồ thị giúp xem cả cụm một lần.

## Trường hợp lành tính dễ nhầm {mule_ring}

Hộ gia đình dùng chung điện thoại hoặc địa chỉ, ký túc xá hoặc nhà trọ chung địa chỉ, và công ty chi lương cho nhiều nhân viên đều tạo ra cụm giống mule ring. Tương tự, một cửa hàng nhận tiền từ nhiều khách hoặc một quỹ từ thiện nhận quyên góp cũng là đầu mối hợp lệ.

Điểm phân biệt: tiền đến có mục đích rõ ràng, người gửi không phải toàn người mới, và tiền không bị chuyển đi hết ngay.
