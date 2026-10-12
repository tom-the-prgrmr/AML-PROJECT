---
id: neo4j-queries
status: approved
approved_by: pthieu
---

# Phase 6b-i — Truy vấn điều tra Cypher: trace bản thứ tư (method `neo4j`), vòng 3–5, thuộc tính dùng chung, fan-in / fan-out, `aml graph query`

## Bối cảnh
Phần "Cypher queries" của Phase 6 trong PROJECT_BRIEF.md (mục 7). 6a (`specs/neo4j-sync.md`) đã dựng projection chỉ đọc
trong Neo4j cùng đường đọc có guard (`run_read`, `run_read_file`). Phần 6b được người dùng tách đôi (2026-10-12):
**6b-i (spec này)** là sáu file `.cypher` điều tra chạy qua `run_read_file` — fund-flow trace đăng ký làm method
`neo4j` trong registry của 5b (cùng tập dòng với `cte_raw`), vòng tiền dài 3–5, giá trị thuộc tính dùng chung, cụm
quanh một khách hàng, fan-in, fan-out — cùng timeout cho đường đọc và phép kiểm "đồ thị có khớp nguồn không";
**6b-ii** (`specs/neo4j-gds.md`) là GDS và việc ghi đặc trưng về hệ thống gốc, xây trên spec này; 6c là benchmark
`aml bench`, chỉ cần 6b-i. Người dùng: investigator chạy `aml trace --method neo4j` và `aml graph query`; 6c gọi
`trace(..., method="neo4j")` như ba method của 5b; người phỏng vấn xem cùng một câu hỏi viết bằng SQL và Cypher. Mọi
truy vấn chạy trong session `READ_ACCESS` và chỉ trả kết quả điều tra: **không ghi gì vào Neo4j, không sinh alert,
không đóng alert, không chấm điểm ưu tiên**.

### Hiện trạng đã kiểm (2026-10-12, seed 42)
Đo bằng script tạm ngoài repo trên **Neo4j 5.26.31 Community thật** (driver Python 6.4.0, heap tối đa 1 GB); Cypher nằm
trong file `.cypher` tạm, được tách bằng `split_statements` và kiểm bằng `assert_read_only` của repo, chạy trong
session `READ_ACCESS` với timeout phía server. Các bộ MINI và TINY được sync vào Neo4j bằng `run_sync(..., full=True)`
của 6a để lấy số ghim cho AC; sau khi đo, đồ thị dev đã được trả về bộ `small` bằng `uv run aml graph sync --full`
(run 7, `in_sync=True`). Trên Oracle chỉ chạy `SELECT`.
- **Dịch vụ**: Oracle UP (23.26.3, đang chứa TINY); Neo4j UP (`bolt://localhost:7687`, 5.26.31 Community); Ollama DOWN.
- **Trace bằng Cypher — ba cách viết đã thử** (`small`, tài khoản `A5461833942` có 190 chuyển khoản đi; trung vị 5 lần,
  mili giây; `cte_raw` chạy trên DuckDB; mọi ô đều cho **đúng cùng frame** với `cte_raw` sau `normalise`):

  | T (giờ) | hop | số dòng | `cte_raw` | (A) 6 khối cố định `UNION ALL` | (B) từng hop bằng `CALL (…) { }` | (C) quantified path pattern |
  |---|---|---|---|---|---|---|
  | 72 | 2 / 4 / 6 | 632 / 658 / 658 | 28 / 45 / 47 | 41 / 51 / 85 | 44 / 44 / 42 | 894 / 883 / 853 (1 lần) |
  | 168 | 2 / 4 / 6 | 1249 / 1424 / 1429 | 27 / 46 / 73 | 70 / 98 / 125 | 71 / 79 / 83 | 15 382 / 15 301 / 16 870 (1 lần) |
  | 720 | 2 / 4 / 6 | 4289 / 10 955 / 22 394 | 34 / 79 / 148 | 218 / 579 / 1437 | 221 / 587 / 1206 | quá 30 giây ở cả ba mức |

  - Số dòng code (không tính dòng trống và comment): (C) 17, (B) 58, (A) 90.
  - (C) dùng `(()-[r:TRANSFERRED_TO]->() WHERE r.ts > e1.ts AND r.ts <= e1.ts + duration({hours: $hours})){0,5}`:
    vị từ **trong** quantifier chỉ thấy phần tử của vòng lặp hiện tại và biến đã gắn trước đó (`e1`), nên cắt được cửa
    sổ T nhưng **không** diễn đạt được "hop sau phải sau hop trước" lẫn "không lặp tài khoản" — hai điều kiện đó phải
    lọc sau khi đã liệt kê mọi walk. Hệ quả: 15–17 giây ở T = 168 bất kể số hop, và một lần chạy ở T = 720 **không
    xong sau 18 phút** (đã phải dừng tiến trình khách). Đây là bẫy bùng nổ path: tài khoản xuất phát có 190 cạnh ra
    và 131 path 2 hop quay về chính nó, nên walk không có thứ tự đi qua nó nhiều lần.
  - Biên của quantifier **không nhận tham số** (`{1,$n}` → `Neo.ClientError.Statement.SyntaxError`), `*1..$n` cũng
    vậy; path mode `ACYCLIC` không có ở 5.26. Vì thế (A) và (B) viết sẵn 6 tầng và mỗi tầng tự tắt bằng điều kiện
    `$hops >= k` — không cần Python cắt file như `pgq.sql` của 5b.
  - (B) trùng khít `cte_raw` ở mọi ca đã thử: 21 ca `small` (`A5461833942` với T 24 / 72 / 168 / 720 và `EXT-000001`
    với T 72 / 168 / 720, mỗi T ở 2 / 4 / 6 hop), 10 ca TINY (4, 2, 3, 4, 104, 41, 120, 20, 65, 120 dòng), 10 ca
    MINI-T (9, 10, 3, 2, 9, 8, 0, 0, 7, 1 dòng) và 3 ca MINI-G (8, 4, 3 dòng).
  - `LIMIT $row_limit` cắt đúng (1001 dòng trên 22 394, 0,24 giây).
- **Vòng tiền bằng Cypher** (quantified path pattern `{2,5}` sau hop đầu, cùng ngữ nghĩa với `NET_CYCLE` của 5c): với
  mặc định (sàn 50 triệu, tỉ lệ 0,70, 168 giờ, dài 3–5) `small` cho 15 vòng (8 vòng dài 3, 7 vòng dài 4) — **đúng 15
  alert `NET_CYCLE`**, tập `txn_id` của từng vòng trùng evidence của từng alert, trung vị 0,12 giây; TINY 2 / 2;
  MINI-CYC 3 vòng = 3 `instances` của 2 alert. **Bỏ sàn số tiền** thì truy vấn không xong trong 120 giây (NetworkX
  của 5c: 13 239 bước, 0,2 giây) — sàn số tiền là điều kiện để bản Cypher chạy được.
- **Fan-in / fan-out bằng Cypher** (số đối tác khác nhau trong cửa sổ 7 ngày tính từ từng chuyển khoản, ≥ 8 đối tác và
  ≥ 100 triệu; không có bộ lọc "đối tác đã quen" và "giai đoạn khởi động" của 5a): `small` fan-in 7 tài khoản = 5
  collector + 2 tài khoản nền, **chứa đủ 5 alert `FAN_IN`**; fan-out 25 tài khoản = 20 source + 5 employer payroll,
  **chứa đủ 20 alert `FAN_OUT`**; trung vị 2,75 và 2,83 giây. TINY: fan-in 1 (= `FAN_IN`), fan-out 5 (4 `FAN_OUT` +
  employer `A3906301972`).
- **Thuộc tính dùng chung bằng Cypher**: `small` có 278 giá trị do 2–50 khách hàng cùng mang (268 địa chỉ, 5 thiết bị,
  5 điện thoại; nhiều nhất 10 khách hàng) — đúng số nút giá trị trong đồ thị liên kết của 5c; 0,02 giây. Cụm quanh
  một khách hàng bằng `ANY SHORTEST` trên mẫu lặp `Customer → giá trị ← Customer`: 5 cụm ring của `small` cho 23 / 27 /
  22 / 20 / 12 khách hàng (= 5c), xa nhất 3 bước, dưới 0,01 giây; TINY 29 khách hàng (15 ở bước 1, 13 ở bước 2).
