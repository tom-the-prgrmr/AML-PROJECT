---
id: neo4j-sync
status: approved
approved_by: pthieu
---

# Phase 6a — Sync Oracle → Neo4j: projection chỉ đọc, guard chặn write clause, `aml graph sync`

## Bối cảnh
Phase 6 của PROJECT_BRIEF.md (mục 7, "Neo4j projection & benchmark") được tách làm ba spec như Phase 5: **6a (spec
này)** dựng projection trong Neo4j từ hệ thống gốc và chốt interface Python để đọc nó; 6b là các truy vấn `.cypher`
(fund-flow trace bản thứ tư, vòng 3–5, cụm thuộc tính dùng chung, fan-in/fan-out) và GDS ghi đặc trưng về Oracle; 6c là
benchmark `aml bench`. 6a nạp năm loại node (`Customer` theo golden customer của Phase 4, `Account`, `Device`, `Phone`,
`Address`) và sáu loại quan hệ (`OWNS`, `USES_DEVICE`, `HAS_PHONE`, `LIVES_AT`, `TRANSFERRED_TO`, `SENT_TO`) bằng
`UNWIND` + `MERGE` (chạy lại không sinh trùng), tăng dần theo `txn_ts`, đọc Oracle qua user chỉ đọc
`aml_graph_sync_usr` của 2b. Neo4j Community không có RBAC nên tính "chỉ đọc" của đường điều tra đến từ hai lớp:
session `READ` access mode (server từ chối ghi — đã đo) và guard tầng ứng dụng từ chối write clause trước khi gửi đi.
Người dùng: 6b / 6c / assistant Phase 8 / UI Phase 9 gọi `run_read` và `run_read_file`; người vận hành chạy
`aml graph sync`; người phỏng vấn xem số đo sync lag và đánh đổi consistency. Oracle vẫn là system of record: sync
không ghi gì vào bảng nghiệp vụ, không tạo alert, không đóng gì.

### Hiện trạng đã kiểm (2026-10-12, seed 42)
Đo bằng script tạm ngoài repo: một prototype dựng các DataFrame node / quan hệ đúng theo thiết kế dưới đây và một
prototype `run_sync` đầy đủ (Cypher viết thẳng trong script, đúng các câu lệnh mô tả ở mục Thiết kế) chạy trên **Neo4j
thật**. Trên Oracle chỉ chạy `SELECT`. Sau khi đo, Neo4j đã được xoá sạch (0 node, 0 constraint, 0 index ngoài hai
index LOOKUP mặc định).
- **Dịch vụ** (`uv run aml status`): Oracle **UP** (`localhost:1521/FREEPDB1`, 23.26.3.0.0); Neo4j **UP**
  (`bolt://localhost:7687`, container `aml-toolkit-neo4j-1`, **Neo4j 5.26.31 Community**, bolt 5.8); Ollama DOWN.
  Driver Python `neo4j` **6.4.0** làm việc với server này. `RETURN apoc.version()` = **5.26.31** (APOC core lấy từ
  thư mục `labs` có sẵn trong image, không tải mạng); `RETURN gds.version()` = **2.13.13** (entrypoint tải
  `versions.json` và file jar từ `graphdatascience.ninja` khi khởi động — phiên bản không ghim).
- **docker-compose** (profile `graph` / `full`): image `neo4j:5.26-community` (tag trôi theo bản vá), heap 512m–1g,
  page cache 512m, `mem_limit` 2500m. Log khởi động có dòng `Anonymous Usage Data is being sent to Neo4j` và
  `SHOW SETTINGS` cho `dbms.usage_report.enabled = true` — trái quy tắc "no external API calls". Đã thử trên một
  container tạm (đã xoá): với biến môi trường `NEO4J_dbms_usage__report_enabled=false`, `SHOW SETTINGS` cho `false` và
  dòng log đó không còn.
- **Năm điểm kỹ thuật đã kiểm trên Neo4j 5.26.31 Community**:
  1. Constraint duy nhất trên thuộc tính **quan hệ** dùng được (`SHOW CONSTRAINTS` cho type
     `RELATIONSHIP_UNIQUENESS`); tạo quan hệ thứ hai cùng `txn_id` bị từ chối với
     `Neo.ClientError.Schema.ConstraintValidationFailed`.
  2. Ghi trong session `READ_ACCESS` trên server đơn **bị server từ chối**: `CREATE`, `MERGE`, `SET` qua
     `execute_read` và qua `session.run` đều raise `neo4j.exceptions.ClientError`, mã
     `Neo.ClientError.Statement.AccessMode`, thông điệp `Writing in read access mode not allowed. Attempted write to
     neo4j`; sau đó không có node hay thuộc tính nào được tạo. Trong session đó `MATCH`, `CALL db.labels()` và
     `SHOW CONSTRAINTS` vẫn chạy.
  3. Driver 6.4.0: `datetime` naive → `LOCAL DATETIME`, `date` → `DATE`, `int` 64 bit và `list[str]` giữ nguyên;
     đọc ra là `neo4j.time.DateTime` / `neo4j.time.Date` (phải `.to_native()` để thành kiểu Python).
  4. `CALL (x) { } IN TRANSACTIONS OF n ROWS` chạy được trong transaction tự commit (`session.run`), và **bị từ
     chối** trong `execute_write` (`Neo.DatabaseError.Transaction.TransactionStartFailed`). Dạng `CALL { WITH x }`
     không khai báo phạm vi bị 5.26 báo deprecated. **`DETACH DELETE` 10 000 node mỗi transaction làm hết bộ nhớ**
     trên `small` (`Neo.TransientError.General.MemoryPoolOutOfMemoryError`, mỗi tài khoản kéo theo hàng chục quan hệ)
     → phải xoá quan hệ theo từng kiểu trước, node sau (thiết kế `wipe` đã đổi theo).
  5. Thời gian (mỗi cấu hình đo một lần, máy dev, heap 1 GB; `small` batch 5000 đo hai lần):

     | bộ dữ liệu, nguồn | batch | FULL (giây) | trong đó `TRANSFERRED_TO` / `SENT_TO` / wipe | INCREMENTAL không có gì mới |
     |---|---|---|---|---|
     | MINI-G, DuckDB | 5000 | 0,3 | — | 0,1–0,3 |
     | TINY, DuckDB | 1000 / 5000 | 2,2 / 1,4 | 0,4–0,6 / 0,2–0,4 / 0,1–0,3 | 0,5 |
     | TINY, Oracle (kết nối owner) | 5000 | 1,4 | 0,3 / 0,2 / 0,2 | 0,4 |
     | `small`, DuckDB | 1000 | 55,4 | 20,5 / 23,4 / 5,1 | — |
     | `small`, DuckDB | 5000 | 46,1 và 49,0 | 19,5–19,8 / 17,0–17,3 / 4,6–6,4 | 1,8 |
     | `small`, DuckDB | 20 000 | 49,5 | 19,5 / 20,3 / 4,7 | — |
     | `dense`, DuckDB | 5000 | 43,7 (đồ thị trống, không wipe) | 20,5 / 17,3 / — | 1,8 |

     Cỡ batch gần như không đổi kết quả (5000 nhỉnh hơn một chút); `MERGE` quan hệ đạt khoảng 11–12 nghìn quan hệ /
     giây. Lần INCREMENTAL không có gì mới trên `small` đọc lại 17 chuyển khoản và 1096 cạnh ngày, phần lớn 1,8 giây
     là nạp lại phía khách hàng. Bộ nhớ container sau các lần đo: 1,75–2,09 GiB trên giới hạn 2,44 GiB.
- **Kịch bản đã chạy thật trên Neo4j**: toàn bộ chuỗi của AC6 và AC7 trên MINI-G (FULL, chạy lại, giao dịch tới muộn,
  `--full`, prune, sweep, lỗi giữa chừng rồi chạy lại) cho **đúng các con số ghi trong AC**; TINY từ DuckDB và từ
  Oracle cho năm tập ảnh đồ thị bằng nhau (273 / 1314 / 1357 / 3651 / 3575 phần tử) — lần Oracle đọc bằng **kết nối
  owner** trên bảng `customers`, vì view `graph_customer_attrs` và ba quyền mới chưa tồn tại; chặn "đổi nguồn không
  `--full`" hoạt động.
- **Code sẵn có**: `Neo4jConfig` chỉ có `uri`, `user`, `password`; `aml.common.services.neo4j_status`; marker `neo4j`
  trong `tests/conftest.py` tự skip; `ServiceUnavailableError` trong `aml.common.db`. Chưa có `src/aml/graph/neo4j/`,
  chưa có file `.cypher` nào. `SCHEMA_SCRIPTS` đã dùng `000`–`130` → 6a dùng **`140`**. `aml graph` và `aml bench` là
  stub chung in `arrives in Phase 6` (exit 1), và `tests/graph/test_cli.py` (dòng 107–111) đang khẳng định cả hai
  lệnh in `Phase 6`.
- **Cột thời gian ở nguồn**: `transactions.txn_ts` (`TIMESTAMP(0)`, thời điểm nghiệp vụ, giờ Việt Nam naive) là cột
  thời gian **duy nhất** của các bảng nguồn; không bảng nào có cột thời điểm nạp / sửa. `customers` không có cột thời
  gian nào; `accounts` chỉ có `open_date`; `acct_edge_daily` có `day`; `er_runs` có `run_id` / `run_ts`. `aml load`
  luôn xoá sạch rồi nạp lại toàn bộ.
- **Quyền của user sync** (đăng nhập thật bằng `aml_graph_sync_usr`, `ALTER SESSION SET CURRENT_SCHEMA = aml_owner`):
  đọc được `transactions`, `acct_edge_daily`, `accounts`, `customers_masked`; **ORA-00942** với `customer_golden`,
  `customers`, `admin_unit_mapping`, `er_runs`, `audit_log`. `customers_masked` không có `device_id`, `street`, và
  `phone` chỉ còn 3 số cuối → với 4 quyền hiện tại user sync không dựng được `Customer` (golden), `Device`, `Phone`,
  `Address` (Q2). `tests/security/test_oracle_security.py` đang khẳng định đúng 4 quyền này.
- **Dữ liệu nguồn và kích thước projection** (số node / quan hệ của cả bốn bộ đã được đếm lại **trong Neo4j** sau
  khi sync; Oracle hiện chứa TINY; `small` = bản sao `data/aml.duckdb`; `dense` sinh vào thư mục tạm rồi `aml load`
  + `aml er`):

  | | MINI-G | TINY | `small` | `dense` |
  |---|---|---|---|---|
  | `customers` / `accounts` / `transactions` | 22 / 23 / 9 | 300 / 532 / 5100 | 5000 / 8958 / 306 000 | 5000 / 8958 / chưa đếm |
  | giao dịch một phía null (không thành quan hệ) | 1 | 1449 | 91 411 | chưa đếm |
  | `Customer` (có > 1 CIF) | 20 (1) | 273 (22) | 4545 (364) | 4545 (364) |
  | `Account` (trong `accounts` + ngoài) | 24 (23 + 1) | 1314 (532 + 782) | 10 958 (8958 + 2000) | 10 958 |
  | `Device` / `Phone` / `Address` | 14 / 10 / 14 | 264 / 267 / 265 | 4653 / 4515 / 4243 | 4653 / 4515 / 4243 |
  | `OWNS` / `USES_DEVICE` / `HAS_PHONE` / `LIVES_AT` | 23 / 17 / 17 / 17 | 532 / 279 / 273 / 273 | 8958 / 4685 / 4545 / 4548 | 8958 / 4685 / 4545 / 4548 |
  | `TRANSFERRED_TO` | 8 | 3651 | 214 589 | 228 235 |
  | `SENT_TO` (= dòng `acct_edge_daily`) | 7 | 3575 | 205 726 | 223 766 |
  | `txn_ts` lớn nhất (= watermark sau FULL) | 2026-07-01 10:00:00 | 2026-06-30 21:53:57 | 2026-06-30 23:56:20 | 2026-06-30 23:54:35 |
  | số `TRANSFERRED_TO` nhiều nhất chạm một tài khoản | 7 | 120 | 390 | 174 |

  - Mọi mã tài khoản không có trong `accounts` đều bắt đầu bằng `EXT-` (0 ngoại lệ trên MINI-G / TINY / `small`).
    Không có self-transfer. Tổng `txn_count` của `acct_edge_daily` bằng đúng số giao dịch hai phía.
  - TINY: đúng 1 khoá thiết bị có ≥ 2 khách hàng (16 khách hàng), 1 khoá điện thoại (7), 2 khoá địa chỉ (lớn nhất 8) —
    khớp `details.links` của alert `SHARED-CIF00000002` ở 5c, tức projection dùng cùng khoá với NetworkX.
  - `golden_customer_id` có dạng `G-CIF00000001`. ER trên Oracle và DuckDB cho cùng golden id.
