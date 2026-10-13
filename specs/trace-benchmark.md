---
id: trace-benchmark
status: approved
approved_by: pthieu
---

# Phase 6c — Benchmark bốn bản fund-flow trace (`aml bench` / `make bench`)

## Bối cảnh
Phần "Benchmark (`make bench`)" của Phase 6 trong PROJECT_BRIEF.md (mục 7) — phần cuối của Phase 6. 5b
(`specs/fund-flow-trace.md`) đã có `cte_raw`, `cte_edge`, `pgq`; 6b-i (`specs/neo4j-queries.md`) thêm method `neo4j`.
Spec này thêm lệnh `aml bench`: chạy bốn method ở 2 / 4 / 6 hop, mỗi ô nhiều lần với cache ấm, ghi median / p95 / số
path / số dòng code truy vấn vào một file kết quả, rồi dựng bảng Markdown và biểu đồ **từ file kết quả đó**. Spec tách
hai việc: **(a) code benchmark** — tất định, kiểm thử được, không AC nào ghim thời gian; **(b) lần chạy thật trên
`small` và `dense` cùng phần kết luận viết** ("khi nào SQL đủ, khi nào property graph trong database có ích, khi nào
graph DB riêng xứng đáng") — là bước demo của phase, do người chạy làm sau khi code xong, mọi con số lấy từ file kết
quả kèm lệnh, ngày, phiên bản, máy. Người dùng: người chạy demo và người phỏng vấn đọc bảng. Benchmark chỉ đọc: không
sinh alert, không sync, không nạp dữ liệu.

### Hiện trạng đã kiểm (2026-10-13, seed 42)
Đo bằng script tạm ngoài repo, gọi đúng `trace(..., record_audit=False)` của repo; mỗi ô 1 lần làm ấm rồi 5 lần bấm giờ
(7 lần với DuckDB), lấy `TraceResult.seconds`; không chạy hai việc song song. Oracle 23.26.3 Free và Neo4j 5.26.31
Community trong Docker trên cùng máy (Windows 11, 12 CPU logic, Docker 7,68 GiB), DuckDB 1.5.6 in-process, driver
`neo4j` 6.4.0, `oracledb` 3.0.6. Để đo, `small` rồi `dense` đã được nạp thật vào Oracle và sync sang Neo4j; sau đó
trạng thái dev đã được trả về: Oracle chứa TINY (`load_parquet` + `run_er` + `apply_security`), Neo4j chứa `small`
sync từ `data/aml.duckdb` (run 12, `in_sync=True`), `gds.graph.list()` rỗng.
- **Chạy đủ bốn bản trên Oracle là khả thi và nhanh** (trái với lo ngại ban đầu):

  | bước chuẩn bị một profile | `small` | `dense` |
  |---|---|---|
  | `aml data --profile … --out <tmp>` | (đã có) | 3 giây |
  | `aml load` vào DuckDB / `aml er` | — | 4 / 3 giây |
  | `aml load --backend oracle` (338 753 dòng, 9 bảng) | 18 giây | 25 giây |
  | `aml er` + `aml security-setup` trên Oracle | 3 + 2 giây | 4 giây |
  | `aml graph sync --full` từ Oracle | 49,9 giây | 48,9 giây |
  | `aml graph sync --full` từ DuckDB / INCREMENTAL không có gì mới | 47,4 giây / — | 51,3 / 2,1 giây |

  Tổng chuẩn bị một profile trên Oracle khoảng 75–80 giây; lượt đo 24 ô × 4 method với 5 lần lặp mất 118 giây
  (`small`) và 70 giây (`dense`). Segment của `aml_owner` tăng từ 44,8 lên 131,4 MB (giới hạn Oracle Free: 12 GB).
  Bộ nhớ container trong lúc đo: Neo4j 1,99–2,03 / 2,44 GiB, Oracle 1,93–2,12 / 3 GiB.
- **Bốn method trên Oracle, cùng dữ liệu, đồ thị sync từ Oracle** (trung vị mili giây ở 2 / 4 / 6 hop; `cte_raw`,
  `pgq`, `neo4j` cho cùng số dòng ở mọi ô):

  | profile, tài khoản | T (giờ) | số dòng | `cte_raw` | `cte_edge` (số dòng) | `pgq` | `neo4j` |
  |---|---|---|---|---|---|---|
  | `small`, `A5461833942` | 72 | 632 / 658 / 658 | 14 / 15 / 17 | 5 / 5 / 5 (13) | 25 / 188 / **7525** | 42 / 57 / 43 |
  | `small`, `A5461833942` | 720 | 4289 / 10 955 / 22 394 | 43 / 150 / 422 | 4 / 5 / 5 (26–27) | 50 / 266 / **8171** | 240 / 574 / 1210 |
  | `dense`, `A4173555232` | 72 | 94 / 112 / 112 | 6 / 7 / 7 | 4 / 4 / 4 (5) | 5 / 134 / **4402** | 15 / 18 / 17 |
  | `dense`, `A4173555232` | 720 | 435 / 4098 / 12 366 | 9 / 70 / 290 | 4 / 5 / 5 (11–14) | 12 / 175 / **4722** | 31 / 226 / 681 |

  `pgq` 6 hop mất 4–8 giây bất kể số dòng (ở tài khoản chỉ có 35 dòng: 146 mili giây so với 5 của `cte_raw`) — chưa
  tuning, đúng như 5b đã ghi. Không ô nào timeout (60 giây) hay vượt `trace.max_paths` (100 000).
- **Ba method trên DuckDB** (không có `pgq`; trung vị mili giây, 2 / 4 / 6 hop): `small` T = 720 — `cte_raw` 32 / 76 /
  144, `cte_edge` 11 / 14 / 14, `neo4j` 228 / 589 / 1196; T = 72 — 25 / 43 / 42, 12 / 14 / 14, 53 / 48 / 53. `dense`
  T = 720 — 20 / 50 / 111, 10 / 16 / 16, 33 / 232 / 685; T = 72 — 18 / 36 / 42, 10 / 10 / 9, 19 / 17 / 17.
- **`dense` không bùng nổ path trong cửa sổ cho phép** (`trace.max_hours` = 720): cùng 306 000 giao dịch nhưng rải
  trên nhiều đối tác hơn, nên tài khoản nặng nhất của `dense` cho 12 366 dòng ở 6 hop / 720 giờ, ít hơn `small`
  (22 394). Bùng nổ chỉ có ở T ngoài trần (5b: 4,6 triệu dòng ở T = 4320).
- **Chọn tài khoản xuất phát**: tiêu chí "nhiều chuyển khoản đi nhất" **hỏng trên `dense`** — nó chọn employer payroll
  `A8716824780` (174 dòng ở mọi hop và mọi T vì nhân viên không chuyển tiếp). Tài khoản của kịch bản typology cũng
  phẳng (`small`: 0–89 dòng, mọi method dưới 30 mili giây). Tiêu chí **"nhiều path 2 hop đúng thứ tự thời gian nhất
  trong T lớn nhất, hoà thì `account_id` nhỏ hơn"** chọn `A5461833942` (`small`, 4099 path) và `A4173555232` (`dense`,
  376); truy vấn chọn mất 0,07 giây trên DuckDB, 0,02–0,05 giây trên Oracle TINY và cho cùng kết quả ở hai backend
  (TINY: `A7341585768` với T = 720; với T = 168 hoà 24–24 và chọn `A5040436031`). Ba tài khoản đứng đầu cho thời gian
  cùng bậc (`small` 6 hop / 720 giờ: 141 / 178 / 151 mili giây).