- **Guard `guard/v1` của 6a đủ cho 6b-i** (gọi `assert_read_only` thật với `neo4j.read_procedures` hiện có): cả sáu
  statement — kể cả `trace.cypher` với 5 tầng `CALL (…) { }` và `fan_*.cypher` với `CALL (a, e) { }` — **qua guard
  không cần sửa gì**. Việc sửa guard (`guard/v2`) chỉ cần cho GDS và thuộc 6b-ii.
- **Chi phí ngoài truy vấn**: `open_driver` 48–54 mili giây mỗi lần; đọc `SyncState` + đếm `TRANSFERRED_TO` trong
  Neo4j 6–11 mili giây (lần đầu 95); đếm giao dịch hai phía ở DuckDB 4–9 mili giây.
- **Timeout**: `neo4j.unit_of_work(timeout=...)` trên `execute_read` dừng truy vấn phía server với mã
  `Neo.ClientError.Transaction.TransactionTimedOutClientConfiguration` (đã thử 0,5 / 30 / 120 giây), sau đó
  `SHOW TRANSACTIONS` không còn giao dịch nào. Không đặt timeout thì truy vấn vẫn chạy trên server sau khi tiến trình
  khách hết giờ.
- **Code sẵn có**: `TraceMethod` / `register_method` / `trace()` của 5b (`seconds` bao quanh `chosen.run`); `METHODS`
  có 3 method và `tests/graph/test_config_sql.py` khẳng định `list(METHODS) == ["cte_raw", "cte_edge", "pgq"]`;
  `count_query_lines` bỏ dòng trống và dòng `--`; `load_statements` đã bỏ dòng `//`. `run_read` chưa có timeout.
  `read_state`, `source_stats` của 6a dùng lại được. `aml graph` hiện có `sync`, `status`.
- **Chưa đo**: mọi thứ trên profile `dense` và `large`; trace Cypher với nguồn là Oracle (chỉ đo nguồn DuckDB); output
  và exit code của CLI; chuỗi `reason` và thông điệp lỗi (chưa có code).

### Interface đề xuất (để test, 6b-ii và 6c gọi trực tiếp)
```python
# src/aml/common/config.py
class Neo4jConfig(BaseModel):
    ...
    read_timeout_seconds: float  # timeout phía server của mọi truy vấn trên đường đọc; > 0


class GraphQueryConfig(BaseModel):
    max_rows: int  # run_query: quá số dòng này -> QueryError, không cắt bớt âm thầm; >= 1


class Settings(BaseModel):
    ...
    graph_queries: GraphQueryConfig


# src/aml/graph/model.py  (5b; chỉ thêm, không đổi cái đã có)
class TraceUnavailableError(TraceError): ...  # dịch vụ tắt hoặc đồ thị lệch nguồn


@dataclass(frozen=True)
class TraceMethod:
    name: str
    backends: frozenset[str]
    exact: bool
    run: Callable[[Database, Settings, TraceRequest], pd.DataFrame]
    query_text: Callable[[str, TraceRequest], str]
    uses_filters: bool = False
    prepare: Callable[[Database, Settings], None] | None = None  # chạy trước khi bấm giờ `seconds`


# src/aml/graph/neo4j/client.py
class QueryTimeoutError(GraphError): ...


def run_read(
    driver: neo4j.Driver,
    settings: Settings,
    cypher: str,
    params: Mapping[str, Any] | None = None,
    *,
    audit_db: Database | None = None,
    actor: str | None = None,
    timeout: float | None = None,  # None -> settings.neo4j.read_timeout_seconds
) -> pd.DataFrame: ...
def run_read_file(
    driver: neo4j.Driver,
    settings: Settings,
    name: str,
    params: Mapping[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> pd.DataFrame: ...


# src/aml/graph/neo4j/session.py
class StaleGraphError(GraphError): ...


def shared_driver(
    settings: Settings,
) -> neo4j.Driver: ...  # một driver cho mỗi (uri, user, database), đóng khi thoát
def check_fresh(
    state: tuple[datetime | None, str] | None,  # (watermark, source_backend) của SyncState
    backend: str,
    graph_transfers: int,
    source_transfers: int,
) -> None: ...  # thuần Python; raise StaleGraphError
def require_fresh(driver: neo4j.Driver, db: Database, settings: Settings) -> None: ...


# src/aml/graph/neo4j/trace.py
TRACE_FILE = "queries/trace.cypher"
NEO4J_METHOD: TraceMethod  # name="neo4j", backends={"oracle", "duckdb"}, exact=True, có prepare


# src/aml/graph/neo4j/queries.py
QUERY_NAMES = ("cycles", "shared_attributes", "shared_cluster", "fan_in", "fan_out")
QUERY_COLUMNS: dict[str, list[str]] = {
    "cycles": ["length", "path", "step_path", "first_ts", "last_ts", "first_vnd", "last_vnd"],
    "shared_attributes": ["kind", "key", "customers", "customer_ids"],
    "shared_cluster": ["customer", "distance", "via", "accounts"],
    "fan_in": [
        "account_id",
        "window_start",
        "window_end",
        "counterparties",
        "transfers",
        "total_vnd",
    ],
    "fan_out": [
        "account_id",
        "window_start",
        "window_end",
        "counterparties",
        "transfers",
        "total_vnd",
    ],
}


class QueryError(GraphError): ...  # tên truy vấn / tham số không hợp lệ, hoặc quá max_rows


@dataclass(frozen=True)
class QueryResult:
    name: str
    params: dict[str, Any]  # đúng dict đã gửi sang Neo4j
    rows: pd.DataFrame  # cột = QUERY_COLUMNS[name], thứ tự do ORDER BY của file
    n_rows: int
    seconds: float
    query_lines: int


def query_params(
    name: str,
    settings: Settings,
    *,
    account: str | None = None,
    customer: str | None = None,
    as_of: date | None = None,
) -> dict[str, Any]: ...  # thuần Python: ngưỡng lấy từ config, raise QueryError khi sai
def run_query(
    db: Database,
    settings: Settings,
    name: str,
    *,
    account: str | None = None,
    customer: str | None = None,
    as_of: date | None = None,
    actor: str | None = None,
    record_audit: bool = True,
) -> QueryResult: ...
```
- `config.yaml`: mục `neo4j` thêm `read_timeout_seconds: 60`; mục mới `graph_queries: {max_rows: 10000}`.
  `neo4j.read_procedures` **không đổi**. Ngưỡng nghiệp vụ dùng lại mục có sẵn: `trace.*`, `network.cycles.*`,
  `network.shared_attributes.max_customers_per_value`, `monitoring.fan_in_out.*`.
- File Cypher mới dưới `src/aml/graph/neo4j/cypher/queries/`: `trace.cypher`, `cycles.cypher`,
  `shared_attributes.cypher`, `shared_cluster.cypher`, `fan_in.cypher`, `fan_out.cypher`. Mỗi file đúng một statement,
  mọi giá trị qua `$tham_số`. `WRITE_PREFIXES` và guard **không đổi**.
- `aml.graph.trace`: gọi `register_method(NEO4J_METHOD)` sau `pgq`; `trace()` gọi `chosen.prepare(db, settings)` (nếu
  có) sau khi kiểm đầu vào và **trước** khi bấm giờ.
- CLI: `aml trace --method` nhận thêm `neo4j`; nhóm `aml graph` thêm `aml graph query NAME [--account ID] [--customer
  ID] [--as-of YYYY-MM-DD] [--limit 20]`. Không đụng `aml bench`, `aml network`, `aml graph sync`, `aml graph status`.
- Tài liệu `docs/neo4j-queries.md`: từng truy vấn và khác biệt ngữ nghĩa với 5a / 5c, vì sao trace không viết bằng
  quantified path pattern (kèm số đo), `read_timeout_seconds`, và ba thông điệp `graph not synced` / `synced from` /
  `out of sync` cùng cách sửa.
