---
id: fund-flow-trace
status: approved
approved_by: pthieu
---

# Phase 5b — Fund-flow tracing: recursive CTE (raw / `acct_edge_daily`) và Oracle SQL property graph, `aml trace`

## Bối cảnh
Phase 5 của PROJECT_BRIEF.md (mục 6) được tách làm ba spec: 5a rules (`specs/monitoring-rules.md`: bảng `alerts`,
DDL `110`, mục config `monitoring`, lệnh `aml monitor`), **5b (spec này)** fund-flow tracing, 5c network detections
bằng NetworkX. 5b trả lời một câu hỏi duy nhất — "từ tài khoản X, lần theo dòng tiền đi ra tối đa N hop trong T
giờ, các hop theo thứ tự thời gian, không quay lại tài khoản đã đi qua" — bằng ba hiện thực so sánh được với nhau:
(1) recursive CTE trên `transactions` thô (Oracle dùng `CYCLE ... SET`, DuckDB tự mang danh sách đã đi qua),
(2) recursive CTE trên `acct_edge_daily` có ngưỡng số tiền và top-K, (3) Oracle 23ai SQL property graph
(`GRAPH_TABLE ... MATCH`, chỉ Oracle). Bản thứ tư (Neo4j Cypher) thuộc Phase 6 và cắm vào cùng một registry.
Người dùng: investigator lần theo tiền từ một tài khoản; người phỏng vấn xem cùng một câu hỏi viết bằng ba cách;
benchmark Phase 6 và bộ chọn backend của UI Phase 9 gọi cùng hàm `trace()`. Trace chỉ đọc: không tạo alert, không
sửa bảng `alerts`, không phụ thuộc 5a đã chạy hay chưa.

### Hiện trạng đã kiểm (seed 42; DuckDB 1.5.6; Oracle 23.26.3 Free tại localhost:1521/FREEPDB1 đang nạp sẵn TINY)
Mọi con số dưới đây đo bằng script tạm ngoài repo. Trên Oracle chỉ `SELECT` trên bảng sẵn có và tạo/xoá đối tượng
tạm tiền tố `TMP_5B_` (đã dọn sạch). Mỗi truy vấn đều được đối chiếu với một bản duyệt DFS thuần Python.
- **Dữ liệu**: TINY 5100 giao dịch, 3651 có cả hai phía khác null (1449 dòng CASH/CARD một phía null), 3575 dòng
  `acct_edge_daily`, 1149 tài khoản phân biệt xuất hiện trong `acct_edge_daily`. **782 mã `EXT-` không có trong
  `accounts`**, trong đó 401 mã vừa nhận vừa gửi (pool `EXT-` dùng chung nên chúng là "hub" nối các tài khoản nội bộ
  không liên quan). 100 nhóm giao dịch trùng (DQ) và 99 cặp (tài khoản gửi, giây) có nhiều hơn một giao dịch →
  phải định nghĩa rõ so sánh thời gian là `>` hay `>=`. Không có self-transfer trong dữ liệu sinh ra.
- **Tài khoản typology không có giao dịch nền** nên là ca kiểm thử sạch: `GT-RND-0001` (TINY) là chu trình
  `A8201784530 → A3312263346 → A9950029109 → A1070944972 → A8201784530` từ 2026-03-22 15:00:00 đến
  2026-03-27 00:11:51 (105,2 giờ); `GT-RAP-0001` có nguồn `A4879560749` → subject `A1425071026` → 3 đích trong 17
  giờ; `GT-MULE-0001` có nguồn `A2582841008` → member → collector `A4937939209` → 3 đích.
- **Oracle `CYCLE account_id SET is_cycle TO 'Y' DEFAULT 'N'`**: dòng có `account_id` trùng một dòng tổ tiên vẫn
  **được trả về** (đánh dấu `Y`) và không được mở rộng tiếp. Nếu dòng neo (hop 0) là chính tài khoản xuất phát thì
  hop quay về điểm xuất phát cũng bị đánh dấu. Bản DuckDB mang `visited` dạng `VARCHAR[]`, tính
  `is_cycle = list_contains(visited, to_account_id)` và chỉ mở rộng dòng `NOT is_cycle` cho **đúng cùng tập dòng**:
  10/10 ca TINY, 6/6 ca MINI và 9/9 ca `small` (nạp vào bảng tạm) trùng khít giữa Oracle, DuckDB và DFS Python.
- **Hàm phân tích trong nhánh đệ quy** (`ROW_NUMBER() OVER (PARTITION BY <đường đi cha> ORDER BY total_amount DESC,
  dst_acct, day)`) chạy được trên cả Oracle lẫn DuckDB; lọc `rk <= K` ở vòng lặp kế tiếp (Oracle không cho subquery
  tham chiếu tên CTE trong nhánh đệ quy). Bản `acct_edge_daily` trên hai backend trùng khít ở 5/5 ca MINI và 18/18
  ca `small` (cả có lẫn không có ngưỡng/top-K). Bind null phải ép kiểu (`CAST(:since AS TIMESTAMP)`), nếu không
  Oracle báo ORA-00932.
