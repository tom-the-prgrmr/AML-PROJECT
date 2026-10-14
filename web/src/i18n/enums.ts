/**
 * Vietnamese labels of the coded values the API returns. Display only: requests, the audit log
 * and the database keep the original values. Every lookup returns the raw value when it has no
 * label (new data is never hidden) and "—" when the value is missing.
 */
import { DASH } from "./format";

export type Labels = Readonly<Record<string, string>>;
export type Lookup = (value: string | null | undefined) => string;

/** Label of `value` in `map`; the raw value when unknown; "—" when missing. */
export function labelOf(map: Labels, value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return DASH;
  return Object.prototype.hasOwnProperty.call(map, value) ? map[value] : value;
}

const lookup =
  (map: Labels): Lookup =>
  (value) =>
    labelOf(map, value);

// --- Cases (src/aml/cases/runner.py, dispositions.py) ---
export const CASE_STATUS_LABELS: Labels = {
  OPEN: "Đang mở",
  REOPENED: "Mở lại",
  CLOSED: "Đã đóng",
};
export const DISPOSITION_LABELS: Labels = {
  SUSPICIOUS: "Đáng ngờ",
  FALSE_POSITIVE: "Báo động giả",
};
export const DISPOSITION_ORIGIN_LABELS: Labels = {
  HUMAN: "Người quyết định",
  SIMULATED: "Mô phỏng",
};
export const ALERT_SOURCE_LABELS: Labels = {
  RULE: "Luật giao dịch",
  NETWORK: "Mạng lưới",
  SCREENING: "Sàng lọc danh sách",
};

// --- Screening (src/aml/screening/, src/aml/datagen/watchlist.py) ---
export const SCREENING_DECISION_LABELS: Labels = {
  ALERT: "Cảnh báo",
  REVIEW: "Cần rà soát",
  AUTO_CLEARED: "Tự động loại",
};
export const REVIEW_DECISION_LABELS: Labels = {
  TRUE_MATCH: "Khớp thật",
  FALSE_MATCH: "Khớp giả",
};
export const LIST_TYPE_LABELS: Labels = {
  PEP: "Người có ảnh hưởng chính trị (PEP)",
  SANCTIONS: "Danh sách trừng phạt",
};
/** `matched_name_type`: PRIMARY, or the alias type of the matched alias. */
export const NAME_TYPE_LABELS: Labels = {
  PRIMARY: "Tên chính",
  AKA: "Bí danh",
  TRANSLITERATION: "Tên phiên âm",
};

// --- Data quality (src/aml/dq/rules.py, runner.py) ---
export const DQ_STATUS_LABELS: Labels = {
  PASS: "Đạt",
  FAIL: "Không đạt",
  NO_DATA: "Không có dữ liệu",
};
export const DQ_DIMENSION_LABELS: Labels = {
  COMPLETENESS: "Đầy đủ",
  VALIDITY: "Hợp lệ",
  UNIQUENESS: "Duy nhất",
  CONSISTENCY: "Nhất quán",
  TIMELINESS: "Kịp thời",
};
export const DQ_SCOPE_LABELS: Labels = {
  ROW: "Dòng",
  TABLE: "Bảng",
};
export const TABLE_LABELS: Labels = {
  customers: "Khách hàng",
  accounts: "Tài khoản",
  transactions: "Giao dịch",
  transfers: "Chuyển khoản",
};

// --- Customers, accounts, transactions (src/aml/datagen/) ---
export const CHANNEL_LABELS: Labels = {
  CASH: "Tiền mặt",
  CARD: "Thẻ",
  EBANKING: "Ngân hàng điện tử",
  INTERNAL_TRANSFER: "Chuyển khoản nội bộ",
  INTERBANK_TRANSFER: "Chuyển khoản liên ngân hàng",
};
export const ACCOUNT_TYPE_LABELS: Labels = {
  CURRENT: "Thanh toán",
  SAVINGS: "Tiết kiệm",
  CARD: "Thẻ",
};
export const KYC_RISK_LABELS: Labels = {
  LOW: "Thấp",
  MEDIUM: "Trung bình",
  HIGH: "Cao",
};
export const ID_TYPE_LABELS: Labels = {
  CCCD: "CCCD",
  CMND: "CMND",
  PASSPORT: "Hộ chiếu",
};
export const GENDER_LABELS: Labels = {
  F: "Nữ",
  M: "Nam",
};
export const DIRECTION_LABELS: Labels = {
  IN: "Vào",
  OUT: "Ra",
};