- **Sửa kéo theo ở phần đã duyệt — là một phần của 6b-i**: (1) `src/aml/graph/model.py` của 5b: thêm
  `TraceUnavailableError` và trường `prepare` (chỉ thêm); (2) `tests/graph/test_config_sql.py`: danh sách `METHODS`
  thành `["cte_raw", "cte_edge", "pgq", "neo4j"]`, `backends` và `exact` thêm phần tử thứ tư; `specs/fund-flow-trace.md`
  AC1 thêm ghi chú dẫn về spec này.

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **Đường đọc** (`run_read`, `run_read_file`): thêm `timeout` (giây; mặc định `neo4j.read_timeout_seconds`), áp bằng
  timeout giao dịch của driver trên `execute_read`. Lỗi của server có mã chứa `TransactionTimedOut` →
  `QueryTimeoutError` chứa `query exceeded <n> s`. Guard, allowlist và session `READ_ACCESS` giữ nguyên như 6a.
- **Kiểm đồ thị trước khi dùng** (`check_fresh`, theo đúng thứ tự):
  1. `state is None` → `StaleGraphError("graph not synced: run aml graph sync")`;
  2. `state[1] != backend` → `graph was synced from <state[1]> but the database is <backend>: run aml graph sync --full`;
  3. `graph_transfers != source_transfers` → `graph is out of sync (<graph_transfers> of <source_transfers> transfers): run aml graph sync`.
  - `require_fresh` đọc `SyncState` (`read_state`), đếm `TRANSFERRED_TO` trong Neo4j và lấy `source_stats(db).transfers`.
    Trace và `run_query` gọi nó trước khi chạy (6b-ii gọi lại cho GDS); không lần nào tự sync.
- **Method `neo4j` của trace** (`exact = True`, `backends = {"oracle", "duckdb"}`, `uses_filters = False`):
  - Ngữ nghĩa là **đúng ngữ nghĩa chuẩn của 5b** (`cte_raw`): thứ tự thời gian chặt, cửa sổ T neo vào hop đầu (biên
    trên bao gồm), `since` trên hop đầu, tiền tố không lặp tài khoản, hop cuối rơi vào tài khoản đã qua được trả về
    với `is_cycle = True` và không mở rộng tiếp, đi xuyên qua `EXT-`, mỗi tiền tố là một dòng. Cột trả về =
    `PATH_COLUMNS`, đi qua `normalise` của 5b nên cùng kiểu và cùng thứ tự sắp xếp.
  - `queries/trace.cypher` viết theo cách (B): `MATCH` hop đầu từ `(:Account {account_id: $account})`, rồi 5 tầng
    `CALL (…) { RETURN dòng hiện có UNION ALL … MATCH hop kế … }`; tầng k chỉ mở rộng dòng chưa đóng chu trình, đang
    dài đúng k − 1 và khi `$hops >= k`; kết thúc bằng `LIMIT $row_limit`. Tham số: `account`, `hops`, `hours`,
    `since`, `row_limit` (= `trace.max_paths + 1`). File không dùng quantified path pattern, không dùng APOC.
  - `prepare`: lấy `shared_driver` rồi `require_fresh`; `ServiceUnavailableError` → `TraceUnavailableError` chứa
    `neo4j not available`; `StaleGraphError` → `TraceUnavailableError` với cùng thông điệp. Kiểm đầu vào của 5b
    (`hops`, `hours`, `account_id`) vẫn chạy trước và không mở kết nối nào.
  - `query_text(backend, request)` = statement của file (đã bỏ dòng `//`), **giống nhau với mọi `hops`**.
  - Audit như 5b: 1 dòng `TRACED`, `version='trace/neo4j'`, `details.backend` = backend của `db`.
- **Năm truy vấn điều tra** (`run_query`; tham số do `query_params` dựng từ config; `cutoff` = 00:00:00 ngày `as_of +
  1`, `as_of` mặc định `settings.data.reference_date`; `row_limit` = `graph_queries.max_rows + 1`):

  | tên | tham số gửi đi | nhận `account` / `customer` | sắp xếp |
  |---|---|---|---|
  | `cycles` | `min_length`, `max_length`, `window_hours`, `min_amount`, `min_amount_ratio` (từ `network.cycles`), `cutoff`, `account`, `row_limit` | `account` tuỳ chọn | `first_ts`, `step_path` |
  | `shared_attributes` | `max_customers_per_value`, `customer`, `row_limit` | `customer` tuỳ chọn | `customers` giảm dần, `kind`, `key` |
  | `shared_cluster` | `max_customers_per_value`, `customer`, `row_limit` | `customer` **bắt buộc** | `distance`, `customer` |
  | `fan_in`, `fan_out` | `window_days`, `min_counterparties`, `min_total_vnd` (từ `monitoring.fan_in_out`), `cutoff`, `account`, `row_limit` | `account` tuỳ chọn | `counterparties` giảm dần, `account_id` |

  - `cycles`: mỗi dòng là **một vòng** (không gộp thành đợt như alert của 5c) theo đúng định nghĩa `NET_CYCLE`: các
    tài khoản đều có trong `accounts` (`is_external = false`), đôi một khác nhau và thuộc các `Customer` khác nhau;
    mọi chuyển khoản `>= min_amount`, `ts` tăng chặt, trước `cutoff`, chặng cuối `<` chặng đầu + `window_hours`; số
    tiền nhỏ nhất `>= min_amount_ratio ×` lớn nhất; chặng đầu là chặng sớm nhất nên mỗi vòng ra đúng một lần. `path` =
    các tài khoản từ người gửi chặng đầu nối bằng `>`; `step_path` = các `txn_id` nối bằng `>`. `account` khác null →
    chỉ giữ vòng có tài khoản đó.
  - `shared_attributes`: mỗi dòng là một node `Device` / `Phone` / `Address` có từ 2 tới `max_customers_per_value`
    khách hàng; `kind` = `device` / `phone` / `address`, `key` = khoá băm của 6a, `customer_ids` tăng dần. `customer`
    khác null → chỉ giữ giá trị mà khách hàng đó mang.
  - `shared_cluster`: mọi khách hàng tới được từ `customer` qua chuỗi giá trị dùng chung (chỉ đi qua giá trị có ≤
    `max_customers_per_value` khách hàng), mỗi người một đường ngắn nhất; `distance` = số giá trị trên đường, `via` =
    loại của từng giá trị theo thứ tự, `accounts` = số tài khoản người đó sở hữu. Không gồm chính `customer`.
  - `fan_in` / `fan_out`: với mỗi tài khoản trong `accounts` và mỗi chuyển khoản vào (ra) của nó làm mốc, đếm trong
    `[ts mốc, ts mốc + window_days)` và trước `cutoff`: số đối tác khác nhau (kể cả `EXT-`), số chuyển khoản, tổng
    tiền; giữ mốc có `counterparties >= min_counterparties` và `total_vnd >= min_total_vnd`; mỗi tài khoản trả **một
    dòng** là mốc có nhiều đối tác nhất (hoà: tổng tiền lớn hơn, rồi `ts`, rồi `txn_id`). **Không** có bộ lọc "đối tác
    đã quen" và "giai đoạn khởi động" của 5a → kết quả là tập cha của tài khoản có alert `FAN_IN` / `FAN_OUT`.
  - Lỗi (`QueryError`, không mở kết nối): tên ngoài `QUERY_NAMES` (thông điệp liệt kê 5 tên); `shared_cluster` thiếu
    `customer`; truyền `account` cho `shared_*` hoặc `customer` cho `cycles` / `fan_*` (`does not take`). Kết quả
    nhiều hơn `max_rows` dòng → `QueryError` chứa `more than <max_rows> rows`.
  - Audit (khi `record_audit`): 1 dòng `module='graph'`, `entity_type='graph_query'`, `entity_id=<tên>`,
    `decision='QUERIED'`, `version='query/v1'`, `actor` = tham số hoặc `audit.system_actor`, `reason` =
    `{tên} on the Neo4j projection: {n} row(s)`, `details` = `{name, params, rows}` (`cutoff` dạng ISO). Lần gọi bị
    lỗi không ghi gì.
