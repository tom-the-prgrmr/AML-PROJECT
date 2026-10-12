---
id: neo4j-gds
status: approved
approved_by: pthieu
---

# Phase 6b-ii — GDS trên projection Neo4j (WCC, Louvain, PageRank, degree) và ghi đặc trưng về hệ thống gốc, `aml graph gds`

## Bối cảnh
Phần "GDS" của Phase 6 trong PROJECT_BRIEF.md (mục 7): Weakly Connected Components và Louvain cho ring, PageRank và
degree centrality cho hub, ghi kết quả về Oracle làm đặc trưng cho Phase 7. Spec này **xây trên 6b-i đã xong**
(`specs/neo4j-queries.md`): dùng lại `shared_driver`, `check_fresh` / `require_fresh`, tham số `timeout` và
`QueryTimeoutError` của đường đọc. GDS chạy trên đồ thị **in-memory** dựng trong session `READ_ACCESS`, đọc kết quả
bằng `.stream` và ghi vào bảng `gds_account_features` của hệ thống gốc qua `Database` (Oracle lẫn DuckDB). Neo4j vẫn là
projection chỉ đọc: không thuộc tính, node hay quan hệ nào được ghi vào database Neo4j (không `.write`, không
`.mutate`). Người dùng: người vận hành chạy `aml graph gds`; Phase 7 / 7b đọc `gds_account_features_current`; người
phỏng vấn xem cùng một đặc trưng tính bằng NetworkX (5c) lẫn GDS. Hệ thống chỉ ghi đặc trưng: **không sinh alert,
không đóng alert, không chấm điểm ưu tiên**. 6c (benchmark) không phụ thuộc spec này.

### Hiện trạng đã kiểm (2026-10-12, seed 42)
Đo bằng script tạm ngoài repo trên **Neo4j 5.26.31 Community thật** (driver Python 6.4.0, APOC 5.26.31, GDS 2.13.13,
heap tối đa 1 GB, container giới hạn 2,44 GiB); Cypher nằm trong file `.cypher` tạm, kiểm bằng `assert_read_only` của
repo, chạy trong session `READ_ACCESS` với timeout phía server. MINI-G, MINI-HUB, MINI-CYC và TINY được sync vào
Neo4j bằng `run_sync(..., full=True)` của 6a để lấy số ghim cho AC; sau khi đo, đồ thị dev đã được trả về bộ `small`
bằng `uv run aml graph sync --full` (run 7, `in_sync=True`) và `gds.graph.list()` trả 0 dòng. Trên Oracle chỉ `SELECT`.
- **Dịch vụ**: Oracle UP (23.26.3, đang chứa TINY: 5100 giao dịch, 532 tài khoản; chưa có bảng nào tên `GDS%`); Neo4j
  UP; Ollama DOWN. `gds.debug.sysInfo`: `gdsEdition = Unlicensed`, 12 CPU khả dụng, `heapMax = 1024 MiB`.
  `gds.list()` trả 446 tên, có đủ `gds.graph.project`, `gds.graph.drop`, `gds.wcc.stream`, `gds.louvain.stream`,
  `gds.pageRank.stream`, `gds.degree.stream`.
- **GDS trong session `READ_ACCESS`** (đã thử thật): `CALL gds.graph.project(...)`, hàm tổng hợp
  `gds.graph.project(...)` trong `RETURN` (Cypher projection), `gds.*.stream`, `gds.*.mutate` (chỉ đổi đồ thị
  in-memory) và `gds.graph.drop` **đều chạy được**; `gds.degree.write` bị server từ chối với
  `Neo.ClientError.Statement.AccessMode` và không thuộc tính nào được tạo. Vậy toàn bộ đường GDS đi được qua
  `run_read_file`, không cần tiền tố mới trong `WRITE_PREFIXES`.
  - Cypher projection trả một dòng toàn `null` và **không tạo đồ thị** khi không có cặp nào khớp (đã gặp với
    MINI-CYC không có thuộc tính dùng chung và với `as_of` sớm hơn mọi giao dịch).
  - Đồ thị in-memory tốn 3–68 MiB theo `gds.graph.list`; bộ nhớ container 1,88 → 2,00 GiB trong ba lần chạy liên
    tiếp trên `small`, không lỗi hết bộ nhớ.
- **Guard hiện tại với GDS** (gọi `assert_read_only` thật):
  - `CALL gds.graph.drop($graph, false)` bị chặn với `write clause DROP` **kể cả khi tên procedure đã nằm trong
    allowlist** — từ `drop` trong tên procedure khớp `\bDROP\b`.
  - `MATCH ... RETURN gds.graph.project('g', s, t)` **qua guard với allowlist rỗng**: guard chỉ xét `CALL`, không
    xét lời gọi hàm. Không phải ghi vào database, nhưng ai đi qua `run_read` (Text2Cypher của Phase 8) cũng dựng
    được đồ thị in-memory chiếm heap.
  - `gds.pageRank.stream` bị chặn với `neo4j.read_procedures` hiện tại (đúng ý), qua khi allowlist có `gds.*.stream`.
- **GDS so với NetworkX của 5c** (đồ thị tài khoản dựng bằng Cypher projection từ `SENT_TO`: hai đầu có `OWNS`, khác
  chủ, `day` trong 365 ngày trước cutoff, một quan hệ cho mỗi cặp):

  | | MINI-G | MINI-HUB | TINY | `small` |
  |---|---|---|---|---|
  | node / quan hệ của đồ thị tài khoản | 6 / 4 | 51 / 47 | 298 / 450 | 4980 / 8610 (= `active_accounts` và số cặp của 5c) |
  | `in_degree`, `out_degree`, `in_vnd`, `out_vnd` bằng `nx_account_features` | mọi tài khoản | mọi tài khoản | 532 / 532 | 8958 / 8958 |
  | lệch lớn nhất của `pagerank` / `pagerank_ratio` | 0 / 0 | 0 / 0 | 0 / 0 | 1e-8 / 1e-4 (do làm tròn 8 và 4 chữ số) |
  | tài khoản thoả điều kiện hub của 5c tính từ GDS | 0 | `P0` | `A4937939209` | đúng 5 collector |
  | WCC đồ thị tài khoản: số thành phần / lớn nhất | 2 / 4 | 5 / 11 | 9 / 98 | 52 / 2179 (hai thành phần 2179) |
  | Louvain (`concurrency: 1`): số cộng đồng / lớn nhất | 2 / 4 | 5 / 11 | 20 / 36 | 151 / 82 |
  | WCC đồ thị khách hàng – giá trị dùng chung: số cụm | 4 | 0 | 2 (29 và 2) | 260 (242 cụm 2, 13 cụm 3, và 12 / 20 / 22 / 23 / 27) = 5c |
  | thời gian cả lượt (dựng 3 đồ thị + 8 lần stream + xoá) | 0,28 giây | 0,28 giây | 0,59 giây | 1,7–2,5 giây |

  - PageRank của GDS không chuẩn hoá (tổng 4408 trên `small`) và không chia lại khối lượng của nút cụt như NetworkX;
    chia cho **tổng điểm** thì ra đúng `pagerank` của 5c, nhân số nút có cạnh thì ra đúng `pagerank_ratio`.
  - Cấu hình mặc định của GDS (20 vòng lặp, `tolerance` 1e-7) **chưa hội tụ** (`didConverge = false`, lệch tới 10,5 %
    so với bản đã hội tụ); với `maxIterations: 200`, `tolerance: 1e-10` thì hội tụ sau 148 vòng. PageRank, degree và
    WCC cho kết quả giống hệt giữa `concurrency` 1 và 4.
  - **Louvain không tất định khi `concurrency: 4`** (ba lần chạy trên `small`: 135, 135, 134 cộng đồng) và tất định
    khi `concurrency: 1` (hai lần giống hệt, cả mã cộng đồng). `gds.louvain` 2.13 **không có** tham số `randomSeed`
    (`Unexpected configuration key: randomSeed`).
  - Louvain trên đồ thị khách hàng – giá trị dùng chung cho **đúng phân hoạch của WCC** (260 cộng đồng, modularity
    0,9898) — không thêm thông tin. Trên đồ thị tài khoản, Louvain tách hai thành phần 2179 tài khoản thành các cộng
    đồng ≤ 82; cả 5 mule ring (19–31 tài khoản) và 15 vòng round-tripping của `small` mỗi cái nằm trọn trong một
    cộng đồng. Bản có trọng số theo số tiền cho 278 cộng đồng.
  - Mã `componentId` / `communityId` của GDS là mã nội bộ của node (đổi sau mỗi lần sync lại) → không dùng làm khoá.
