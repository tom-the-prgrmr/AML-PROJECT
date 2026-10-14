/*
 * Vietnamese for the fixed English texts the backend sends that are not audit records: the
 * benchmark notes, the reason a benchmark cell or a trace method was skipped, and the warning that
 * exact methods disagree. Each function recognises the exact sentence (or its pattern, with the
 * values carried over) and returns the original text when it does not, so nothing is ever hidden.
 * Audit reasons (alert, case, screening, trace) are NOT translated: they are the record itself.
 */

import { backendLabel, traceMethodLabel } from "./enums";

/** The notes of `src/aml/graph/bench/report.py::NOTES`, in the same order. */
const BENCH_NOTES: Record<string, string> = {
  "Time is `TraceResult.seconds`: the query, fetching the answer into a DataFrame and normalising it (sorting). The freshness check of `neo4j` (`prepare`), the warm-up runs and the audit row are outside the clock.":
    "Thời gian đo là `TraceResult.seconds`: gồm chạy truy vấn, đưa kết quả vào DataFrame và chuẩn hoá (sắp xếp). Bước kiểm tra độ mới của đồ thị `neo4j` (`prepare`), các lần chạy khởi động và việc ghi nhật ký kiểm toán nằm ngoài phép đo.",
  "p95 is taken by linear interpolation between the two nearest ranks (the NumPy default). With fewer than 20 timed runs it is close to the slowest run; min, max and every raw time are in the JSON file.":
    "P95 được tính bằng nội suy tuyến tính giữa hai thứ hạng gần nhất (mặc định của NumPy). Khi có dưới 20 lần đo, P95 gần với lần chậm nhất; giá trị nhỏ nhất, lớn nhất và mọi thời gian gốc đều có trong tệp JSON.",
  "`cte_edge` is an approximation (daily edges, top-K), so its number of paths cannot be compared with the exact methods.":
    "`cte_edge` là phương pháp xấp xỉ (cạnh gộp theo ngày, chỉ giữ top-K), nên số đường đi của nó không so sánh được với các phương pháp chính xác.",
  "Query lines are the non-blank, non-comment lines of the query that ran. For `pgq` they grow with the number of hops (one GRAPH_TABLE block per hop); for `neo4j` one Cypher file serves every hop count.":
    "Số dòng truy vấn là các dòng không trống, không phải chú thích của truy vấn đã chạy. Với `pgq`, số dòng tăng theo số bước (mỗi bước một khối GRAPH_TABLE); với `neo4j`, một tệp Cypher dùng cho mọi số bước.",
  "DuckDB runs in-process; Oracle and Neo4j are reached over the network (local Docker ports). Methods are comparable only within one file: same backend, same data, a graph synced from that backend.":
    "DuckDB chạy ngay trong tiến trình; Oracle và Neo4j được truy cập qua mạng (cổng Docker cục bộ). Chỉ so sánh các phương pháp trong cùng một tệp: cùng cơ sở dữ liệu, cùng dữ liệu, đồ thị đồng bộ từ chính cơ sở dữ liệu đó.",
  "`skipped`: the method cannot run there (wrong backend, service down, graph out of sync). `error`: it ran and failed; the reason is in the note.":
    "“Bỏ qua”: phương pháp không chạy được ở đó (sai cơ sở dữ liệu, dịch vụ không chạy, đồ thị chưa đồng bộ). “Lỗi”: đã chạy nhưng thất bại; lý do nằm ở cột ghi chú.",
  "The account is the heaviest case by time-ordered 2-hop paths when it was picked automatically, not a typical one.":
    "Khi được chọn tự động, tài khoản đo là trường hợp nặng nhất theo số đường đi 2 bước có thứ tự thời gian, không phải một tài khoản điển hình.",
};

export function benchNote(text: string): string {
  return BENCH_NOTES[text] ?? text;
}

/** Each pattern carries its values over into the Vietnamese sentence. */
const REASONS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^not available on (\w+)$/, (m) => `Không chạy được trên ${backendLabel(m[1])}`],
  [
    /^method (\w+) is Oracle only; backend is (\w+)$/,
    (m) => `${traceMethodLabel(m[1])} chỉ chạy trên Oracle; cơ sở dữ liệu hiện tại là ${backendLabel(m[2])}`,
  ],
  [/^oracle not available: (.*)$/s, (m) => `Oracle không truy cập được: ${m[1]}`],
  [/^neo4j not available: (.*)$/s, (m) => `Neo4j không truy cập được: ${m[1]}`],
  [/^graph not synced: run aml graph sync$/, () => "Đồ thị Neo4j chưa được đồng bộ: chạy `aml graph sync`"],
  [
    /^graph was synced from (\w+) but the database is (\w+): run aml graph sync --full$/,
    (m) =>
      `Đồ thị được đồng bộ từ ${backendLabel(m[1])} nhưng cơ sở dữ liệu hiện tại là ${backendLabel(m[2])}: chạy \`aml graph sync --full\``,
  ],
  [
    /^graph is out of sync \((\d+) of (\d+) transfers\): run aml graph sync$/,
    (m) => `Đồ thị chưa đồng bộ (${m[1]} trên ${m[2]} giao dịch chuyển tiền): chạy \`aml graph sync\``,
  ],
];

/** Why a benchmark cell or a trace method was skipped / unavailable. */
export function skipReason(text: string | null | undefined): string {
  if (!text) return "—";
  for (const [pattern, render] of REASONS) {
    const m = text.match(pattern);
    if (m) return render(m);
  }
  return text;
}

/** One line of `path_mismatches`: "<account>, T <h> h, <n> hops: cte_raw 10, neo4j 12". */
export function mismatchLine(text: string): string {
  const m = text.match(/^(.+), T (\d+) h, (\d+) hops: (.+)$/);
  if (!m) return text;
  const counts = m[4]
    .split(", ")
    .map((part) => {
      const [method, n] = part.split(" ");
      return `${traceMethodLabel(method)}: ${n} đường đi`;
    })
    .join("; ");
  return `Tài khoản ${m[1]}, khung ${m[2]} giờ, ${m[3]} bước — ${counts}`;
}
