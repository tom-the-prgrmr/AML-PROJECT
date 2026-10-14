# Đối chiếu luật trong app với pháp luật PCRT Việt Nam

Ghi chú tra cứu ngày 2026-10-14. Đây là bảng đối chiếu để tham khảo, không phải ý kiến pháp lý. Nội dung các điều khoản bên dưới được **tóm tắt** từ trang tra cứu, không trích nguyên văn. Trước khi viện dẫn, hãy đối chiếu từng điều với văn bản chính thức.

## Văn bản liên quan

- **Luật Phòng, chống rửa tiền 2022** (số 14/2022/QH15):
  - Đ25: báo cáo giao dịch có giá trị lớn.
  - Đ26: báo cáo giao dịch đáng ngờ.
  - Đ27: dấu hiệu đáng ngờ cơ bản.
  - Đ28: dấu hiệu đáng ngờ trong lĩnh vực ngân hàng (14 khoản).
  - Đ37: thời hạn báo cáo.
- **QĐ 11/2023/QĐ-TTg**: mức giao dịch giá trị lớn phải báo cáo là 400 triệu đồng. Hiệu lực từ 01/12/2023, thay mức 300 triệu của QĐ 20/2013.
- **Thông tư 09/2023/TT-NHNN**: hướng dẫn thi hành Luật. Theo nguồn thứ cấp, thông tư này đã được **Thông tư 27/2025/TT-NHNN** thay thế (hiệu lực 01/11/2025). Thông tin này chưa được kiểm tra trên văn bản gốc.

## Bảng đối chiếu

| Luật trong app | Căn cứ pháp lý | Mức khớp |
|---|---|---|
| `STRUCTURING`: nộp tiền mặt nhiều lần, mỗi lần sát dưới 400 triệu | Đ28 k2 (nhiều giao dịch, mỗi giao dịch sát dưới mức phải báo cáo). Ngưỡng 400 triệu lấy theo Đ25 và QĐ 11/2023 | Mạnh |
| `RAPID_MOVEMENT`: nhận khoản tiền lớn rồi chuyển ra gần hết (≥ 90%) trong 24 giờ | Đ28 k1 (tiền vào ra tài khoản nhanh, doanh số trong ngày lớn nhưng số dư rất nhỏ hoặc bằng 0) | Mạnh |
| `FAN_IN`: nhiều người gửi mới cùng chuyển vào một tài khoản | Đ28 k2 (nhiều khoản nhỏ từ nhiều tài khoản chuyển về một tài khoản trong thời gian ngắn). Đ28 k6 cũng gần | Mạnh |
| `FAN_OUT`: một tài khoản chuyển cho nhiều người nhận mới | Đ28 k2 (tiền được chuyển qua nhiều tài khoản) | Trung bình |
| `HIGH_VELOCITY`: nhiều giao dịch với đối tác mới trong thời gian ngắn | Đ28 k1 (doanh số biến động đột biến) | Trung bình |
| `DORMANT_REACTIVATION`: tài khoản lâu không hoạt động rồi phát sinh số tiền lớn | Đ28 k1 (đột biến) và Đ28 k5 (đột ngột nhận khoản tiền lớn bất thường). Luật không có khái niệm "tài khoản ngủ" | Một phần |
| `NET_CYCLE`: tiền chạy vòng qua nhiều tài khoản | Đ28 k2 (tiền được chuyển qua nhiều tài khoản, tức layering) | Một phần |
| `NET_SHARED_ATTRIBUTE`: nhiều khách hàng dùng chung thiết bị, SĐT hoặc địa chỉ (không xét IP) | Đ28 k13 (dùng tài khoản cá nhân để giao dịch hộ người khác). Đ28 k14 nói về thiết bị hoặc IP thay đổi, IP ở nước ngoài, nên chỉ gần ở phần thiết bị | Một phần |
| `NET_HUB`: tài khoản trung tâm có nhiều dòng tiền đổ về | Không có khoản tương ứng trực tiếp. Gần nhất là Đ28 k2 | Yếu |
| Screening theo danh sách | Đ27 k5–6 (giao dịch theo lệnh của, hoặc có liên hệ với, đối tượng trong Danh sách cảnh báo) | Mạnh |
| DQ: thiếu nghề nghiệp, số giấy tờ sai, … | Đ27 k1 (thông tin nhận biết khách hàng thiếu, sai hoặc mâu thuẫn). Đây là dấu hiệu KYC, không phải luật phát hiện giao dịch | Một phần |

## Dấu hiệu trong luật mà app chưa có

| Điều khoản | Nội dung | Vì sao chưa có |
|---|---|---|
| Đ27 k7 | Giao dịch số tiền lớn không phù hợp với thu nhập hoặc hoạt động kinh doanh | Có thể làm được, vì dữ liệu đã có cột `occupation`. Đây là ứng viên dễ thêm nhất |
| Đ28 k14 | Đăng nhập bằng nhiều thiết bị hoặc IP nước ngoài | Mỗi khách hàng chỉ có một `device_id`/`ip` cố định, chưa có log đăng nhập |
| Đ28 k4 | Mở nhiều tài khoản ở nơi khác nơi cư trú hoặc kinh doanh | Dữ liệu không có địa điểm mở tài khoản |
| Đ28 k6, k7 | Chuyển tiền ra nước ngoài, doanh nghiệp FDI chuyển vốn ra ngay sau khi nhận | Dữ liệu không có giao dịch xuyên biên giới |
| Đ28 k8 | Đổi tiền mệnh giá nhỏ sang mệnh giá lớn | Dữ liệu không có giao dịch đổi tiền |
| Đ37 | Thời hạn báo cáo giao dịch đáng ngờ: 3 ngày làm việc kể từ khi phát sinh, hoặc 1 ngày làm việc kể từ khi phát hiện | App không mô phỏng việc nộp báo cáo |

## Cần kiểm tra

- Mức 400 triệu có thể chỉ áp dụng cho **giao dịch tiền mặt** và được cộng dồn trong ngày. Điều này chưa được xác minh. Nếu đúng, chia nhỏ trong cùng một ngày vẫn bị báo cáo, nên giá trị thực của `STRUCTURING` là bắt việc chia nhỏ trải qua nhiều ngày (cửa sổ 14 ngày).
- Nếu cần dẫn thông tư hướng dẫn, kiểm tra TT 27/2025 thay vì TT 09/2023.

## Nguồn

- [Luật PCRT 2022, caselaw.vn](https://caselaw.vn/van-ban-phap-luat/411476-luat-phong-chong-rua-tien-so-14-2022-qh15-ngay-15-11-2022-cua-quoc-hoi)
- [Điều 28, hethongphapluat.com](https://hethongphapluat.com/luat-phong-chong-rua-tien-2022/dieu-28)
- [Thông tư 09/2023/TT-NHNN, caselaw.vn](https://caselaw.vn/van-ban-phap-luat/413201-thong-tu-so-09-2023-tt-nhnn-ngay-28-07-2023-cua-thong-doc-ngan-hang-nha-nuoc-viet-nam-huong-dan-thuc-hien-luat-phong-chong-rua-tien)
- [Thông tư 27/2025, luatvietan.vn](https://luatvietan.vn/thong-tu-27-2025-tt-nhnn-thay-doi-lon-trong-phong-chong-rua-tien-tai-viet-nam.html)
- [QĐ 11/2023/QĐ-TTg, luatvietnam.vn](https://luatvietnam.vn/tai-chinh/quyet-dinh-11-2023-qd-ttg-muc-giao-dich-gia-tri-lon-phai-bao-cao-251149-d1.html)