- **CLI**:
  - `aml trace --method neo4j`: như các method khác; `TraceUnavailableError` → stderr, exit code 2. `--method all`:
    method raise `TraceUnavailableError` in `method=neo4j skipped: <thông điệp>` rồi chạy tiếp (exit 0).
  - `aml graph query NAME`: in `query=<tên> rows=<n> seconds=<s> query_lines=<n>`, một dòng tên cột, rồi tối đa
    `--limit` dòng (các ô cách nhau bằng hai dấu cách, danh sách nối bằng dấu phẩy). `QueryError` → stderr, exit code
    2; `StaleGraphError` / `QueryTimeoutError` / `GraphError` khác → stderr, exit code 1; Neo4j không kết nối được →
    stderr chứa `neo4j not available`, exit code 1.

## Tiêu chí nghiệm thu
<!-- MINI-T = DuckDB rỗng (`duck`) sau `apply_schema`, chèn 14 giao dịch MINI của specs/fund-flow-trace.md (`MINI_ROWS`
của tests/graph/helpers.py; M05, M14 là CASH), thêm 1 khách hàng `C-A` (mọi thuộc tính null), 1 tài khoản (`A`, `C-A`,
CURRENT), er_golden (`C-A` -> `G-C-A`), rồi `refresh_acct_edge_daily`.
MINI-G = như specs/neo4j-sync.md (MINI-SHR của 5c cộng T08, T09). MINI-CYC, MINI-HUB = `load_cyc` / `load_hub` của
tests/network/helpers.py (specs/network-detections.md) rồi `refresh_acct_edge_daily`.
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` rồi `run_er` (`tiny_er`). `settings` =
`load_settings(environ={"DB_BACKEND": "duckdb"})` trừ khi nói khác; test [neo4j] dùng thêm `.env` để có mật khẩu
(`neo_settings`). OFFLINE = thêm `AML__NEO4J__URI=bolt://127.0.0.1:1`. "Đã sync" = `run_sync(db, settings, full=True)`
của 6a trên Neo4j vừa wipe (fixture `neo`). S11 = dict 11 khoá như 6a. Test có nhãn [neo4j] dùng @pytest.mark.neo4j,
[oracle] dùng @pytest.mark.oracle (tự skip khi dịch vụ không chạy) và được phép xoá sạch projection dev. Các AC không
nhãn chạy ở chế độ DuckDB-only và không cần Neo4j. -->
- AC1: Given `config.yaml`, thư mục `src/aml/graph/neo4j/cypher/`, `docs/` của repo và module `aml.graph.trace` (không cần dịch vụ nào), When `load_settings(environ={})`, gọi `load_statements`, `assert_read_only`, `query_params` và đọc `METHODS`, Then `settings.neo4j.read_timeout_seconds == 60`, `settings.graph_queries.max_rows == 10000` và `settings.neo4j.read_procedures` vẫn bằng đúng 7 tên của 6a; `load_settings(environ={"AML__NEO4J__READ_TIMEOUT_SECONDS": "0"})` raise `pydantic.ValidationError` chứa `read_timeout_seconds must be > 0` và `load_settings(environ={"AML__GRAPH_QUERIES__MAX_ROWS": "0"})` raise `pydantic.ValidationError` chứa `max_rows must be >= 1`; thư mục `cypher/queries/` có đúng 6 file `trace.cypher`, `cycles.cypher`, `shared_attributes.cypher`, `shared_cluster.cypher`, `fan_in.cypher`, `fan_out.cypher`, mỗi file cho đúng 1 statement, statement nào cũng chứa `$row_limit`, không chứa `apoc.`, không chứa `CALL {`, và `assert_read_only(statement, allowed_procedures=settings.neo4j.read_procedures)` không raise; statement của `trace.cypher` chứa `$account`, `$hops`, `$hours`, `$since`, chứa đúng 5 lần `CALL (` và không chứa chuỗi `){`; statement của `cycles.cypher` chứa `{2,5}`; `list(METHODS) == ["cte_raw", "cte_edge", "pgq", "neo4j"]`, `METHODS["neo4j"].backends == frozenset({"oracle", "duckdb"})`, `METHODS["neo4j"].exact is True`, `METHODS["neo4j"].uses_filters is False`, `METHODS["neo4j"].prepare is not None` và ba method còn lại có `prepare is None`; `METHODS["neo4j"].query_text("duckdb", TraceRequest("A", 2, 24))` bằng đúng `query_text("oracle", TraceRequest("A9999999999", 6, 720))`, bằng `load_statements("queries/trace.cypher")[0]` và không chứa `A9999999999`; `issubclass(TraceUnavailableError, TraceError)`; `QUERY_NAMES == ("cycles", "shared_attributes", "shared_cluster", "fan_in", "fan_out")`; `query_params("cycles", settings)` bằng đúng `{"min_length": 3, "max_length": 5, "window_hours": 168, "min_amount": 50000000, "min_amount_ratio": 0.7, "cutoff": datetime(2026, 7, 1, 0, 0, 0), "account": None, "row_limit": 10001}`; `query_params("fan_in", settings, account="A1", as_of=date(2026, 3, 3))` bằng đúng `{"window_days": 7, "min_counterparties": 8, "min_total_vnd": 100000000, "cutoff": datetime(2026, 3, 4, 0, 0, 0), "account": "A1", "row_limit": 10001}`; `query_params("shared_cluster", settings, customer="G-C01")` bằng đúng `{"max_customers_per_value": 50, "customer": "G-C01", "row_limit": 10001}`; `query_params("nope", settings)` raise `QueryError` chứa `cycles, shared_attributes, shared_cluster, fan_in, fan_out`, `query_params("shared_cluster", settings)` raise `QueryError` chứa `customer`, `query_params("shared_attributes", settings, account="A1")` và `query_params("cycles", settings, customer="G-C01")` đều raise `QueryError` chứa `does not take`; và `docs/neo4j-queries.md` tồn tại, chứa các chuỗi `quantified path pattern`, `read_timeout_seconds` và `out of sync`.
- AC2: Given hàm `check_fresh`, MINI-T trong DuckDB và `tiny_env` (không có Neo4j: mọi `settings` và lệnh CLI dùng OFFLINE), When kiểm đồ thị và gọi trace / truy vấn, Then `check_fresh(None, "duckdb", 0, 0)` raise `StaleGraphError` (lớp con của `GraphError`) chứa `graph not synced: run aml graph sync`; `check_fresh((datetime(2026, 3, 2, 10, 0, 1), "oracle"), "duckdb", 12, 12)` raise `StaleGraphError` chứa `graph was synced from oracle but the database is duckdb` và `--full`; `check_fresh((datetime(2026, 3, 2, 10, 0, 1), "duckdb"), "duckdb", 12, 13)` raise `StaleGraphError` chứa `graph is out of sync (12 of 13 transfers)`; `check_fresh((datetime(2026, 3, 2, 10, 0, 1), "duckdb"), "duckdb", 12, 12)` trả `None`; `trace(duck, s, "A", method="neo4j", hops=4, hours=24)` raise `TraceUnavailableError` chứa `neo4j not available`; `trace(duck, s, "A", method="neo4j", hops=7)` raise `TraceError` chứa `hops` và không phải `TraceUnavailableError`; `trace(duck, s, "A", method="bfs")` raise `TraceError` chứa `cte_raw, cte_edge, pgq, neo4j`; `run_query(duck, s, "nope")` raise `QueryError`; `run_query(duck, s, "cycles")` raise `ServiceUnavailableError`; sau các lời gọi đó `audit_log` không có dòng `module='graph'` nào và `trace(duck, s, "A", hops=4, hours=24)` (method mặc định `cte_raw`) vẫn trả 9 dòng; và với `tiny_env` đã `aml load`: `aml trace --account A8201784530 --hops 4 --hours 168 --method all` exit code 0, stdout có đúng một dòng tổng kết chứa `method=cte_raw`, đúng một dòng chứa `method=cte_edge`, một dòng chứa `method=pgq skipped: Oracle only` và một dòng bắt đầu bằng `method=neo4j skipped: neo4j not available`; `aml trace --account A8201784530 --method neo4j` exit code 2 với stderr chứa `neo4j not available`; `aml graph query cycles` exit code 1 với stderr chứa `neo4j not available`; `aml graph query nope` exit code 2 với stderr chứa `shared_cluster`; `aml graph query shared_cluster` (không có `--customer`) exit code 2 với stderr chứa `customer`; `aml graph --help` exit code 0 với stdout chứa `sync`, `status` và `query`; và `aml bench` vẫn exit code 1 với stderr chứa `Phase 6`.
- AC3: [neo4j] Given MINI-T đã sync (`graph == S11(1, 10, 0, 0, 0, 1, 0, 0, 0, 12, 12)`), When gọi `trace(duck, settings, "A", method="neo4j", hops=4, hours=24, actor="analyst01")` và các biến thể, Then `paths` có cột đúng bằng `PATH_COLUMNS` và đúng 9 dòng theo thứ tự (`hop`, `path`, `step_path`, `amount_vnd`, `is_cycle`): (1, `A>A`, `M01`, 5000000, True), (1, `A>B`, `M03`, 100000000, False), (2, `A>B>C`, `M03>M06`, 90000000, False), (3, `A>B>C>A`, `M03>M06>M08`, 80000000, True), (3, `A>B>C>B`, `M03>M06>M07`, 10000000, True), (3, `A>B>C>D`, `M03>M06>M11`, 70000000, False), (3, `A>B>C>EXT-000001`, `M03>M06>M09`, 20000000, False), (4, `A>B>C>D>F`, `M03>M06>M11>M12`, 60000000, False), (4, `A>B>C>EXT-000001>K`, `M03>M06>M09>M10`, 15000000, False); dòng `A>B>C>D>F` có `first_ts = 2026-03-01 10:00:00` và `last_ts = 2026-03-02 10:00:00`; `n_paths = 9`, `n_cycles = 3`, `n_accounts = 6`, `method = "neo4j"`, `backend = "duckdb"`, `query_lines > 0`; `hops=4, hours=25` trả 10 dòng (thêm `A>B>C>D>G`), `hops=2, hours=24` trả 3 dòng, `hops=1` trả 2 dòng, `hops=6, hours=24` trả 9 dòng, `since=datetime(2026, 3, 1, 10, 0, 0)` trả 8 dòng, `since=datetime(2026, 3, 1, 10, 0, 1)` trả 0 dòng, `trace(duck, settings, "ZZZ", method="neo4j", hops=3, hours=24)` trả `paths` rỗng với cột đúng bằng `PATH_COLUMNS`, `trace(duck, settings, "C", method="neo4j", hops=3, hours=24)` trả 7 dòng và `trace(duck, settings, "EXT-000001", method="neo4j", hops=2, hours=24)` trả 1 dòng; với mỗi ca trong 10 ca trên, `paths` của `method="neo4j"` bằng `paths` của `method="cte_raw"` theo `pd.testing.assert_frame_equal`; `audit_log` có dòng `module='graph'`, `decision='TRACED'`, `version='trace/neo4j'`, `entity_id='A'`, `actor='analyst01'` với `details.method = "neo4j"`, `details.backend = "duckdb"`, `details.paths = 9`, `details.cycles = 3`, còn lời gọi với `record_audit=False` không thêm dòng nào; Given `load_settings` có thêm `AML__TRACE__MAX_PATHS=8`, When gọi `trace(duck, s, "A", method="neo4j", hops=4, hours=24)`, Then raise `TraceError` chứa `more than 8 paths`; When chèn thêm giao dịch (`M15`, 2026-03-03 09:00:00, `K`, `A`, 1000000) vào DuckDB rồi `refresh_acct_edge_daily` mà không sync, Then `trace(duck, settings, "A", method="neo4j", hops=4, hours=24)` raise `TraceUnavailableError` chứa `graph is out of sync (12 of 13 transfers)` trong khi `method="cte_raw"` vẫn chạy; sau `run_sync(duck, settings)` thì lời gọi `neo4j` lại chạy và bằng `cte_raw`; và Given Neo4j vừa wipe (chưa sync), When gọi `trace(duck, settings, "A", method="neo4j")`, Then raise `TraceUnavailableError` chứa `graph not synced`.
- AC4: [neo4j] Given TINY trong DuckDB đã sync (`graph == S11(273, 1314, 264, 267, 265, 532, 279, 273, 273, 3651, 3575)`), When gọi `trace` với `method="neo4j"` và `method="cte_raw"` trên cùng (X, hops, hours), Then hai `paths` bằng nhau theo `pd.testing.assert_frame_equal` ở cả 9 ca với số dòng lần lượt: (`A8201784530`, 4, 168) 4 dòng, (`A8201784530`, 4, 72) 2, (`A8201784530`, 3, 168) 3, (`A4879560749`, 2, 24) 4, (`A2582841008`, 4, 168) 104, (`A1037369383`, 6, 168) 41, (`A3906301972`, 2, 24) 120, (`A3906301972`, 2, 24, `since=datetime(2026, 6, 1)`) 20, (`A1037369383`, 6, 720) 65; ca (`A8201784530`, 4, 168) có dòng cuối `path = "A8201784530>A3312263346>A9950029109>A1070944972>A8201784530"`, `step_path = "T0000002197>T0000002246>T0000002299>T0000002327"`, `amount_vnd = 399475000`, `last_ts = 2026-03-27 00:11:51`, `is_cycle = True`, `n_cycles = 1`, `n_accounts = 3`; ca (`A2582841008`, 4, 168) có `n_accounts = 24`, `n_cycles = 0`; ca (`A1037369383`, 6, 168) có `n_cycles = 4` và ca (`A1037369383`, 6, 720) có `n_cycles = 16`; `query_lines` của `neo4j` ở `hops=2` bằng ở `hops=6`; Given `tiny_env` đã `aml load`, `aml er`, `aml graph sync --full`, When chạy `aml trace --account A8201784530 --hops 4 --hours 168 --method neo4j`, Then exit code 0, stdout có một dòng chứa `method=neo4j`, `backend=duckdb`, `account=A8201784530`, `hops=4`, `hours=168`, `paths=4`, `accounts=3`, `cycles=1` và một dòng chứa `A8201784530>A3312263346>A9950029109>A1070944972>A8201784530` cùng `CYCLE`; `aml trace --account A8201784530 --hops 4 --hours 168 --method all` exit code 0 với ba dòng tổng kết `method=cte_raw`, `method=cte_edge`, `method=neo4j` (dòng `neo4j` chứa `paths=4`) và một dòng `method=pgq skipped: Oracle only`; còn [oracle] [neo4j] Given TINY nạp vào Oracle (`load_parquet`, `run_er`, `apply_security`; skip với thông điệp nêu tên biến nếu thiếu `ORACLE_SYS_PASSWORD` hoặc `ORACLE_DEMO_PASSWORD`) và `run_sync(oracle, oracle_settings, full=True)`, When gọi `trace` trên kết nối Oracle, Then với 5 ca (`A8201784530`, 4, 168), (`A8201784530`, 4, 72), (`A1037369383`, 6, 168), (`A2582841008`, 4, 168), (`A3906301972`, 2, 24) `paths` của `neo4j`, `cte_raw` và `pgq` bằng nhau từng dòng (4, 2, 41, 104, 120 dòng; `first_ts` / `last_ts` so ở độ phân giải giây) và `TraceResult.backend == "oracle"`, trong khi `trace(duck, settings, "A8201784530", method="neo4j")` trên DuckDB raise `TraceUnavailableError` chứa `graph was synced from oracle but the database is duckdb`.
- AC5: [neo4j] Given lần lượt MINI-CYC, MINI-G và MINI-HUB đã sync, When gọi `run_query` và `run_read`, Then **MINI-CYC**: `run_query(duck, settings, "cycles", actor="analyst01")` trả `rows` có cột đúng bằng `QUERY_COLUMNS["cycles"]` và đúng 3 dòng theo thứ tự (`length`, `path`, `step_path`, `first_vnd`, `last_vnd`): (3, `B1>B2>B3`, `Y01>Y02>Y03`, 100000000, 90000000), (3, `B1>B2>B3`, `Y01>Y02D>Y03`, 100000000, 90000000), (3, `B2>B3>B1`, `Y11>Y12>Y13`, 80000000, 80000000), dòng đầu có `first_ts = 2026-03-01 10:00:00` và `last_ts = 2026-03-03 10:00:00` (kiểu `datetime`), `n_rows = 3`, `query_lines > 0`; không dòng nào có `path` bắt đầu bằng `D`, `F`, `G`, `L` hay `M` (sai thứ tự thời gian, chỉ 2 chặng, cùng chủ, cùng giây, đi qua `EXT-`); với `AML__NETWORK__CYCLES__WINDOW_HOURS=169` trả 4 dòng (thêm `E1>E2>E3`), với `AML__NETWORK__CYCLES__MIN_AMOUNT_RATIO=0.69` trả 4 dòng (thêm `H1>H2>H3`), với `AML__NETWORK__CYCLES__MIN_AMOUNT_VND=49999000` trả 4 dòng (thêm `I1>I2>I3`), với `AML__NETWORK__CYCLES__MAX_LENGTH=6` trả 4 dòng (thêm `J1>J2>J3>J4>J5>J6` có `length = 6`), với `AML__NETWORK__CYCLES__MIN_LENGTH=4` trả 0 dòng; `account="B2"` trả 3 dòng, `account="G1"` trả 0 dòng, `as_of=date(2026, 3, 2)` trả 0 dòng (Y03 nằm sau cutoff); `audit_log` có dòng `module='graph'`, `entity_type='graph_query'`, `entity_id='cycles'`, `decision='QUERIED'`, `version='query/v1'`, `actor='analyst01'`, `details.rows = 3`, `details.params.window_hours = 168`, `reason` bằng đúng `cycles on the Neo4j projection: 3 row(s)`, còn `record_audit=False` không thêm dòng; với `AML__GRAPH_QUERIES__MAX_ROWS=2`, `run_query(duck, s, "cycles")` raise `QueryError` chứa `more than 2 rows` và không thêm dòng audit; **MINI-G**: `run_query(duck, settings, "shared_attributes")` trả đúng 9 dòng, dòng đầu là (`phone`, `842dd8fe262d43a0`, 6, [`G-C14`, `G-C15`, `G-C16`, `G-C17`, `G-C18`, `G-C19`]), 8 dòng còn lại đều có `customers = 2` theo thứ tự `kind` rồi `key` (3 dòng `address`, 3 dòng `device`, 2 dòng `phone`), trong đó có (`address`, `01dabfcfc5ec16dc`, [`G-C01`, `G-C04`]), (`device`, `9780efe92205e69d`, [`G-C01`, `G-C03`]) và (`phone`, `1582642d9e86c0cf`, [`G-C01`, `G-C02`]); `customer="G-C01"` trả đúng 3 dòng đó; với `AML__NETWORK__SHARED_ATTRIBUTES__MAX_CUSTOMERS_PER_VALUE=5` trả 8 dòng (mất dòng `phone` 6 khách hàng); `run_query(duck, settings, "shared_cluster", customer="G-C01")` trả đúng 4 dòng theo thứ tự (`customer`, `distance`, `via`, `accounts`): (`G-C02`, 1, [`phone`], 1), (`G-C03`, 1, [`device`], 1), (`G-C04`, 1, [`address`], 1), (`G-C05`, 2, [`address`, `device`], 1); `customer="G-C05"` trả 4 dòng, trong đó (`G-C04`, 1, [`device`], 1), (`G-C01`, 2, [`device`, `address`], 2) và hai dòng `G-C02`, `G-C03` có `distance = 3`; `customer="G-C06"` trả 3 dòng `G-C09`, `G-C10`, `G-C11` đều `distance = 1`; `customer="G-C14"` trả 5 dòng và với `MAX_CUSTOMERS_PER_VALUE=5` trả 0 dòng; `customer="G-C20"` và `customer="G-NOPE"` trả 0 dòng, không raise; không ô nào của hai kết quả chứa `0901000001`, `DEV-R` hay `Lê Lợi`; **MINI-HUB**: `run_query(duck, settings, "fan_in")` trả đúng 4 dòng theo thứ tự (`account_id`, `counterparties`, `transfers`, `total_vnd`): (`P0`, 11, 12, 720000000), (`W0`, 10, 10, 200000000), (`L0`, 9, 9, 180000000), (`R0`, 9, 9, 180000000), dòng `P0` có `window_start = 2026-03-01 01:00:00` và `window_end = 2026-03-01 13:00:00`; không có `Q0` (tổng 99 990 000 dưới 100 triệu) và với `AML__MONITORING__FAN_IN_OUT__MIN_TOTAL_VND=0` thì có thêm (`Q0`, 10, 10, 99990000); với `AML__MONITORING__FAN_IN_OUT__MIN_COUNTERPARTIES=10` trả đúng 2 dòng `P0`, `W0`; `account="P0"` trả 1 dòng, `account="S01"` trả 0 dòng; `as_of=date(2026, 3, 3)` trả đúng 2 dòng `P0`, `R0`; `run_query(duck, settings, "fan_out")` trả 0 dòng với cột đúng bằng `QUERY_COLUMNS["fan_out"]`; và `run_read(driver, settings, "UNWIND range(1, 2000000000) AS i RETURN count(i) AS n", timeout=0.5)` raise `QueryTimeoutError` (lớp con của `GraphError`) chứa `query exceeded 0.5 s`, sau đó (MINI-HUB vẫn đang sync) `run_read(driver, settings, "MATCH (a:Account) RETURN count(a) AS n")` vẫn trả 55.
- AC6: [neo4j] Given TINY trong DuckDB đã sync, đã `run_monitoring(duck, settings)` và `detections = detect_network(duck, settings)`, When gọi năm truy vấn và so với 5a / 5c, Then `run_query(duck, settings, "cycles")` trả đúng 2 dòng: (4, `A8201784530>A3312263346>A9950029109>A1070944972`, `T0000002197>T0000002246>T0000002299>T0000002327`, `first_ts` 2026-03-22 15:00:00, `last_ts` 2026-03-27 00:11:51, 456916000, 399475000) và (4, `A9059982551>A4750305205>A7799247681>A7641423153`, `T0000002277>T0000002283>T0000002332>T0000002400`, 2026-03-25 09:00:00, 2026-03-29 07:14:22, 394196000, 364863000), và tập {tập `txn_id` của từng dòng} bằng đúng tập {`txn_ids` của từng alert `NET_CYCLE`} trong `detections` (2 alert); `account="A3312263346"` trả 1 dòng và `account="A0000000000"` trả 0 dòng; `run_query(duck, settings, "shared_attributes")` trả đúng 4 dòng theo thứ tự (`kind`, `key`, `customers`): (`device`, `7fa855e04f72697f`, 16), (`address`, `fbe8ded33cfd1ddf`, 8), (`phone`, `387a8bacf21702c0`, 7), (`address`, `7d05ac1a241d4789`, 2); `run_query(duck, settings, "shared_cluster", customer="G-CIF00000002")` trả 28 dòng (15 dòng `distance = 1`, 13 dòng `distance = 2`) và tập `customer` cộng `G-CIF00000002` có 29 phần tử, bằng đúng tập golden customer của các CIF trong `details.cifs` của alert `SHARED-CIF00000002` (`details.customers = 29`); `run_query(duck, settings, "fan_in")` trả đúng 1 dòng (`A4937939209`, `window_start` 2026-04-13 09:28:12, `window_end` 2026-04-17 23:16:36, 31, 31, 2930380000) — đúng tài khoản, cửa sổ, số giao dịch và số tiền của alert `FAN_IN` trong `alerts_current`; `run_query(duck, settings, "fan_out")` trả đúng 5 dòng theo thứ tự (`account_id`, `counterparties`, `total_vnd`): (`A9075004254`, 24, 933113000), (`A5040436031`, 22, 721737000), (`A2582841008`, 21, 751347000), (`A2697723835`, 20, 601193000), (`A3906301972`, 20, 493277000), tập `subject_id` của 4 alert `FAN_OUT` trong `alerts_current` là tập con của tập `account_id` đó, và tài khoản thừa duy nhất là `A3906301972` (employer payroll, `window_start` 2026-01-05 08:05:00 nằm trong giai đoạn khởi động của 5a); `run_query(duck, settings, "fan_out", account="A2582841008")` trả đúng 1 dòng (`A2582841008`, `window_start` 2026-04-13 02:50:10, `window_end` 2026-04-15 18:06:40, 21, 21, 751347000) và `run_query(duck, settings, "fan_in", account="A2582841008")` trả 0 dòng; số dòng `alerts` và `nx_account_features` trong DuckDB không đổi sau các lời gọi trên, và mỗi lời gọi `run_query` thành công làm `audit_log` tăng đúng 1 dòng `decision='QUERIED'` có `entity_id` bằng tên truy vấn; và Given `tiny_env` đã `aml load`, `aml er`, `aml graph sync --full`, When chạy `aml graph query cycles`, Then exit code 0, stdout có một dòng chứa `query=cycles` và `rows=2`, một dòng chứa đủ 7 tên cột của `QUERY_COLUMNS["cycles"]` và một dòng chứa `T0000002197>T0000002246>T0000002299>T0000002327`; `aml graph query shared_cluster --customer G-CIF00000002 --limit 3` exit code 0, in `rows=28` và đúng 3 dòng dữ liệu; `aml graph query fan_out --account A2582841008` in `rows=1`.