// --- Users (src/aml/api/identity.py) ---
export const ROLE_LABELS: Labels = {
  analyst: "Chuyên viên",
  supervisor: "Giám sát",
};
export const PII_LABELS: Labels = {
  masked: "Đã che thông tin cá nhân",
  full: "Hiện đầy đủ thông tin cá nhân",
};

// --- Network and trace (src/aml/cases/enrich_network.py, src/aml/graph/) ---
export const NETWORK_FEATURE_LABELS: Labels = {
  in_degree: "Bậc vào",
  out_degree: "Bậc ra",
  in_vnd: "Tiền vào (VND)",
  out_vnd: "Tiền ra (VND)",
  pagerank_ratio: "Tỷ lệ PageRank",
  shared_cluster_id: "Mã cụm dùng chung thông tin",
  shared_cluster_size: "Số khách hàng trong cụm",
  cycle_alerts: "Số cảnh báo quay vòng",
  is_hub: "Là tài khoản trung tâm",
  wcc_size: "Kích thước thành phần liên thông",
  louvain_size: "Kích thước cộng đồng Louvain",
};
/** `enrichment.network.source`: where the network features came from. */
export const NETWORK_SOURCE_LABELS: Labels = {
  networkx: "NetworkX",
  gds: "Neo4j GDS",
  none: "Chưa có",
};
export const GRAPH_NODE_TYPE_LABELS: Labels = {
  customer: "Khách hàng",
  account: "Tài khoản",
  external_account: "Tài khoản ngoài hệ thống",
};
export const TRACE_METHOD_LABELS: Labels = {
  cte_raw: "CTE trên giao dịch gốc",
  cte_edge: "CTE trên cạnh theo ngày (xấp xỉ)",
  pgq: "Đồ thị thuộc tính SQL (Oracle)",
  neo4j: "Neo4j (Cypher)",
};

// --- Benchmark (src/aml/graph/bench/model.py, runner.py) ---
export const BENCH_STATUS_LABELS: Labels = {
  ok: "Thành công",
  skipped: "Bỏ qua",
  error: "Lỗi",
};
/** Keys of a benchmark run's `meta`, top level and nested, in one flat map. */
export const BENCH_META_LABELS: Labels = {
  schema: "Phiên bản kết quả",
  profile: "Bộ dữ liệu",
  backend: "Cơ sở dữ liệu",
  command: "Lệnh chạy",
  started_at: "Bắt đầu lúc",
  total_seconds: "Tổng thời gian (giây)",
  git_commit: "Commit git",
  versions: "Phiên bản phần mềm",
  python: "Python",
  aml: "Bộ công cụ AML",
  driver: "Trình điều khiển CSDL",
  server: "Máy chủ CSDL",
  neo4j_driver: "Trình điều khiển Neo4j",
  machine: "Máy chạy",
  platform: "Hệ điều hành",
  processor: "Bộ xử lý",
  cpu_count: "Số CPU",
  dataset: "Quy mô dữ liệu",
  customers: "Khách hàng",
  accounts: "Tài khoản",
  transactions: "Giao dịch",
  transfers: "Chuyển khoản",
  params: "Tham số đo",
  hops: "Số bước",
  hours: "Số giờ",
  runs: "Số lần đo",
  warmup_runs: "Số lần chạy làm nóng",
  picked: "Tài khoản do hệ thống chọn",
  trace: "Giới hạn truy vết",
  max_paths: "Số đường đi tối đa",
  edge_min_amount_vnd: "Số tiền tối thiểu của cạnh (VND)",
  edge_top_k: "Số cạnh lớn nhất giữ lại",
  read_timeout_seconds: "Thời gian chờ đọc Neo4j (giây)",
  sync: "Đồng bộ Neo4j",
  full_seconds: "Đồng bộ toàn bộ (giây)",
  incremental_seconds: "Đồng bộ gia tăng (giây)",
  lag_after_seconds: "Độ trễ sau đồng bộ (giây)",
};

// --- Memo categories (src/aml/memo/classify.py, store.py) ---
export const MEMO_CATEGORY_LABELS: Labels = {
  salary: "Lương",
  loan_repayment: "Trả nợ vay",
  gambling_like: "Dấu hiệu cá cược",
  crypto_like: "Dấu hiệu tiền mã hoá",
  suspicious_wording: "Lời lẽ đáng ngờ",
  other: "Khác",
};
export const MEMO_METHOD_LABELS: Labels = {
  RULE: "Luật",
  LLM: "Mô hình",
  HUMAN: "Người gán",
  FALLBACK: "Dự phòng",
};