- **Ghim GDS** (container tạm, đã xoá): bỏ `graph-data-science` khỏi `NEO4J_PLUGINS` và bind-mount file
  `neo4j-graph-data-science-2.13.13.jar` (65 774 694 byte, sha256
  `17cfceb0c78e897baea3dfcdbd852dff779980bcc1eb444126338694bb053264`, chép ra từ volume của container đang chạy) vào
  `/plugins/graph-data-science.jar` thì `gds.version()` = 2.13.13, Cypher projection và `gds.pageRank.stream` chạy
  được, log khởi động **không còn** dòng `Fetching versions.json`. Mount kiểu `:ro` làm container thoát ngay
  (`chown: ... Read-only file system`). Container hiện tại vẫn tải `versions.json` và file jar từ
  `graphdatascience.ninja` mỗi lần khởi động.
- **Code sẵn có**: 6b-i cung cấp `shared_driver`, `require_fresh`, `run_read_file(..., timeout=...)`. `run_read` chỉ
  dùng `settings.neo4j.read_procedures`. `SCHEMA_SCRIPTS` đã dùng `000`–`140` → 6b-ii dùng **`150`**.
  `nx_account_features` không được cấp cho role nào trong `ROLE_GRANTS`. `tests/neo4j_sync/test_read_path.py` khẳng
  định `version == "guard/v1"`. `docker-compose.yml` đang có `NEO4J_PLUGINS: '["apoc", "graph-data-science"]'`.
- **Chưa đo**: GDS trên profile `dense` và `large`; DDL `150` và việc ghi `gds_account_features` / `gds_runs` trên cả
  hai backend; hàm guard sau khi sửa; output CLI; `docker compose up` thật với cấu hình ghim GDS (chỉ thử `docker
  run`); container tạm chạy với `--network none` thì tắt ngay sau khi khởi động, chưa tìm nguyên nhân.

### Interface đề xuất (để test và Phase 7 gọi trực tiếp)
```python
# src/aml/common/config.py
class GdsConfig(BaseModel):
    procedures: list[str]  # allowlist riêng của đường GDS (mẫu fnmatch)
    graph_prefix: str  # tiền tố tên đồ thị in-memory; định danh thường
    concurrency: int  # 1..4; chỉ 1 là tất định với Louvain
    pagerank_max_iterations: int  # >= 1
    pagerank_tolerance: float  # > 0
    louvain_max_levels: int  # >= 1
    louvain_max_iterations: int  # >= 1
    louvain_tolerance: float  # > 0


class Settings(BaseModel):
    ...
    gds: GdsConfig


# src/aml/graph/neo4j/guard.py
GUARD_VERSION = "guard/v2"


# src/aml/graph/neo4j/client.py  (thêm `procedures` vào chữ ký của 6b-i)
def run_read(
    driver: neo4j.Driver,
    settings: Settings,
    cypher: str,
    params: Mapping[str, Any] | None = None,
    *,
    audit_db: Database | None = None,
    actor: str | None = None,
    procedures: Sequence[str] | None = None,  # None -> settings.neo4j.read_procedures
    timeout: float | None = None,
) -> pd.DataFrame: ...
def run_read_file(
    driver: neo4j.Driver,
    settings: Settings,
    name: str,
    params: Mapping[str, Any] | None = None,
    *,
    procedures: Sequence[str] | None = None,
    timeout: float | None = None,
) -> pd.DataFrame: ...


# src/aml/graph/neo4j/features.py  (thuần pandas, không import driver)
GDS_FEATURE_COLUMNS = [
    "account_id",
    "in_degree",
    "out_degree",
    "in_vnd",
    "out_vnd",
    "pagerank",
    "pagerank_ratio",
    "wcc_id",
    "wcc_size",
    "louvain_id",
    "louvain_size",
    "shared_cluster_id",
    "shared_cluster_size",
]


@dataclass(frozen=True)
class GdsStreams:  # mỗi trường là DataFrame, có thể rỗng
    in_degree: pd.DataFrame  # account_id, score
    out_degree: pd.DataFrame  # account_id, score
    in_vnd: pd.DataFrame  # account_id, score
    out_vnd: pd.DataFrame  # account_id, score
    pagerank: pd.DataFrame  # account_id, score (điểm thô của GDS)
    wcc: pd.DataFrame  # account_id, component
    louvain: pd.DataFrame  # account_id, community
    shared: pd.DataFrame  # golden_customer_id, component


def build_features(
    accounts: pd.DataFrame,  # account_id, cif
    owner_of_cif: Mapping[str, str],  # cif -> golden_customer_id
    streams: GdsStreams,
) -> pd.DataFrame: ...  # GDS_FEATURE_COLUMNS, một dòng cho mỗi dòng accounts, sắp theo account_id


# src/aml/graph/neo4j/gds.py
class GdsError(GraphError): ...


@dataclass(frozen=True)
class GdsRun:
    run_id: int
    as_of: date
    accounts: int  # số dòng gds_account_features của lần chạy
    active_accounts: int  # số node của đồ thị tài khoản
    wcc_components: int
    louvain_communities: int
    shared_clusters: int
    graphs: dict[
        str, tuple[int, int]
    ]  # "accounts" | "accounts_undirected" | "shared" -> (node, quan hệ)
    sync_run_id: int  # SyncState.last_run_id lúc chạy
    watermark: datetime | None
    gds_version: str
    seconds: float


def run_gds(
    db: Database, settings: Settings, *, as_of: date | None = None, actor: str | None = None
) -> GdsRun: ...
```
- `config.yaml`: mục mới `gds: {procedures: [gds.graph.project, gds.graph.drop, "gds.*.stream"], graph_prefix: aml_gds,
  concurrency: 1, pagerank_max_iterations: 200, pagerank_tolerance: 1.0e-10, louvain_max_levels: 10,
  louvain_max_iterations: 10, louvain_tolerance: 0.0001}`. `neo4j.read_procedures` **không đổi**. Dùng lại
  `network.hubs.lookback_days`, `network.hubs.pagerank_alpha`, `network.shared_attributes.max_customers_per_value`.
- File Cypher mới dưới `src/aml/graph/neo4j/cypher/gds/`: `version.cypher`, `project_accounts.cypher`,
  `project_accounts_undirected.cypher`, `project_shared.cypher`, `drop.cypher`, `degree.cypher`, `pagerank.cypher`,
  `wcc_accounts.cypher`, `louvain_accounts.cypher`, `wcc_shared.cypher`. Mỗi file đúng một statement, mọi giá trị qua
  `$tham_số`. `WRITE_PREFIXES` **không đổi**.