## Ngoài phạm vi
- **6b-ii** (`specs/neo4j-gds.md`): GDS (WCC, Louvain, PageRank, degree), đồ thị in-memory, config `gds`, allowlist
  `gds.procedures`, tham số `procedures` của `run_read`, guard `guard/v2`, bảng `gds_runs` / `gds_account_features`,
  DDL `150`, ghim file jar GDS trong `docker-compose.yml`, `aml graph gds`, `docs/neo4j-gds.md`. Danh sách **mọi** cụm
  thuộc tính dùng chung (thành phần liên thông) cũng thuộc 6b-ii.
- **6c**: `aml bench`, chạy nhiều lần, warm cache, median / p95, profile `dense`, bảng và biểu đồ, kết luận "khi nào
  SQL đủ". 6b-i chỉ bảo đảm `trace(..., method="neo4j", record_audit=False)` dùng được như ba method kia và `seconds` /
  `query_lines` có nghĩa giống nhau.
- **Alert từ Neo4j**: không ghi `alerts`, `alert_accounts`, `alert_evidence`, `monitoring_runs`; không gộp đợt, không
  `reason` cho từng vòng / cụm (người dùng xác nhận 2026-10-12: Phase 6b không sinh alert).
- Bản trace bằng quantified path pattern như một method đăng ký (chỉ mô tả trong tài liệu kèm số đo); trace ngược,
  trace hai chiều, đường ngắn nhất giữa hai tài khoản; ngưỡng số tiền / top-K cho method `neo4j`; trace trên `SENT_TO`.
