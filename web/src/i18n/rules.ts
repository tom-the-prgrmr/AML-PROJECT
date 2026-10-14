/**
 * Vietnamese names and descriptions of every rule id the backend can emit. Display only: the
 * API, the audit log and the database keep the English id, and the UI shows that id next to the
 * Vietnamese name so an investigator can still quote it.
 *
 * Sources: `src/aml/dq/rules.py` (RULES), `src/aml/monitoring/rules.py` (RULES),
 * `src/aml/graph/network/rules.py` (NETWORK_RULES), `sql/<backend>/cases/items.sql`
 * (`'SCREENING_' || decision`).
 */
export interface RuleText {
  name: string;
  description: string;
}

export const RULE_TEXT: Record<string, RuleText> = {
  // Data quality - customers
  KYC_OCCUPATION_MISSING: {
    name: "Thiếu nghề nghiệp",
    description: "Trường nghề nghiệp (occupation) để trống.",
  },
  KYC_NATIONALITY_MISSING: {
    name: "Thiếu quốc tịch",
    description: "Trường quốc tịch (nationality) để trống.",
  },
  KYC_ID_FORMAT: {
    name: "Sai định dạng giấy tờ tùy thân",
    description:
      "Số giấy tờ không khớp mẫu của loại giấy tờ (CCCD 12 chữ số, CMND 9 chữ số, hộ chiếu 1 chữ cái + 7 chữ số) hoặc loại giấy tờ không xác định.",
  },
  KYC_DOB_FUTURE: {
    name: "Ngày sinh ở tương lai",
    description: "Ngày sinh nằm sau ngày dữ liệu (as_of).",
  },
  KYC_CCCD_DOB_MISMATCH: {
    name: "CCCD không khớp ngày sinh",
    description:
      "Chữ số thứ 5-6 hoặc chữ số thứ 4 của CCCD không khớp với năm sinh hoặc với thế kỷ sinh và giới tính.",
  },
  // Data quality - transactions
  TXN_DUPLICATE: {
    name: "Giao dịch trùng lặp",
    description:
      "Trùng tài khoản gửi, tài khoản nhận, thời điểm, số tiền và kênh với một giao dịch có mã (txn_id) nhỏ hơn.",
  },
  TXN_VALUE_INVALID: {
    name: "Giá trị giao dịch không hợp lệ",
    description:
      "Số tiền bị thiếu hoặc không dương, kênh bị thiếu hoặc không xác định, hoặc thiếu thời điểm giao dịch.",
  },
  TXN_ACCOUNT_UNKNOWN: {
    name: "Tài khoản không tồn tại",
    description:
      "Tài khoản gửi hoặc nhận nội bộ (không có tiền tố EXT-) không có trong bảng tài khoản.",
  },
  TXN_BEFORE_ACCOUNT_OPEN: {
    name: "Giao dịch trước ngày mở tài khoản",
    description:
      "Giao dịch có ngày trước ngày mở (open_date) của tài khoản gửi hoặc nhận nội bộ.",
  },
  TXN_FEED_STALE: {
    name: "Dữ liệu giao dịch chậm cập nhật",
    description:
      "Giao dịch mới nhất cũ hơn ngày dữ liệu (as_of) trừ đi số ngày trễ cho phép (dq.max_feed_lag_days).",
  },
  // Transaction monitoring
  STRUCTURING: {
    name: "Chia nhỏ tiền mặt dưới ngưỡng",
    description:
      "Nộp tiền mặt nhiều lần với số tiền ngay dưới ngưỡng báo cáo giao dịch tiền mặt giá trị lớn.",
  },
  RAPID_MOVEMENT: {
    name: "Tiền vào rồi chuyển đi nhanh",
    description: "Khoản tiền lớn vào tài khoản rồi được chuyển đi tiếp chỉ trong vài giờ.",
  },
  HIGH_VELOCITY: {
    name: "Tần suất giao dịch cao",
    description:
      "Số giao dịch với đối tác mới nhiều bất thường trong một khoảng thời gian ngắn.",
  },
  FAN_IN: {
    name: "Gom tiền từ nhiều người gửi",
    description: "Nhiều người gửi mới chuyển tiền vào một tài khoản trong vài ngày.",
  },
  FAN_OUT: {
    name: "Phân tán tiền tới nhiều người nhận",
    description: "Một tài khoản chuyển tiền cho nhiều người nhận mới trong vài ngày.",
  },
  DORMANT_REACTIVATION: {
    name: "Tài khoản ngủ đông hoạt động lại",
    description: "Tài khoản im lặng lâu ngày bất ngờ chuyển một khoản tiền lớn.",
  },
  // Network detections
  NET_SHARED_ATTRIBUTE: {
    name: "Cụm khách hàng dùng chung thông tin",
    description:
      "Các khách hàng trong một cụm liên kết với nhau do dùng chung thiết bị, số điện thoại hoặc địa chỉ.",
  },
  NET_CYCLE: {
    name: "Dòng tiền quay vòng",
    description:
      "Tiền rời một tài khoản rồi quay về chính tài khoản đó qua các khách hàng khác trong vài ngày.",
  },
  NET_HUB: {
    name: "Tài khoản trung tâm gom tiền",
    description:
      "Tài khoản nhận tiền từ nhiều khách hàng khác và có chỉ số PageRank cao vượt trội.",
  },
  // Screening: the backend has no description for these two, so the sentences state only what
  // the id itself says (the system decision of the screening pair).
  SCREENING_ALERT: {
    name: "Khớp danh sách theo dõi - mức cảnh báo",
    description:
      "Khách hàng khớp một mục trong danh sách theo dõi và hệ thống sàng lọc xếp cặp này ở mức cảnh báo.",
  },
  SCREENING_REVIEW: {
    name: "Khớp danh sách theo dõi - cần rà soát",
    description:
      "Khách hàng khớp một mục trong danh sách theo dõi và hệ thống sàng lọc xếp cặp này ở mức cần rà soát.",
  },
};

function known(id: string): RuleText | undefined {
  return Object.prototype.hasOwnProperty.call(RULE_TEXT, id) ? RULE_TEXT[id] : undefined;
}

/** Vietnamese name of a rule; an unknown id is returned as is. */
export function ruleName(id: string): string {
  return known(id)?.name ?? id;
}

/** Vietnamese description of a rule; an unknown id gives `fallback` (the API text) or the id. */
export function ruleDescription(id: string, fallback?: string | null): string {
  return known(id)?.description ?? fallback ?? id;
}