- **Chọn T**: với T = 72 số dòng gần như không đổi từ 4 lên 6 hop; chỉ T = 720 mới tách được 2 / 4 / 6 hop.
- **Công bằng**: `TraceResult.seconds` ở cả bốn method bao quanh truy vấn + kéo kết quả về DataFrame + `normalise` (có
  sắp xếp); `prepare` của `neo4j` nằm ngoài, tốn 13–16 mili giây (nguồn DuckDB) hoặc 21–29 (nguồn Oracle). Lần chạy
  đầu chậm hơn rõ (`neo4j` 367 so với 53 mili giây; `pgq` 6 hop 8764 so với 7525) → cần làm ấm. Chạy tuần tự từng ô
  hay xen kẽ theo vòng cho trung vị như nhau (`small`, `neo4j` 6 hop: 1195,6 và 1195,4). DuckDB chạy in-process còn
  Oracle và Neo4j qua cổng localhost của Docker. `cte_edge` trả tập dòng khác (xấp xỉ theo ngày, top-K) — trên MINI-T
  nó còn trả **nhiều** dòng hơn `cte_raw` (11 so với 9).
- **Số dòng code** (`query_lines`): Oracle `cte_raw` 30, `cte_edge` 38, `pgq` 19 / 49 / 99 theo 2 / 4 / 6 hop, `neo4j`
  58 ở mọi hop; DuckDB `cte_raw` 38, `cte_edge` 43.
- **p95 với ít lần chạy**: nội suy tuyến tính (mặc định của NumPy) trên 5 lần = lần chậm thứ tư + 0,8 × khoảng cách
  tới lần chậm nhất — gần như là max.
- **Biểu đồ**: `pyproject.toml` chưa có thư viện vẽ. Đã thử `matplotlib` 3.11.2 trong môi trường tạm (`uv run --with`,
  không đổi `uv.lock`): SVG 21 KB, hai lần vẽ cho file giống hệt từng byte khi đặt `svg.hashsalt`, `svg.fonttype =
  none`, `metadata={"Date": None}`, và tên method còn là chữ trong file; kéo thêm 11 gói.
- **Code sẵn có**: `aml bench` là stub chung (`arrives in Phase 6`, exit 1), được ba test khẳng định:
  `tests/graph/test_cli.py`, `tests/neo4j_queries/test_offline.py`, `tests/neo4j_sync/test_cli.py`. `Makefile` /
  `tasks.ps1` đã có `bench`. `results/phaseN/` được commit (CSV, txt); `README.md` chưa có bảng số liệu nào. Method
  `pgq` trên DuckDB raise `TraceError` thường (`Oracle only`), không phải `TraceUnavailableError`. Timeout Neo4j thành
  `TraceError("neo4j trace failed: …")`. Method SQL không có timeout. `audit_log` có dòng `datagen` / `LOADED` với
  `entity_id = <profile>-seed<seed>` (TINY cũng mang nhãn `small-seed42`).
- **Chưa đo**: `large`; truy vấn chọn tài khoản trên Oracle với `small` / `dense` (chỉ đo trên TINY); thời gian của
  lượt đo với 10 lần lặp; output và exit code của CLI, chuỗi `reason` (chưa có code); biểu đồ thật từ file kết quả.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class BenchConfig(BaseModel):
    hops: list[int]  # không rỗng, tăng dần, mỗi giá trị 1..trace.max_hops
    hours: list[int]  # không rỗng, tăng dần, mỗi giá trị 1..trace.max_hours
    runs: int  # số lần bấm giờ mỗi ô; >= 5
    warmup_runs: int  # số lần chạy bỏ đi trước khi bấm giờ; >= 0
    accounts: list[str]  # rỗng -> tự chọn bằng pick_accounts
    top_accounts: int  # số tài khoản tự chọn; 1..10
    results_dir: str