- **Giới hạn thực tế của SQL property graph trên 23.26.3**:
  - `aml_owner` đã có quyền `CREATE PROPERTY GRAPH`; tạo trùng tên báo ORA-00955 (nuốt được theo quy ước DDL);
    `CREATE PROPERTY GRAPH IF NOT EXISTS`, `CREATE OR REPLACE PROPERTY GRAPH` và `GRANT SELECT ON PROPERTY GRAPH`
    đều chạy được.
  - **Không dùng `accounts` làm bảng đỉnh được**: cạnh có đầu mút không nằm trong bảng đỉnh bị bỏ khỏi `MATCH` —
    graph trên `accounts` chỉ khớp 1037/3651 giao dịch hai phía của TINY (mất mọi hop tới/từ `EXT-`).
  - Bảng đỉnh là **view** (`UNION` các mã tài khoản trong `transactions`) thì chạy được ở 2–4 hop nhưng truy vấn
    6 hop trên TINY **không xong sau 20 giây** (bản dùng bảng thật: 0,13 giây). Bảng đỉnh là **materialized view**
    có unique index chạy nhanh như bảng thường, và graph vẫn `VALID` sau `DBMS_MVIEW.REFRESH`.
  - Quantifier có biên `->{1,4}` chạy được kèm `LISTAGG`/`COUNT`/`MIN`/`MAX` trên biến nhóm và `ONE ROW PER STEP`;
    **không** hỗ trợ: quantifier không biên `+` (ORA-40985), biên là bind (ORA-40984), biên `{0,0}`, path mode
    `ACYCLIC`/`SIMPLE`/`TRAIL`, `ANY`/`ALL SHORTEST`, mệnh đề `KEEP`, `ALL_DIFFERENT` (có `VERTEX_EQUAL`).
  - `WHERE` trong mẫu lặp chỉ thấy phần tử của **vòng lặp hiện tại** và biến bên ngoài, nên **không diễn đạt được**
    "hop sau phải sau hop trước" lẫn "không lặp đỉnh" bên trong quantifier. Hai cách khả thi: **(A)** mỗi độ dài
    một mẫu cố định `(a0)-[e1]->(a1)-...` với điều kiện so sánh chéo `e2.txn_ts > e1.txn_ts`, `a2 <> a0`..., nối
    bằng `UNION ALL` (6 hop = 6 khối, 153 dòng trong prototype); **(B)** quantifier + `ONE ROW PER STEP` rồi lọc thứ
    tự/chu trình ở SQL bên ngoài (39 dòng, nhưng phải liệt kê mọi walk trước khi lọc).
  - Cả (A) và (B) cho **đúng cùng tập dòng** với bản CTE thô trên mọi ca TINY, MINI và `small`. Thời gian một lần
    chạy trên `small` (bảng tạm có index, đã gather stats), tài khoản `A5461833942`, T = 168 giờ, 2/4/6 hop: CTE
    thô 0,02 / 0,02 / 0,01 giây; (A) 0,03 / 0,20 / **8,2 giây**; (B) 0,02 / 0,74 / **57,5 giây**. Với T = 24 giờ ở
    6 hop: (A) 7,7 giây, (B) 0,24 giây. Số đo một lần, chưa tuning — số chính thức do benchmark Phase 6 đo.
  - Drop bảng nền làm graph `INVALID` (truy vấn báo ORA-04045); tạo lại bảng thì graph tự hợp lệ lại ở lần truy
    vấn kế tiếp — không xung đột với các test 2a drop/tạo lại `transactions`.
- **Số path** (bản thô, chưa lọc): TINY tối đa 120 dòng trên các tài khoản đã thử (employer payroll); `small`
  `A5461833942` ở 6 hop: 358 (T = 24), 658 (72), 1429 (168), 22 394 (720), **11,9 triệu** (4320 giờ = cả 6 tháng,
  6,8 giây trên DuckDB); `dense` ở T ≤ 72 giờ không quá 174 dòng nhưng 4,6 triệu ở T = 4320. Với T ngắn, số dòng
  hầu như không tăng từ 4 lên 6 hop (dữ liệu nền mỗi cạnh chỉ có ~1 giao dịch trong 6 tháng) — benchmark Phase 6
  cần T đủ rộng mới thấy khác biệt. Nếu **dừng ở tài khoản `EXT-`** thì `small` 6 hop / 168 giờ còn 213 dòng thay
  vì 1429 (Q4).
- `SCHEMA_SCRIPTS` đã dùng `000`–`100`; `110` thuộc 5a; 5b dùng **`120`** (chỉ Oracle). Lệnh `graph`, `bench` là
  stub Phase 6 trong `src/aml/cli.py`; chưa có `src/aml/graph/`; chưa có `specs/monitoring-rules.md` (đang soạn).

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class TraceConfig(BaseModel):
    default_hops: int  # N khi không truyền
    default_hours: int  # T khi không truyền
    max_hops: int  # trần của N; không được vượt 6 (số khối của pgq.sql, độ rộng cột path)
    max_hours: int  # trần của T (chặn bùng nổ số path)
    max_paths: int  # quá số dòng này -> TraceError, không cắt bớt âm thầm
    edge_min_amount_vnd: int  # cte_edge: bỏ cạnh ngày có total_amount nhỏ hơn
    edge_top_k: int  # cte_edge: số cạnh ngày lớn nhất được theo ở mỗi bước; 0 = không giới hạn


class Settings(BaseModel):
    ...
    trace: TraceConfig


# src/aml/graph/trace.py
PATH_COLUMNS = [
    "hop",
    "path",
    "account_id",
    "step_path",
    "first_ts",
    "last_ts",
    "amount_vnd",
    "is_cycle",
]
PATH_SEPARATOR = ">"


class TraceError(RuntimeError): ...


@dataclass(frozen=True)
class TraceRequest:
    account_id: str
    hops: int
    hours: int
    since: datetime | None = None  # hop đầu tiên phải có txn_ts >= since
    min_amount_vnd: int = 0  # chỉ cte_edge dùng
    top_k: int = 0  # chỉ cte_edge dùng; 0 = không giới hạn


@dataclass(frozen=True)
class TraceMethod:
    name: str  # "cte_raw" | "cte_edge" | "pgq" (Phase 6 đăng ký thêm "neo4j")
    backends: frozenset[str]  # backend của `Database` mà method chạy được
    exact: bool  # True: cùng tập dòng với cte_raw; False: xấp xỉ theo ngày
    run: Callable[[Database, Settings, TraceRequest], pd.DataFrame]  # trả PATH_COLUMNS
    query_text: Callable[[str, TraceRequest], str]  # (backend, request) -> câu truy vấn thực chạy


METHODS: dict[str, TraceMethod]  # thứ tự: cte_raw, cte_edge, pgq


def register_method(method: TraceMethod) -> None: ...  # chỗ cắm cho backend thứ tư


@dataclass(frozen=True)
class TraceResult:
    request: TraceRequest
    method: str
    backend: str
    paths: pd.DataFrame  # PATH_COLUMNS, sắp theo (hop, path, step_path)
    n_paths: int  # số dòng
    n_accounts: int  # số account_id phân biệt trên các dòng is_cycle = False
    n_cycles: int  # số dòng is_cycle = True
    seconds: float  # thời gian chạy truy vấn
    query_lines: int  # số dòng không rỗng, không phải comment của câu truy vấn thực chạy


def trace(
    db: Database,
    settings: Settings,
    account_id: str,
    *,
    method: str = "cte_raw",
    hops: int | None = None,
    hours: int | None = None,
    since: datetime | None = None,
    min_amount_vnd: int | None = None,
    top_k: int | None = None,
    actor: str | None = None,
    record_audit: bool = True,
) -> TraceResult: ...