- Tái hiện chính xác `FAN_IN` / `FAN_OUT` của 5a (đối tác đã quen, giai đoạn khởi động, gộp đợt) và `STRUCTURING`,
  `RAPID_MOVEMENT`, `HIGH_VELOCITY`, `DORMANT_REACTIVATION` bằng Cypher; vòng tiền không có sàn số tiền.
- Truy vấn Cypher tự do từ CLI (`aml graph query` chỉ chạy 5 tên đã đăng ký); Text2Cypher, GraphRAG (Phase 8); API
  FastAPI và UI đồ thị (Phase 9); xuất kết quả ra file; vẽ đồ thị.
- Tự sync khi đồ thị lệch; khoá chống chạy truy vấn đồng thời với `aml graph sync`; timeout riêng cho từng truy vấn.
- Sửa guard, `WRITE_PREFIXES`, `neo4j.read_procedures`, `docker-compose.yml`, DDL, quyền Oracle.
- Đo trên profile `dense` / `large`; ghi số liệu vào README (làm ở bước demo của phase, từ lần chạy thật của code đã
  hiện thực trên `small`, rồi chép vào `docs/neo4j-queries.md`).

## Giả định
- **Đã đo trên Neo4j 5.26.31 Community + driver 6.4.0** (mục Hiện trạng): mọi số dòng, giá trị và phép so khớp của
  AC3, AC4 (phần DuckDB), AC5, AC6 — bằng prototype ngoài repo dùng đúng các câu Cypher mô tả ở mục Thiết kế, không
  phải bằng code của repo; timeout phía server; sáu statement qua guard `guard/v1`. Phiên bản Neo4j khác có thể cho
  kết quả khác — image đã ghim ở 6a.