// --- System (config.yaml ui.mock, src/aml/api/errors.py, web/src/api/client.ts) ---
export const MOCK_FLAG_LABELS: Labels = {
  sample: "Panel mẫu",
};
export const ERROR_CODE_LABELS: Labels = {
  not_found: "Không tìm thấy",
  invalid_request: "Yêu cầu không hợp lệ",
  unavailable: "Dịch vụ chưa sẵn sàng",
  not_implemented: "Tính năng chưa có bản thật",
  unknown_user: "Người dùng không tồn tại",
  missing_user: "Thiếu thông tin người dùng",
  internal_error: "Lỗi máy chủ",
  network_error: "Không kết nối được máy chủ",
  unknown_source: "Phản hồi không rõ nguồn dữ liệu",
  method_not_allowed: "Phương thức không được phép",
  forbidden: "Không được phép",
  http_error: "Lỗi HTTP",
  unknown_error: "Lỗi không xác định",
};

export const caseStatusLabel = lookup(CASE_STATUS_LABELS);
export const dispositionLabel = lookup(DISPOSITION_LABELS);
export const dispositionOriginLabel = lookup(DISPOSITION_ORIGIN_LABELS);
export const alertSourceLabel = lookup(ALERT_SOURCE_LABELS);
export const screeningDecisionLabel = lookup(SCREENING_DECISION_LABELS);
export const reviewDecisionLabel = lookup(REVIEW_DECISION_LABELS);
export const listTypeLabel = lookup(LIST_TYPE_LABELS);
export const nameTypeLabel = lookup(NAME_TYPE_LABELS);
export const dqStatusLabel = lookup(DQ_STATUS_LABELS);
export const dqDimensionLabel = lookup(DQ_DIMENSION_LABELS);
export const dqScopeLabel = lookup(DQ_SCOPE_LABELS);
export const tableLabel = lookup(TABLE_LABELS);
export const channelLabel = lookup(CHANNEL_LABELS);
export const accountTypeLabel = lookup(ACCOUNT_TYPE_LABELS);
export const kycRiskLabel = lookup(KYC_RISK_LABELS);
export const idTypeLabel = lookup(ID_TYPE_LABELS);
export const genderLabel = lookup(GENDER_LABELS);
export const directionLabel = lookup(DIRECTION_LABELS);
export const roleLabel = lookup(ROLE_LABELS);
export const piiLabel = lookup(PII_LABELS);
export const networkFeatureLabel = lookup(NETWORK_FEATURE_LABELS);
export const networkSourceLabel = lookup(NETWORK_SOURCE_LABELS);
export const graphNodeTypeLabel = lookup(GRAPH_NODE_TYPE_LABELS);
export const traceMethodLabel = lookup(TRACE_METHOD_LABELS);
export const benchStatusLabel = lookup(BENCH_STATUS_LABELS);
export const benchMetaLabel = lookup(BENCH_META_LABELS);
export const mockFlagLabel = lookup(MOCK_FLAG_LABELS);
export const memoCategoryLabel = lookup(MEMO_CATEGORY_LABELS);
export const memoMethodLabel = lookup(MEMO_METHOD_LABELS);
export const errorCodeLabel = lookup(ERROR_CODE_LABELS);

// --- Case graph and trace panels (src/aml/api/routers/graph.py, src/aml/api/reads/trace.py) ---
/** `type` of a case-graph edge. */
export const GRAPH_EDGE_TYPE_LABELS: Labels = {
  owns: "Sở hữu tài khoản",
  transfer: "Chuyển khoản",
};
/** `meta.graph_source` of the case graph: where its nodes and edges were read from. */
export const GRAPH_SOURCE_LABELS: Labels = {
  sql: "Dữ liệu gốc (SQL)",
  neo4j: "Bản chiếu Neo4j",
};
/** Database engines by their product names (`meta.backend`). */
export const BACKEND_LABELS: Labels = {
  duckdb: "DuckDB",
  oracle: "Oracle",
  neo4j: "Neo4j",
};
export const graphEdgeTypeLabel = lookup(GRAPH_EDGE_TYPE_LABELS);
export const graphSourceLabel = lookup(GRAPH_SOURCE_LABELS);
export const backendLabel = lookup(BACKEND_LABELS);