# src/aml/graph/bench/stats.py  (thuần Python)
def median(values: Sequence[float]) -> float: ...
def percentile(
    values: Sequence[float], q: float
) -> float: ...  # nội suy tuyến tính, vị trí (n - 1) * q / 100


# src/aml/graph/bench/model.py
SCHEMA = "bench/v1"
NOTE_APPROXIMATE = "approximate (daily edges, top-K): paths not comparable"


class BenchError(RuntimeError): ...


@dataclass(frozen=True)
class BenchCell:
    method: str
    account: str
    hours: int
    hops: int
    status: str  # "ok" | "skipped" | "error"
    reason: str | None  # None khi ok
    exact: bool
    seconds: tuple[float, ...]  # TraceResult.seconds của từng lần bấm giờ; rỗng khi không ok
    median_ms: float | None
    p95_ms: float | None
    min_ms: float | None
    max_ms: float | None
    n_paths: int | None
    n_accounts: int | None
    n_cycles: int | None
    query_lines: int | None


@dataclass(frozen=True)
class BenchResult:
    meta: dict[str, Any]
    cells: list[BenchCell]


# src/aml/graph/bench/runner.py
def pick_accounts(db: Database, settings: Settings) -> list[str]: ...
def run_bench(
    db: Database,
    settings: Settings,
    *,
    profile: str | None = None,  # None -> lấy từ dòng audit LOADED mới nhất, không có thì "unknown"
    command: str = "aml bench",
    actor: str | None = None,
) -> BenchResult: ...