- **Suy ra từ thiết kế, chưa đo** (chưa có code): chuỗi `reason`, thông điệp lỗi, việc mỗi `run_query` ghi 1 dòng
  audit, định dạng stdout / stderr và exit code của CLI, thông điệp `ValidationError`, toàn bộ AC2.
- **Chưa kiểm trên Oracle** (chỉ chạy `SELECT`): phần [oracle] của AC4. 6a đã đo: sync TINY từ Oracle và từ DuckDB cho
  cùng ảnh đồ thị, và 5b đã đo `cte_raw` = `pgq` trên Oracle — phần [oracle] dựa vào hai điều đó.
- Thời gian trong mục Hiện trạng là số đo trên máy dev (trung vị 5 lần hoặc một lần như ghi rõ), `cte_raw` đo trên
  DuckDB chứ không phải Oracle; chúng chỉ để chọn cách viết, **không phải** kết quả benchmark — số chính thức do 6c
  đo. AC chỉ cam kết cho các bộ MINI và TINY seed 42; số của `small` không phải cam kết.
- `METHODS["neo4j"]` cho cùng tập dòng với `cte_raw` **chỉ khi đồ thị khớp nguồn**; `require_fresh` kiểm bằng backend
  nguồn và số chuyển khoản — hai bộ dữ liệu khác nhau có cùng backend và cùng số chuyển khoản, hoặc giao dịch bị sửa
  tại chỗ, không bị phát hiện (giới hạn đã nêu ở 6a).
- Truy vấn chạy trên ảnh chụp của lần sync gần nhất; `as_of` chỉ cắt chuyển khoản (thuộc tính khách hàng và `OWNS`
  không có lịch sử), như 5c. Kết quả tất định với cùng dữ liệu; `settings.seed` không tham gia.
- `fan_in` / `fan_out` và `cycles` trả kết quả điều tra, không phải alert: `fan_*` chứa cả employer payroll và tài
  khoản nền mà 5a đã loại; người dùng đọc kèm alert của 5a.
- Test [neo4j] xoá sạch projection trong Neo4j dev và để lại projection của dữ liệu test; sau `pytest` có Neo4j,
  người dùng chạy lại `aml graph sync --full` (như 6a). Test [oracle] nạp lại TINY vào `aml_owner`.