- **Vẫn chưa đo**: DDL `140` và ba quyền mới trên Oracle, đường đọc qua `aml_graph_sync_usr` (AC10), việc ghi
  `graph_sync_runs` / `audit_log`, output CLI, hàm guard (chỉ là thiết kế), profile `large` (xem Giả định).

### Interface đề xuất (để test và 6b / 6c gọi trực tiếp)
```python
# src/aml/common/config.py
class Neo4jConfig(BaseModel):
    uri: str
    user: str
    password: str
    database: str = "neo4j"
    read_procedures: list[str]  # mẫu fnmatch của procedure được CALL trên đường đọc


class GraphSyncConfig(BaseModel):
    oracle_user: str  # user chỉ đọc; mật khẩu = db.oracle.demo_password (ORACLE_DEMO_PASSWORD)
    batch_size: int  # số dòng mỗi lần UNWIND = một transaction; 1..50000
    overlap_minutes: int  # incremental đọc lại từ (watermark - overlap); >= 0


class Settings(BaseModel):
    ...
    graph_sync: GraphSyncConfig


# src/aml/graph/neo4j/guard.py  (thuần Python, không import driver)
WRITE_KEYWORDS: tuple[str, ...]  # CREATE, MERGE, SET, DELETE, DETACH, REMOVE, DROP, FOREACH, LOAD,
#                                  ALTER, RENAME, GRANT, DENY, REVOKE, TERMINATE


class GraphError(RuntimeError): ...


class WriteBlockedError(GraphError): ...


def assert_read_only(cypher: str, *, allowed_procedures: Sequence[str] = ()) -> None: ...


# src/aml/graph/neo4j/client.py
CYPHER_ROOT: Path  # src/aml/graph/neo4j/cypher
WRITE_PREFIXES: tuple[str, ...]  # ("schema.cypher", "sync/"); 6b thêm tiền tố của nó


def cypher_file(name: str) -> Path: ...  # FileNotFoundError nếu không có
def split_statements(text: str) -> list[str]: ...  # mỗi statement kết thúc bằng ';' ở cuối dòng
def load_statements(name: str) -> list[str]: ...
def open_driver(
    settings: Settings,
) -> neo4j.Driver: ...  # ServiceUnavailableError nếu không kết nối được
def run_read(
    driver: neo4j.Driver,
    settings: Settings,
    cypher: str,
    params: Mapping[str, Any] | None = None,
    *,
    audit_db: Database | None = None,
    actor: str | None = None,
) -> pd.DataFrame: ...  # guard + session READ; cột = khoá RETURN
def run_read_file(
    driver: neo4j.Driver, settings: Settings, name: str, params: Mapping[str, Any] | None = None
) -> pd.DataFrame: ...  # file đúng 1 statement; cũng qua guard
def run_write_file(
    driver: neo4j.Driver,
    settings: Settings,
    name: str,
    params: Mapping[str, Any] | None = None,
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, int]: ...  # chỉ nhận tên file thuộc WRITE_PREFIXES; trả bộ đếm cộng dồn


# src/aml/graph/neo4j/extract.py  (không cần Neo4j)
NODE_LABELS = ("Customer", "Account", "Device", "Phone", "Address")
REL_TYPES = ("OWNS", "USES_DEVICE", "HAS_PHONE", "LIVES_AT", "TRANSFERRED_TO", "SENT_TO")
COLUMNS: dict[str, list[str]] = {
    "Customer": ["golden_customer_id", "cifs", "cif_count"],
    "Account": [
        "account_id",
        "cif",
        "account_type",
        "branch_id",
        "open_date",
        "currency",
        "is_external",
    ],
    "Device": ["key"],
    "Phone": ["key"],
    "Address": ["key"],
    "OWNS": ["golden_customer_id", "account_id", "cif"],
    "USES_DEVICE": ["golden_customer_id", "key"],
    "HAS_PHONE": ["golden_customer_id", "key"],
    "LIVES_AT": ["golden_customer_id", "key"],
    "TRANSFERRED_TO": ["txn_id", "src", "dst", "amount", "ts", "channel"],
    "SENT_TO": ["src", "dst", "day", "count", "total"],
}


class SyncError(GraphError): ...


@dataclass(frozen=True)
class Projection:
    frames: dict[
        str, pd.DataFrame
    ]  # 11 khoá = NODE_LABELS + REL_TYPES, cột theo COLUMNS, đã sắp xếp
    er_run_id: int
    max_ts: datetime | None  # txn_ts lớn nhất trong các chuyển khoản đã đọc


def attribute_key(kind: str, value: str) -> str: ...  # kind: "device" | "phone" | "address"
def open_source(
    db: Database, settings: Settings
) -> Database: ...  # DuckDB: chính db; Oracle: user chỉ đọc
def build_projection(source: Database, *, since: datetime | None = None) -> Projection: ...
def to_rows(frame: pd.DataFrame) -> list[dict[str, Any]]: ...  # kiểu Python thuần cho driver
def batches(rows: Sequence[T], size: int) -> Iterator[Sequence[T]]: ...


# src/aml/graph/neo4j/sync.py
@dataclass(frozen=True)
class SyncRun:
    run_id: int
    mode: str  # "FULL" | "INCREMENTAL"
    source_backend: str
    source_user: str | None  # None trên DuckDB
    since: datetime | None  # mốc đọc chuyển khoản; None = đọc hết
    watermark_from: datetime | None
    watermark_to: datetime | None
    er_run_id: int
    sent: dict[str, int]  # 11 khoá: số dòng gửi sang MERGE trong lần chạy này
    graph: dict[str, int]  # 11 khoá: số node / quan hệ trong Neo4j sau lần chạy
    source: dict[str, int]  # {"TRANSFERRED_TO": .., "SENT_TO": ..} đếm ở nguồn sau lần chạy
    pruned: int  # quan hệ bị xoá vì cũ hơn giao dịch cũ nhất còn ở nguồn
    swept: int  # node + quan hệ phía khách hàng bị xoá vì không còn ở nguồn
    lag_before_seconds: int | None
    lag_after_seconds: int
    seconds: float
    in_sync: bool


def plan_since(
    watermark: datetime | None, overlap_minutes: int, *, full: bool
) -> datetime | None: ...
def run_sync(
    db: Database, settings: Settings, *, full: bool = False, actor: str | None = None
) -> SyncRun: ...
```
- `config.yaml`: mục `neo4j` thêm `database: neo4j` và `read_procedures: [db.labels, db.relationshipTypes,
  db.propertyKeys, db.schema.visualization, db.schema.nodeTypeProperties, db.schema.relTypeProperties,
  dbms.components]`; mục mới `graph_sync: {oracle_user: aml_graph_sync_usr, batch_size: 5000, overlap_minutes: 60}`.
- Gói `src/aml/graph/neo4j/` (`guard.py`, `client.py`, `extract.py`, `sync.py`) và thư mục Cypher
  `src/aml/graph/neo4j/cypher/`: `schema.cypher`; `sync/merge_customers.cypher`, `sync/merge_accounts.cypher`,
  `sync/merge_external_accounts.cypher`, `sync/merge_owns.cypher`, `sync/merge_devices.cypher`,
  `sync/merge_phones.cypher`, `sync/merge_addresses.cypher`, `sync/merge_transfers.cypher`,
  `sync/merge_daily_edges.cypher`, `sync/sweep.cypher`, `sync/prune.cypher`, `sync/wipe.cypher`,
  `sync/save_state.cypher`; `read/sync_state.cypher`, `read/counts.cypher`. 6b thêm thư mục con của nó.
- DDL `sql/duckdb/ddl/140_graph_sync.sql` và `sql/oracle/ddl/140_graph_sync.sql`, thêm vào `SCHEMA_SCRIPTS` của cả
  hai backend sau `ddl/130_network.sql` và trước các script `050_*`: view `graph_customer_attrs` và bảng
  `graph_sync_runs`.
- `aml.dba.security.ROLE_GRANTS["aml_graph_sync"]` và `sql/oracle/security/020_grants.sql` thêm `SELECT` trên
  `graph_customer_attrs`, `customer_golden`, `admin_unit_mapping` (4 → 7 quyền).