- DDL `sql/duckdb/ddl/150_gds.sql` và `sql/oracle/ddl/150_gds.sql`, thêm vào `SCHEMA_SCRIPTS` của cả hai backend sau
  `ddl/140_graph_sync.sql` và trước các script `050_*`: bảng `gds_runs`, bảng `gds_account_features`, view
  `gds_account_features_current`. File chèn `sql/duckdb/graph/insert_gds_run.sql` và bản Oracle.
- CLI: nhóm `aml graph` thêm `aml graph gds [--as-of YYYY-MM-DD]`. Không đụng các lệnh khác.
- `docker-compose.yml`, service `neo4j`: `NEO4J_PLUGINS: '["apoc"]'` và thêm volume
  `./docker/neo4j/plugins/neo4j-graph-data-science-2.13.13.jar:/plugins/graph-data-science.jar` (không `:ro`);
  `.gitignore` thêm `docker/neo4j/plugins/*.jar`.
- Tài liệu `docs/neo4j-gds.md`: GDS chạy in-memory trong session `READ` và vì sao không có gì được ghi vào Neo4j, đồ
  thị nào cho thuật toán nào, tính tất định (`concurrency`), quan hệ với `nx_account_features`, và cách lấy file jar
  (`docker cp` từ volume hiện có hoặc tải tay) kèm sha256 đầy đủ để người dùng tự đối chiếu.
- **Sửa kéo theo ở phần đã duyệt — là một phần của 6b-ii**: (1) `tests/neo4j_sync/test_read_path.py`: `guard/v1` →
  `guard/v2`, và `specs/neo4j-sync.md` (mục Đường đọc, AC8) thêm ghi chú tương ứng; (2) xoá chú thích `6b adds the
  prefix of its own` cạnh `WRITE_PREFIXES`; (3) container Neo4j phải được tạo lại (`up -d`) sau khi đổi
  `docker-compose.yml`, sau khi đã đặt file jar vào `docker/neo4j/plugins/`.

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **Đường đọc** (`run_read`, `run_read_file`): thêm `procedures` — allowlist thay cho `neo4j.read_procedures`; chỉ
  module GDS truyền `settings.gds.procedures`. Mọi lời gọi của 6b-ii chạy trong session `READ_ACCESS` với timeout của
  6b-i; không file nào của 6b-ii nằm trong `WRITE_PREFIXES`.
- **Guard `guard/v2`** — hai thay đổi, mọi hành vi khác của 6a giữ nguyên:
  1. Tên procedure đứng sau `CALL` **đã khớp allowlist** được bỏ khỏi văn bản trước khi quét `WRITE_KEYWORDS` (để
     `CALL gds.graph.drop(...)` qua được khi được phép). Tên không khớp allowlist vẫn bị chặn như cũ.
  2. Mọi tên bắt đầu bằng `gds.graph.` theo sau là `(` — dù đứng sau `CALL` hay dùng như hàm — phải khớp allowlist,
     nếu không → `procedure <tên> is not allowed in a read-only query`. Hàm `gds.util.*`, `gds.version` không bị xét.
  - `audit_log` của truy vấn bị chặn ghi `version='guard/v2'`.
- **GDS** (`run_gds`):
  1. `shared_driver` → `require_fresh` (lỗi → `GdsError` cùng thông điệp) → `gds/version.cypher` (không có GDS →
     `GdsError` chứa `GDS plugin not available`). Chưa ghi gì.
  2. Tên đồ thị: `<graph_prefix>_accounts`, `<graph_prefix>_accounts_undirected`, `<graph_prefix>_shared`. Xoá cả ba
     nếu còn sót (`gds/drop.cypher`, không lỗi khi thiếu) rồi dựng bằng Cypher projection:
     - `accounts` (có hướng): mỗi cặp tài khoản (gửi, nhận) có `SENT_TO` với `day` trong `[cutoff −
       network.hubs.lookback_days, cutoff)`, cả hai có `OWNS` từ **hai `Customer` khác nhau** → một quan hệ, thuộc
       tính `total_vnd` = tổng `total`, `transfers` = tổng `count`. Đây đúng là đồ thị hub của 5c.
     - `accounts_undirected`: cùng các cặp, vô hướng.
     - `shared`: `Customer` — giá trị, chỉ với giá trị có từ 2 tới `max_customers_per_value` khách hàng, vô hướng.
     - Projection trả `null` (không có cặp nào) → coi là đồ thị rỗng, bỏ qua các stream của nó.
  3. Stream (tất cả `concurrency` = `gds.concurrency`): `gds/degree.cypher` bốn lần trên `accounts` (`REVERSE` /
     `NATURAL` × không trọng số / `total_vnd`); `gds/pagerank.cypher` trên `accounts` (không trọng số,
     `dampingFactor` = `network.hubs.pagerank_alpha`, `maxIterations`, `tolerance` từ config);
     `gds/wcc_accounts.cypher` và `gds/louvain_accounts.cypher` (không trọng số) trên `accounts_undirected`;
     `gds/wcc_shared.cypher` trên `shared` (chỉ trả node `Customer`).
  4. Xoá cả ba đồ thị trong `finally` — kể cả khi một stream lỗi.
  5. Đọc `accounts`, `customers`, `customer_golden` qua `db` (CIF không có trong `customer_golden` → `'G-' + cif`),
     gọi `build_features`, cấp `run_id` = `MAX(run_id) + 1` của `gds_runs`, chèn `gds_account_features`, chèn 1 dòng
     `gds_runs`, ghi 1 dòng audit. Mọi lỗi ở bước 1–4 xảy ra trước lần ghi đầu tiên → không để lại dòng nào.
- **`build_features`** (một dòng cho **mọi** dòng của `accounts`, sắp theo `account_id`):
  - `in_degree`, `out_degree`, `in_vnd`, `out_vnd`: điểm của stream tương ứng, kiểu int; không có trong stream → 0.
  - `pagerank` = điểm ÷ tổng điểm của stream, làm tròn 8; `pagerank_ratio` = điểm ÷ tổng điểm × số dòng của stream
    `pagerank`, làm tròn 4; không có trong stream → 0.0. (Cùng định nghĩa với hai cột cùng tên của 5c.)
  - `wcc_id` = `account_id` nhỏ nhất (so chuỗi) của thành phần, `wcc_size` = số tài khoản của thành phần; không có
    trong stream → null và 0. `louvain_id`, `louvain_size` tương tự theo `community`.
  - `shared_cluster_id` = `'SHARED-'` + CIF nhỏ nhất trong mọi CIF của các khách hàng cùng `component` của stream
    `shared` (cùng cách đặt tên với `subject_id` của `NET_SHARED_ATTRIBUTE`), `shared_cluster_size` = số khách hàng
    của thành phần; gán cho mọi tài khoản của các khách hàng đó; khách hàng không có trong stream → null và 0. **Mọi
    cụm từ 2 khách hàng** đều được ghi, không áp `min_customers`.
  - Kiểu: các cột đếm và tiền int64, hai cột PageRank float64, ba cột `*_id` object (null là `None`).
- **Bảng** (DDL `150`; cùng tên cột trên hai backend; không bao giờ UPDATE / DELETE):
  - `gds_account_features(run_id, account_id, in_degree, out_degree, in_vnd, out_vnd, pagerank, pagerank_ratio,
    wcc_id, wcc_size, louvain_id, louvain_size, shared_cluster_id, shared_cluster_size)`, PK `(run_id, account_id)`.
  - View `gds_account_features_current` = các dòng có `run_id = MAX(run_id)` của chính bảng đó.
  - `gds_runs(run_id PK, run_ts UTC, as_of, source_backend, sync_run_id, txn_watermark, gds_version, accounts,
    active_accounts, wcc_components, louvain_communities, shared_clusters, seconds, params JSON)`; `params` = `{lookback_days,
    max_customers_per_value, pagerank_alpha, pagerank_max_iterations, pagerank_tolerance, louvain_max_levels,
    louvain_max_iterations, louvain_tolerance, concurrency, graphs}`.