# src/aml/graph/bench/report.py
def write_result(
    result: BenchResult, results_dir: Path
) -> Path: ...  # bench_<profile>_<backend>.json
def read_results(results_dir: Path) -> list[BenchResult]: ...  # mọi bench_*.json, theo tên file
def render_report(results: Sequence[BenchResult]) -> str: ...  # Markdown, thuần Python
def render_chart(results: Sequence[BenchResult], path: Path) -> Path: ...  # SVG
def write_report(results_dir: Path) -> tuple[Path, Path]: ...  # bench_report.md, bench_chart.svg
```
- `config.yaml`: mục mới `bench: {hops: [2, 4, 6], hours: [72, 720], runs: 10, warmup_runs: 1, accounts: [],
  top_accounts: 1, results_dir: results/phase6}`.
- SQL mới `sql/duckdb/bench/pick_accounts.sql` và `sql/oracle/bench/pick_accounts.sql` (bind `hours`, `top_n`).
- CLI: `aml bench [--profile NHÃN] [--report-only]`. `Makefile` / `tasks.ps1` không đổi.
- `pyproject.toml`: thêm `matplotlib` (Q8). Tài liệu `docs/trace-benchmark.md`.
- **Sửa kéo theo ở phần đã duyệt — là một phần của 6c**: ba test đang khẳng định `aml bench` là stub (nêu ở Hiện
  trạng) bỏ phần `bench`; `specs/neo4j-queries.md` AC2 và `specs/neo4j-sync.md` thêm ghi chú dẫn về spec này.

### Thiết kế (đề xuất, chờ xác nhận ở Câu hỏi mở)
- **Một lượt = trạng thái hiện có của một backend.** `run_bench` đo trên `db` đang mở và đồ thị Neo4j đang có; không
  sinh dữ liệu, không nạp, không sync. Người chạy tự chuẩn bị từng profile (lệnh ghi trong `docs/trace-benchmark.md`)
  và chạy `aml bench` mỗi lần một file kết quả; báo cáo gộp mọi file trong `results_dir`.
- **Chọn tài khoản** (`pick_accounts`): `bench.accounts` khác rỗng thì dùng nguyên; ngược lại lấy `top_accounts` tài
  khoản có trong `accounts` có nhiều cặp chuyển khoản (e1, e2) nhất với `e1.from = X`, `e2.from = e1.to`, `e2.ts >
  e1.ts` và `e2.ts <= e1.ts + max(bench.hours)` giờ; hoà thì `account_id` tăng dần. Không có tài khoản nào →
  `BenchError("no account to benchmark: run aml load first")`.
- **Ô** = (tài khoản, T, hop, method), thứ tự: tài khoản → `hours` → `hops` → `METHODS`. Chạy tuần tự, mỗi ô
  `warmup_runs` lần bỏ đi rồi `runs` lần bấm giờ liền nhau bằng `trace(..., record_audit=False)`; thời gian =
  `TraceResult.seconds`. `median_ms` / `p95_ms` / `min_ms` / `max_ms` tính từ `seconds` bằng `stats`; `n_paths`,
  `n_accounts`, `n_cycles`, `query_lines` lấy từ lần chạy cuối. `cte_edge` dùng ngưỡng và top-K mặc định của config.
- **Trạng thái ô**: `skipped` — method không chạy trên backend này (`reason = "not available on <backend>"`), hoặc
  `prepare` / lần chạy raise `TraceUnavailableError` (`reason` = thông điệp; `prepare` được thử một lần cho mỗi
  method); `error` — mọi exception khác ở bất kỳ lần chạy nào (`reason = "<TênLớp>: <thông điệp>"`, gồm vượt
  `max_paths` và timeout Neo4j), các lần còn lại của ô bị bỏ. Ô không `ok` có `seconds = ()` và mọi số là `None`.
  Một ô hỏng không dừng lượt.
- **`meta`**: `schema`, `profile`, `backend`, `command`, `started_at` (UTC ISO), `total_seconds`, `git_commit`,
  `versions` (python, aml, driver, server), `machine` (platform, processor, cpu_count), `dataset` (customers,
  accounts, transactions, transfers), `params` (hops, hours, runs, warmup_runs, accounts, picked — `True` khi tự
  chọn), `trace` (max_paths, edge_min_amount_vnd, edge_top_k), `read_timeout_seconds`, `sync` (`None`, hoặc
  `{full_seconds, incremental_seconds, lag_after_seconds}` của lần FULL và INCREMENTAL mới nhất trong
  `graph_sync_runs` khi có ô `neo4j` nào `ok`).
- **Audit**: mỗi lượt đúng 1 dòng `module='graph'`, `entity_type='benchmark'`, `entity_id='<profile>-<backend>'`,
  `decision='BENCHMARKED'`, `version='bench/v1'`, `reason` = `trace benchmark on <backend> (<profile>): <a> cells ok,
  <b> skipped, <c> failed; <runs> timed runs per cell`, `details = {accounts, hops, hours, runs, warmup_runs, ok,
  skipped, error}`. Không có dòng `TRACED` nào.
- **Báo cáo** (`render_report`): mỗi file một khối xuất xứ (lệnh, `started_at`, commit, phiên bản, máy, dataset, số
  lần lặp, chi phí sync nếu có) rồi một bảng, mỗi ô một dòng: `| profile | backend | account | T (h) | hops | method |
  status | paths | median ms | p95 ms | query lines | note |`; mili giây 1 chữ số thập phân; ô không `ok` để trống các
  cột số và ghi `reason` vào `note`; ô `cte_edge` có `note` = `NOTE_APPROXIMATE`. Cuối báo cáo có chú thích cố định:
  thời gian gồm truy vấn + kéo kết quả + chuẩn hoá; p95 là nội suy tuyến tính; `pgq` dài theo số hop còn `neo4j` là
  một file cho mọi hop; DuckDB in-process còn Oracle / Neo4j qua mạng. **Báo cáo không chứa câu kết luận nào.**
- **Biểu đồ** (`render_chart`): một file SVG, mỗi (file kết quả, tài khoản) một ô lưới ở T lớn nhất: trục x là hop,
  trục y là `median_ms` thang log, mỗi method có ô `ok` một đường. Tất định từng byte.
- **CLI**: `aml bench` mở backend cấu hình, `run_bench`, `write_result`, `write_report`; in `bench profile=<p>
  backend=<b> accounts=<…> cells=<n> ok=<a> skipped=<b> error=<c> seconds=<s>`, mỗi method bị bỏ một dòng `method=<m>
  skipped: <reason>`, rồi ba dòng `wrote <đường dẫn>`. Exit 0 kể cả khi có ô `skipped` / `error`; `BenchError` hoặc
  cơ sở dữ liệu nguồn không mở được → stderr, exit 1. `--report-only`: chỉ `write_report`; thư mục không có file
  kết quả → stderr chứa `no benchmark results`, exit 1.

## Tiêu chí nghiệm thu
<!-- MINI-T, TINY, OFFLINE, `tiny_env`, `tiny_er`, `neo`, "đã sync" = như specs/neo4j-queries.md. `settings` =
`load_settings(environ={"DB_BACKEND": "duckdb", ...})` với `AML__BENCH__RUNS=5` và `AML__BENCH__RESULTS_DIR` trỏ vào
`tmp_path` trừ khi nói khác. Test [neo4j] / [oracle] dùng marker tương ứng và tự skip khi dịch vụ không chạy. Không AC
nào khẳng định giá trị thời gian; không test nào chạy `small` / `dense`.
SAMPLE = `BenchResult` dựng tay: `meta` có `profile="small"`, `backend="oracle"`, `command="aml bench"`,
`params.hours=[720]`, `params.hops=[6]`, `sync=None`; 4 ô cùng (`A1`, 720, 6): `cte_raw` ok với
`seconds=(0.4, 0.5, 0.6, 0.7, 0.8)`, `median_ms=600.0`, `p95_ms=780.0`, `n_paths=22394`, `query_lines=30`; `cte_edge` ok
(`exact=False`) với `seconds=(0.004,) * 5`, `n_paths=27`, `query_lines=38`; `pgq` error với
`reason="TraceError: more than 100000 paths"`; `neo4j` skipped với `reason="neo4j not available"`. -->
- AC1: Given `config.yaml`, module `aml.graph.bench.stats` và `docs/` của repo (không cần dịch vụ nào), When `load_settings(environ={})` và gọi các hàm thống kê, Then `settings.bench.hops == [2, 4, 6]`, `settings.bench.hours == [72, 720]`, `settings.bench.runs == 10`, `settings.bench.warmup_runs == 1`, `settings.bench.accounts == []`, `settings.bench.top_accounts == 1`, `settings.bench.results_dir == "results/phase6"`; `load_settings(environ={"AML__BENCH__RUNS": "4"})` raise `pydantic.ValidationError` chứa `runs must be >= 5`, `AML__BENCH__HOPS=[2, 7]` raise `ValidationError` chứa `hops must be between 1 and 6`, `AML__BENCH__HOURS=[721]` raise `ValidationError` chứa `hours must be between 1 and 720`, `AML__BENCH__HOPS=[]` raise `ValidationError` chứa `hops must not be empty`, `AML__BENCH__TOP_ACCOUNTS=0` raise `ValidationError` chứa `top_accounts must be between 1 and 10`; `median([10, 20, 30, 40, 100]) == 30`, `median([4, 1, 3, 2]) == 2.5`, `percentile([10, 20, 30, 40, 100], 95) == pytest.approx(88.0)`, `percentile([100, 10, 40, 20, 30], 95) == pytest.approx(88.0)`, `percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 95) == pytest.approx(9.55)`, `percentile([5.0], 95) == 5.0`, `percentile([10, 20], 50) == median([10, 20]) == 15`, `median([])` và `percentile([], 95)` raise `ValueError` chứa `empty`, `percentile([1], 101)` raise `ValueError` chứa `between 0 and 100`; và `docs/trace-benchmark.md` tồn tại, chứa các chuỗi `aml bench`, `aml graph sync --full`, `warm`, `p95` và `cte_edge`.
- AC2: Given MINI-T trong DuckDB và `settings` OFFLINE có thêm `AML__BENCH__HOURS=[24]`, When gọi `result = run_bench(duck, settings, profile="mini")`, Then `result.meta["schema"] == "bench/v1"`, `meta["profile"] == "mini"`, `meta["backend"] == "duckdb"`, `meta["params"]["accounts"] == ["A"]`, `meta["params"]["picked"] is True`, `meta["params"]["runs"] == 5`, `meta["dataset"]["transfers"] == 12`, `meta["sync"] is None`; `result.cells` có đúng 12 ô theo thứ tự (`hops`, `method`) = (2, `cte_raw`), (2, `cte_edge`), (2, `pgq`), (2, `neo4j`), (4, …), (6, …), mọi ô có `account == "A"` và `hours == 24`; ba ô `cte_raw` có `status == "ok"`, `exact is True`, `n_paths` lần lượt 3, 9, 9, `n_accounts` 2, 6, 6, `n_cycles` 1, 3, 3; ba ô `cte_edge` có `status == "ok"`, `exact is False`, `n_paths` lần lượt 4, 11, 11; mỗi ô `ok` có `len(seconds) == 5`, mọi phần tử `> 0`, `median_ms == pytest.approx(median(seconds) * 1000)`, `p95_ms == pytest.approx(percentile(seconds, 95) * 1000)`, `min_ms <= median_ms <= p95_ms <= max_ms` và `query_lines > 0`; ba ô `pgq` có `status == "skipped"` và `reason == "not available on duckdb"`; ba ô `neo4j` có `status == "skipped"` và `reason` chứa `neo4j not available`; mọi ô không `ok` có `seconds == ()` và `median_ms`, `p95_ms`, `n_paths`, `query_lines` đều `None`; `audit_log` tăng đúng 1 dòng, dòng đó có `module='graph'`, `entity_type='benchmark'`, `entity_id='mini-duckdb'`, `decision='BENCHMARKED'`, `version='bench/v1'`, `reason` bằng đúng `trace benchmark on duckdb (mini): 6 cells ok, 6 skipped, 0 failed; 5 timed runs per cell`, `details.ok = 6`, `details.skipped = 6`, `details.error = 0`, và không có dòng `decision='TRACED'` nào; `run_bench(duck, settings)` (không truyền `profile`) cho `meta["profile"] == "unknown"`; `write_result(result, tmp_path)` trả `tmp_path / "bench_mini_duckdb.json"`, `read_results(tmp_path)` trả 1 phần tử có `cells == result.cells` và `meta == result.meta`; và gọi `run_bench(duck, settings, profile="mini")` lần hai cho kết quả bằng lần đầu ở mọi trường của mọi ô trừ `seconds`, `median_ms`, `p95_ms`, `min_ms`, `max_ms`, và `meta` bằng nhau trừ `started_at`, `total_seconds`.
- AC3: Given MINI-T trong DuckDB, `settings` OFFLINE với `AML__BENCH__HOURS=[24]`, When benchmark gặp ô lỗi, Then với thêm `AML__TRACE__MAX_PATHS=8`: ô (`cte_raw`, 2) `ok` với `n_paths == 3`, hai ô (`cte_raw`, 4) và (`cte_raw`, 6) có `status == "error"` và `reason` bắt đầu bằng `TraceError:` và chứa `more than 8 paths`, ô (`cte_edge`, 2) `ok` với `n_paths == 4`, hai ô (`cte_edge`, 4) và (`cte_edge`, 6) `error`, dòng audit có `reason` chứa `2 cells ok, 6 skipped, 4 failed`; Given `METHODS["cte_edge"]` được thay bằng method giả có `run` raise `RuntimeError("boom")` (settings mặc định `max_paths`), Then ba ô `cte_edge` có `status == "error"` và `reason == "RuntimeError: boom"` trong khi ba ô `cte_raw` vẫn `ok` với `n_paths` 3, 9, 9; Given `METHODS["cte_raw"]` được thay bằng method giả đếm số lần `run` được gọi và trả frame rỗng có cột `PATH_COLUMNS`, với `AML__BENCH__WARMUP_RUNS=2` và `AML__BENCH__RUNS=5`, Then `run` được gọi đúng 21 lần (3 ô × 7) và mỗi ô `cte_raw` có `len(seconds) == 5` và `n_paths == 0`; với `AML__BENCH__ACCOUNTS=["ZZZ"]`: `meta["params"]["accounts"] == ["ZZZ"]`, `meta["params"]["picked"] is False` và ba ô `cte_raw` `ok` với `n_paths == 0`; và Given DuckDB rỗng sau `apply_schema`, When gọi `run_bench(duck, settings)`, Then raise `BenchError` chứa `no account to benchmark` và `audit_log` không có dòng `BENCHMARKED` nào.
- AC4: Given SAMPLE đã ghi bằng `write_result(SAMPLE, tmp_path)`, When dựng báo cáo, Then `render_report([SAMPLE])` chứa đúng dòng `| small | oracle | A1 | 720 | 6 | cte_raw | ok | 22394 | 600.0 | 780.0 | 30 |  |`, đúng dòng `| small | oracle | A1 | 720 | 6 | cte_edge | ok | 27 | 4.0 | 4.0 | 38 | approximate (daily edges, top-K): paths not comparable |`, đúng dòng `| small | oracle | A1 | 720 | 6 | pgq | error |  |  |  |  | TraceError: more than 100000 paths |`, đúng dòng `| small | oracle | A1 | 720 | 6 | neo4j | skipped |  |  |  |  | neo4j not available |`, chứa chuỗi `aml bench`, chứa `linear interpolation` và không chứa chuỗi `SQL is enough`; `render_report([SAMPLE]) == render_report(read_results(tmp_path))`; `write_report(tmp_path)` trả (`tmp_path / "bench_report.md"`, `tmp_path / "bench_chart.svg"`), cả hai file tồn tại, nội dung file `.md` bằng `render_report([SAMPLE])`, file `.svg` chứa `<svg`, chứa `cte_raw` và `cte_edge`, không chứa `neo4j`; gọi `write_report(tmp_path)` lần hai cho hai file giống hệt từng byte; và Given thư mục rỗng, When chạy `aml bench --report-only` với `AML__BENCH__RESULTS_DIR` trỏ vào đó, Then exit code 1 với stderr chứa `no benchmark results`, còn với thư mục có file SAMPLE thì exit code 0, stdout có 2 dòng bắt đầu bằng `wrote` và `audit_log` không được ghi.
- AC5: Given `tiny_env` (OFFLINE) đã `aml load`, có thêm `AML__BENCH__HOURS=[168, 720]`, `AML__BENCH__RUNS=5` và `AML__BENCH__RESULTS_DIR=<tmp>/bench`, When chạy `aml bench`, Then exit code 0; stdout có một dòng chứa `bench profile=small backend=duckdb accounts=A7341585768 cells=24 ok=12 skipped=12 error=0`, một dòng `method=pgq skipped: not available on duckdb`, một dòng bắt đầu bằng `method=neo4j skipped: neo4j not available` và 3 dòng bắt đầu bằng `wrote`; `<tmp>/bench/` có đúng 3 file `bench_small_duckdb.json`, `bench_report.md`, `bench_chart.svg`; file JSON có `meta.profile == "small"`, `meta.dataset.transactions == 5100`, `meta.dataset.transfers == 3651`, `meta.params.accounts == ["A7341585768"]` và 24 ô, trong đó `cte_raw` ở T = 168 có `n_paths` 34, 34, 34 theo 2 / 4 / 6 hop, ở T = 720 có 92, 125, 125 (`n_accounts` 12, 19, 19; `n_cycles` 15, 31, 31), `cte_edge` ở T = 168 có 1, 1, 1 và ở T = 720 có 3, 3, 3; `bench_report.md` có đúng 24 dòng bảng bắt đầu bằng `| small | duckdb |`; `pick_accounts` trên cùng dữ liệu với `AML__BENCH__TOP_ACCOUNTS=3` trả `["A7341585768", "A1401926848", "A2459177476"]` và với `AML__BENCH__HOURS=[168]` trả `["A5040436031"]` (hoà 24–24 với `A9075004254`); `aml bench --profile dense-test` ghi `bench_dense-test_duckdb.json` và thư mục có 4 file; và `aml --help` vẫn liệt kê `bench`, `aml bench --help` exit code 0 với stdout chứa `--report-only`.
- AC6: [neo4j] Given TINY trong DuckDB (`tiny_er`) đã sync, `settings` có `AML__BENCH__HOURS=[720]`, When gọi `run_bench(db, settings, profile="tiny")`, Then ba ô `neo4j` có `status == "ok"`, `exact is True`, `n_paths` lần lượt 92, 125, 125 — bằng `n_paths` của ô `cte_raw` cùng hop — và `query_lines` của ba ô `neo4j` bằng nhau; ba ô `pgq` `skipped`; `meta["sync"]["full_seconds"] > 0` và `meta["sync"]["lag_after_seconds"] == 0`; dòng audit có `reason` chứa `9 cells ok, 3 skipped, 0 failed`; `audit_log` không có dòng `TRACED` nào; When chèn thêm một chuyển khoản vào DuckDB rồi `refresh_acct_edge_daily` mà không sync và gọi lại `run_bench`, Then ba ô `neo4j` có `status == "skipped"` với `reason` chứa `graph is out of sync`, `meta["sync"] is None`, sáu ô `cte_raw` / `cte_edge` vẫn `ok`; và Given `settings` có thêm `AML__NEO4J__READ_TIMEOUT_SECONDS=0.000001`, đồ thị đã sync lại, Then mỗi ô `neo4j` không `ok` và có `reason` khác `None`, các ô `cte_raw` vẫn `ok`, và sau lượt đó `SHOW TRANSACTIONS` không còn giao dịch nào của benchmark.
- AC7: [oracle] [neo4j] Given TINY nạp vào Oracle (`load_parquet`, `run_er`, `apply_security`; skip với thông điệp nêu tên biến nếu thiếu `ORACLE_SYS_PASSWORD` hoặc `ORACLE_DEMO_PASSWORD`) và `run_sync(oracle, oracle_settings, full=True)`, `oracle_settings` có `AML__BENCH__HOURS=[720]`, `AML__BENCH__RUNS=5`, When gọi `result = run_bench(oracle, oracle_settings)`, Then `meta["backend"] == "oracle"`, `meta["profile"] == "small"`, `meta["params"]["accounts"] == ["A7341585768"]`; cả 12 ô có `status == "ok"`; `n_paths` của `cte_raw`, `pgq` và `neo4j` đều là 92, 125, 125 theo 2 / 4 / 6 hop; `query_lines` của `pgq` tăng chặt theo hop còn của `neo4j` và `cte_raw` không đổi theo hop; `write_result` ghi `bench_small_oracle.json`; `audit_log` của Oracle tăng đúng 1 dòng `BENCHMARKED` với `entity_id='small-oracle'`.

## Ngoài phạm vi
- **Lần chạy thật và phần kết luận viết**: chạy `aml bench` trên `small` và `dense` (Oracle và DuckDB), commit file
  kết quả, chép bảng / biểu đồ vào `README.md` và `docs/trace-benchmark.md`, viết kết luận "khi nào SQL đủ / property
  graph trong database / graph DB riêng" kèm chi phí vận hành — là bước demo của phase, không có AC. Dữ kiện sản
  phẩm của Neo4j Community (không RBAC, không cluster / HA, không online backup) ghi là dữ kiện, không phải số đo.
- Tự sinh dữ liệu, nạp, chạy ER, sync Neo4j, đổi profile, hay trả trạng thái dev từ trong `aml bench`.
- Profile `large`; benchmark của truy vấn khác trace (vòng, fan-in / fan-out, GDS, rule 5a); trace bằng quantified
  path pattern; tuning `pgq` (index, hint, viết lại) — benchmark đo cái đang có.
- Timeout cho method SQL (`cte_raw`, `cte_edge`, `pgq`); cache lạnh (khởi động lại dịch vụ); đo bộ nhớ / CPU của
  container; chạy song song; so plan thực thi.
- Tự bỏ các ô hop lớn hơn sau khi một ô lỗi; gộp nhiều lượt của cùng (profile, backend) — lượt sau ghi đè.
- Sửa `trace()`, bốn method, file SQL / Cypher của 5b và 6b, guard, `docker-compose.yml`.

## Giả định
- **Đã đo thật** (mục Hiện trạng): mọi thời gian và số dòng trên `small` / `dense`; số dòng và tài khoản được chọn
  của MINI-T và TINY trong AC2, AC3, AC5 (bằng `trace` của repo và truy vấn chọn viết tạm, trên DuckDB; truy vấn chọn
  cũng đã chạy trên Oracle TINY). **Suy ra, chưa đo** (chưa có code): AC6, AC7 (dựa vào AC4 của 6b-i: `neo4j` =
  `cte_raw` = `pgq` trên TINY), chuỗi `reason`, thông điệp lỗi, output CLI, nội dung SVG từ file kết quả.
- Thời gian trong mục Hiện trạng là số của máy dev với 5–7 lần lặp, chỉ để chọn thiết kế; **không phải** kết quả
  benchmark và không được chép vào README — số chính thức đến từ file kết quả của `aml bench`.
- Nhãn profile lấy từ dòng audit `LOADED` mới nhất chỉ là nhãn: dữ liệu TINY cũng mang nhãn `small`; `meta.dataset`
  (số dòng) mới là thứ xác định bộ dữ liệu. `git_commit` là `None` khi không chạy trong repo git.
- So sánh giữa các method chỉ công bằng trong cùng một file kết quả (cùng backend, cùng dữ liệu, đồ thị sync từ chính
  backend đó). Bảng chính của kết luận là các lượt Oracle; lượt DuckDB là phụ lục "không cần cài gì".
- Không có `aml graph sync`, `aml load` hay tiến trình nặng nào khác chạy trong lúc benchmark. Test [neo4j] / [oracle]
  để lại projection và dữ liệu của test như các phase trước.
- `matplotlib` cho SVG giống hệt từng byte giữa hai lần vẽ trên cùng máy và cùng phiên bản (đã thử 3.11.2); khác
  phiên bản có thể khác byte — AC4 chỉ so hai lần vẽ trong cùng một lần chạy test.
- Tên file kết quả, tên cột của bảng và ba trạng thái ô là cấu trúc (hằng trong code); hop, T, số lần lặp, tài khoản
  và thư mục kết quả là cấu hình. `reason`, báo cáo và output CLI bằng tiếng Anh như các lệnh hiện có.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** `aml bench` tự chuẩn bị từng profile hay chỉ đo trạng thái hiện có? — đề xuất mặc định: **chỉ đo trạng thái hiện có**, mỗi lượt một file `bench_<profile>_<backend>.json`; người chạy tự chuẩn bị (4 lệnh, đã đo 75–80 giây mỗi profile trên Oracle) và báo cáo gộp mọi file. Lý do: tự chuẩn bị nghĩa là xoá sạch Oracle và Neo4j dev từ một lệnh tên là "bench" và để lại profile cuối cùng; bản chỉ đọc thì kiểm thử được và không bất ngờ. Phương án thay thế: thêm `aml bench --prepare` làm trọn chuỗi cho cả hai profile (khoảng 6–7 phút, đổi trạng thái dev). — Trả lời: theo đề xuất.
- [x] Q2. **(cần người dùng quyết)** Bảng chính đo trên backend nào? — đề xuất mặc định: **cả bốn method trên Oracle cho cả `small` và `dense`** (đã chạy thật: nạp 18–25 giây, đo 70–118 giây mỗi profile), cộng lượt DuckDB (ba method) làm phụ lục; tổng cộng 4 file kết quả. Lý do: `pgq` chỉ có trên Oracle và so sánh công bằng đòi cùng dữ liệu, cùng đồ thị sync từ Oracle. Hệ quả: Oracle dev sẽ chứa `small` / `dense` sau bước demo cho tới khi test [oracle] nạp lại TINY. — Trả lời: theo đề xuất.
- [x] Q3. **(cần người dùng quyết)** Tài khoản xuất phát chọn thế nào và mấy tài khoản? — đề xuất mặc định: tự chọn **1** tài khoản nội bộ có nhiều path 2 hop đúng thứ tự thời gian nhất trong T lớn nhất (hoà: `account_id` nhỏ hơn); `bench.accounts` ghi đè được, `bench.top_accounts` tăng được tới 10. Lý do: "nhiều chuyển khoản đi nhất" chọn nhầm employer payroll trên `dense` (174 dòng ở mọi hop); tài khoản typology quá nhỏ để phân biệt method; ba tài khoản đứng đầu cho thời gian cùng bậc nên 1 là đủ và giữ lượt đo dưới 4 phút. Cái giá: một tài khoản là ca nặng nhất, không phải ca điển hình — báo cáo phải nói rõ. — Trả lời: theo đề xuất.
- [x] Q4. Cửa sổ T? — đề xuất mặc định: `bench.hours: [72, 720]` — 72 là mặc định của `aml trace` (ca investigator thường chạy), 720 là trần `trace.max_hours` (ca nặng). Lý do: ở T = 72 số dòng không đổi từ 4 lên 6 hop nên một mình nó không cho thấy gì; ở T = 720 số dòng là 4289 / 10 955 / 22 394. — Trả lời: theo đề xuất.
- [x] Q5. Số lần lặp, làm ấm và thứ tự chạy? — đề xuất mặc định: 1 lần làm ấm bỏ đi + **10** lần bấm giờ mỗi ô (tối thiểu cấu hình được là 5 theo brief), chạy tuần tự từng ô. Lý do: lần đầu chậm hơn tới 7 lần (`neo4j` 367 so với 53 mili giây); tuần tự và xen kẽ cho trung vị như nhau (đã đo) mà tuần tự đơn giản hơn; 10 lần ước 3–4 phút mỗi profile trên Oracle (chưa đo). — Trả lời: theo đề xuất.
- [x] Q6. p95 tính thế nào khi chỉ có 5–10 lần? — đề xuất mặc định: nội suy tuyến tính giữa hai thứ hạng gần nhất (mặc định của NumPy), kèm `min_ms`, `max_ms` và toàn bộ `seconds` trong file; báo cáo có chú thích rằng với dưới 20 lần p95 gần bằng lần chậm nhất. Lý do: brief đòi p95; giấu đi cỡ mẫu là nói quá. — Trả lời: theo đề xuất.
- [x] Q7. Ô lỗi / timeout / method không dùng được ghi thế nào? — đề xuất mặc định: `skipped` (không chạy được trên backend này, dịch vụ tắt, đồ thị lệch) và `error` (vượt `max_paths`, timeout Neo4j 60 giây, exception khác) đều là một dòng trong file và trong bảng kèm `reason`; lượt đo vẫn chạy tiếp và exit 0. Method SQL **không** được thêm timeout (ô chậm nhất đã đo là 8,2 giây). Phương án thay thế: thêm timeout cho Oracle (`call_timeout`) — nên làm nếu sau này đo `large`. — Trả lời: theo đề xuất.
- [x] Q8. **(cần người dùng quyết)** Thư viện vẽ biểu đồ? — đề xuất mặc định: thêm `matplotlib` vào dependency chính, xuất **SVG** (chữ còn là chữ, diff được, hiển thị trong README). Lý do: đã thử — 21 KB, tất định từng byte; cái giá là 11 gói mới. Phương án thay thế: tự viết SVG bằng Python thuần (không dependency, khoảng 80 dòng code phải tự bảo trì), hoặc PNG. — Trả lời: theo đề xuất.
- [x] Q9. File kết quả đặt ở đâu, định dạng gì, có commit không? — đề xuất mặc định: `results/phase6/bench_<profile>_<backend>.json` (có `meta` + từng ô kèm thời gian thô), `bench_report.md`, `bench_chart.svg`; **commit cả ba loại** như `results/phase2`–`phase5`; README chỉ chép từ `bench_report.md`. Lý do: JSON giữ được xuất xứ (lệnh, ngày, commit, phiên bản, máy) trong cùng file với số đo; CSV thì không. — Trả lời: theo đề xuất.
- [x] Q10. Nhãn profile lấy từ đâu? — đề xuất mặc định: từ dòng audit `datagen` / `LOADED` mới nhất của cơ sở dữ liệu đang đo (`small-seed42` → `small`), `--profile` ghi đè, không có thì `unknown`; `meta.dataset` ghi số dòng thật. Lý do: không để người chạy gõ nhầm nhãn; cơ sở dữ liệu không lưu profile ở chỗ nào khác. — Trả lời: theo đề xuất.
- [x] Q11. Ghi `audit_log` thế nào? — đề xuất mặc định: mỗi lượt đúng 1 dòng `BENCHMARKED` (tham số, số ô ok / skipped / failed), không có dòng `TRACED` nào (`record_audit=False`); `--report-only` không ghi gì. Lý do: benchmark không phải quyết định tự động, nhưng vài trăm dòng `TRACED` giả sẽ làm bẩn dấu vết truy cập thật. — Trả lời: theo đề xuất.
- [x] Q12. Chi phí vận hành đưa vào kết luận lấy từ đâu? — đề xuất mặc định: file kết quả tự ghi `meta.sync` (thời gian FULL / INCREMENTAL và lag mới nhất từ `graph_sync_runs`) khi có ô `neo4j` chạy được; bộ nhớ container và số thành phần phải vận hành lấy từ `docs/neo4j-sync.md` và `docker-compose.yml`; giới hạn của Community ghi là dữ kiện sản phẩm. Lý do: "để số liệu quyết định câu chữ" — phía chi phí cũng phải là số đo có nguồn. — Trả lời: theo đề xuất.
- [x] Q13. Package đặt ở đâu? — đề xuất mặc định: `src/aml/graph/bench/` (`stats.py`, `model.py`, `runner.py`, `report.py`), test ở `tests/trace_bench/`. Lý do: benchmark chỉ đo trace của `aml.graph`, cùng kiểu với `graph/network/` và `graph/neo4j/`. — Trả lời: theo đề xuất.