- **Sửa kéo theo ở phần đã duyệt — là một phần của 6a** (người dùng xác nhận 2026-10-12): (1)
  `tests/security/test_oracle_security.py`: `EXPECTED_GRANTS["aml_graph_sync"]` thêm ba đối tượng trên và `sizes`
  đổi `4` → `7`; (2) `specs/oracle-security.md`: dòng `aml_graph_sync` của bảng ma trận quyền và AC6 ("lần lượt 10,
  7, 4, 1" → "10, 7, 7, 1"), kèm ghi chú dẫn về spec này; (3) `tests/graph/test_cli.py`: bỏ `graph` khỏi tham số
  của test đang khẳng định `Phase 6` (chỉ còn `bench`).
- `docker-compose.yml`, service `neo4j`: thêm `NEO4J_dbms_usage__report_enabled: "false"` và ghim image
  `neo4j:5.26.31-community` (ghim luôn APOC core, vì APOC đi kèm image).
- CLI: `aml graph` thành nhóm lệnh (như `aml dq`): `aml graph sync [--full]`, `aml graph status`. Không đụng
  `aml bench`, `aml trace`, `aml network`.
- Tài liệu `docs/neo4j-sync.md`: mô hình, cách chạy, định nghĩa sync lag, đánh đổi consistency, khi nào cần `--full`,
  và hạn chế của khoá băm (sha256 không muối dò ngược được — che khuất, không phải ẩn danh).

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **Mô hình đồ thị** — 6b / 6c dựa vào đúng các tên dưới đây:

  | Node | Khoá (duy nhất) | Thuộc tính khác |
  |---|---|---|
  | `Customer` | `golden_customer_id` | `cifs` (danh sách CIF tăng dần), `cif_count`, `synced_run` |
  | `Account` | `account_id` | `cif`, `account_type`, `branch_id`, `open_date` (Date), `currency`, `is_external` (bool) |
  | `Device` / `Phone` / `Address` | `key` | `synced_run` |
  | `SyncState` | `name` (= `'projection'`) | `txn_watermark` (LocalDateTime), `source_backend`, `er_run_id`, `last_run_id`, `updated_at` |

  | Quan hệ | Hướng | Khoá `MERGE` | Thuộc tính |
  |---|---|---|---|
  | `OWNS` | `(Customer)->(Account)` | cặp node | `cif`, `synced_run` |
  | `USES_DEVICE` / `HAS_PHONE` / `LIVES_AT` | `(Customer)->(Device / Phone / Address)` | cặp node | `synced_run` |
  | `TRANSFERRED_TO` | `(Account)->(Account)` | `txn_id` | `txn_id`, `amount` (số nguyên VND), `ts` (LocalDateTime), `channel` |
  | `SENT_TO` | `(Account)->(Account)` | cặp node + `day` | `day` (Date), `count`, `total` (số nguyên VND) |

  - **Chủ** của một CIF = `golden_customer_id` trong `customer_golden`; CIF không có dòng nào → `'G-' + cif` (như 5c).
  - `Account` gồm mọi dòng `accounts` (`is_external = false`) và mọi mã tài khoản xuất hiện ở hai đầu một chuyển khoản
    nhưng không có trong `accounts` (`is_external = true`, các thuộc tính khác không có, không có `OWNS`).
  - `Device` / `Phone` / `Address`: `key = attribute_key(kind, value)` =
    16 ký tự hex đầu của `sha256((kind + "|" + value).encode("utf-8"))`, với `value` là đúng `device_key` /
    `phone_key` / `address_key` do `aml.graph.network.shared.attribute_keys` trả về (khoá của 5c). Giá trị `None`
    không sinh node. **Mọi** giá trị đều thành node, kể cả giá trị chỉ một khách hàng mang; mỗi cặp (khách hàng, khoá)
    là một quan hệ dù nhiều CIF của khách hàng đó cùng mang giá trị.
  - Không thuộc tính nào của Neo4j chứa tên, số giấy tờ, số điện thoại, địa chỉ, mã thiết bị, `memo`,
    `counterparty_name`.
  - `TRANSFERRED_TO` = một quan hệ cho mỗi dòng `transactions` có cả hai phía khác null (kể cả giao dịch trùng DQ và
    self-transfer). Giao dịch một phía null không vào đồ thị. `ts` = `txn_ts` naive (giờ Việt Nam).
  - `SENT_TO` = một quan hệ cho mỗi dòng `acct_edge_daily` (`day`, `count = txn_count`, `total = total_amount`).
- **`schema.cypher`** (9 statement, đều `IF NOT EXISTS`): constraint duy nhất `customer_id_unique`
  (`Customer.golden_customer_id`), `account_id_unique`, `device_key_unique`, `phone_key_unique`, `address_key_unique`,
  `sync_state_name_unique`, `transfer_txn_unique` (trên quan hệ `TRANSFERRED_TO.txn_id` — đã kiểm là dùng được ở
  Community); index `transfer_ts_idx` (`TRANSFERRED_TO.ts`), `sent_day_idx` (`SENT_TO.day`).
- **File `.cypher`**: comment bằng `//`; mỗi statement kết thúc bằng `;` ở cuối dòng (thiếu → `ValueError`, như quy ước
  `/` của Oracle); giá trị chỉ truyền bằng tham số `$tên`, Python không nối chuỗi vào Cypher. Mỗi file `merge_*` có
  đúng một statement dạng `UNWIND $rows AS row` + `MERGE` + `SET`. Subquery viết dạng có phạm vi `CALL (x) { }`
  (dạng `CALL { WITH x }` bị 5.26 báo deprecated). Không file nào dùng APOC.
- **Đường đọc** (`run_read`, `run_read_file`): gọi `assert_read_only(cypher,
  allowed_procedures=settings.neo4j.read_procedures)` rồi mới mở session
  `default_access_mode=READ_ACCESS` trên `settings.neo4j.database` và chạy bằng `execute_read`. Kết quả là DataFrame;
  giá trị `neo4j.time.*` của driver được đổi về kiểu Python bằng `.to_native()` (`datetime`, `date`). Khi guard chặn
  và có `audit_db`: ghi 1 dòng `audit_log` `module='graph'`, `entity_type='cypher'`, `entity_id` = 16 ký tự hex đầu
  của sha256 câu truy vấn, `decision='QUERY_BLOCKED'`, `reason` = thông điệp lỗi, `version='guard/v1'`,
  `details = {query}` (cắt còn 2000 ký tự), rồi raise. Truy vấn chạy thành công không ghi audit ở 6a.
  > Cập nhật 6b-ii: guard nâng lên `guard/v2` và `run_read` / `run_read_file` nhận thêm `procedures`; xem `specs/neo4j-gds.md`.
- **Guard** `assert_read_only` (thuần Python, fail-closed, không phải parser):
  1. Bỏ chuỗi trong nháy đơn / nháy kép (có `\` thoát), định danh trong dấu backtick và comment (`//` tới hết dòng,
     `/* */`; `//` nằm trong chuỗi không phải comment). Còn lại rỗng → `WriteBlockedError("empty query")`.
  2. Có `;` mà sau nó còn ký tự không phải khoảng trắng → `multiple statements are not allowed`.
  3. Có một từ trọn vẹn (không phân biệt hoa thường) thuộc `WRITE_KEYWORDS` → `write clause <TỪ> is not allowed in a
     read-only query`, với `<TỪ>` là từ xuất hiện sớm nhất, viết hoa.
  4. Mỗi `CALL` theo sau là tên procedure: tên phải khớp (fnmatch, không phân biệt hoa thường) một mẫu trong
     `allowed_procedures`, nếu không → `procedure <tên> is not allowed in a read-only query`. `CALL {` và `CALL (`
     (subquery) được phép; nội dung bên trong vẫn chịu bước 3.
  - Hạn chế chấp nhận: định danh không đặt trong backtick trùng từ khoá (ví dụ thuộc tính tên `set`) bị chặn nhầm.
    Lớp bảo vệ thật là session `READ` của server (đã đo: `Neo.ClientError.Statement.AccessMode`); guard cho lời từ
    chối sớm, có lý do và ghi audit được.
- **Đường ghi** (`run_write_file`): chỉ nhận **tên file** bắt đầu bằng một tiền tố trong `WRITE_PREFIXES`; tên khác
  → `GraphError` chứa `not a write file`. Không có hàm nào nhận chuỗi Cypher tuỳ ý để ghi. Mỗi statement chạy trong
  một transaction **tự commit** (`session.run`, không dùng `execute_write` — bắt buộc để `IN TRANSACTIONS` chạy được);
  có `rows` thì file được chạy một lần cho mỗi lô `graph_sync.batch_size` dòng với tham số `$rows` (lô do Python
  cắt, vì dữ liệu đến từ Python: không phải gửi cả trăm nghìn dòng trong một tham số). Trả bộ đếm cộng dồn
  `nodes_created`, `nodes_deleted`, `relationships_created`, `relationships_deleted`, `properties_set`.
- **Xoá theo lô** (`sync/wipe.cypher`, `sync/prune.cypher`): dùng `CALL (x) { DELETE x } IN TRANSACTIONS OF 10000
  ROWS`. `wipe` xoá **quan hệ trước, theo từng kiểu** (6 statement), **rồi mới xoá node theo từng nhãn** (5 nhãn của
  projection + `SyncState`); không `DETACH DELETE` node còn quan hệ (đã đo: hết bộ nhớ transaction trên `small`).
  Node mang nhãn khác không bị đụng.
- **Nguồn** (`open_source`): `db.backend == "duckdb"` → trả chính `db` (DuckDB không có role). `"oracle"` → mở kết nối
  mới bằng `graph_sync.oracle_user` + `db.oracle.demo_password`, chạy `ALTER SESSION SET CURRENT_SCHEMA = <owner>`;
  `demo_password` rỗng → `SyncError` chứa `ORACLE_DEMO_PASSWORD` (không mở kết nối nào); đăng nhập thất bại hoặc
  ORA-00942 → `SyncError` chứa ``run `aml security-setup` first``. Mọi câu đọc dữ liệu của sync đi qua kết nối này;
  `graph_sync_runs` và `audit_log` được ghi bằng `db` (kết nối thường của ứng dụng).
- **Đọc nguồn** (`build_projection`; tên cột hạ về chữ thường, mọi phép sắp xếp làm trong Python; cột ngày của
  Oracle về `date`):
  - phía khách hàng — **luôn đọc toàn bộ**: `graph_customer_attrs` (view: `cif`, `phone`, `device_id`, `street`,
    `ward`, `district`, `province` của `customers`), `admin_unit_mapping`, `accounts`, `customer_golden`;
  - chuyển khoản: `transactions` hai phía khác null, thêm `txn_ts >= since` khi có `since`;
  - cạnh ngày: `acct_edge_daily`, thêm `day >=` ngày của `since` khi có `since`;
  - `Account` trong `frames` = mọi dòng `accounts` + các mã ngoài `accounts` ở hai đầu **các chuyển khoản vừa đọc**.
  - `graph_customer_attrs` hoặc `accounts` rỗng / chưa có → `SyncError` chứa ``run `aml load` first``;
    `customer_golden` rỗng → `SyncError` chứa ``run `aml er` first``. `transactions` rỗng thì không lỗi.
- **Trình tự `run_sync`**:
  1. Kiểm nguồn (các lỗi ở trên) → `open_driver` → đọc `SyncState`. Chưa ghi gì.
  2. `SyncState.source_backend` khác backend nguồn hiện tại và không `full` → `SyncError` chứa `run with --full`.
  3. `mode = "FULL"` khi `full=True` hoặc chưa có `SyncState`; ngược lại `"INCREMENTAL"`. `FULL`: chạy
     `sync/wipe.cypher`. Luôn chạy `schema.cypher`.
  4. `since = plan_since(watermark, overlap_minutes, full=...)`: `None` khi `FULL` hoặc chưa có watermark, ngược lại
     `watermark - overlap_minutes`. `run_id` = `MAX(run_id) + 1` của `graph_sync_runs`.
  5. Nạp phía khách hàng (đủ bộ, gắn `synced_run = run_id`), rồi `sync/sweep.cypher` xoá quan hệ `OWNS` /
     `USES_DEVICE` / `HAS_PHONE` / `LIVES_AT` và node `Customer` / `Device` / `Phone` / `Address` có
     `synced_run <> run_id`. `swept` = số node + quan hệ bị xoá.
  6. Nạp `Account` (trong `accounts` trước, mã ngoài sau với `ON CREATE SET is_external = true`), `TRANSFERRED_TO`,
     `SENT_TO` (`SET` lại `count`, `total`).
  7. `sync/prune.cypher`: xoá `TRANSFERRED_TO` có `ts <` `txn_ts` nhỏ nhất của giao dịch hai phía còn ở nguồn và
     `SENT_TO` có `day <` ngày đó. `pruned` = số quan hệ bị xoá. Node `Account` không bị xoá. Nguồn không còn giao
     dịch hai phía nào → bỏ qua bước này.
  8. Đếm `graph` (11 khoá) và `source` (`COUNT(*)` giao dịch hai phía; `COUNT(*)` `acct_edge_daily`);
     `in_sync = graph["TRANSFERRED_TO"] == source["TRANSFERRED_TO"] and graph["SENT_TO"] == source["SENT_TO"]`.
  9. `watermark_to` = lớn nhất của `watermark_from` và `Projection.max_ts`; `sync/save_state.cypher`; chèn 1 dòng
     `graph_sync_runs`; ghi 1 dòng `audit_log`.
  - Lỗi sau bước 2: `SyncState` và `graph_sync_runs` **không đổi**, ghi 1 dòng audit `decision='SYNC_FAILED'` (`reason`
    = thông điệp lỗi), raise `SyncError`. Dữ liệu đã `MERGE` dở vẫn nằm trong đồ thị; chạy lại là an toàn (đã đo).
- **Sync lag** (đo theo thời gian dữ liệu, vì `txn_ts` là mốc duy nhất):
  `lag_before_seconds` = (`txn_ts` lớn nhất ở nguồn lúc bắt đầu) − (`txn_watermark` lúc bắt đầu), `None` khi `FULL`;
  `lag_after_seconds` = (`txn_ts` lớn nhất ở nguồn lúc đếm ở bước 8) − `watermark_to` (0 khi không có gì tới trong lúc
  chạy); `seconds` = thời gian chạy của cả lần sync.
- **`graph_sync_runs`**: `run_id` (khoá chính), `run_ts` (UTC), `mode`, `source_backend`, `source_user`, `since_ts`,
  `watermark_from`, `watermark_to`, `er_run_id`, `nodes_sent`, `rels_sent`, `pruned`, `swept`, `lag_before_seconds`,
  `lag_after_seconds`, `seconds`, `in_sync` (0/1), `details` (JSON: `sent`, `graph`, `source`).
- **Audit** (mỗi lần `run_sync` thành công 1 dòng): `module='graph'`, `entity_type='neo4j'`, `entity_id='projection'`,
  `decision='SYNCED'`, `version='graph_sync/v1'`, `actor` = tham số hoặc `audit.system_actor`, `details` = `{run_id,
  mode, source_backend, source_user, since, watermark_to, sent, graph, source, pruned, swept, lag_before_seconds,
  lag_after_seconds, in_sync}`, `reason` =
  `{mode} sync from {source_backend}: sent {nodes} nodes and {rels} relationships, pruned {pruned}, swept {swept}; graph has {g_t} of {s_t} transfers and {g_e} of {s_e} daily edges; watermark {watermark_to}`,
  nối thêm `; OUT OF SYNC: run aml graph sync --full` khi `in_sync` là `False`.
- **CLI**:
  - `aml graph sync [--full]`: in dòng tổng kết `run_id= mode= source= since= watermark= nodes= rels= pruned= swept=
    lag_before_s= lag_after_s= seconds= in_sync=` rồi 11 dòng `<nhãn / kiểu> sent=<n> graph=<n>` theo thứ tự
    `NODE_LABELS` + `REL_TYPES`; thời điểm in dạng `YYYY-MM-DDTHH:MM:SS`, giá trị thiếu in `-`. `in_sync=False` → vẫn
    exit 0, thêm dòng `OUT OF SYNC: run aml graph sync --full` ra stderr. `SyncError` / `GraphError` → stderr, exit 1.
    Neo4j không kết nối được → stderr chứa `neo4j not available`, exit 1, không ghi gì.
  - `aml graph status`: chỉ đọc (qua `run_read_file`), in `watermark= source= last_run_id= lag_s=` rồi 11 dòng
    `<nhãn / kiểu> <số lượng>`; chưa sync lần nào → stderr `graph not synced: run aml graph sync`, exit 1. Không ghi
    audit, không ghi bảng nào.

## Tiêu chí nghiệm thu
<!-- MINI-G = DuckDB rỗng (`duck`) sau `load_shr` của tests/network/helpers.py (MINI-SHR của specs/network-detections.md:
22 CIF C01..C22, 23 tài khoản A01..A22 + A01S, er_golden gộp C06/C07/C08 thành G-C06 và không có dòng cho C19,
giao dịch T01..T07) cộng thêm hai giao dịch rồi `refresh_acct_edge_daily`:
  T08 2026-03-06 09:00:00 A02->null 9 000 000 (CASH)        T09 2026-03-01 15:00:00 A02->A01 4 000 000 (INTERNAL_TRANSFER)
Nhắc lại T01..T07: T01 2026-03-01 10:00:00 A02->A01 10M; T02 2026-03-02 10:00:00 A03->A01 20M; T03 2026-03-03 10:00:00
A01->EXT-01 25M; T04 2026-03-03 11:00:00 A01->A20 5M; T05 2026-03-04 10:00:00 A01->A01S 3M; T06 2026-07-01 10:00:00
A04->A01 7M; T07 2026-03-05 10:00:00 A05->A04 1M.
LATE = ba giao dịch INTERNAL_TRANSFER chèn thêm vào MINI-G rồi `refresh_acct_edge_daily`:
  T10 2026-07-01 09:30:00 A03->A02 2M;  T11 2026-07-01 08:00:00 A03->A02 1M;  T12 2026-07-02 10:00:00 A05->EXT-02 3M.
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` rồi `run_er` (như `tiny_er` của tests/network). `settings` =
`load_settings(environ={"DB_BACKEND": "duckdb"})` trừ khi nói khác. S11(a, b, c, d, e, f, g, h, i, j, k) = dict 11 khoá
theo thứ tự Customer, Account, Device, Phone, Address, OWNS, USES_DEVICE, HAS_PHONE, LIVES_AT, TRANSFERRED_TO, SENT_TO.
Test có nhãn [neo4j] dùng @pytest.mark.neo4j, [oracle] dùng @pytest.mark.oracle (cả hai tự skip khi dịch vụ không
chạy); fixture [neo4j] chạy `sync/wipe.cypher` trước mỗi test. Các AC không có nhãn chạy ở chế độ DuckDB-only và
không mở kết nối Neo4j nào. -->
- AC1: Given `config.yaml`, `docker-compose.yml`, thư mục `sql/`, thư mục `src/aml/graph/neo4j/cypher/`, `docs/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS`, `ROLE_GRANTS`, phân tích `docker-compose.yml` bằng `yaml.safe_load`, gọi `load_statements` và gọi `apply_schema(duck)` hai lần, Then `settings.neo4j.database == "neo4j"`, `settings.neo4j.read_procedures == ["db.labels", "db.relationshipTypes", "db.propertyKeys", "db.schema.visualization", "db.schema.nodeTypeProperties", "db.schema.relTypeProperties", "dbms.components"]`, `settings.graph_sync` = (`oracle_user` `aml_graph_sync_usr`, `batch_size` 5000, `overlap_minutes` 60); `load_settings(environ={"AML__GRAPH_SYNC__BATCH_SIZE": "0"})` raise `pydantic.ValidationError` chứa `batch_size must be between 1 and 50000`, `load_settings(environ={"AML__GRAPH_SYNC__OVERLAP_MINUTES": "-1"})` raise `pydantic.ValidationError` chứa `overlap_minutes must be >= 0` và `load_settings(environ={"AML__GRAPH_SYNC__ORACLE_USER": "bad name"})` raise `pydantic.ValidationError` chứa `oracle_user must be a plain identifier`; trong `docker-compose.yml`, `services.neo4j.environment["NEO4J_dbms_usage__report_enabled"] == "false"` và `services.neo4j.image == "neo4j:5.26.31-community"`; `ddl/140_graph_sync.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]`, đứng sau `ddl/130_network.sql` và trước `ddl/050_customers_masked.sql` / `ddl/050_security_objects.sql`; `apply_schema` không raise, `SELECT COUNT(*) FROM graph_sync_runs` trả 0 và `SELECT * FROM graph_customer_attrs` có đúng các cột `cif`, `phone`, `device_id`, `street`, `ward`, `district`, `province`; `ROLE_GRANTS["aml_graph_sync"]` bằng đúng 7 cặp `SELECT` trên `customers_masked`, `accounts`, `transactions`, `acct_edge_daily`, `graph_customer_attrs`, `customer_golden`, `admin_unit_mapping`, và `security/020_grants.sql` chứa ba dòng `GRANT SELECT ON graph_customer_attrs TO aml_graph_sync`, `GRANT SELECT ON customer_golden TO aml_graph_sync`, `GRANT SELECT ON admin_unit_mapping TO aml_graph_sync`; `load_statements("schema.cypher")` trả 9 statement, 7 cái chứa `CREATE CONSTRAINT`, 2 cái chứa `CREATE INDEX`, cả 9 chứa `IF NOT EXISTS`, và hợp lại chứa đủ các tên `customer_id_unique`, `account_id_unique`, `device_key_unique`, `phone_key_unique`, `address_key_unique`, `sync_state_name_unique`, `transfer_txn_unique`, `transfer_ts_idx`, `sent_day_idx`; thư mục `cypher/sync/` có đúng 9 file `merge_*.cypher`, mỗi file cho đúng 1 statement chứa `UNWIND $rows AS row` và `MERGE`; `load_statements("sync/merge_transfers.cypher")[0]` chứa `TRANSFERRED_TO` và `txn_id`; `load_statements("sync/wipe.cypher")` trả 12 statement, 6 statement đầu chứa `DELETE r` và không chứa `DETACH`, cả 12 chứa `IN TRANSACTIONS`; mỗi file trong `cypher/read/` cho đúng 1 statement và `assert_read_only` không raise với statement đó; không file `.cypher` nào chứa `apoc.` hay `CALL {`; `cypher_file("nope.cypher")` raise `FileNotFoundError`; `split_statements("MATCH (n) RETURN n;\n// note\nMATCH (m)\nRETURN m;\n")` trả 2 statement không còn dấu `;`, và `split_statements("MATCH (n) RETURN n")` raise `ValueError`; và `docs/neo4j-sync.md` tồn tại, chứa các chuỗi `Sync lag`, `Consistency`, `--full` và `not anonymisation`.
- AC2: Given hàm `assert_read_only` (không cần dịch vụ nào), When gọi với từng câu Cypher dưới đây, Then **không raise** với: `MATCH (a:Account {account_id: $id})-[r:TRANSFERRED_TO]->(b) RETURN b.account_id, r.amount ORDER BY r.ts LIMIT 10`; `MATCH (n) WHERE n.note CONTAINS 'please DELETE and CREATE' RETURN count(n)`; `// SET x` xuống dòng `MATCH (n) RETURN n.created_at, n.offset LIMIT 1`; ``MATCH (n:`CREATE`) RETURN count(n)``; `MATCH (a:Account) CALL { WITH a MATCH (a)<-[:OWNS]-(c) RETURN count(c) AS n } RETURN a.account_id, n`; `MATCH (a:Account) CALL (a) { MATCH (a)<-[:OWNS]-(c) RETURN count(c) AS n } RETURN a.account_id, n`; `EXPLAIN MATCH (n) RETURN n LIMIT 1`; `MATCH (n) RETURN count(n);`; `SHOW CONSTRAINTS YIELD name RETURN name`; `CALL db.labels() YIELD label RETURN label` với `allowed_procedures=("db.labels",)`; và `CALL gds.pageRank.stream('g') YIELD nodeId RETURN nodeId` với `allowed_procedures=("gds.*.stream",)`; và **raise `WriteBlockedError`** (là lớp con của `GraphError`) có thông điệp chứa chuỗi trong ngoặc với: `CREATE (n:X)` (`write clause CREATE is not allowed in a read-only query`); `match (n) set n.x = 1` (`SET`); `MERGE (n:X {id: 1})` (`MERGE`); `MATCH (n) DETACH DELETE n` (`DETACH`); `MATCH (n) DELETE n` (`DELETE`); `MATCH (n) REMOVE n.x` (`REMOVE`); `DROP CONSTRAINT account_id_unique` (`DROP`); `MATCH (n) FOREACH (x IN [1] | SET n.x = x)` (`FOREACH`); `LOAD CSV FROM 'file:///x.csv' AS row RETURN row` (`LOAD`); `MATCH (n) WHERE n.url = 'http://x' SET n.y = 1` (`SET` — `//` trong chuỗi không che phần sau); `MATCH (n)` xuống dòng `SET` tab `n.x = 1` (`SET`); `MATCH (n) RETURN n.set` (`SET`, chặn nhầm có chủ ý); `CALL apoc.create.node(['X'], {})` (`procedure apoc.create.node is not allowed in a read-only query`); `CALL gds.pageRank.write('g', {writeProperty: 'pr'})` với `allowed_procedures=("gds.*.stream",)` (`gds.pageRank.write`); `CALL db.labels()` với `allowed_procedures=()` (`db.labels`); `MATCH (n) RETURN n; MATCH (m) RETURN m` (`multiple statements are not allowed`); và chuỗi rỗng, chuỗi ba dấu cách, chuỗi `// only a comment` (`empty query`); và `"CALL" not in WRITE_KEYWORDS` còn `{"CREATE", "MERGE", "SET", "DELETE", "DETACH", "REMOVE", "DROP", "FOREACH", "LOAD"} <= set(WRITE_KEYWORDS)`.
- AC3: Given MINI-G, When gọi `build_projection(duck)`, Then `list(frames) == list(NODE_LABELS) + list(REL_TYPES)`, mỗi frame có cột đúng bằng `COLUMNS[tên]`, và số dòng theo thứ tự đó là 20, 24, 14, 10, 14, 23, 17, 17, 17, 8, 7; `er_run_id == 1`; `max_ts == datetime(2026, 7, 1, 10, 0, 0)`; frame `Customer` sắp theo `golden_customer_id`, dòng `G-C06` có `cifs == ["C06", "C07", "C08"]` và `cif_count == 3`, có dòng `G-C19` (C19 không có trong `customer_golden`) với `cifs == ["C19"]`; frame `Account` có 23 dòng `is_external == False` và đúng 1 dòng `is_external == True` là `EXT-01` với `cif`, `account_type`, `open_date` đều null, dòng `A01S` có `cif == "C01"` và `account_type == "SAVINGS"`; `attribute_key("phone", "0901000001") == "1582642d9e86c0cf"`, `attribute_key("device", "DEV-R") == "9780efe92205e69d"`, `attribute_key("address", "1 LE LOI|PHUONG AN PHU|TP. HO CHI MINH") == "01dabfcfc5ec16dc"`; trong `HAS_PHONE` khoá `1582642d9e86c0cf` có đúng 2 dòng (`G-C01`, `G-C02` — số `+84 90 100 0001` và `0901000001` là một), và có một khoá mang đúng 6 khách hàng `G-C14` tới `G-C19`; trong `USES_DEVICE` khoá `9780efe92205e69d` có đúng 2 dòng (`G-C01`, `G-C03`) và `G-C06` có đúng 1 dòng (ba CIF cùng một thiết bị); trong `LIVES_AT` khoá `01dabfcfc5ec16dc` có đúng 2 dòng (`G-C01`, `G-C04` — địa chỉ viết theo đơn vị hành chính cũ quy về cùng khoá); `G-C20`, `G-C21`, `G-C22` không có dòng nào trong ba frame đó; `OWNS` có dòng (`G-C06`, `A07`, `C07`); `TRANSFERRED_TO` có `txn_id` đúng bằng T01, T02, T03, T04, T05, T06, T07, T09 (không có T08 vì một phía null), dòng T03 = (`A01`, `EXT-01`, 25000000, 2026-03-03 10:00:00, `INTERNAL_TRANSFER`); `SENT_TO` có dòng (`A02`, `A01`, 2026-03-01, 2, 14000000); không frame nào chứa các chuỗi `0901000001`, `DEV-R`, `1 Lê Lợi` hay `Khach C01` ở bất kỳ ô nào; `to_rows(frames["TRANSFERRED_TO"])[0]["ts"]` có kiểu đúng là `datetime.datetime` (không phải `pd.Timestamp`), `amount` kiểu `int`, `to_rows(frames["SENT_TO"])[0]["day"]` kiểu `datetime.date`, và ô null trong `to_rows(frames["Account"])` là `None`; `[len(b) for b in batches(to_rows(frames["Account"]), 10)] == [10, 10, 4]`; và sau lời gọi, số dòng `transactions` vẫn là 9 và `audit_log` không có dòng `module='graph'` nào.
- AC4: Given TINY trong DuckDB (đã `run_er`), When gọi `build_projection(duck)`, Then số dòng 11 frame theo thứ tự `NODE_LABELS` + `REL_TYPES` là 273, 1314, 264, 267, 265, 532, 279, 273, 273, 3651, 3575; `max_ts == datetime(2026, 6, 30, 21, 53, 57)`; frame `Customer` có 22 dòng `cif_count > 1`; frame `Account` có 782 dòng `is_external == True`, tất cả có `account_id` bắt đầu bằng `EXT-`; `OWNS` có dòng (`G-CIF00000206`, `A8201784530`, `CIF00000206`) và dòng (`G-CIF00000189`, `A4937939209`, `CIF00000189`); đếm số `golden_customer_id` theo `key`: `USES_DEVICE` có đúng 1 khoá từ 2 khách hàng trở lên và khoá đó có 16 khách hàng, `HAS_PHONE` có đúng 1 khoá như vậy với 7 khách hàng, `LIVES_AT` có đúng 2 khoá như vậy và khoá lớn nhất có 8 khách hàng; `TRANSFERRED_TO` có dòng `T0000002197` = (`A8201784530`, `A3312263346`, 456916000, 2026-03-22 15:00:00, `EBANKING`); tổng cột `count` của `SENT_TO` bằng 3651; và Given một DuckDB khác chứa cùng dữ liệu TINY (kể cả các bảng `er_*`) nhưng các dòng `customers`, `accounts`, `transactions` được chèn lại theo thứ tự đã xáo rồi `refresh_acct_edge_daily`, When gọi `build_projection`, Then cả 11 frame bằng frame của DuckDB gốc theo `pd.testing.assert_frame_equal`.
- AC5: Given hàm `plan_since`, MINI-G và các biến thể của nó, When lập cửa sổ đọc và gọi `build_projection` / `open_source`, Then `plan_since(None, 60, full=False) is None`, `plan_since(datetime(2026, 7, 1, 10, 0, 0), 60, full=False) == datetime(2026, 7, 1, 9, 0, 0)`, `plan_since(datetime(2026, 7, 1, 10, 0, 0), 0, full=False) == datetime(2026, 7, 1, 10, 0, 0)` và `plan_since(datetime(2026, 7, 1, 10, 0, 0), 60, full=True) is None`; Given MINI-G cộng LATE, When gọi `build_projection(duck, since=datetime(2026, 7, 1, 9, 0, 0))`, Then `TRANSFERRED_TO` có đúng 3 dòng T06, T10, T12 (T11 lúc 08:00:00 nằm trước mốc), `SENT_TO` có đúng 3 dòng (`A03`, `A02`, 2026-07-01, 2, 3000000), (`A04`, `A01`, 2026-07-01, 1, 7000000), (`A05`, `EXT-02`, 2026-07-02, 1, 3000000), frame `Account` có 24 dòng gồm 23 tài khoản của `accounts` và `EXT-02` (không có `EXT-01`), các frame `Customer`, `Device`, `Phone`, `Address`, `OWNS`, `USES_DEVICE`, `HAS_PHONE`, `LIVES_AT` vẫn có 20, 14, 10, 14, 23, 17, 17, 17 dòng, và `max_ts == datetime(2026, 7, 2, 10, 0, 0)`; với `since=datetime(2026, 7, 1, 10, 0, 0)` thì `TRANSFERRED_TO` có đúng T06 và T12 (biên `>=` bao gồm); Given DuckDB chỉ mới `apply_schema`, When gọi `build_projection`, Then raise `SyncError` chứa ``run `aml load` first``; Given MINI-G sau `DELETE FROM er_runs`, When gọi `build_projection`, Then raise `SyncError` chứa ``run `aml er` first``; `open_source(duck, settings) is duck`; và Given `load_settings(environ={"DB_BACKEND": "oracle"})` (không có `ORACLE_DEMO_PASSWORD`) cùng một đối tượng `Database` giả có `backend = "oracle"`, When gọi `open_source`, Then raise `SyncError` chứa `ORACLE_DEMO_PASSWORD` mà `oracledb.connect` không bị gọi lần nào (monkeypatch raise nếu bị gọi).
- AC6: [neo4j] Given MINI-G và Neo4j đã wipe, When gọi `run_sync(duck, settings, full=True)` rồi `run_sync(duck, settings)`, Then lần một trả `SyncRun` có `run_id = 1`, `mode = "FULL"`, `source_backend = "duckdb"`, `source_user is None`, `since is None`, `watermark_from is None`, `watermark_to = datetime(2026, 7, 1, 10, 0, 0)`, `er_run_id = 1`, `sent = graph = S11(20, 24, 14, 10, 14, 23, 17, 17, 17, 8, 7)`, `source = {"TRANSFERRED_TO": 8, "SENT_TO": 7}`, `pruned = 0`, `swept = 0`, `lag_before_seconds is None`, `lag_after_seconds = 0`, `in_sync is True`; `MATCH (n) RETURN count(n) AS n` trả 83 (82 node của projection và 1 `SyncState`) và `MATCH ()-[r]->() RETURN count(r) AS n` trả 89; qua `run_read`: `MATCH (c:Customer {golden_customer_id: 'G-C06'}) RETURN c.cifs AS cifs, c.cif_count AS n` trả (`["C06", "C07", "C08"]`, 3); `MATCH (:Account {account_id: 'A01'})-[r:TRANSFERRED_TO {txn_id: 'T03'}]->(b) RETURN b.account_id AS dst, b.is_external AS ext, r.amount AS amount, toString(r.ts) AS ts, r.channel AS channel` trả đúng 1 dòng (`EXT-01`, `true`, 25000000, `2026-03-03T10:00:00`, `INTERNAL_TRANSFER`); `MATCH (:Account {account_id: 'A02'})-[r:SENT_TO]->(:Account {account_id: 'A01'}) RETURN toString(r.day) AS day, r.count AS n, r.total AS total` trả đúng 1 dòng (`2026-03-01`, 2, 14000000); `MATCH (:Customer {golden_customer_id: 'G-C01'})-[:HAS_PHONE]->(:Phone)<-[:HAS_PHONE]-(c:Customer) RETURN c.golden_customer_id AS id` trả đúng 1 dòng `G-C02`; `MATCH (c:Customer)-[o:OWNS]->(:Account {account_id: 'A01S'}) RETURN c.golden_customer_id AS id, o.cif AS cif` trả (`G-C01`, `C01`); `MATCH (:Account {account_id: 'EXT-01'})<-[:OWNS]-(c) RETURN count(c) AS n` trả 0; tập tên thuộc tính của mọi node bằng đúng {`account_id`, `account_type`, `branch_id`, `cif`, `cif_count`, `cifs`, `currency`, `er_run_id`, `golden_customer_id`, `is_external`, `key`, `last_run_id`, `name`, `open_date`, `source_backend`, `synced_run`, `txn_watermark`, `updated_at`} và của mọi quan hệ bằng đúng {`amount`, `channel`, `cif`, `count`, `day`, `synced_run`, `total`, `ts`, `txn_id`}; `SHOW CONSTRAINTS YIELD name RETURN name` trả đúng 7 tên constraint của AC1 và `SHOW INDEXES` có `transfer_ts_idx`, `sent_day_idx`; có đúng 1 node `SyncState` với `name = 'projection'`, `toString(txn_watermark) = '2026-07-01T10:00:00'`, `source_backend = 'duckdb'`, `er_run_id = 1`, `last_run_id = 1`; `graph_sync_runs` có 1 dòng (`run_id = 1`, `mode = 'FULL'`, `nodes_sent = 82`, `rels_sent = 89`, `in_sync = 1`); `audit_log` có đúng 1 dòng `module='graph'`: `entity_type='neo4j'`, `entity_id='projection'`, `decision='SYNCED'`, `version='graph_sync/v1'`, `actor='system'`, `details.in_sync = true`, `reason` bằng đúng `FULL sync from duckdb: sent 82 nodes and 89 relationships, pruned 0, swept 0; graph has 8 of 8 transfers and 7 of 7 daily edges; watermark 2026-07-01 10:00:00`; và lần hai (không có gì đổi ở nguồn) trả `run_id = 2`, `mode = "INCREMENTAL"`, `since = datetime(2026, 7, 1, 9, 0, 0)`, `watermark_from = watermark_to = datetime(2026, 7, 1, 10, 0, 0)`, `sent = S11(20, 23, 14, 10, 14, 23, 17, 17, 17, 1, 1)` (chỉ T06 nằm trong 60 phút đọc lại), `graph = S11(20, 24, 14, 10, 14, 23, 17, 17, 17, 8, 7)`, tổng số node vẫn 83 và tổng số quan hệ vẫn 89 (không gì bị nhân đôi), `pruned = 0`, `swept = 0`, `lag_before_seconds = 0`, `in_sync is True`, `MATCH ()-[r:TRANSFERRED_TO {txn_id: 'T06'}]->() RETURN count(r) AS n` trả 1, và số dòng của `transactions`, `accounts`, `customers`, `er_golden` trong DuckDB không đổi sau cả hai lần.
- AC7: [neo4j] Given MINI-G đã `run_sync(duck, settings, full=True)` (run 1), When lần lượt đổi nguồn và chạy lại, Then (a) sau khi chèn LATE, `run_sync(duck, settings)` trả `run_id = 2`, `mode = "INCREMENTAL"`, `since = datetime(2026, 7, 1, 9, 0, 0)`, `lag_before_seconds = 86400`, `sent = S11(20, 24, 14, 10, 14, 23, 17, 17, 17, 3, 3)`, `graph = S11(20, 25, 14, 10, 14, 23, 17, 17, 17, 10, 9)`, `source = {"TRANSFERRED_TO": 11, "SENT_TO": 9}`, `in_sync is False` (T11 có `txn_ts` cũ hơn mốc đọc lại nên bị sót), `watermark_to = datetime(2026, 7, 2, 10, 0, 0)`, không có quan hệ `txn_id = 'T11'` trong đồ thị, node `EXT-02` có `is_external = true`, và dòng audit `SYNCED` của lần này có `reason` kết thúc bằng `; OUT OF SYNC: run aml graph sync --full`; (b) `run_sync(duck, settings, full=True)` trả `run_id = 3`, `mode = "FULL"`, `lag_before_seconds is None`, `sent = graph = S11(20, 25, 14, 10, 14, 23, 17, 17, 17, 11, 9)`, `in_sync is True`; (c) sau `DELETE FROM transactions WHERE txn_ts < TIMESTAMP '2026-03-02 00:00:00'` và `refresh_acct_edge_daily`, `run_sync(duck, settings)` trả `run_id = 4`, `since = datetime(2026, 7, 2, 9, 0, 0)`, `pruned = 3` (quan hệ T01, T09 và cạnh ngày `A02`→`A01` 2026-03-01), `swept = 0`, `sent = S11(20, 24, 14, 10, 14, 23, 17, 17, 17, 1, 1)`, `graph = S11(20, 25, 14, 10, 14, 23, 17, 17, 17, 9, 8)` (node `Account` không bị xoá), `source = {"TRANSFERRED_TO": 9, "SENT_TO": 8}`, `in_sync is True`; (d) sau `UPDATE er_golden SET golden_customer_id = 'G-C01' WHERE cif = 'C02'`, `run_sync(duck, settings)` trả `run_id = 5`, `swept = 5` (node `G-C02` và 4 quan hệ của nó), `pruned = 0`, `sent = S11(19, 24, 14, 10, 14, 23, 17, 16, 17, 1, 1)`, `graph = S11(19, 25, 14, 10, 14, 23, 17, 16, 17, 9, 8)`, node `G-C01` có `cifs = ["C01", "C02"]`, `A02` thuộc `G-C01` và không còn node `G-C02`; (e) khi `run_write_file` bị monkeypatch để raise với tên `sync/merge_transfers.cypher`, `run_sync(duck, settings)` raise `SyncError`, `graph_sync_runs` vẫn có đúng 5 dòng, `SyncState.last_run_id` vẫn là 5 và `toString(txn_watermark)` vẫn là `2026-07-02T10:00:00`, `audit_log` có thêm đúng 1 dòng `module='graph'`, `decision='SYNC_FAILED'`, và sau khi gỡ monkeypatch `run_sync(duck, settings)` trả `run_id = 6`, `swept = 0`, `pruned = 0`, `graph` như ở (d) và `in_sync is True`.
- AC8: [neo4j] Given MINI-G đã `run_sync(duck, settings, full=True)` và `driver = open_driver(settings)`, When thử đọc và ghi qua các đường khác nhau, Then `run_read(driver, settings, "MATCH (a:Account) RETURN count(a) AS n")` trả DataFrame 1 dòng, cột `n`, giá trị 24; `run_read(driver, settings, "MATCH (a:Account {account_id: $id}) RETURN a.open_date AS d", {"id": "A01"})` trả giá trị có kiểu đúng là `datetime.date` (không phải `neo4j.time.Date`) bằng 2025-01-01; `run_read_file(driver, settings, "read/counts.cypher")` trả DataFrame không rỗng; `run_read(driver, settings, "CALL db.labels() YIELD label RETURN label")` trả đúng 6 nhãn `Account`, `Address`, `Customer`, `Device`, `Phone`, `SyncState`; `run_read(driver, settings, "MATCH (a:Account) SET a.flag = 1", audit_db=duck, actor="analyst01")` raise `WriteBlockedError` chứa `SET` và `audit_log` có thêm đúng 1 dòng `module='graph'`, `entity_type='cypher'`, `decision='QUERY_BLOCKED'`, `actor='analyst01'`, `version='guard/v1'`, `details.query` bằng câu truy vấn đó; cùng lời gọi không truyền `audit_db` raise `WriteBlockedError` và không thêm dòng audit nào; `run_read(driver, settings, "CALL apoc.create.node(['X'], {})")` raise `WriteBlockedError`; bỏ qua guard bằng cách mở trực tiếp `driver.session(database=settings.neo4j.database, default_access_mode=neo4j.READ_ACCESS)` rồi chạy lần lượt `CREATE (:Intruder)`, `MERGE (:Intruder {a: 1})` và `MATCH (a:Account) SET a.flag = 1` bằng `execute_read`, và `CREATE (:Intruder)` bằng `session.run`, thì cả bốn raise `neo4j.exceptions.ClientError` có `code == "Neo.ClientError.Statement.AccessMode"` và thông điệp chứa `Writing in read access mode not allowed`; `run_write_file(driver, settings, "read/counts.cypher")` raise `GraphError` chứa `not a write file`; sau tất cả các lời gọi trên `MATCH (n:Intruder) RETURN count(n) AS n` trả 0, `MATCH (a:Account) WHERE a.flag IS NOT NULL RETURN count(a) AS n` trả 0 và `MATCH (a:Account) RETURN count(a) AS n` vẫn trả 24; và Given `load_settings(environ={"AML__NEO4J__URI": "bolt://127.0.0.1:1"})`, When gọi `open_driver`, Then raise `ServiceUnavailableError`.
  > Cập nhật 6b-ii: `QUERY_BLOCKED` ghi `version='guard/v2'` (không còn `guard/v1`); xem `specs/neo4j-gds.md`.
- AC9: Given `DB_BACKEND=duckdb` với TINY đã `aml load` và `aml er` (`tiny_env`), When chạy các lệnh `aml graph`, Then với biến môi trường `AML__NEO4J__URI=bolt://127.0.0.1:1` (không có Neo4j): `aml graph sync` exit code 1, stderr chứa `neo4j not available`, `graph_sync_runs` có 0 dòng và `audit_log` không có dòng `module='graph'` nào; `aml graph status` exit code 1 với stderr chứa `neo4j not available`; `aml graph --help` exit code 0, stdout chứa `sync` và `status`, không chứa `Phase 6`; `aml bench` vẫn exit code 1 với stderr chứa `Phase 6`; và Given DuckDB chưa `aml load`, `aml graph sync` exit code 1 với stderr chứa ``run `aml load` first``; còn [neo4j] với Neo4j đã wipe: `aml graph status` exit code 1 với stderr chứa `graph not synced: run aml graph sync`; `aml graph sync --full` exit code 0, stdout có một dòng chứa `run_id=1`, `mode=FULL`, `source=duckdb`, `since=-`, `watermark=2026-06-30T21:53:57`, `nodes=2383`, `rels=8583`, `pruned=0`, `swept=0`, `lag_before_s=-`, `lag_after_s=0`, `in_sync=True`, và 11 dòng theo thứ tự `NODE_LABELS` + `REL_TYPES`, trong đó dòng `Customer` chứa `sent=273 graph=273`, dòng `Account` chứa `sent=1314 graph=1314` và dòng `TRANSFERRED_TO` chứa `sent=3651 graph=3651`; chạy tiếp `aml graph sync` exit code 0 với dòng tổng kết chứa `run_id=2`, `mode=INCREMENTAL`, `since=2026-06-30T20:53:57`, `lag_before_s=0`, `in_sync=True`, dòng `Account` chứa `sent=533 graph=1314`, dòng `TRANSFERRED_TO` chứa `sent=1 graph=3651` và dòng `SENT_TO` chứa `sent=19 graph=3575`; `aml graph status` exit code 0, stdout có dòng chứa `watermark=2026-06-30T21:53:57`, `source=duckdb`, `last_run_id=2`, `lag_s=0`, dòng `Customer 273` và dòng `SENT_TO 3575`, và số dòng `audit_log` `module='graph'` không tăng sau `status`.
- AC10: [oracle] [neo4j] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, `run_er` trên cả hai, `apply_security` đã chạy trên Oracle (test skip với thông điệp nêu tên biến nếu thiếu `ORACLE_SYS_PASSWORD` hoặc `ORACLE_DEMO_PASSWORD`), và Neo4j đã wipe, When gọi `run_sync(duck, settings, full=True)`, ghi lại ảnh đồ thị, rồi gọi `run_sync` trên kết nối Oracle, Then `run_sync(oracle, oracle_settings)` không có `full` raise `SyncError` chứa `run with --full` (đồ thị đang là bản sync từ `duckdb`) và không thêm dòng `graph_sync_runs` nào trên Oracle; `run_sync(oracle, oracle_settings, full=True)` trả `mode = "FULL"`, `source_backend = "oracle"`, `source_user = "aml_graph_sync_usr"`, `sent = graph = S11(273, 1314, 264, 267, 265, 532, 279, 273, 273, 3651, 3575)`, `source = {"TRANSFERRED_TO": 3651, "SENT_TO": 3575}`, `watermark_to = datetime(2026, 6, 30, 21, 53, 57)`, `in_sync is True`; ảnh đồ thị sau lần sync từ Oracle bằng ảnh sau lần sync từ DuckDB ở cả năm tập (273, 1314, 1357, 3651 và 3575 phần tử): (`golden_customer_id`, `cifs`) của `Customer`; (`account_id`, `cif`, `account_type`, `is_external`, `toString(open_date)`) của `Account`; (`golden_customer_id`, kiểu quan hệ, `key` hoặc `account_id`) của `OWNS` / `USES_DEVICE` / `HAS_PHONE` / `LIVES_AT`; (`txn_id`, tài khoản gửi, tài khoản nhận, `amount`, `toString(ts)`, `channel`) của `TRANSFERRED_TO`; (tài khoản gửi, tài khoản nhận, `toString(day)`, `count`, `total`) của `SENT_TO`; gọi tiếp `run_sync(oracle, oracle_settings)` trả `mode = "INCREMENTAL"`, `since = datetime(2026, 6, 30, 20, 53, 57)`, `sent["TRANSFERRED_TO"] = 1`, `sent["SENT_TO"] = 19`, `graph` không đổi và `in_sync is True`; `graph_sync_runs` trên Oracle có dòng của hai lần chạy đó với `source_user = 'aml_graph_sync_usr'` và `in_sync = 1`, `user_views` có `GRAPH_CUSTOMER_ATTRS`; trong `dba_tab_privs` (kết nối admin) tập (`privilege`, `table_name`) của `AML_GRAPH_SYNC` bằng đúng 7 cặp của AC1; đăng nhập bằng `aml_graph_sync_usr` thì `SELECT COUNT(*) FROM aml_owner.graph_customer_attrs` = 300 và `SELECT COUNT(*) FROM aml_owner.customer_golden` = 300, nhưng `SELECT` trên `aml_owner.customers` và `aml_owner.audit_log` raise lỗi chứa `ORA-00942`, còn `DELETE FROM aml_owner.transactions` raise lỗi chứa `ORA-01031` hoặc `ORA-41900`; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- **6b**: mọi truy vấn điều tra `.cypher` (fund-flow trace và việc đăng ký method `neo4j` vào `METHODS` của 5b, vòng
  3–5, cụm thuộc tính dùng chung, fan-in / fan-out); GDS (WCC, Louvain, PageRank, degree), in-memory graph
  projection của GDS, bảng đặc trưng `gds_*` ghi về Oracle; so khớp với NetworkX của 5c; mở rộng `WRITE_PREFIXES` và
  `read_procedures` cho GDS.
- **Ghim phiên bản GDS** (đang là 2.13.13, không ghim) và bỏ việc entrypoint tải `versions.json` / file jar từ
  `graphdatascience.ninja` khi khởi động: `NEO4J_PLUGINS` không cho ghim phiên bản, phải tự mount file jar hoặc dựng
  image riêng → làm ở 6b, nơi GDS thật sự được dùng. 6a chỉ ghim image (kéo theo APOC core) và tắt usage report.
- **6c**: `aml bench`, chạy nhiều lần, median / p95, profile `dense`, bảng và biểu đồ, kết luận "khi nào SQL đủ".
- Text2Cypher, GraphRAG, việc ghi audit cho từng câu hỏi của assistant (Phase 8); API FastAPI và UI đồ thị (Phase 9).
- Tên khách hàng, số giấy tờ, số điện thoại, địa chỉ, mã thiết bị ở dạng đọc được trong Neo4j; khoá băm có muối /
  HMAC; `memo`, `counterparty_name`, `counterparty_bank`, `device_id` / `ip` trên từng giao dịch; node cho tiền mặt /
  ATM / thẻ; node `Alert`, `Case`, `Watchlist`; thuộc tính `kyc_risk` trên `Customer`.
- Change data capture thật (LogMiner, GoldenGate, Kafka, trigger, `ORA_ROWSCN`), thêm cột thời điểm nạp vào bảng
  nguồn, sync theo lịch / daemon, sync song song, sync hai chiều; phát hiện giao dịch bị **sửa** hoặc bị **xoá ở giữa**
  khoảng thời gian (chỉ xử lý xoá từ đầu cũ nhất như retention 2c; còn lại dùng `--full`).
- Nạp lần đầu bằng `CREATE` / `neo4j-admin import` để nhanh hơn `MERGE`; tối ưu `MERGE` của `SENT_TO`.
- Xoá node `Account` không còn quan hệ nào sau khi prune; lịch sử thuộc tính khách hàng theo thời gian; nhiều
  projection / nhiều database Neo4j; Neo4j Enterprise (RBAC, role reader), cluster, backup, TLS cho bolt.
- Sửa policy unified audit `aml_pii_access` của 2b để phủ view `graph_customer_attrs`; quyền Oracle trên
  `graph_sync_runs`, `acct_node` và property graph cho các role của 2b.
- Giới hạn thời gian / số dòng cho truy vấn đọc (timeout, `LIMIT` ép buộc) — 6b / Phase 8 quyết định khi có truy vấn
  thật; đo hiệu năng sync trên profile `large`.
- Target mới trong `Makefile` / `tasks.ps1`; ghi số liệu vào README (làm ở bước demo của phase, từ lần chạy thật của
  code đã hiện thực trên `small`: thời gian sync, `lag_before_seconds`, số node / quan hệ — và chép các số đó vào
  `docs/neo4j-sync.md`).

## Giả định
- **Đã xác nhận bằng đo trên Neo4j 5.26.31 Community + driver 6.4.0** (mục Hiện trạng): constraint duy nhất trên
  quan hệ; server từ chối ghi trong session `READ_ACCESS` với `Neo.ClientError.Statement.AccessMode`; ánh xạ kiểu
  `datetime` / `date`; `IN TRANSACTIONS` chỉ chạy trong transaction tự commit; mọi con số node / quan hệ, `sent`,
  `graph`, `pruned`, `swept`, `lag_*`, watermark của AC6, AC7 và phần [neo4j] của AC9 (đo bằng prototype, không phải
  bằng code của repo). Bản vá Neo4j khác có thể cho hành vi khác — image được ghim để tránh điều đó.
- **Suy ra từ thiết kế, chưa đo** (chưa có code): chuỗi `reason`, số dòng `graph_sync_runs` / `audit_log`, định dạng
  stdout / stderr và exit code của CLI, thông điệp `ValidationError`, toàn bộ AC2 (guard) và phần guard / audit của
  AC8, số statement của `wipe.cypher` trong AC1.
- **Chưa kiểm trên Oracle** (chỉ chạy `SELECT`): DDL `140` (view + bảng), ba quyền mới, việc `aml_graph_sync_usr` đọc
  view `graph_customer_attrs` khi không có quyền trên `customers` (dựa vào quyền của chủ view), và việc truy cập
  `customers` qua view có được policy `aml_pii_access` ghi nhận hay không. Phần so khớp đồ thị của AC10 đã đo bằng
  **kết nối owner** đọc thẳng `customers`; phần "qua user chỉ đọc" thì chưa.
- Thời gian trong mục Hiện trạng là số đo một lần trên máy dev, chỉ để chốt `batch_size` và định hướng; số chính
  thức cho README do bước demo đo bằng code thật. `small` / `dense` trong mục Hiện trạng không phải cam kết; AC chỉ
  cam kết cho MINI-G và TINY seed 42.
- Nguồn sync đọc qua `Database` (Q1): câu "through a dedicated read-only Oracle user" của brief chỉ áp dụng trên
  đường Oracle; trên DuckDB không có phân quyền.
- Projection chứa mọi giá trị thuộc tính, kể cả giá trị chỉ một khách hàng mang (Q4); tài khoản ngoài `accounts`
  thành node `is_external` (Q5); giao dịch một phía null không vào đồ thị (Q6) — structuring bằng tiền mặt là việc
  của rule SQL 5a.
- Khoá băm sha256 không muối (Q3) là **che khuất, không phải ẩn danh**: số điện thoại 10 chữ số dò ngược được bằng
  vét cạn. Người dùng chấp nhận cho dữ liệu tổng hợp; `docs/neo4j-sync.md` phải ghi rõ.
- `txn_ts` là thời điểm nghiệp vụ, không phải thời điểm nạp (Q9): giao dịch tới muộn với `txn_ts` cũ hơn
  `watermark - overlap_minutes` bị sót cho tới lần `--full`; `in_sync = False` là tín hiệu. Sửa tại chỗ không đổi số
  lượng (sửa số tiền) thì không cơ chế nào thấy (Q11).
- Lần sync không nguyên tử (Q14): trong lúc chạy người đọc có thể thấy đồ thị dở dang; đồ thị là bản chụp trễ, mọi
  quyết định báo cáo vẫn dựa trên Oracle. `in_sync = False` không làm lệnh thất bại (exit 0) và không tự chạy
  `--full` (Q13).
- Hai bộ dữ liệu khác nhau trên **cùng** backend (TINY rồi `small`) không bị guard đổi nguồn phát hiện (Q20).
- Phase 4 đã chạy (`customer_golden` có dữ liệu) trước `aml graph sync`; `acct_edge_daily` đã được refresh sau lần
  sửa `transactions` gần nhất (`load_parquet` và `purge_transactions` tự làm) — nếu chưa, `in_sync` vẫn `True` nhưng
  `SENT_TO` lệch `TRANSFERRED_TO`.
- `aml security-setup` đã chạy lại sau khi có DDL `140` (cấp ba quyền mới); test nào drop / tạo lại bảng thì phải
  chạy lại `020_grants.sql` như quy ước 2b.
- Test [neo4j] **xoá sạch projection** trong Neo4j dev (bản Community chỉ có một database) và để lại projection của
  dữ liệu test; sau khi chạy `pytest` có Neo4j, người dùng chạy lại `aml graph sync --full` (Q21, đã xác nhận). Test
  [oracle] nạp lại TINY vào schema `aml_owner` và để lại dòng trong `graph_sync_runs` / `audit_log`.
- Không có hai lần `run_sync` chạy đồng thời (`run_id` cấp bằng `MAX + 1`); không tiến trình nào ghi `transactions`
  trong lúc sync ngoài kịch bản "tới trong lúc chạy" mà `lag_after_seconds` đo.
- Sync không dùng số ngẫu nhiên; `settings.seed` không tham gia. Kết quả tất định với cùng dữ liệu nguồn; ngoài
  `run_ts`, `updated_at`, `seconds`, `event_ts` không giá trị nào phụ thuộc đồng hồ máy.
- `txn_ts` là giờ Việt Nam naive, độ phân giải giây (quy ước 1b-i); `ts` trong Neo4j giữ nguyên dạng naive. Mã tài
  khoản và `txn_id` là duy nhất và không đổi sau khi sinh.
- PII (`phone`, `street`, `device_id`) được kéo về bộ nhớ tiến trình sync để tính khoá như Phase 4 / 5c, không ghi
  ra đĩa, không ghi vào Neo4j, `graph_sync_runs` hay `audit_log`.
- Gói `aml.graph.neo4j` không che driver `neo4j`: mọi import trong repo là import tuyệt đối và không script nào chạy
  với thư mục làm việc là `src/aml/graph/`.
- Tên nhãn, kiểu quan hệ, tên constraint, cỡ lô xoá 10 000 và danh sách `WRITE_KEYWORDS` là **cấu trúc** (hằng trong
  code / file `.cypher`), không phải ngưỡng nghiệp vụ nên không đưa vào `config.yaml`; `batch_size`,
  `overlap_minutes`, `oracle_user`, `database`, `read_procedures` là cấu hình.
- `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có.

## Câu hỏi mở
- [x] Q1. Nguồn sync đọc qua `Database` abstraction (chạy được cả từ DuckDB) hay chỉ Oracle? — đề xuất mặc định: qua `Database`; `open_source` trả chính kết nối DuckDB khi backend là `duckdb`, và mở kết nối `aml_graph_sync_usr` khi backend là `oracle`. Lý do: AC3–AC5 kiểm toàn bộ logic dựng node / quan hệ / cửa sổ mà không cần dịch vụ nào, AC6–AC9 chỉ cần Neo4j; đúng quy tắc "feature module không import driver trực tiếp". — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q2. User Oracle nào cho sync, và cấp thêm quyền gì? — đề xuất mặc định: dùng lại `aml_graph_sync_usr` của 2b (mật khẩu `ORACLE_DEMO_PASSWORD`), cấp thêm `SELECT` trên view mới `graph_customer_attrs` (`cif`, `phone`, `device_id`, `street`, `ward`, `district`, `province`), `customer_golden` và `admin_unit_mapping` (4 → 7 quyền). Lý do: đã đo — với 4 quyền hiện tại user này nhận ORA-00942 trên `customer_golden`, và `customers_masked` không có `device_id` / `street`, `phone` chỉ còn 3 số cuối; view hẹp giữ tên, ngày sinh, số giấy tờ, email ngoài tầm user sync. Phương án thay thế: tiến trình owner tính sẵn bảng khoá đã băm. — Trả lời: theo đề xuất mặc định; việc sửa `tests/security/test_oracle_security.py` và ma trận quyền + AC6 của `specs/oracle-security.md` là một phần của 6a (2026-10-12).
- [x] Q3. Neo4j Community không có RBAC — đưa gì của khách hàng sang? — đề xuất mặc định: `Device` / `Phone` / `Address` chỉ mang `key` = 16 ký tự hex đầu của sha256 (không muối) trên khoá chuẩn hoá của 5c; `Customer` chỉ mang `golden_customer_id`, `cifs`, `cif_count`; không tên, không số, không địa chỉ. Lý do: cùng hướng với Q5 của 2b và với 5c; băm tất định nên 6b vẫn so được cụm với NetworkX. Hạn chế: sha256 không muối trên số điện thoại 10 chữ số dò ngược được bằng vét cạn. Phương án thay thế: HMAC với khoá bí mật trong `.env`; hoặc lưu giá trị thô / tên đã che. — Trả lời: theo đề xuất mặc định; ghi rõ hạn chế dò ngược trong `docs/neo4j-sync.md` (2026-10-12).
- [x] Q4. Node thuộc tính cho mọi giá trị hay chỉ giá trị dùng chung? — đề xuất mặc định: mọi giá trị (kể cả chỉ một khách hàng mang), không áp `max_customers_per_value` của 5c; CIF không có trong `customer_golden` thành khách hàng riêng `'G-' + cif`; `customer_golden` rỗng thì dừng với ``run `aml er` first``. Lý do: projection là dữ liệu, ngưỡng là việc của truy vấn 6b. Hệ quả đo được: `small` có 4653 + 4515 + 4243 node thuộc tính. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q5. Tài khoản `EXT-*` (không có trong `accounts`) xử lý sao? — đề xuất mặc định: node `Account` tối giản với `is_external = true`, không có `OWNS`; nhận diện bằng "không có trong `accounts`", không dựa vào tiền tố. Lý do: 5b đã chốt đi xuyên qua `EXT-` nên bản trace Cypher của 6b chỉ khớp `cte_raw` khi các node này tồn tại. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q6. Giao dịch một phía null (CASH / CARD) và self-transfer? — đề xuất mặc định: giao dịch một phía null không vào đồ thị (như `acct_edge_daily` và 5b); self-transfer vẫn thành quan hệ vòng trên một node. Lý do: không có node đối tác để nối; `small` có 91 411 giao dịch như vậy. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q7. `TRANSFERRED_TO` là một quan hệ cho mỗi giao dịch? — đề xuất mặc định: có, `MERGE` theo `txn_id`, thuộc tính `txn_id`, `amount`, `ts`, `channel`; constraint duy nhất trên `txn_id` của quan hệ (đã đo là dùng được ở Community). Không đưa `memo` / `counterparty_name`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q8. `SENT_TO` lấy từ đâu? — đề xuất mặc định: từ `acct_edge_daily` (một quan hệ cho mỗi dòng), khoá `MERGE` là cặp tài khoản + `day`, mỗi lần sync `SET` lại `count` / `total`. Hệ quả: nếu `acct_edge_daily` chưa refresh thì `SENT_TO` lệch `TRANSFERRED_TO` mà `in_sync` không thấy. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q9. Cột nào làm watermark, bảng nào nạp lại toàn bộ? — đề xuất mặc định: `transactions.txn_ts` cho `TRANSFERRED_TO` (đọc `txn_ts >= watermark - overlap_minutes`, mặc định 60 phút); `acct_edge_daily.day >=` ngày của mốc đó cho `SENT_TO`; `customers` / `accounts` / `customer_golden` / `admin_unit_mapping` nạp lại toàn bộ mỗi lần vì không có cột thời gian nào. Đã đo: phần nạp lại này mất khoảng 1,2 giây trên `small`. Hạn chế: giao dịch tới muộn với `txn_ts` cũ bị sót cho tới lần `--full` (AC7a). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q10. Watermark lưu ở đâu? — đề xuất mặc định: trong chính Neo4j, node `SyncState {name: 'projection'}`, cập nhật ở bước cuối của lần chạy thành công; bảng `graph_sync_runs` (DDL `140`) chỉ là nhật ký lần chạy. Lý do: user sync chỉ đọc; và nếu volume Neo4j bị xoá thì watermark mất cùng dữ liệu → lần sau tự chạy `FULL`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q11. Xoá / sửa ở nguồn (retention 2c archive rồi drop partition cũ)? — đề xuất mặc định: prune theo giao dịch cũ nhất còn ở nguồn; sweep phía khách hàng bằng `synced_run`; mọi trường hợp khác → `aml graph sync --full`. Đã đo trên Neo4j: AC7c (`pruned = 3`) và AC7d (`swept = 5`). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q12. "Sync lag" định nghĩa và đo thế nào? — đề xuất mặc định: theo thời gian dữ liệu — `lag_before_seconds` = `txn_ts` lớn nhất ở nguồn − watermark lúc bắt đầu chạy; `lag_after_seconds` = cùng phép đo ngay sau khi nạp; kèm `seconds`. `aml graph status` in `lag_s`. Lý do: dữ liệu tổng hợp kết thúc 2026-06-30 nên độ trễ theo đồng hồ máy vô nghĩa; với lịch chạy mỗi N phút, độ trễ tệ nhất ≈ N + `seconds` (đo được: 1,8 giây cho một lần INCREMENTAL không có gì mới trên `small`, 46–49 giây cho FULL). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q13. Phép kiểm consistency và khi lệch thì sao? — đề xuất mặc định: so số `TRANSFERRED_TO` với số giao dịch hai phía ở nguồn và số `SENT_TO` với số dòng `acct_edge_daily`; lệch → `in_sync = False`, `reason` và stderr ghi `OUT OF SYNC: run aml graph sync --full`, exit code vẫn 0, không tự chạy `--full`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q14. Cỡ batch `UNWIND` và phạm vi transaction? — đề xuất mặc định: `graph_sync.batch_size = 5000` dòng, mỗi lô một transaction tự commit, trần cấu hình 50 000. Đã đo trên `small` (FULL, heap 1 GB): 55,4 giây ở 1000; 46,1 và 49,0 giây ở 5000; 49,5 giây ở 20 000 — cỡ batch gần như không ảnh hưởng, 5000 không tệ hơn cỡ nào; `dense` 43,7 giây. Hệ quả: lần sync không nguyên tử (AC7e). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q15. Có cần APOC không? — đề xuất mặc định: không ở 6a; mỗi nhãn / kiểu quan hệ một file `.cypher`, xoá theo lô bằng `CALL (x) { } IN TRANSACTIONS` thuần Cypher (đã đo là chạy được, với điều kiện xoá quan hệ trước node). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q16. Guard chặn write nhận diện gì, ngoại lệ cho đường sync thế nào? — đề xuất mặc định: chặn theo từ khoá trọn vẹn (`CREATE`, `MERGE`, `SET`, `DELETE`, `DETACH`, `REMOVE`, `DROP`, `FOREACH`, `LOAD`, `ALTER`, `RENAME`, `GRANT`, `DENY`, `REVOKE`, `TERMINATE`) sau khi bỏ chuỗi / định danh backtick / comment; `CALL <procedure>` chỉ qua khi tên khớp `neo4j.read_procedures`; nhiều statement bị chặn. Đường sync không đi qua guard: `run_write_file` chỉ nhận tên file thuộc `WRITE_PREFIXES`. Lớp bảo vệ thật là session `READ` (đã đo). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q17. Ghi `audit_log` những gì? — đề xuất mặc định: 1 dòng `SYNCED` cho mỗi lần sync thành công, 1 dòng `SYNC_FAILED` khi lỗi giữa chừng, 1 dòng `QUERY_BLOCKED` khi guard chặn và người gọi truyền `audit_db`; truy vấn đọc thành công, `aml graph status` và lỗi tiền điều kiện không ghi. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q18. Hình dạng CLI? — đề xuất mặc định: `aml graph` thành nhóm lệnh với `aml graph sync [--full]` và `aml graph status`; `aml bench` giữ nguyên stub. Hệ quả: sửa `tests/graph/test_cli.py` của 5b (bỏ `graph` khỏi test `Phase 6`) là một phần của 6a. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q19. Đặt code và file `.cypher` ở đâu? — đề xuất mặc định: gói `src/aml/graph/neo4j/` và Cypher trong `src/aml/graph/neo4j/cypher/` (`schema.cypher`, `sync/`, `read/`); mỗi statement kết thúc bằng `;` cuối dòng, comment `//`, giá trị chỉ qua `$tham_số`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q20. Đồ thị đang chứa bản sync từ nguồn khác? — đề xuất mặc định: `SyncState.source_backend` khác backend hiện tại thì `aml graph sync` dừng với `run with --full`, không tự xoá (đã đo: DuckDB rồi Oracle). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q21. Test [neo4j] được phép xoá projection trong Neo4j dev? — đề xuất mặc định: có; fixture chạy `sync/wipe.cypher` trước mỗi test, sau `pytest` người dùng chạy lại `aml graph sync --full`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q22. Một spec hay tách đôi? — đề xuất mặc định: một spec (10 AC). — Trả lời: giữ một spec 10 AC; khởi động Neo4j và đo lại trước khi duyệt — đã làm, kết quả ở mục Hiện trạng (2026-10-12).
- [x] Q23. Thay đổi `docker-compose.yml` trong 6a? — đề xuất mặc định: (a) thêm `NEO4J_dbms_usage__report_enabled: "false"` vào service `neo4j`; (b) ghim image `neo4j:5.26-community` → `neo4j:5.26.31-community`; (c) **không** ghim GDS ở 6a (để 6b). Lý do: (a) log khởi động hiện có dòng `Anonymous Usage Data is being sent to Neo4j`, trái quy tắc "no external API calls" — đã thử trên container tạm: biến này đưa `dbms.usage_report.enabled` về `false` và dòng log biến mất; (b) mọi số đo của spec lấy trên 5.26.31, tag `5.26-community` trôi theo bản vá, và APOC core đi kèm image nên được ghim theo; (c) `NEO4J_PLUGINS` không cho ghim phiên bản GDS, phải mount file jar hoặc dựng image riêng, và 6a không dùng GDS. Hệ quả: container đang chạy phải được tạo lại (`up -d`) để nhận cấu hình; entrypoint vẫn tải GDS từ mạng khi khởi động cho tới khi 6b xử lý. — Trả lời: theo đề xuất (a), (b), (c); tạo lại container Neo4j khi implement.