- **Audit của GDS** (mỗi lần `run_gds` thành công 1 dòng): `module='graph'`, `entity_type='gds_run'`, `entity_id` =
  `run_id`, `decision='GDS_FEATURES_WRITTEN'`, `version='gds/v1'`, `actor` = tham số hoặc `audit.system_actor`,
  `details` = `{run_id, as_of, sync_run_id, watermark, gds_version, accounts, active_accounts, wcc_components,
  louvain_communities, shared_clusters, graphs}`, `reason` =
  `GDS {gds_version} on the Neo4j projection (sync run {sync_run_id}): wrote features for {accounts} accounts, {active_accounts} with transfers; {wcc_components} components, {louvain_communities} communities, {shared_clusters} shared-attribute clusters`.
- **CLI** `aml graph gds`: in `run_id= as_of= accounts= active= wcc_components= louvain_communities= shared_clusters=
  seconds= gds=<phiên bản>` rồi ba dòng `<tên đồ thị> nodes=<n> relationships=<n>`. `GdsError` → stderr, exit code 1;
  Neo4j không kết nối được → stderr chứa `neo4j not available`, exit code 1, không ghi gì.

## Tiêu chí nghiệm thu
<!-- MINI-G = như specs/neo4j-sync.md (MINI-SHR của 5c cộng T08, T09). MINI-HUB = `load_hub` của tests/network/helpers.py
(specs/network-detections.md) rồi `refresh_acct_edge_daily`. TINY = fixture `tiny_parquet` nạp bằng `load_parquet` rồi
`run_er` (`tiny_er`). `settings` = `load_settings(environ={"DB_BACKEND": "duckdb"})` trừ khi nói khác; test [neo4j] dùng
thêm `.env` để có mật khẩu (`neo_settings`). OFFLINE = thêm `AML__NEO4J__URI=bolt://127.0.0.1:1`. "Đã sync" =
`run_sync(db, settings, full=True)` của 6a trên Neo4j vừa wipe (fixture `neo`). Test có nhãn [neo4j] dùng
@pytest.mark.neo4j, [oracle] dùng @pytest.mark.oracle (tự skip khi dịch vụ không chạy) và được phép xoá sạch
projection dev. Các AC không nhãn chạy ở chế độ DuckDB-only và không cần Neo4j. -->
- AC1: Given `config.yaml`, `docker-compose.yml`, `.gitignore`, thư mục `sql/`, thư mục `cypher/gds/`, `docs/` của repo, hàm `assert_read_only` và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS`, phân tích `docker-compose.yml` bằng `yaml.safe_load`, gọi `load_statements`, `assert_read_only` và `apply_schema(duck)` hai lần, Then `settings.gds` = (`procedures` `["gds.graph.project", "gds.graph.drop", "gds.*.stream"]`, `graph_prefix` `"aml_gds"`, `concurrency` 1, `pagerank_max_iterations` 200, `pagerank_tolerance` 1e-10, `louvain_max_levels` 10, `louvain_max_iterations` 10, `louvain_tolerance` 0.0001); `load_settings(environ={"AML__GDS__CONCURRENCY": "5"})` raise `pydantic.ValidationError` chứa `concurrency must be between 1 and 4`, `load_settings(environ={"AML__GDS__GRAPH_PREFIX": "bad name"})` raise `pydantic.ValidationError` chứa `graph_prefix must be a plain identifier` và `load_settings(environ={"AML__GDS__PAGERANK_TOLERANCE": "0"})` raise `pydantic.ValidationError` chứa `pagerank_tolerance must be > 0`; trong `docker-compose.yml`, `services.neo4j.environment["NEO4J_PLUGINS"] == '["apoc"]'`, `services.neo4j.volumes` có phần tử `./docker/neo4j/plugins/neo4j-graph-data-science-2.13.13.jar:/plugins/graph-data-science.jar`, `services.neo4j.image` vẫn là `neo4j:5.26.31-community`, và `.gitignore` có dòng `docker/neo4j/plugins/*.jar`; `ddl/150_gds.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]`, đứng sau `ddl/140_graph_sync.sql` và trước `ddl/050_customers_masked.sql` / `ddl/050_security_objects.sql`; `apply_schema` không raise, `SELECT COUNT(*)` trên `gds_runs`, `gds_account_features` và `gds_account_features_current` đều trả 0, và `SELECT * FROM gds_account_features` có đúng các cột `run_id` cộng `GDS_FEATURE_COLUMNS` theo thứ tự; `ROLE_GRANTS` không chứa cặp nào có `gds_runs` hay `gds_account_features`; thư mục `cypher/gds/` có đúng 10 file `version.cypher`, `project_accounts.cypher`, `project_accounts_undirected.cypher`, `project_shared.cypher`, `drop.cypher`, `degree.cypher`, `pagerank.cypher`, `wcc_accounts.cypher`, `louvain_accounts.cypher`, `wcc_shared.cypher`, mỗi file cho đúng 1 statement mà `assert_read_only(statement, allowed_procedures=settings.gds.procedures)` không raise; không statement nào trong 10 file chứa `.write`, `.mutate`, `writeProperty` hay `mutateProperty`; với `allowed_procedures=settings.neo4j.read_procedures` thì statement của `drop.cypher`, `pagerank.cypher`, `degree.cypher`, `wcc_accounts.cypher`, `louvain_accounts.cypher`, `wcc_shared.cypher` raise `WriteBlockedError` chứa `procedure gds.` và statement của ba file `project_*.cypher` raise `WriteBlockedError` chứa `procedure gds.graph.project is not allowed in a read-only query`; `WRITE_PREFIXES == ("schema.cypher", "sync/")`; `GUARD_VERSION == "guard/v2"`; `assert_read_only("CALL gds.graph.drop('g', false) YIELD graphName RETURN graphName", allowed_procedures=("gds.graph.drop",))` không raise, cùng câu đó với `allowed_procedures=()` raise `WriteBlockedError` chứa `procedure gds.graph.drop`; `assert_read_only("MATCH (s)-[r]->(t) RETURN gds.graph.project('g', s, t) AS g", allowed_procedures=("gds.*.stream",))` raise `WriteBlockedError` chứa `procedure gds.graph.project`, và không raise với `allowed_procedures=("gds.graph.project",)`; `assert_read_only("CALL gds.wcc.stream('g') YIELD nodeId RETURN gds.util.asNode(nodeId).account_id AS a", allowed_procedures=("gds.*.stream",))` không raise; `assert_read_only("CALL gds.graph.drop('g') YIELD graphName MATCH (n) DETACH DELETE n", allowed_procedures=("gds.graph.drop",))` raise `WriteBlockedError` chứa `DETACH`; `assert_read_only("CALL gds.pageRank.write('g', {writeProperty: 'pr'})", allowed_procedures=settings.gds.procedures)` raise `WriteBlockedError` chứa `gds.pageRank.write`; `assert_read_only("DROP CONSTRAINT account_id_unique")` vẫn raise chứa `write clause DROP` và `assert_read_only("MATCH (n) RETURN n.set")` vẫn raise chứa `SET`; sáu statement của `cypher/queries/` (6b-i) vẫn qua `assert_read_only` với `settings.neo4j.read_procedures`; `docs/neo4j-gds.md` tồn tại, chứa các chuỗi `in-memory`, `concurrency`, `docker cp` và `17cfceb0c78e897baea3dfcdbd852dff779980bcc1eb444126338694bb053264`; và Given `tiny_env` đã `aml load` với OFFLINE, When chạy CLI, Then `aml graph --help` exit code 0 với stdout chứa `query` và `gds`, còn `aml graph gds` exit code 1 với stderr chứa `neo4j not available` và `gds_runs` không có dòng nào.
- AC2: Given hàm `build_features` (thuần pandas), `accounts` = 6 dòng (`A01`, `C01`), (`A02`, `C02`), (`A03`, `C03`), (`A04`, `C04`), (`A04S`, `C04`), (`A05`, `C05`) đưa vào theo thứ tự đảo ngược, `owner_of_cif` = {`C01`: `G-C01`, `C02`: `G-C01`, `C03`: `G-C03`, `C04`: `G-C04`, `C05`: `G-C05`} và `GdsStreams` với `in_degree` = [(`A01`, 2), (`A02`, 0), (`A03`, 1)], `out_degree` = [(`A01`, 1), (`A02`, 1), (`A03`, 1)], `in_vnd` = [(`A01`, 30000000), (`A02`, 0), (`A03`, 5000000)], `out_vnd` = [(`A01`, 5000000), (`A02`, 25000000), (`A03`, 5000000)], `pagerank` = [(`A01`, 3.0), (`A02`, 0.5), (`A03`, 1.5)], `wcc` = [(`A03`, 7), (`A02`, 7), (`A01`, 7)], `louvain` = [(`A01`, 11), (`A02`, 12), (`A03`, 11)], `shared` = [(`G-C04`, 40), (`G-C01`, 40)], When gọi `build_features(accounts, owner_of_cif, streams)`, Then kết quả có cột đúng bằng `GDS_FEATURE_COLUMNS`, 6 dòng sắp theo `account_id` (`A01`, `A02`, `A03`, `A04`, `A04S`, `A05`); dòng `A01` = (2, 1, 30000000, 5000000, 0.6, 1.8, `A01`, 3, `A01`, 2, `SHARED-C01`, 2); dòng `A02` = (0, 1, 0, 25000000, 0.1, 0.3, `A01`, 3, `A02`, 1, `SHARED-C01`, 2); dòng `A03` = (1, 1, 5000000, 5000000, 0.3, 0.9, `A01`, 3, `A01`, 2, `None`, 0); dòng `A04` và `A04S` = (0, 0, 0, 0, 0.0, 0.0, `None`, 0, `None`, 0, `SHARED-C01`, 2); dòng `A05` = (0, 0, 0, 0, 0.0, 0.0, `None`, 0, `None`, 0, `None`, 0); tổng cột `pagerank` bằng 1.0; kiểu của `in_degree`, `out_degree`, `in_vnd`, `out_vnd`, `wcc_size`, `louvain_size`, `shared_cluster_size` là int64, của `pagerank`, `pagerank_ratio` là float64, và ô null của ba cột `*_id` là `None` (không phải NaN); đổi mã `component` 7 → 99 và `community` 11 ↔ 12 trong đầu vào thì kết quả không đổi (mã của GDS không lọt vào kết quả); với `GdsStreams` có cả 8 frame rỗng, kết quả vẫn có 6 dòng, mọi cột số bằng 0 và ba cột `*_id` đều `None`; và `in_vnd` = [(`A01`, 5000000000)] (vượt 32 bit) cho `in_vnd` của `A01` bằng đúng 5000000000 kiểu int64.
- AC3: [neo4j] Given MINI-G đã sync, When gọi `run_gds(duck, settings, actor="analyst01")` rồi gọi lần hai, Then lần một trả `GdsRun` có `run_id = 1`, `as_of = date(2026, 6, 30)`, `accounts = 23`, `active_accounts = 6`, `wcc_components = 2`, `louvain_communities = 2`, `shared_clusters = 4`, `graphs = {"accounts": (6, 4), "accounts_undirected": (6, 8), "shared": (26, 44)}`, `sync_run_id = 1`, `watermark = datetime(2026, 7, 1, 10, 0, 0)`, `gds_version` bắt đầu bằng `2.13`; `gds_account_features` có 23 dòng `run_id = 1`, trong đó theo (`in_degree`, `out_degree`, `in_vnd`, `out_vnd`, `pagerank_ratio`, `wcc_id`, `wcc_size`, `louvain_id`, `louvain_size`, `shared_cluster_id`, `shared_cluster_size`): `A01` = (2, 1, 34000000, 5000000, 1.4938, `A01`, 4, `A01`, 4, `SHARED-C01`, 5) với `pagerank` cách 0.248963 không quá 1e-6; `A20` = (1, 0, 5000000, 0, 1.823, `A01`, 4, `A01`, 4, null, 0) với `pagerank` cách 0.303827 không quá 1e-6; `A04` = (1, 0, 1000000, 0, 1.0235, `A04`, 2, `A04`, 2, `SHARED-C01`, 5); `A02` = (0, 1, 0, 14000000, 0.5533, `A01`, 4, `A01`, 4, `SHARED-C01`, 5); `A01S` = (0, 0, 0, 0, 0.0, null, 0, null, 0, `SHARED-C01`, 5); `A07` = (0, 0, 0, 0, 0.0, null, 0, null, 0, `SHARED-C06`, 4); `A12` có (`SHARED-C12`, 2), `A19` có (`SHARED-C14`, 6), còn `A21`, `A22` có `shared_cluster_id` null; đúng 20 dòng có `shared_cluster_size >= 2` và tổng cột `pagerank` cách 1.0 không quá 1e-6; chuyển khoản T06 (2026-07-01, sau cutoff), T03 (tới `EXT-01`) và T05 (`A01` → `A01S`, cùng chủ) không được tính vào `A01`; `gds_account_features_current` trả đúng 23 dòng đó; `gds_runs` có 1 dòng (`run_id = 1`, `as_of = 2026-06-30`, `source_backend = 'duckdb'`, `sync_run_id = 1`, `accounts = 23`, `active_accounts = 6`, `shared_clusters = 4`, `params.concurrency = 1`, `params.lookback_days = 365`); `audit_log` có đúng 1 dòng `decision='GDS_FEATURES_WRITTEN'`: `module='graph'`, `entity_type='gds_run'`, `entity_id='1'`, `version='gds/v1'`, `actor='analyst01'`, `details.accounts = 23`, `reason` kết thúc bằng `wrote features for 23 accounts, 6 with transfers; 2 components, 2 communities, 4 shared-attribute clusters`; trong Neo4j sau lần chạy: `CALL gds.graph.list() YIELD graphName RETURN count(*) AS n` (chạy với `procedures=("gds.graph.list",)`) trả 0, `MATCH (n) RETURN count(n) AS n` vẫn trả 83, `MATCH ()-[r]->() RETURN count(r) AS n` vẫn trả 89, và tập tên thuộc tính của mọi node và mọi quan hệ bằng đúng hai tập của AC6 trong specs/neo4j-sync.md (không có `pagerank`, `componentId`, `communityId` hay thuộc tính mới nào); số dòng `alerts`, `nx_account_features`, `transactions` trong DuckDB không đổi; lần hai trả `run_id = 2` và 23 dòng `run_id = 2` có mọi cột ngoài `run_id` bằng đúng lần một, `gds_account_features` có 46 dòng và view current trả 23 dòng `run_id = 2`; `run_gds(duck, settings, as_of=date(2026, 7, 1))` trả `run_id = 3`, `active_accounts = 6`, `wcc_components = 1`, `louvain_communities = 2`, `graphs["accounts"] == (6, 5)`, và dòng `A01` có (`in_degree`, `in_vnd`, `wcc_size`) = (3, 41000000, 6); `run_gds(duck, settings, as_of=date(2026, 2, 28))` (trước mọi giao dịch) trả `run_id = 4`, `active_accounts = 0`, `wcc_components = 0`, `graphs["accounts"] == (0, 0)`, `shared_clusters = 4`, và 23 dòng của nó đều có `in_degree = 0`, `wcc_size = 0`; Given MINI-HUB đã sync, When gọi `run_gds` và `detect_network(duck, settings)`, Then `active_accounts = 51`, `wcc_components = 5`, `louvain_communities = 5`, `shared_clusters = 0`, `graphs["shared"] == (0, 0)`, dòng `P0` = (`in_degree` 10, `out_degree` 1, `in_vnd` 220000000, `out_vnd` 150000000, `pagerank_ratio` 12.1302, `wcc_id` `P0`, `wcc_size` 11), dòng `W0` có `in_degree = 8` (hai người gửi cùng chủ không tính), dòng `X09` có `in_degree = 0` và `wcc_id` null, và bốn cột `in_degree`, `out_degree`, `in_vnd`, `out_vnd` của cả 54 dòng bằng đúng `features` của `detect_network(duck, settings)`, còn `pagerank` lệch không quá 1e-7 và `pagerank_ratio` lệch không quá 2e-4; Given khi `run_read_file` bị monkeypatch để raise `GraphError` với tên `gds/pagerank.cypher`, When gọi `run_gds`, Then raise `GdsError`, `gds_runs` và `gds_account_features` không thêm dòng nào, không có dòng audit `GDS_FEATURES_WRITTEN` mới và `gds.graph.list()` vẫn trả 0 đồ thị; và Given Neo4j vừa wipe, When gọi `run_gds(duck, settings)`, Then raise `GdsError` chứa `graph not synced` và `gds_runs` không thêm dòng.
- AC4: [neo4j] Given TINY trong DuckDB đã sync và đã `run_network(duck, settings)`, When gọi `run_gds(duck, settings)` và so `gds_account_features_current` với `nx_account_features_current`, Then `GdsRun` có `accounts = 532`, `active_accounts = 298`, `wcc_components = 9`, `louvain_communities = 20`, `shared_clusters = 2`, `graphs = {"accounts": (298, 450), "accounts_undirected": (298, 900), "shared": (35, 66)}`; hai bảng có cùng 532 `account_id`, bốn cột `in_degree`, `out_degree`, `in_vnd`, `out_vnd` bằng nhau ở mọi dòng, `pagerank` lệch không quá 1e-7 và `pagerank_ratio` lệch không quá 2e-4 ở mọi dòng; tập tài khoản có `in_degree >= 10`, `pagerank_ratio >= 1.8` và `in_vnd >= 100000000` trong bảng GDS là đúng {`A4937939209`} = tập `is_hub = 1` của 5c; mọi dòng có `shared_cluster_size >= 5` trong bảng GDS có (`shared_cluster_id`, `shared_cluster_size`) bằng đúng bảng NetworkX (53 dòng `SHARED-CIF00000002`, 29) và mọi dòng có `shared_cluster_size > 0` của bảng NetworkX nằm trong số đó; bảng GDS có 63 dòng `shared_cluster_size >= 2` (thêm một cụm 2 khách hàng mà 5c không báo); dòng `A4937939209` = (`in_degree` 31, `out_degree` 3, `in_vnd` 2930380000, `out_vnd` 2851894000, `pagerank_ratio` 6.7651, `wcc_id` `A1043446740`, `wcc_size` 36, `louvain_id` `A1043446740`, `louvain_size` 36, `SHARED-CIF00000002`, 29); dòng `A1463821795` (merchant) = (34, 0, 38925000, 0, 7.3002, `A1463821795`, 35, `A1463821795`, 35, null, 0); dòng `A8201784530` = (1, 1, 399475000, 456916000, 1.6277, `A1070944972`, 4, `A1070944972`, 4, null, 0) và bốn tài khoản của vòng `GT-RND-0001` có cùng `wcc_id` và cùng `louvain_id`; `wcc_size` lớn nhất là 98 và `louvain_size` lớn nhất là 36; gọi `run_gds` lần hai cho bảng `run_id = 2` có mọi cột ngoài `run_id` bằng đúng `run_id = 1`; Given `tiny_env` đã `aml load`, `aml er`, `aml graph sync --full`, When chạy `aml graph gds`, Then exit code 0, stdout có một dòng chứa `run_id=1`, `as_of=2026-06-30`, `accounts=532`, `active=298`, `wcc_components=9`, `louvain_communities=20`, `shared_clusters=2`, `gds=2.13.13` và ba dòng chứa lần lượt `nodes=298 relationships=450`, `nodes=298 relationships=900`, `nodes=35 relationships=66`; `aml graph gds --as-of 2026-13-01` exit code 2 và `gds_runs` không thêm dòng; còn [oracle] [neo4j] Given TINY nạp vào Oracle (`load_parquet`, `run_er`, `apply_security`; skip với thông điệp nêu tên biến nếu thiếu `ORACLE_SYS_PASSWORD` hoặc `ORACLE_DEMO_PASSWORD`), `run_sync(oracle, oracle_settings, full=True)`, When gọi `run_gds(oracle, oracle_settings)`, Then `user_tables` có `GDS_RUNS` và `GDS_ACCOUNT_FEATURES`, `user_views` có `GDS_ACCOUNT_FEATURES_CURRENT`; `GdsRun` có `accounts = 532`, `active_accounts = 298`, `wcc_components = 9`, `louvain_communities = 20`, `shared_clusters = 2`; 532 dòng của `gds_account_features_current` trên Oracle (tên cột hạ về chữ thường, sắp theo `account_id`) bằng 532 dòng của lần chạy DuckDB ở mọi cột ngoài `run_id` (`pagerank` so với sai số 1e-9); dòng `gds_runs` của lần chạy đó có `source_backend = 'oracle'`; `run_gds(duck, settings)` trên DuckDB lúc này raise `GdsError` chứa `graph was synced from oracle but the database is duckdb`; trong `dba_tab_privs` (kết nối admin) không role nào trong `AML_APP`, `AML_ANALYST`, `AML_GRAPH_SYNC`, `AML_AUDITOR` có quyền trên `GDS_RUNS` hay `GDS_ACCOUNT_FEATURES`; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- **6b-i** (`specs/neo4j-queries.md`, đã xong trước spec này): method `neo4j` của trace, năm truy vấn Cypher, `aml graph
  query`, `read_timeout_seconds`, `check_fresh` / `require_fresh` — 6b-ii chỉ gọi lại, không sửa. **6c**: `aml bench`.
- **Alert từ GDS**: không ghi `alerts`, `alert_accounts`, `alert_evidence`, `monitoring_runs`; không rule mới `GDS_*`;
  không cờ `is_hub` trong bảng đặc trưng (ngưỡng là việc của 5c và Phase 7).
- Consolidation thành case, chấm điểm ưu tiên, dùng đặc trưng GDS trong mô hình (Phase 7 / 7b); chọn giữa
  `nx_account_features` và `gds_account_features`; bảng đặc trưng theo golden customer.
- Ghi bất cứ thứ gì vào database Neo4j từ GDS (`.write`), `.mutate`, lưu / nạp đồ thị in-memory (`gds.graph.export`,
  backup), model catalog, pipeline ML của GDS, node embedding (FastRP, node2vec), similarity, link prediction.
- Thuật toán khác: Leiden, Label Propagation, SCC, betweenness / closeness, ArticleRank, triangle count, k-core; PageRank
  và Louvain có trọng số; PageRank trên đồ thị đảo chiều (hub chiều ra); GDS trên đồ thị có tài khoản `EXT-`.
- Cho đường Text2Cypher (Phase 8) gọi GDS; thêm tên GDS vào `neo4j.read_procedures`; tiền tố mới trong `WRITE_PREFIXES`.
- Quyền Oracle trên `gds_runs`, `gds_account_features` cho các role của 2b; sửa `ROLE_GRANTS` / `020_grants.sql`.
- Tự sync khi đồ thị lệch; khoá chống chạy đồng thời `run_gds` với `aml graph sync`; đồ thị in-memory tồn tại giữa các
  lần chạy; ước lượng bộ nhớ (`.estimate`) trước khi dựng; chỉnh heap của container.
- Dựng image Neo4j riêng (Dockerfile); tự động tải file jar hay tự kiểm sha256 lúc khởi động (sha256 ghi trong tài
  liệu để người dùng đối chiếu tay); target mới trong `Makefile` / `tasks.ps1`; nâng phiên bản Neo4j / GDS; Neo4j
  Enterprise, GDS có license.
- Đo trên profile `dense` / `large`; ghi số liệu vào README (làm ở bước demo của phase, từ lần chạy thật của code đã
  hiện thực trên `small`, rồi chép vào `docs/neo4j-gds.md`).

## Giả định
- **Đã đo trên Neo4j 5.26.31 Community + GDS 2.13.13 + driver 6.4.0** (mục Hiện trạng): mọi giá trị và phép so khớp
  của AC3 và AC4 (phần DuckDB) — bằng prototype ngoài repo dùng đúng các câu Cypher và đúng phép ghép đặc trưng mô tả
  ở mục Thiết kế, không phải bằng code của repo; GDS chạy trong session `READ_ACCESS`; hành vi hiện tại của guard với
  `gds.graph.drop` và hàm `gds.graph.project`; GDS nạp từ file jar bind-mount. Phiên bản khác có thể cho kết quả khác
  — image đã ghim ở 6a, GDS được ghim bởi spec này.
- **Suy ra từ thiết kế, chưa đo** (chưa có code): chuỗi `reason`, thông điệp lỗi, số dòng `audit_log` và `gds_runs`,
  định dạng stdout / stderr và exit code của CLI, thông điệp `ValidationError`, hành vi guard `guard/v2` trong AC1,
  `sync_run_id` / `watermark` của `GdsRun`. AC2 là số học thuần trên dữ liệu viết tay.
- **Chưa kiểm trên Oracle** (chỉ chạy `SELECT`): DDL `150`, chèn `BINARY_DOUBLE` / JSON vào `gds_*`, và toàn bộ phần
  [oracle] của AC4. 6a đã đo: sync TINY từ Oracle và từ DuckDB cho cùng ảnh đồ thị — phần [oracle] dựa vào đó.
- 6b-i đã được hiện thực và duyệt trước: `require_fresh` từ chối đồ thị chưa sync / sync từ backend khác / lệch số
  chuyển khoản. Phép kiểm đó không thấy `SENT_TO` lệch `TRANSFERRED_TO` (chưa refresh `acct_edge_daily`) — khi đó
  đặc trưng GDS lệch mà không có cảnh báo.
- GDS chạy trên ảnh chụp của lần sync gần nhất; `as_of` chỉ cắt chuyển khoản (thuộc tính khách hàng và `OWNS` không có
  lịch sử), như 5c. Thời gian trong mục Hiện trạng là số đo trên máy dev; AC chỉ cam kết cho MINI-G, MINI-HUB và TINY
  seed 42, số của `small` không phải cam kết.
- Kết quả tất định với cùng dữ liệu và cùng cấu hình khi `gds.concurrency = 1` (đã đo: hai lần chạy cho frame giống
  hệt trên MINI-G, TINY, `small`). Đặt `concurrency` lớn hơn 1 thì `louvain_id` / `louvain_size` không còn tất định
  (đã đo); các cột khác vẫn vậy. `settings.seed` không tham gia: không thuật toán nào được chọn có tham số seed.
- `louvain_id`, `wcc_id` là tài khoản nhỏ nhất của nhóm nên ổn định qua các lần sync lại, nhưng **đổi khi thành viên
  đổi**; chúng là nhãn nhóm của một lần chạy, không phải danh tính lâu dài.
- `shared_cluster_id` có ở mọi cụm từ 2 khách hàng (phần lớn là cặp trùng địa chỉ lành tính): nơi dùng phải dựa vào
  `shared_cluster_size`, không dựa vào "có mã cụm hay không".
- Test [neo4j] xoá sạch projection trong Neo4j dev và để lại projection của dữ liệu test; sau `pytest` có Neo4j,
  người dùng chạy lại `aml graph sync --full` (như 6a). Test [oracle] nạp lại TINY vào `aml_owner`, để lại dòng trong
  `gds_runs`, `gds_account_features`, `graph_sync_runs`, `audit_log`.
- Không có hai lần `run_gds` chạy đồng thời (tên đồ thị in-memory cố định, `run_id` cấp bằng `MAX + 1`), và không có
  `aml graph sync` chạy trong lúc `run_gds`.
- File jar GDS 2.13.13 không nằm trong git (65,8 MB): người dùng đặt nó vào `docker/neo4j/plugins/` một lần (chép từ
  volume `neo4jplugins` hiện có bằng `docker cp`, hoặc tải tay) và đối chiếu sha256 với tài liệu trước `up`; thiếu file
  thì Docker tạo thư mục trùng tên và GDS không nạp được — `run_gds` báo `GDS plugin not available`, phần còn lại của
  Phase 6 (sync, trace, truy vấn) vẫn chạy. Container Neo4j được tạo lại khi hiện thực spec này.
- Tên file `.cypher`, tên đồ thị, tên cột và `WRITE_KEYWORDS` là cấu trúc (hằng trong code); tham số GDS là cấu hình.
  `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có.

## Câu hỏi mở
- [x] Q1. Một spec hay tách đôi? — đề xuất mặc định: tách thành `neo4j-queries` và `neo4j-gds`. Lý do: 6c chỉ cần phần truy vấn; phần GDS mang toàn bộ rủi ro hạ tầng (tạo lại container, đổi guard đã duyệt, DDL mới, phần chưa đo trên Oracle). — Trả lời: tách đôi; spec này là 6b-ii, xây trên 6b-i đã xong (2026-10-12).
- [x] Q2. Đồ thị chưa sync, sync từ backend khác, hoặc lệch số chuyển khoản thì `run_gds` làm gì? — đề xuất mặc định: **từ chối** bằng `GdsError` mang thông điệp của `require_fresh` (6b-i), không tự sync, không ghi dòng nào. Lý do: đặc trưng ghi về hệ thống gốc chỉ đúng khi đồ thị khớp nguồn. — Trả lời: theo đề xuất mặc định, cùng quyết định với Q4 của 6b-i (2026-10-12).
- [x] Q3. 6b có sinh alert mới không? — đề xuất mặc định: **không** — truy vấn chỉ trả kết quả, GDS chỉ ghi đặc trưng. Lý do: 5c đã sinh alert `NETWORK` (`NET_CYCLE`, `NET_SHARED_ATTRIBUTE`, `NET_HUB`) và GDS cho đúng cùng tài khoản (đã đo: hub 5 / 5, cụm 5 / 5, vòng 15 / 15) → alert từ Neo4j chỉ là bản trùng mà Phase 7 phải khử; Neo4j là projection có độ trễ, không nên là nguồn alert. Phương án thay thế: thêm nguồn `GRAPH` qua `record_run` với `alert_key` trùng 5c để gộp. — Trả lời: theo đề xuất mặc định — không sinh alert (2026-10-12).
- [x] Q4. Bảng đặc trưng: tên, khoá, quan hệ với `nx_account_features`? — đề xuất mặc định: bảng riêng `gds_account_features`, khoá `(run_id, account_id)`, một dòng cho mọi tài khoản trong `accounts` (cùng hạt với 5c), kèm `gds_runs` và view `gds_account_features_current`; `run_id` riêng của `gds_runs`. Sáu cột `in_degree`, `out_degree`, `in_vnd`, `out_vnd`, `pagerank`, `pagerank_ratio` trùng tên và trùng định nghĩa với 5c (để đối chiếu chéo); cột mới là `wcc_*`, `louvain_*` và cụm dùng chung ở mọi cỡ. Phase 7 chọn nguồn. Phương án thay thế: bảng theo golden customer (Phase 7 gộp case theo khách hàng, nhưng mất chi tiết tài khoản và không so được với 5c); hoặc chỉ ghi các cột mới. — Trả lời: theo đề xuất mặc định — `gds_account_features` khoá `(run_id, account_id)`, kèm `gds_runs` và view `_current`, sáu cột trùng định nghĩa với `nx_account_features` (2026-10-12).
- [x] Q5. PageRank / degree tính trên đồ thị nào? — đề xuất mặc định: đúng đồ thị hub của 5c — tài khoản trong `accounts`, cặp khác chủ, `lookback_days` trước cutoff, không trọng số, dựng từ `SENT_TO`. Lý do: cho kết quả đối chiếu được từng dòng với NetworkX (đã đo: bằng nhau trên 8958 tài khoản của `small`); pool `EXT-` dùng chung của dữ liệu tổng hợp sẽ thành hub giả nếu đưa vào. Phương án thay thế: toàn bộ node `Account` kể cả `EXT-`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q6. WCC và Louvain "cho ring" chạy trên đồ thị nào? — đề xuất mặc định: WCC trên đồ thị khách hàng – giá trị dùng chung (→ `shared_cluster_*`, đã đo trùng 260 cụm của 5c) **và** trên đồ thị tài khoản (→ `wcc_*`); Louvain chỉ trên đồ thị tài khoản, không trọng số (→ `louvain_*`). Lý do: Louvain trên đồ thị dùng chung cho đúng phân hoạch của WCC (đã đo) nên không đáng một cột; trên đồ thị tài khoản nó tách hai thành phần 2179 tài khoản thành cộng đồng ≤ 82 và giữ trọn từng mule ring. Phương án thay thế: Louvain có trọng số theo số tiền (278 cộng đồng thay vì 151). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q7. Làm sao để GDS tất định? — đề xuất mặc định: `gds.concurrency: 1`; PageRank `maxIterations: 200`, `tolerance: 1e-10`; mã nhóm là tài khoản / CIF nhỏ nhất của nhóm thay cho mã nội bộ của GDS. Lý do: đã đo — Louvain với `concurrency: 4` cho 135 / 135 / 134 cộng đồng qua ba lần chạy và không có tham số `randomSeed`; PageRank mặc định chưa hội tụ (lệch tới 10,5 %); cả lượt chỉ mất 1,7–2,5 giây trên `small` nên một luồng là đủ. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q8. `shared_cluster_id` ghi cho cụm nào? — đề xuất mặc định: mọi cụm từ 2 khách hàng, kèm `shared_cluster_size`; không áp `min_customers = 5` của 5c. Lý do: cỡ cụm là đặc trưng, ngưỡng là quyết định của nơi dùng. Hệ quả đã đo: `small` có 1264 tài khoản mang mã cụm (5c: 194), phần lớn là cặp trùng địa chỉ lành tính — Phase 7 phải dùng `shared_cluster_size`, không dùng "có mã cụm hay không". — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q9. Đồ thị in-memory của GDS đi qua đường nào? — đề xuất mặc định: `run_read_file` trong session `READ` với allowlist riêng `gds.procedures` (`gds.graph.project`, `gds.graph.drop`, `gds.*.stream`); `WRITE_PREFIXES` và `neo4j.read_procedures` không đổi. Lý do: đã đo — project, stream, drop chạy được trong session `READ` còn `.write` bị server từ chối, nên lớp bảo vệ thật vẫn nguyên; allowlist riêng giữ cho Text2Cypher của Phase 8 không gọi được GDS. Phương án thay thế: thêm tiền tố `gds/` vào `WRITE_PREFIXES` (chạy bằng session ghi, không qua guard). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q10. Sửa guard đã duyệt của 6a? — đề xuất mặc định: có, hai điểm, và nâng `guard/v1` → `guard/v2`: (1) tên procedure đã khớp allowlist không bị quét từ khoá (`gds.graph.drop` đang bị chặn nhầm vì chữ `drop`); (2) `gds.graph.*(` dùng như hàm cũng phải khớp allowlist (hiện `RETURN gds.graph.project(...)` qua guard với allowlist rỗng). Hệ quả: sửa một dòng của `tests/neo4j_sync/test_read_path.py`. Phương án thay thế: giữ `guard/v1` và cho `gds/drop.cypher` chạy ngoài guard. — Trả lời: theo đề xuất mặc định; việc sửa guard và `tests/neo4j_sync/test_read_path.py` thuộc 6b-ii vì sáu truy vấn của 6b-i đã qua `guard/v1` (2026-10-12).
- [x] Q11. Ghim GDS và bỏ việc tải mạng lúc khởi động? — đề xuất mặc định: bỏ `graph-data-science` khỏi `NEO4J_PLUGINS`, bind-mount `docker/neo4j/plugins/neo4j-graph-data-science-2.13.13.jar` (git-ignore; sha256 ghi trong tài liệu) vào `/plugins/graph-data-science.jar`. Lý do: đã thử trên container tạm — GDS 2.13.13 nạp được, không còn dòng `Fetching versions.json`; hiện mỗi lần khởi động đều gọi `graphdatascience.ninja`, trái quy tắc "no external API calls" và phiên bản có thể trôi. Cái giá: một bước tay lấy file jar; thiếu file thì GDS không nạp; phải tạo lại container. Phương án thay thế: Dockerfile riêng tải jar lúc build (chưa thử); hoặc để nguyên và ghi nhận ngoại lệ. — Trả lời: theo đề xuất mặc định — bỏ `graph-data-science` khỏi `NEO4J_PLUGINS`, bind-mount file jar 2.13.13 (git-ignore), ghi hướng dẫn lấy jar và sha256 để đối chiếu; container được tạo lại khi hiện thực 6b-ii (2026-10-12).
- [x] Q12. Tên lệnh CLI? — đề xuất mặc định: `aml graph gds [--as-of]` trong nhóm `aml graph`. Lý do: nhóm này giữ mọi thứ chỉ có ở Neo4j. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q13. Ghi `audit_log` những gì? — đề xuất mặc định: 1 dòng `GDS_FEATURES_WRITTEN` cho mỗi `run_gds` thành công, kèm lần sync và phiên bản GDS; lần chạy lỗi không ghi. Lý do: đặc trưng ghi về hệ thống gốc phải truy được về lần sync và phiên bản GDS. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q14. Cấp quyền Oracle trên `gds_runs` / `gds_account_features` cho role nào? — đề xuất mặc định: chưa cấp cho role nào (như `nx_account_features` của 5c); `run_gds` và Phase 7 chạy bằng kết nối owner. Lý do: `ROLE_GRANTS` có test so khớp chính xác với `dba_tab_privs`; `aml_graph_sync` chỉ đọc nguồn và không cần ghi. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q15. `as_of` của `run_gds` nghĩa là gì? — đề xuất mặc định: mặc định `data.reference_date`; chỉ cắt chuyển khoản (`day` trước ngày `as_of + 1`, và trong `lookback_days` trước đó); thuộc tính khách hàng luôn là hiện trạng. Lý do: giống hệt 5c nên so được. — Trả lời: theo đề xuất mặc định (2026-10-12).