# src/aml/graph/schema.py
def refresh_account_nodes(
    db: Database,
) -> int: ...  # Oracle: refresh MV acct_node, trả số dòng; DuckDB: 0
```
- `config.yaml` thêm mục `trace`: `default_hops: 3`, `default_hours: 72`, `max_hops: 6`, `max_hours: 720`,
  `max_paths: 100000`, `edge_min_amount_vnd: 10000000`, `edge_top_k: 5`.
- SQL: `sql/oracle/trace/cte_raw.sql`, `sql/duckdb/trace/cte_raw.sql`, `sql/oracle/trace/cte_edge.sql`,
  `sql/duckdb/trace/cte_edge.sql`, `sql/oracle/trace/pgq.sql`. Giá trị truyền bằng **bind** (Oracle `:name`,
  DuckDB `$name`): `account`, `hops`, `hours`, `since`, và với `cte_edge` thêm `days`, `min_amount`, `top_k`.
  `account_id` không bao giờ được nối chuỗi vào SQL.
- DDL `sql/oracle/ddl/120_property_graph.sql`, thêm vào `SCHEMA_SCRIPTS["oracle"]` sau `ddl/100_entity_resolution.sql`
  (và sau `110` của 5a nếu đã có), trước `ddl/050_security_objects.sql`. DuckDB không có script `120`.
- `load_parquet` gọi `refresh_account_nodes(db)` ngay sau `refresh_acct_edge_daily(db)`.
- CLI mới `aml trace --account ID [--hops N] [--hours T] [--method cte_raw|cte_edge|pgq|all] [--since TS]
  [--min-amount VND] [--top-k K] [--limit 20]`. Không đụng stub `graph`, `bench`, `monitor`.

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Ngữ nghĩa chuẩn (`cte_raw`, và `pgq` phải cho đúng cùng tập dòng)**. Một path là dãy giao dịch `t1..tk`
  (1 ≤ k ≤ N), cả hai phía khác null, `t1.from_account_id = X`, `t(i+1).from_account_id = t(i).to_account_id`, và:
  - *Theo thứ tự thời gian*: `t(i+1).txn_ts > t(i).txn_ts` (lớn hơn **chặt**; cùng giây không được nối).
  - *Trong T giờ*: `t(k).txn_ts <= t1.txn_ts + T giờ` — cửa sổ neo vào **giao dịch đầu tiên của chính path đó**,
    biên trên **bao gồm**. Mỗi giao dịch đi ra của X mở một cửa sổ riêng.
  - *`since`*: nếu có, `t1.txn_ts >= since`; không có thì xét mọi giao dịch đi ra của X.
  - *Không chu trình*: các tài khoản `X, a1, ..., a(k-1)` đôi một khác nhau. Hop cuối **được phép** rơi vào tài
    khoản đã có trên path (kể cả X, kể cả self-transfer): dòng đó được trả về với `is_cycle = True` và **không bao
    giờ được mở rộng tiếp**. Đây chính là hành vi của `CYCLE ... SET` trên Oracle.
  - Tài khoản `EXT-` được đi xuyên qua như mọi tài khoản khác (Q4). Giao dịch trùng (DQ) là các path riêng.
  - Mỗi tiền tố của một path cũng là một dòng kết quả (mỗi dòng = một path độ dài `hop`).
- **Cột kết quả** (giống nhau cho mọi method): `hop` (int, 1..N); `path` = các mã tài khoản từ X đến tài khoản
  cuối nối bằng `>`; `account_id` = tài khoản cuối; `step_path` = các `txn_id` nối bằng `>` (`cte_raw`, `pgq`) hoặc
  các ngày `YYYY-MM-DD` nối bằng `>` (`cte_edge`); `first_ts`, `last_ts` = thời điểm hop đầu và hop cuối
  (`cte_edge`: 00:00:00 của ngày); `amount_vnd` = số tiền của hop cuối (`cte_edge`: `total_amount` của cạnh cuối);
  `is_cycle` (bool). Kết quả sắp theo (`hop`, `path`, `step_path`); kiểu: `hop`/`amount_vnd` int64, `is_cycle` bool.
- **`cte_raw`**: dòng neo hop 0 là chính X (không phải giao dịch), nhánh đệ quy nối `transactions` theo
  `from_account_id = account_id`; kết quả bỏ dòng hop 0. Oracle: `CYCLE account_id SET is_cycle TO 'Y' DEFAULT 'N'`,
  `path`/`step_path` là `VARCHAR2(200 CHAR)`. DuckDB: mang `visited VARCHAR[]`, không dùng `USING KEY`.
- **`cte_edge`** (xấp xỉ theo ngày, `exact = False`): cùng cấu trúc trên `acct_edge_daily` với `D = ceil(T / 24)`:
  cạnh sau có `day >= day` của cạnh trước (**không chặt**, vì trong cùng ngày không biết thứ tự), cạnh cuối có
  `day <= day của cạnh đầu + D`; `since` so theo ngày (`day >= ngày của since`). Lọc `total_amount >= min_amount_vnd`.
  Top-K: tại mỗi dòng cha, trong các cạnh ngày đã qua mọi điều kiện trên, chỉ K cạnh có `total_amount` lớn nhất
  (hoà thì `dst_acct` rồi `day` tăng dần) được giữ; cạnh đóng chu trình cũng chiếm chỗ trong K.
  - **Quan hệ đã chứng minh và đã đo**: với `min_amount_vnd = 0` và `top_k = 0`, tập `path` của `cte_edge` là
    **superset** của tập `path` của `cte_raw` cùng (X, N, T, since) — mọi path thô đều thoả điều kiện thô hơn theo
    ngày. Số **dòng** thì không so được (một cạnh ngày gộp nhiều giao dịch; TINY có ca 45 dòng edge so với 46 dòng
    thô). Khi bật ngưỡng hoặc top-K, `cte_edge` không còn là superset — chỉ là bản rút gọn để nhìn nhanh.
- **`pgq`** (chỉ Oracle, `exact = True`): cách (A) — `pgq.sql` chứa đúng 6 khối `SELECT ... FROM GRAPH_TABLE
  (aml_fund_flow MATCH ...)` độ dài 1..6 nối bằng các dòng chỉ chứa `UNION ALL`; Python giữ N khối đầu. Mỗi khối
  viết tường minh điều kiện thứ tự thời gian, cửa sổ T, tiền tố không lặp đỉnh và `CASE` tính `is_cycle` (Q8).
- **DDL `120` (Oracle)**: (1) materialized view `acct_node(account_id)` = hợp `src_acct` và `dst_acct` của
  `acct_edge_daily`, `BUILD IMMEDIATE REFRESH COMPLETE ON DEMAND`, unique index `UX_ACCT_NODE(account_id)`;
  (2) property graph `aml_fund_flow`: đỉnh `acct_node KEY (account_id) LABEL account`, cạnh `transactions KEY
  (txn_id) SOURCE KEY (from_account_id) REFERENCES acct_node (account_id) DESTINATION KEY (to_account_id)
  REFERENCES acct_node (account_id) LABEL transfer PROPERTIES (txn_id, txn_ts, amount_vnd, channel)`. Mọi lệnh bọc
  `EXECUTE IMMEDIATE`, nuốt ORA-00955 / ORA-12006 / ORA-01408, kết thúc bằng dòng `/`.
- **Kiểm tra đầu vào** (raise `TraceError`, không chạm DB): `method` không có trong `METHODS`; `account_id` rỗng
  hoặc chứa `>`; `hops` ngoài [1, `max_hops`]; `hours` ngoài [1, `max_hours`]; `min_amount_vnd < 0`; `top_k < 0`;
  method không hỗ trợ backend đang dùng (thông điệp chứa `Oracle only`). Tài khoản không tồn tại hoặc không có
  giao dịch đi ra → kết quả rỗng, không lỗi. Truy vấn lấy tối đa `max_paths + 1` dòng; vượt → `TraceError` chứa
  `more than <max_paths> paths`. `min_amount_vnd` / `top_k` bằng `None` → lấy từ config; `cte_raw` và `pgq` bỏ qua
  hai tham số này.
- **Audit**: mỗi lần `trace()` thành công ghi 1 dòng `module='graph'`, `entity_type='account'`,
  `entity_id=<account_id>`, `decision='TRACED'`, `version='trace/<method>'`, `actor` = tham số `actor` hoặc
  `audit.system_actor`, `reason` nêu method, backend, N, T và số path/tài khoản/hop đóng chu trình, `details` =
  `{method, backend, hops, hours, since, min_amount_vnd, top_k, paths, accounts, cycles}`. `record_audit=False`
  (cho benchmark Phase 6) thì không ghi. Lần gọi bị `TraceError` không ghi gì (Q10).
- **CLI**: in một dòng tổng kết `method=... backend=... account=... hops=... hours=... paths=... accounts=...
  cycles=... seconds=... query_lines=...` rồi tối đa `--limit` dòng path (`hop`, `path`, `step_path`, `last_ts`,
  `amount_vnd`, dấu `CYCLE` nếu `is_cycle`). `--method all` chạy lần lượt mọi method hỗ trợ backend hiện tại, mỗi
  method một dòng tổng kết; method không hỗ trợ in `method=<tên> skipped: Oracle only`. `TraceError` → thông điệp
  ra stderr, exit code 2.

## Tiêu chí nghiệm thu
<!-- MINI = DuckDB rỗng (`duck`) sau `apply_schema`, chèn 14 giao dịch (txn_id, txn_ts, from, to, amount_vnd; channel
INTERNAL_TRANSFER, riêng M05/M14 là CASH) rồi gọi `refresh_acct_edge_daily`:
  M01 2026-03-01 08:00:00 A->A 5000000          M08 2026-03-01 15:00:00 C->A 80000000
  M02 2026-03-01 09:00:00 B->E 50000000         M09 2026-03-01 16:00:00 C->EXT-000001 20000000
  M03 2026-03-01 10:00:00 A->B 100000000        M10 2026-03-01 17:00:00 EXT-000001->K 15000000
  M04 2026-03-01 10:00:00 B->H 30000000         M11 2026-03-02 09:00:00 C->D 70000000
  M05 2026-03-01 11:00:00 A->null 7000000       M12 2026-03-02 10:00:00 D->F 60000000
  M06 2026-03-01 12:00:00 B->C 90000000         M13 2026-03-02 10:00:01 D->G 40000000
  M07 2026-03-01 13:00:00 C->B 10000000         M14 2026-03-01 07:00:00 null->A 300000000
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` (5100 giao dịch, seed 42). `settings` = `load_settings(environ={})`
trừ khi nói khác. "Không lọc" = `min_amount_vnd=0, top_k=0`. Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC
còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given `config.yaml`, thư mục `sql/` và module `aml.graph.trace` (không cần DB), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS`, `METHODS` và gọi `query_text`, Then `settings.trace` có `default_hops = 3`, `default_hours = 72`, `max_hops = 6`, `max_hours = 720`, `max_paths = 100000`, `edge_min_amount_vnd = 10000000`, `edge_top_k = 5`; `load_settings(environ={"AML__TRACE__MAX_HOPS": "7"})` raise lỗi validation; `ddl/120_property_graph.sql` có trong `SCHEMA_SCRIPTS["oracle"]` trước `ddl/050_security_objects.sql`, không có trong `SCHEMA_SCRIPTS["duckdb"]`, và chứa `PROPERTY GRAPH`, `aml_fund_flow`, `acct_node`; `list(METHODS) == ["cte_raw", "cte_edge", "pgq"]` với `backends` lần lượt `{"oracle", "duckdb"}`, `{"oracle", "duckdb"}`, `{"oracle"}` và `exact` lần lượt `True`, `False`, `True`; `trace/cte_raw.sql` và `trace/cte_edge.sql` resolve qua `sql_file` về `sql/oracle/` và `sql/duckdb/`; hai file Oracle đó chứa `CYCLE` và `SET is_cycle`, hai file DuckDB không chứa từ `CYCLE`; `trace/pgq.sql` chỉ có ở `sql/oracle/`, qua `split_oracle_script` ra đúng 1 statement chứa đúng 6 lần `GRAPH_TABLE`; `query_text("oracle", TraceRequest("A", 2, 24))` của `pgq` chứa đúng 2 lần `GRAPH_TABLE`, với `hops=6` chứa đúng 6 lần; không file nào trong `sql/*/trace/` chứa ký tự `{`.
- AC2: Given MINI, When gọi `trace(duck, settings, "A", method="cte_raw", hops=4, hours=24)`, Then `paths` có cột đúng bằng `PATH_COLUMNS` và đúng 9 dòng theo thứ tự (`hop`, `path`, `step_path`, `amount_vnd`, `is_cycle`): (1, `A>A`, `M01`, 5000000, True), (1, `A>B`, `M03`, 100000000, False), (2, `A>B>C`, `M03>M06`, 90000000, False), (3, `A>B>C>A`, `M03>M06>M08`, 80000000, True), (3, `A>B>C>B`, `M03>M06>M07`, 10000000, True), (3, `A>B>C>D`, `M03>M06>M11`, 70000000, False), (3, `A>B>C>EXT-000001`, `M03>M06>M09`, 20000000, False), (4, `A>B>C>D>F`, `M03>M06>M11>M12`, 60000000, False), (4, `A>B>C>EXT-000001>K`, `M03>M06>M09>M10`, 15000000, False); không dòng nào có `path` bắt đầu bằng `A>A>`, `A>B>C>A>` hoặc `A>B>C>B>` (dòng đóng chu trình không được mở rộng); không có `A>B>E` (M02 xảy ra trước M03) và không có `A>B>H` (M04 cùng giây với M03); dòng `A>B>C>D>F` có `first_ts = 2026-03-01 10:00:00` và `last_ts = 2026-03-02 10:00:00`; `n_paths = 9`, `n_cycles = 3`, `n_accounts = 6`, `method = "cte_raw"`, `backend = "duckdb"`, `query_lines > 0`.
- AC3: Given MINI, When gọi `trace` trên MINI với `account_id="A"`, `method="cte_raw"` và các tham số khác nhau, Then `hops=4, hours=25` trả 10 dòng = 9 dòng của AC2 cộng (4, `A>B>C>D>G`, `M03>M06>M11>M13`, 40000000, False); `hops=4, hours=24` không có `A>B>C>D>G` (M13 trễ 1 giây so với biên) nhưng có `A>B>C>D>F` (M12 đúng bằng biên); `hops=2, hours=24` trả đúng 3 dòng `A>A`, `A>B`, `A>B>C`; `hops=1` trả đúng 2 dòng; `hops=6, hours=24` trả đúng 9 dòng của AC2; `hops=4, hours=24, since=datetime(2026, 3, 1, 10, 0, 0)` trả 8 dòng (mất `A>A`); `since=datetime(2026, 3, 1, 10, 0, 1)` trả 0 dòng; `trace(duck, settings, "ZZZ", hops=3, hours=24)` trả `paths` rỗng với cột đúng bằng `PATH_COLUMNS`, `n_paths = 0`, không raise; và gọi `trace(duck, settings, "A")` không truyền `hops`/`hours` thì `request.hops = 3`, `request.hours = 72`.
- AC4: Given MINI, When gọi `trace` với `account_id="A"`, `method="cte_edge"`, `hops=4`, `hours=24` và các bộ lọc khác nhau, Then với `min_amount_vnd=0, top_k=0` trả 12 dòng, `n_cycles = 3`, tập `path` = tập `path` của AC2 cộng đúng ba path `A>B>E`, `A>B>H`, `A>B>C>D>G`; dòng `A>B>C>D` có `step_path = "2026-03-01>2026-03-01>2026-03-02"`, `amount_vnd = 70000000`, `last_ts = 2026-03-02 00:00:00`; với `min_amount_vnd=20000000, top_k=0` trả 9 dòng, không có `A>A`, `A>B>C>B`, `A>B>C>EXT-000001>K`; với `min_amount_vnd=0, top_k=2` trả đúng 8 dòng có `path` là `A>A`, `A>B`, `A>B>C`, `A>B>E`, `A>B>C>A`, `A>B>C>D`, `A>B>C>D>F`, `A>B>C>D>G`; với `min_amount_vnd=20000000, top_k=1` trả đúng 3 dòng `A>B`, `A>B>C`, `A>B>C>A` (dòng cuối `is_cycle = True`); và `trace(duck, settings, "A", method="cte_raw", hops=4, hours=24, min_amount_vnd=20000000, top_k=1)` vẫn trả 9 dòng của AC2.
- AC5: Given TINY trong DuckDB, When gọi `trace` với `method="cte_raw"` từ tài khoản X, Then X = `A8201784530`, `hops=4, hours=168` trả đúng 4 dòng có `path` lần lượt `A8201784530>A3312263346`, `A8201784530>A3312263346>A9950029109`, `A8201784530>A3312263346>A9950029109>A1070944972`, `A8201784530>A3312263346>A9950029109>A1070944972>A8201784530`, dòng cuối có `is_cycle = True`, `step_path = "T0000002197>T0000002246>T0000002299>T0000002327"`, `amount_vnd = 399475000`, `last_ts = 2026-03-27 00:11:51`, ba dòng đầu `is_cycle = False`; cùng X với `hours=72` trả 2 dòng, 0 chu trình; với `hops=3, hours=168` trả 3 dòng, 0 chu trình; X = `A4879560749`, `hops=2, hours=24` trả 4 dòng (1 dòng hop 1 tới `A1425071026` với `amount_vnd = 525932000`, 3 dòng hop 2 tới `A4383611454`, `A8857496274`, `A9439686600`); X = `A2582841008`, `hops=4, hours=168` trả 104 dòng (21 hop 1, 23 hop 2, 60 hop 3, 0 hop 4), `n_cycles = 0`, `n_accounts = 24`, và ba tài khoản `A5212040158`, `A5340314117`, `A9706971063` đều xuất hiện ở hop 3; X = `A1037369383`, `hops=6, hours=168` trả 41 dòng với `n_cycles = 4`; X = `A3906301972`, `hops=2, hours=24` trả 120 dòng và thêm `since=datetime(2026, 6, 1)` thì còn 20 dòng; gọi lại bất kỳ ca nào lần hai cho `paths` bằng nhau theo `pd.testing.assert_frame_equal`.
- AC6: Given TINY trong DuckDB, When so `cte_edge` với `cte_raw` cùng (X, hops, hours), Then với `cte_edge` không lọc, tập `path` của `cte_raw` là tập con của tập `path` của `cte_edge` cho cả 5 ca (`A8201784530`, 4, 168), (`A4879560749`, 2, 24), (`A2582841008`, 4, 168), (`A1037369383`, 6, 168), (`A1037369383`, 2, 24); ca (`A1037369383`, 2, 24) có `cte_raw` 33 dòng / 10 path phân biệt và `cte_edge` 36 dòng / 12 path phân biệt, hai path thừa là `A1037369383>A1129199111>A1037369383` và `A1037369383>A7341585768>A1037369383`; ca (`A2582841008`, 2, 24) có `cte_raw` 23 dòng và `cte_edge` 24 dòng; và với `cte_edge` gọi không truyền `min_amount_vnd`/`top_k` (lấy 10000000 và 5 từ config), ca (`A2582841008`, 4, 168) trả 25 dòng (5 hop 1, 5 hop 2, 15 hop 3), `n_accounts = 9`, `request.min_amount_vnd = 10000000`, `request.top_k = 5`, còn ca (`A3906301972`, 2, 24) trả 5 dòng.
- AC7: Given MINI, When gọi `trace` với đầu vào không hợp lệ, Then mỗi lời gọi sau raise `TraceError`: `method="bfs"` (thông điệp chứa `cte_raw, cte_edge, pgq`), `account_id=""`, `account_id="A>B"`, `hops=0`, `hops=7` (thông điệp chứa `1` và `6`), `hours=0`, `hours=721`, `method="cte_edge", min_amount_vnd=-1`, `method="cte_edge", top_k=-1`, và `method="pgq"` trên DuckDB (thông điệp chứa `Oracle only`); và Given `load_settings(environ={"AML__TRACE__MAX_PATHS": "8"})`, When gọi `trace(duck, s, "A", hops=4, hours=24)` (9 path), Then raise `TraceError` chứa `more than 8 paths`, trong khi `hops=2` (3 path) không raise; sau tất cả các lời gọi bị lỗi trên, `audit_log` không có dòng `module='graph'` nào.
- AC8: Given MINI, When gọi `trace(duck, settings, "A", method="cte_raw", hops=4, hours=24, actor="analyst01")`, rồi cùng lời gọi với `method="cte_edge"` (không truyền `actor`), rồi lại `method="cte_raw"` với `record_audit=False`, Then `audit_log` có đúng 2 dòng `module='graph'`, cả hai `entity_type='account'`, `entity_id='A'`, `decision='TRACED'`, `reason` khác rỗng; dòng thứ nhất có `version='trace/cte_raw'`, `actor='analyst01'`, `details` gồm `method = "cte_raw"`, `backend = "duckdb"`, `hops = 4`, `hours = 24`, `since = null`, `paths = 9`, `accounts = 6`, `cycles = 3`; dòng thứ hai có `version='trace/cte_edge'`, `actor='system'`, `details.min_amount_vnd = 10000000`, `details.top_k = 5`; và sau cả ba lời gọi, số dòng của `transactions` vẫn là 14 và `acct_edge_daily` vẫn là 12.
- AC9: [oracle] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, When đọc data dictionary và gọi `trace` trên hai backend, Then `user_property_graphs` có `AML_FUND_FLOW`, `user_mviews` có `ACCT_NODE`, `SELECT COUNT(*) FROM acct_node` = 1149, và `SELECT COUNT(*) FROM GRAPH_TABLE(aml_fund_flow MATCH (a IS account) -[e IS transfer]-> (b IS account) COLUMNS (e.txn_id AS txn_id))` = 3651; gọi `apply_schema` lần hai không raise; với 5 ca (`A8201784530`, 4, 168), (`A8201784530`, 4, 72), (`A1037369383`, 6, 168), (`A2582841008`, 4, 168), (`A3906301972`, 2, 24), `paths` của `cte_raw` trên Oracle, `pgq` trên Oracle và `cte_raw` trên DuckDB bằng nhau từng dòng (4, 2, 41, 104, 120 dòng; `first_ts`/`last_ts` so sau khi đưa về cùng độ phân giải giây), ca (`A1037369383`, 6, 168) có `n_cycles = 4` ở cả ba; `cte_edge` trên Oracle bằng `cte_edge` trên DuckDB cho cả 5 ca, cả khi không lọc lẫn với mặc định config; `trace(oracle, settings, "A8201784530", method="pgq", hops=4, hours=168)` có dòng cuối `is_cycle = True` và `query_lines` lớn hơn `query_lines` của cùng lời gọi với `hops=2`; và Given MINI chèn vào Oracle (xoá `transactions`, chèn 14 dòng, `refresh_acct_edge_daily`, `refresh_account_nodes` trả 10), When gọi `cte_raw` và `pgq` với `hops=4, hours=24`, Then cả hai trả đúng 9 dòng của AC2.
- AC10: Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), When chạy `aml trace --account A8201784530 --hops 4 --hours 168`, Then exit code 0, stdout có một dòng chứa `method=cte_raw`, `backend=duckdb`, `account=A8201784530`, `hops=4`, `hours=168`, `paths=4`, `accounts=3`, `cycles=1`, và một dòng chứa `A8201784530>A3312263346>A9950029109>A1070944972>A8201784530` cùng `CYCLE`; `aml trace --account A2582841008 --hops 4 --hours 168 --method cte_edge` in `paths=25`, và thêm `--min-amount 0 --top-k 0 --limit 3` thì in `paths=104` và đúng 3 dòng path; `aml trace --account A8201784530 --hops 4 --hours 168 --method all` exit 0, in hai dòng tổng kết `method=cte_raw` và `method=cte_edge` cùng một dòng chứa `method=pgq skipped: Oracle only`; `aml trace --account A8201784530 --method pgq` exit code 2 với stderr chứa `Oracle only`; `aml trace --account A8201784530 --hops 7` exit code 2 với stderr chứa `hops`; `aml graph` và `aml bench` vẫn exit code 1 với stderr chứa `Phase 6`.

## Ngoài phạm vi
- Rules, bảng `alerts`, DDL `110`, mục config `monitoring`, lệnh `aml monitor` (5a); lấy điểm xuất phát từ `alerts`.
- Network detections bằng NetworkX: cụm thiết bị/điện thoại/địa chỉ dùng chung, phát hiện chu trình, hub (5c).
- Neo4j: projection, file `.cypher`, method `neo4j`, GDS (Phase 6) — 5b chỉ để sẵn `register_method`.
- Benchmark: chạy nhiều lần, median/p95, profile `dense`, bảng và biểu đồ kết quả, lệnh `aml bench`, kết luận
  "khi nào SQL đủ" (Phase 6). `seconds` và `query_lines` của `TraceResult` chỉ là số liệu thô cho Phase 6 dùng.
- Trace ngược (tiền đi **vào** X), trace hai chiều, đường đi ngắn nhất, gộp path theo tài khoản, tính số tiền
  "còn lại" dọc path (min/tỉ lệ), lọc theo channel.
- Ngưỡng số tiền và top-K cho `cte_raw` và `pgq` (Q7); cửa sổ T tính giữa hai hop liên tiếp (Q1).
- Tuning phía Oracle cho `pgq` (hint, index mới, in-memory graph, viết lại thứ tự join); property graph có thêm
  đỉnh `Customer`/`Device`/`Phone`, cạnh `OWNS`; property graph trên `acct_edge_daily`.
- Extension `duckpgq` của DuckDB (phải tải từ mạng) — DuckDB không có method `pgq`.
- Quyền Oracle trên `acct_node` và trên property graph cho các role của 2b (`020_grants.sql`, `ROLE_GRANTS`) (Q12).
- Fast refresh / lịch refresh cho `acct_node`; tự phát hiện `acct_node` hay `acct_edge_daily` lỗi thời.
- API FastAPI và UI chọn backend (Phase 9); xuất kết quả ra file; vẽ đồ thị.
- Target mới trong `Makefile` / `tasks.ps1`; ghi số liệu vào README.

## Giả định
- Đã kiểm trên Oracle 23.26.3: cú pháp `CYCLE ... SET`, hàm phân tích trong nhánh đệ quy, `CREATE PROPERTY GRAPH`
  trên materialized view + `transactions`, `GRAPH_TABLE` với mẫu độ dài cố định và so sánh chéo giữa các cạnh,
  graph còn `VALID` sau khi refresh MV. Bản vá khác có thể cho giới hạn khác — khi đó cập nhật spec.
- **Chưa kiểm**: script `120` chạy trong `apply_schema` thật (prototype dùng đối tượng `TMP_5B_`, chưa chạy trên
  `transactions` đã partition cùng MV `acct_node` thật); hành vi khi `acct_edge_daily` bị drop và tạo lại; quyền
  truy vấn property graph từ user không phải owner; kế hoạch thực thi và thời gian của `pgq` trên bảng
  `transactions` partition thật ở profile `small`/`dense` (chỉ đo trên bảng tạm không partition).
- `txn_ts` là thời điểm naive theo giờ Việt Nam (quy ước 1b-i), độ phân giải giây; `day` của `acct_edge_daily` là
  ngày của `txn_ts` (2a). Mã tài khoản không chứa ký tự `>` (dạng `A` + chữ số hoặc `EXT-` + chữ số).
- `acct_edge_daily` (và `acct_node` trên Oracle) đã được refresh sau lần nạp gần nhất; ai sửa `transactions` trực
  tiếp phải tự gọi `refresh_acct_edge_daily` rồi `refresh_account_nodes`, nếu không `cte_edge` và `pgq` sẽ lệch.
- Trace chạy bằng kết nối owner như các phase trước; không tiến trình nào ghi `transactions` trong lúc trace.
- Test [oracle] nạp lại TINY (và MINI) vào schema `aml_owner`, để lại dòng trong `audit_log` — giống các spec trước.
- `refresh_account_nodes` không ghi `audit_log` (bảng phụ trợ kỹ thuật; `REFRESHED` của `acct_edge_daily` đã có).
- Thông điệp lỗi và output CLI bằng tiếng Anh; ngoài `event_ts` của audit và `seconds`, kết quả không phụ thuộc
  đồng hồ máy và tất định với cùng dữ liệu.
- Số dòng của `sql/oracle/trace/pgq.sql` tăng tuyến tính theo N là chủ ý: đó là phát hiện để Phase 6 báo cáo.

## Câu hỏi mở
- [x] Q1. "Trong T giờ" tính từ đâu? — đề xuất mặc định: từ **giao dịch đầu tiên của path** (`t(k).txn_ts <= t1.txn_ts + T`, biên bao gồm); mỗi giao dịch đi ra của X mở một cửa sổ riêng. Lý do: đúng câu chữ của brief ("up to N hops within T hours"), tổng thời gian trace bị chặn bởi T nên số path không nổ theo N, và diễn đạt được ở cả ba bản. Phương án thay thế: T là khoảng cách tối đa giữa hai hop liên tiếp (bắt được chuỗi chậm nhưng dài; tổng thời gian có thể tới N × T). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q2. Hai hop cùng giây có được nối không? — đề xuất mặc định: không, yêu cầu `>` **chặt**. Lý do: tiền chưa tới thì chưa thể đi; TINY có 99 cặp (tài khoản, giây) trùng nhau nên `>=` sẽ tạo path không có thứ tự xác định. Hệ quả: chuỗi chuyển tiền tự động trong cùng một giây bị bỏ sót ở `cte_raw`/`pgq` (bản `cte_edge` theo ngày vẫn thấy). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q3. Hop quay lại tài khoản đã đi qua thì bỏ hẳn hay giữ? — đề xuất mặc định: **giữ dòng đó** với `is_cycle = True` và không mở rộng tiếp. Lý do: đây là hành vi nguyên bản của `CYCLE ... SET` trên Oracle, và investigator nhìn thấy ngay vòng round-tripping (`GT-RND-0001` hiện đủ 4 hop, hop cuối đánh dấu) thay vì path cụt không lời giải thích. Phương án thay thế: lọc bỏ `is_cycle` (kết quả chỉ gồm path đơn; bản `pgq` gọn hơn một chút). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q4. Có đi xuyên qua tài khoản `EXT-` không? — đề xuất mặc định: **có**, coi như mọi tài khoản khác. Lý do: tiền ra ngân hàng khác rồi quay lại là mẫu layering thật, và ba bản dùng chung một định nghĩa không có ngoại lệ. Cái giá: pool `EXT-` dùng chung của dữ liệu tổng hợp tạo nhiễu (`small`, 6 hop, 168 giờ: 1429 dòng so với 213 nếu dừng ở `EXT-`). Phương án thay thế: hop vào `EXT-` được trả về nhưng không mở rộng tiếp. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q5. Bảng đỉnh của property graph lấy từ đâu khi `accounts` không chứa `EXT-`? — đề xuất mặc định: materialized view mới `acct_node` (hợp `src_acct`/`dst_acct` của `acct_edge_daily`) có unique index, refresh trong `load_parquet` ngay sau `acct_edge_daily`. Lý do: graph trên `accounts` chỉ khớp 1037/3651 giao dịch; view thường làm truy vấn 6 hop không xong sau 20 giây; MV chạy như bảng thật và graph vẫn hợp lệ sau refresh. Hệ quả: brief nói "over the existing tables" nhưng thực tế phải thêm một đối tượng, và `load_parquet` có thêm một bước. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q6. `cte_edge` so thời gian theo ngày thế nào? — đề xuất mặc định: cạnh sau có `day >=` cạnh trước (không chặt), cạnh cuối `<=` ngày cạnh đầu + `ceil(T / 24)` ngày. Lý do: là điều kiện thô nhất vẫn bảo đảm tập `path` không lọc là **superset** của `cte_raw` (đã chứng minh và đã đo), nên `cte_edge` dùng làm bước sàng nhanh mà không sót path nào. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q7. Ngưỡng số tiền và top-K áp cho bản nào? — đề xuất mặc định: chỉ `cte_edge` (đúng như brief); `cte_raw` và `pgq` bỏ qua hai tham số. Lý do: giữ `cte_raw`/`pgq` là "đáp án đầy đủ" để đối chiếu; ngưỡng trên từng giao dịch và ngưỡng trên tổng theo ngày không tương đương nên áp cho cả ba chỉ gây hiểu nhầm là so được. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q8. Bản `pgq` viết theo cách (A) mẫu độ dài cố định + `UNION ALL` hay (B) quantifier + `ONE ROW PER STEP` rồi lọc bên ngoài? — đề xuất mặc định: **(A)**, file `pgq.sql` chứa 6 khối, Python giữ N khối đầu. Lý do: (A) cắt nhánh sai thứ tự/lặp đỉnh ngay trong `MATCH`; (B) phải liệt kê mọi walk rồi mới lọc (`small`, 6 hop, 168 giờ: 57,5 giây so với 8,2 giây của (A) và 0,01 giây của CTE). Cái giá: (A) dài (khoảng 150 dòng ở 6 hop) và chậm ở 6 hop kể cả khi cửa sổ hẹp (7,7 giây ở T = 24, trong khi (B) chỉ 0,24 giây) — cả hai đều là số liệu đáng báo cáo ở Phase 6. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q9. Top-K xếp hạng cái gì? — đề xuất mặc định: tại mỗi dòng cha, K **cạnh ngày** `(dst_acct, day)` có `total_amount` lớn nhất trong số cạnh đã qua điều kiện thời gian và ngưỡng; hoà thì `dst_acct` rồi `day` tăng dần; `0` = không giới hạn. Lý do: tính được bằng `ROW_NUMBER()` ngay trong nhánh đệ quy trên cả hai backend. Hệ quả: một đối tác có thể chiếm nhiều chỗ nếu xuất hiện nhiều ngày, và ở hop 1 khi không có `since` thì K cạnh được chọn trên toàn bộ lịch sử của X (payroll TINY: 5 dòng thay vì 120). Phương án thay thế: xếp hạng trước theo (`src_acct`, `day`), độc lập với path. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q10. Mỗi lần trace có ghi `audit_log` không? — đề xuất mặc định: **có**, 1 dòng `decision='TRACED'` kèm tham số và số path; tắt được bằng `record_audit=False` cho benchmark. Lý do: trace không phải quyết định tự động, nhưng "ai đã lần theo tiền của tài khoản nào, bằng tham số gì" là dấu vết truy cập dữ liệu nhạy cảm mà governance cần và Phase 9 sẽ gắn `actor` thật; benchmark chạy hàng trăm lần thì không nên làm bẩn log. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q11. Giá trị mặc định và trần của tham số? — đề xuất mặc định: `default_hops = 3`, `default_hours = 72`, `max_hops = 6`, `max_hours = 720`, `max_paths = 100000` (vượt thì báo lỗi, không cắt bớt), `edge_min_amount_vnd = 10000000`, `edge_top_k = 5`. Lý do: 72 giờ phủ rapid movement (24 giờ) và phần lớn mule ring; 6 hop là mức cao nhất của benchmark; ở T = 720 giờ ca tệ nhất đã đo là 22 394 dòng, còn T = 4320 giờ cho 11,9 triệu dòng — phải chặn. Round-tripping kéo dài tới 168 giờ nên cần truyền `--hours 168`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q12. Quyền trên `acct_node` và property graph cho `aml_app` / `aml_analyst` / `aml_graph_sync`? — đề xuất mặc định: **chưa cấp** trong 5b; trace chạy bằng owner. Lý do: file grant và `ROLE_GRANTS` thuộc 2b và có test so khớp chính xác với `dba_tab_privs`; `GRANT SELECT ON PROPERTY GRAPH` đã thử chạy được nên bổ sung sau (Phase 6 cho `aml_graph_sync`, Phase 9 cho analyst) là việc nhỏ. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q13. `since` có đủ không, hay cần thêm `until` cho hop đầu? — đề xuất mặc định: chỉ `since` (bao gồm biên). Lý do: đủ để neo trace vào thời điểm một alert; `until` thêm một tham số vào cả năm file SQL mà chưa có người dùng cụ thể. Không truyền `since` thì xét toàn bộ lịch sử của X. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q14. Hình dạng CLI? — đề xuất mặc định: lệnh mới `aml trace` với `--method cte_raw|cte_edge|pgq|all` (mặc định `cte_raw`), `all` chạy mọi method mà backend hiện tại hỗ trợ; lỗi tham số và `pgq` trên DuckDB → exit code 2 (giống `explain-pruning`). Lý do: `all` là màn demo "một câu hỏi, ba cách viết, cùng đáp án" chỉ bằng một lệnh; không chiếm `aml graph` / `aml bench` của Phase 6. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q15. Tài khoản không tồn tại thì báo lỗi hay trả rỗng? — đề xuất mặc định: trả kết quả rỗng, exit code 0. Lý do: mã `EXT-` hợp lệ nhưng không có trong `accounts`, nên không có bảng nào để kiểm "tồn tại"; phân biệt "không có giao dịch đi ra" với "gõ sai mã" cần thêm một truy vấn mà ít giá trị. — Trả lời: theo đề xuất mặc định (2026-10-12).