- Không có `aml graph sync` chạy trong lúc trace / truy vấn. `shared_driver` giữ một kết nối cho cả tiến trình.
- Tên file `.cypher`, tên cột và năm tên truy vấn là cấu trúc (hằng trong code); ngưỡng nghiệp vụ, timeout và số
  dòng tối đa là cấu hình. `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có.

## Câu hỏi mở
- [x] Q1. Một spec hay tách đôi? — đề xuất mặc định: tách thành `neo4j-queries` (trace `neo4j`, năm truy vấn, timeout, kiểm đồ thị, `aml graph query`) và `neo4j-gds` (guard `v2`, GDS, bảng `gds_*`, ghim jar, `aml graph gds`). Lý do: 6c chỉ cần phần truy vấn; phần GDS mang toàn bộ rủi ro hạ tầng. — Trả lời: tách đôi; spec này là 6b-i (2026-10-12).
- [x] Q2. Cách viết nào của trace Cypher được đăng ký làm method `neo4j`? — đề xuất mặc định: **(B) từng hop bằng `CALL (…) { }`** (58 dòng). Lý do: trùng khít `cte_raw` ở mọi ca đã thử và ngang (A) về thời gian (1206 so với 1437 mili giây ở ca nặng nhất), ngắn hơn (A) 90 dòng; (C) quantified path pattern gọn nhất (17 dòng) nhưng mất 15–17 giây ở T = 168 và không xong sau 18 phút ở T = 720 vì không cắt được thứ tự thời gian trong lúc mở rộng. Hệ quả: bản "tự nhiên nhất" của Cypher không dùng được cho câu hỏi này — tài liệu ghi lại kèm số đo, 6c có thể dẫn lại. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q3. Số hop đưa vào truy vấn thế nào khi biên quantifier không nhận tham số? — đề xuất mặc định: file viết sẵn 6 tầng, mỗi tầng có điều kiện `$hops >= k`; Python không cắt hay ghép chuỗi Cypher. Hệ quả: `query_lines` của `neo4j` là hằng số theo `hops` (khác `pgq` tăng theo N) — 6c cần ghi chú khi so "số dòng code". — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q4. Đồ thị chưa sync, sync từ backend khác, hoặc lệch số chuyển khoản thì trace / truy vấn / GDS làm gì? — đề xuất mặc định: **từ chối** với thông điệp chỉ cách sửa (`graph not synced` / `synced from <x>` / `out of sync (a of b transfers)`), không tự sync, không chạy tiếp kèm cảnh báo. Lý do: `exact = True` và đặc trưng ghi về hệ thống gốc chỉ đúng khi đồ thị khớp nguồn; trả lời sai trong im lặng tệ hơn lỗi rõ ràng; phép kiểm tốn khoảng 10–20 mili giây. Phương án thay thế: chỉ cảnh báo ra stderr rồi chạy tiếp (thuận cho demo, nhưng benchmark và Phase 7 có thể dùng số sai). — Trả lời: theo đề xuất mặc định — từ chối kèm thông điệp chỉ cách sửa, không tự sync, không chạy tiếp kèm cảnh báo (2026-10-12).
- [x] Q5. Method `neo4j` dùng được khi `DB_BACKEND` là gì? — đề xuất mặc định: cả `oracle` lẫn `duckdb` (`backends` gồm cả hai), với điều kiện đồ thị được sync từ đúng backend đó; `--method all` in `method=neo4j skipped: <lý do>` khi Neo4j tắt hoặc đồ thị lệch và vẫn exit 0; `--method neo4j` tường minh thì exit 2. Lý do: `pytest` và demo DuckDB-only không đổi hành vi; `all` vẫn là màn "một câu hỏi, bốn cách viết". — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q6. Thêm `prepare` vào `TraceMethod` của 5b? — đề xuất mặc định: có, tham số tuỳ chọn (mặc định `None`), `trace()` gọi trước khi bấm giờ; `neo4j` dùng nó để lấy driver dùng chung và kiểm đồ thị. Lý do: mở driver tốn 48–54 mili giây và phép kiểm 10–20 mili giây — nếu nằm trong `run` thì `seconds` của `neo4j` gánh chi phí mà ba method SQL không có, benchmark 6c sẽ lệch. Hệ quả: sửa model đã duyệt của 5b (chỉ thêm) và `tests/graph/test_config_sql.py`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q7. Giới hạn thời gian và số dòng cho truy vấn đọc (6a hoãn sang đây)? — đề xuất mặc định: `neo4j.read_timeout_seconds: 60` áp cho **mọi** lời gọi `run_read` (timeout phía server, lỗi `QueryTimeoutError`); `graph_queries.max_rows: 10000` cho `run_query` (vượt → lỗi, không cắt âm thầm, như `trace.max_paths`); mọi file truy vấn có `LIMIT $row_limit`. Lý do: đã gặp truy vấn chạy 18 phút trên server sau khi tiến trình khách hết giờ; ca nặng nhất hợp lệ đã đo là 2,8 giây. Phương án thay thế: timeout riêng cho từng truy vấn. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q8. `cycles` trả gì và theo định nghĩa nào? — đề xuất mặc định: mỗi dòng một **vòng** theo đúng định nghĩa `NET_CYCLE` của 5c (tài khoản nội bộ, khác chủ, sàn 50 triệu, tỉ lệ 0,70, 168 giờ, dài 3–5 — đọc từ `network.cycles`), không gộp đợt. Lý do: so khớp trực tiếp được với 5c (đã đo: 15 / 15 trên `small`, 2 / 2 trên TINY, cùng evidence); sàn số tiền là bắt buộc — bỏ sàn thì không xong trong 120 giây. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q9. `fan_in` / `fan_out` theo định nghĩa nào? — đề xuất mặc định: bản **đơn giản** — số đối tác khác nhau (kể cả `EXT-`) trong `window_days` tính từ từng chuyển khoản, ngưỡng lấy từ `monitoring.fan_in_out`, mỗi tài khoản một dòng là cửa sổ đông nhất; không có "đối tác đã quen" và "giai đoạn khởi động". Lý do: đọc được trong 19 dòng Cypher và đã đo là tập cha của alert 5a (`small`: 7 ⊇ 5 và 25 ⊇ 20). Cái giá: trả thêm employer payroll và tài khoản nền. Phương án thay thế: chép đủ logic 5a sang Cypher (dài gấp ba, và hai hiện thực phải giữ đồng bộ). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q10. "Cụm thuộc tính dùng chung" bằng Cypher là truy vấn gì? — đề xuất mặc định: hai truy vấn — `shared_attributes` (giá trị do 2–50 khách hàng cùng mang, lọc được theo một khách hàng) và `shared_cluster` (mọi người tới được từ một khách hàng, đường ngắn nhất, kèm `distance` và `via`); danh sách **mọi** cụm là việc của WCC trong GDS. Lý do: thành phần liên thông toàn đồ thị không phải thế mạnh của Cypher thuần; hai truy vấn này là thứ investigator hỏi khi đứng ở một khách hàng (đã đo: dưới 0,01 giây, khớp cụm của 5c). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q11. Truy vấn Cypher có sinh alert không? — đề xuất mặc định: **không**, chỉ trả kết quả điều tra. Lý do: 5c đã sinh alert `NETWORK` và các truy vấn cho đúng cùng tài khoản (đã đo: vòng 15 / 15, cụm 5 / 5) → alert từ Neo4j chỉ là bản trùng mà Phase 7 phải khử. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q12. Tên lệnh CLI? — đề xuất mặc định: `aml graph query NAME [--account] [--customer] [--as-of] [--limit]` với 5 tên cố định; trace vẫn ở `aml trace --method neo4j`. Lý do: trace đã có lệnh riêng dùng chung cho bốn method; nhóm `aml graph` giữ mọi thứ chỉ có ở Neo4j. Không nhận chuỗi Cypher tự do từ dòng lệnh. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q13. Ghi `audit_log` những gì? — đề xuất mặc định: 1 dòng `QUERIED` cho mỗi `run_query` thành công (tên, tham số, số dòng), 1 dòng `TRACED` cho trace (như 5b); lời gọi lỗi không ghi; `record_audit=False` tắt được cho benchmark. Lý do: truy vấn không phải quyết định tự động, nhưng "ai đã xem cụm của khách hàng nào" là dấu vết truy cập mà governance cần. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q14. `as_of` của truy vấn nghĩa là gì? — đề xuất mặc định: mặc định `data.reference_date`; chỉ cắt chuyển khoản (`ts` trước 00:00 ngày `as_of + 1`); thuộc tính khách hàng luôn là hiện trạng. Lý do: giống hệt 5c nên so được; đồ thị không lưu lịch sử thuộc tính. — Trả lời: theo đề xuất mặc định (2026-10-12).
