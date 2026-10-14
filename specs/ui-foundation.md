---
id: ui-foundation
status: approved
approved_by: pthieu
---

# Phase 9a — Nền móng UI: khung FastAPI (`src/aml/api/`), SPA React (`web/`), actor / role, che PII phía server, envelope `source` và cơ chế mock theo từng tính năng, `aml ui`

## Bối cảnh
Phần "Architecture" của Phase 9 trong PROJECT_BRIEF.md (mục 10). Người dùng quyết định dựng UI **trước** khi 7c
(`specs/case-prioritization.md`), 7d (`specs/case-summary.md`), Phase 8 và Phase 7b của brief xong, và đã đồng ý nới
phase gate cho việc này. Phase 9 được tách thành ba spec viết theo thứ tự phụ thuộc: **`ui-foundation`** (spec này) →
`ui-live-pages` (case detail, network graph, fund-flow trace, screening review, data quality, benchmark — dữ liệu
thật) → `ui-mock-pages` (điểm ưu tiên trên case queue, panel case summary, chat assistant SSE + draft narrative,
metrics dashboard — endpoint trả dữ liệu mẫu cho tới khi phase thật xong). Spec này chỉ dựng **khung và các cơ chế
dùng chung** mà hai spec sau tham chiếu: app factory + router mỏng đọc qua `Database`, định danh actor / role, che PII
phía server, quy ước audit cho endpoint quyết định, envelope JSON có cờ `source`, cơ chế mock bật / tắt theo từng tính
năng, SPA có layout + routing với trang rỗng, và ba endpoint thật tối thiểu (trạng thái, danh sách case không có điểm,
subject của case) cộng một endpoint quyết định (disposition) để chứng minh khung chạy đầu-cuối. Người dùng:
investigator trong buổi demo; hai analyst viết hai spec sau. Quy tắc dự án "never fabricate results" áp vào UI: **không
con số mẫu nào được hiển thị như kết quả thật**.

### Hiện trạng đã kiểm (2026-10-13, seed 42)
Đọc code + chạy một prototype tạm ngoài repo (scratchpad; `uv run --with fastapi --with httpx --with uvicorn`, không
đổi `pyproject.toml` / `uv.lock`): MINI-C của `tests/cases/helpers.py::load_minic` → `run_cases` → một app FastAPI một
file đọc `cases_current` và gọi `record_disposition` qua `TestClient`.
- **CLI**: `aml ui` đã là stub trong `src/aml/cli.py` (`"ui": 9` trong vòng `_not_yet`, in `arrives in Phase 9`, exit
  1); không test nào khẳng định stub `ui` (đã grep `tests/`). `Makefile` và `tasks.ps1` đã có target `ui` gọi `aml ui`.
  Stub `rag` (Phase 8) và `score` (Phase 7, do 7c thay) nằm cùng vòng đó.
- **Dependency**: `pyproject.toml` chưa có `fastapi`, `uvicorn`, `httpx`. Bản prototype kéo về: `fastapi` 0.143.0,
  `starlette` 1.8.0, `uvicorn` 0.54.0. `starlette.testclient` in `StarletteDeprecationWarning: Using httpx with
  starlette.testclient is deprecated; install httpx2 instead` — vẫn chạy.
- **`web/` chưa tồn tại.** Node `v24.12.0`, npm `11.6.2` có sẵn. `.gitignore` chưa có `web/node_modules/`, `web/dist/`;
  thư mục `.claude` **đang bị git-ignore**, nên `.claude/loop.yaml` (hiện: `ruff check`, `ruff format --check`,
  `pytest -q`) là file cục bộ.
- **Masking đã có sẵn (2b, `specs/oracle-security.md`)**: view `customers_masked` trên cả Oracle và DuckDB
  (`ddl/050_*`), cài đặt tham chiếu `aml.dba.masking` (`MASKED_COLUMNS`, 15 cột), test đối chiếu ba cài đặt.
  `load_case(db, case_id, masked=True|False)` (7a) đã chọn `customers_masked` hoặc `customers` cho `subjects`. Đã đo
  trên MINI-C, case `C-C01-20260302`: bản che trả 2 dòng có đúng 15 khoá `MASKED_COLUMNS`, `full_name = "Nguyen T. C."`,
  `id_number = "****4561"`, `birth_year = 1990`; bản không che trả 19 khoá (`cif`, `full_name`, `gender`, `dob`,
  `nationality`, `occupation`, `kyc_risk`, `id_type`, `id_number`, `phone`, `email`, `device_id`, `ip`,
  `address_format`, `street`, `ward`, `district`, `province`, `address`), `full_name = "Nguyen Thi C01"`, `id_number =
  "B1234561"`, và **`dob` là `Timestamp` (`1990-01-01 00:00:00`)** — API phải tự chuẩn về ngày.
- **Role Oracle của 2b không dùng được cho API**: `ROLE_GRANTS["aml_analyst"]` không có quyền nào trên các bảng `case*`
  (AC1 của 7a khẳng định điều đó) và không có quyền trên `audit_log`. Mọi lệnh hiện chạy dưới schema owner. Vì vậy
  "analyst nhận bản đã che" ở spec này là **chọn view ở tầng ứng dụng** trên một kết nối owner, giống hệt ở DuckDB (Q4).
- **Case queue không có PII**: `cases_current` chỉ có `case_id`, `golden_customer_id`, trạng thái, số đếm, mốc thời
  gian, `reason`. Đã đo trên MINI-C (run 1), sắp theo (`last_alert_ts` giảm, `case_id` tăng): `C-C01-20260531`
  (2026-06-30 00:00:00), `C-C05-20260630` (2026-06-30 00:00:00), `C-C01-20260302` (2026-04-20 12:00:00),
  `C-C03-20260305` (2026-03-07 10:00:00), `C-C04-20260305` (2026-03-07 10:00:00); cả 5 `OPEN`.
- **Disposition**: `record_disposition(..., actor="analyst01")` gọi từ bên trong một request của `TestClient` trả `1`
  và ghi đúng 1 dòng `audit_log` (`module='cases'`, `entity_type='case'`, `decision='FALSE_POSITIVE'`,
  `actor='analyst01'`, `version='cases/v1'`, `details = {disposition_id, run_id, origin, decided_on}`). Nó **không đổi
  `cases.status`** — trạng thái chỉ đổi ở lần `aml cases build` kế tiếp (thiết kế của 7a).
- **Kết nối DuckDB**: một `DuckDb` dùng chung cho các request tuần tự của `TestClient` (chạy trong threadpool) hoạt
  động; mở kết nối thứ hai tới cùng file trong cùng tiến trình hoạt động (1,9 mili giây); mở + đóng một kết nối mới
  27,5 mili giây (một lần đo, file MINI-C).
- **404 mặc định của FastAPI** là `{"detail": "Not Found"}` — khác envelope lỗi của spec này, phải ghi đè.
- `audit_log.module` đã dự trù giá trị `ui` (comment trong `sql/duckdb/ddl/000_audit_log.sql`).
- `SCHEMA_SCRIPTS`: 7a `160`, 7b-supp giữ `170`, 7c giữ `180`. **Spec này không cần DDL.** Nếu spec UI sau cần thì
  dùng từ `190`.
- **Chưa đo**: mọi thứ của `web/` (scaffold Vite, phiên bản thư viện, thời gian `npm ci` / `npm run build`); phục vụ file tĩnh + SPA fallback; `aml ui` thật với `uvicorn`; đường Oracle của API; hai tiến trình cùng
  mở một file DuckDB (API đang chạy trong lúc `aml cases build`); các chuỗi thông điệp lỗi và output CLI (chưa có code).

### Interface đề xuất (để test và hai spec sau gọi trực tiếp)
```python
# src/aml/common/config.py
class MockConfig(BaseModel):  # extra="forbid": khoá lạ -> ValidationError
    sample: bool  # ui-mock-pages thêm mỗi tính năng mock một trường bool


class UiConfig(BaseModel):
    host: str  # mặc định 127.0.0.1 — không có xác thực thật nên không mở ra ngoài máy
    port: int  # 1..65535
    dist_dir: str  # thư mục SPA đã build
    users: dict[str, Literal["analyst", "supervisor"]]  # actor -> role; không rỗng
    default_user: str | None  # actor khi request không có header; None -> bắt buộc có header
    page_size: int  # 1..max_page_size
    max_page_size: int
    mock: MockConfig


class Settings(BaseModel):
    ...
    ui: UiConfig


# src/aml/api/app.py
API_PREFIX = "/api/v1"
API_VERSION = "api/v1"  # `version` của các dòng audit do tầng API tự ghi


def create_app(settings: Settings | None = None, *, db: Database | None = None) -> FastAPI: ...


# db=None -> mỗi request mở `get_db(settings)` rồi đóng; db cho trước (test) -> dùng chung, không đóng


# src/aml/api/errors.py
class ApiError(Exception):
    status: int
    code: str
    message: str


# src/aml/api/identity.py
USER_HEADER = "X-AML-User"
ROLE_PII = {"analyst": "masked", "supervisor": "full"}


@dataclass(frozen=True)
class User:
    actor: str
    role: str
    pii: str  # "masked" | "full"


def resolve_user(settings: Settings, header_value: str | None) -> User: ...  # ApiError 401


# src/aml/api/deps.py  (FastAPI dependencies)
def get_database() -> Iterator[Database]: ...
def current_user() -> User: ...


# src/aml/api/envelope.py
LIVE, MOCK = "live", "mock"
SOURCE_HEADER = "X-AML-Source"
MOCK_NOTICE = "Sample data - not a measured result"


def live(feature: str, data: Any, *, status: int = 200, **meta: Any) -> JSONResponse: ...


# src/aml/api/mock.py  (nơi DUY NHẤT đọc src/aml/api/fixtures/)
def features() -> tuple[str, ...]: ...  # tên các tính năng có fixture, tăng dần
def is_mocked(settings: Settings, feature: str) -> bool: ...  # ValueError với tên lạ
def mock_or_live(
    settings: Settings, feature: str, live_fn: Callable[[], Any] | None, **meta: Any
) -> JSONResponse: ...


# src/aml/api/reads/cases.py  (truy vấn đọc của API; router không chứa SQL)
def list_cases(
    db: Database, *, status: str | None, limit: int, offset: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]: ...  # (dòng, meta)
```
- Gói `src/aml/api/`: `app.py`, `deps.py`, `identity.py`, `errors.py`, `envelope.py`, `mock.py`, `static.py`,
  `fixtures/sample.json`, `reads/cases.py`, `routers/system.py` (`health`, `status`, `me`), `routers/cases.py`,
  `routers/sample.py`. Test backend ở `tests/api/`.
- `config.yaml`, mục mới: `ui: {host: 127.0.0.1, port: 8000, dist_dir: web/dist, users: {analyst01: analyst,
  supervisor01: supervisor}, default_user: analyst01, page_size: 50, max_page_size: 200, mock: {sample: true}}`.
- `pyproject.toml`: thêm `fastapi`, `uvicorn` vào `project.dependencies`; `httpx` vào nhóm `dev` (cho `TestClient`).
- SQL đọc của API: `sql/common/api/case_list.sql` (một câu `SELECT` trên `cases_current` nối trái
  `case_dispositions_current`, không tham số, chạy được ở cả hai backend); lọc và phân trang làm bằng pandas.
- CLI: `aml ui [--host H] [--port P] [--api-only]` thay stub. `Makefile` / `tasks.ps1`: target `ui` = `npm --prefix web
  install` → `npm --prefix web run build` → `aml ui`; thêm `ui-api` (= `aml ui --api-only`).
- `web/`: `package.json` (script `dev`, `build` = `tsc -b && vite build`; không có script `test`), `package-lock.json`
  (commit), `vite.config.ts` (proxy `/api` → `http://127.0.0.1:8000`), `src/api/client.ts`, `src/components/`
  (`SourceBadge.tsx`, `ApiPanel.tsx`, `Layout.tsx`, `UserSwitch.tsx`), `src/pages/`, `src/App.tsx`. **Không có test frontend
  tự động** (Q9): không Vitest, không React Testing Library, không jsdom trong `package.json`; hành vi giao diện
  nằm ở mục "Yêu cầu giao diện (kiểm tay)".
- `.gitignore`: thêm `web/node_modules/`, `web/dist/`.
- **Không sửa** `src/aml/cases/` (một loop khác đang làm 7b-supp ở đó): tầng API chỉ **gọi** `load_case` và
  `record_disposition` với chữ ký đã duyệt ở 7a.

### Thiết kế (đề xuất, chờ xác nhận ở Câu hỏi mở)
- **Prefix và phiên bản**: mọi endpoint nằm dưới `/api/v1`. Tên trường JSON là `snake_case`, trùng tên cột / trường
  của module nguồn. Tiền là số nguyên VND. Mốc thời gian của dữ liệu là chuỗi `YYYY-MM-DDTHH:MM:SS` không múi giờ;
  ngày là `YYYY-MM-DD`; `NULL` / `NaN` / `NaT` thành `null`.
- **Envelope thành công** (HTTP 2xx): `{"source": "live" | "mock", "feature": "<tên tính năng>", "data": <object |
  array>, "meta": {}}` — bốn khoá luôn có mặt. Response mock có thêm `meta.mock = {"fixture": "<tên file>", "notice":
  MOCK_NOTICE}`. Header `X-AML-Source` mang cùng giá trị với `source` (dùng cho luồng SSE và file tải về, nơi không có
  thân JSON). Luồng SSE (thuộc `ui-mock-pages`) mở đầu bằng sự kiện `event: meta` có `data` = `{"source", "feature"}`.
- **Envelope lỗi** (HTTP 4xx / 5xx): `{"error": {"code": "<mã>", "message": "<tiếng Anh>"}}`, không có `source` /
  `data`, không có header `X-AML-Source`. Mã: `missing_user` 401, `unknown_user` 401, `not_found` 404,
  `method_not_allowed` 405, `invalid_request` 422 (mọi lỗi kiểm tra đầu vào), `not_implemented` 501, `unavailable` 503
  (`ServiceUnavailableError`), `internal_error` 500 (mọi exception khác; `message` cố định `internal error`, không lộ
  SQL hay stack).
- **Một response = một tính năng = một nguồn.** Không trộn dữ liệu thật và dữ liệu mẫu trong cùng một response. Trang
  cần cả hai (vd case queue có điểm) gọi hai endpoint và ghép phía client theo khoá (`case_id`); mỗi panel tự mang
  nhãn của mình (Q6).
- **Router mỏng**: file trong `routers/` chỉ làm bốn việc — nhận tham số, lấy `User`, gọi một hàm của module nghiệp
  vụ hoặc của `aml.api.reads`, bọc envelope. Không SQL, không `query_df`, không import driver.
- **Actor và role** (Q1, Q2): request mang header `X-AML-User: <actor>`; server tra `ui.users` để ra role — client
  không bao giờ tự khai role. Không có header → `ui.default_user`; `default_user` là `null` → 401 `missing_user`.
  Actor không có trong `ui.users` → 401 `unknown_user`. Chỉ `/api/v1/health` không cần định danh. `ROLE_PII` quyết
  định mức PII: `analyst` → `masked`, `supervisor` → `full`.
- **Che PII phía server**: thuộc tính khách hàng chỉ được đọc từ `customers_masked` khi `user.pii == "masked"`. Mức
  đã áp được ghi ở `meta.pii`. Không có tham số request nào bật được bản không che. Mỗi response trả PII không che ghi
  1 dòng audit `PII_VIEWED` (Q3).
- **Quy ước endpoint quyết định** (mọi `POST` ghi một quyết định của người): thân JSON bắt buộc có `reason` khác
  rỗng sau khi bỏ khoảng trắng; **không nhận** trường `actor` (trường lạ → 422) — actor luôn là `User.actor` của
  request; kết quả là ít nhất 1 dòng `audit_log` có `actor` đó và `reason` đó, ghi qua `aml.common.audit.audit()`
  (trực tiếp, hoặc do hàm nghiệp vụ được gọi tự ghi — không ghi hai lần); trả 201; lỗi thì không ghi gì.
- **Cơ chế mock** (Q7, Q8): mỗi tính năng mock có (a) một trường bool trong `MockConfig` (`ui.mock.<tên>`), (b) một
  fixture tất định `src/aml/api/fixtures/<tên>.json` chứa đúng phần `data` theo hợp đồng JSON cuối cùng (hoặc, khi
  dữ liệu phải khớp id thật, một hàm builder là hàm thuần của `settings.seed` và tham số request — không đồng hồ,
  không ngẫu nhiên không seed), (c) một router gọi `mock_or_live(settings, "<tên>", live_fn)`. Cờ bật → trả fixture
  với `source = "mock"`, **không gọi** `live_fn`. Cờ tắt và có `live_fn` → `source = "live"`. Cờ tắt và `live_fn` là
  `None` → 501 `not_implemented`. Khi phase thật xong: chỉ thay `None` bằng hàm thật và tắt cờ trong `config.yaml`;
  frontend không đổi. `/api/v1/status` liệt kê các cờ để UI hiện cảnh báo chung.
- **Endpoint** của spec này:

  | method, đường dẫn | feature | nguồn | nội dung `data` |
  |---|---|---|---|
  | `GET /api/v1/health` | `health` | live | `{status, backend, version}`; không mở database, không cần định danh |
  | `GET /api/v1/status` | `status` | live | `{backend, profile, seed, reference_date, mock: {<tên>: bool}, case_run: {run_id, as_of, cases} hoặc null}` |
  | `GET /api/v1/me` | `identity` | live | `{actor, role, pii, users: [{actor, role}]}` (`users` tăng dần theo `actor`) |
  | `GET /api/v1/cases` | `cases` | live | mảng case của lần chạy mới nhất; `meta = {run_id, as_of, total, limit, offset}` |
  | `GET /api/v1/cases/{case_id}/subjects` | `cases` | live | `subjects` của `load_case`; `meta = {pii}` |
  | `POST /api/v1/cases/{case_id}/disposition` | `cases` | live | `{disposition_id, case_id, disposition, actor, decided_on}` |
  | `GET /api/v1/sample` | `sample` | mock | nội dung `fixtures/sample.json` |

  - Một case trong `GET /api/v1/cases` có đúng 13 khoá: `case_id`, `golden_customer_id`, `status`, `alerts`,
    `rule_alerts`, `network_alerts`, `screening_alerts`, `sources` (mảng, tách từ chuỗi nối `+`), `window_start`,
    `first_alert_ts`, `last_alert_ts`, `reason`, `disposition` (`{disposition, actor, decided_on}` của
    `case_dispositions_current` hoặc `null`). **Không có** `score`, `queue_rank`. Sắp theo (`last_alert_ts` giảm,
    `case_id` tăng). Tham số: `status` ∈ `OPEN`, `REOPENED`, `CLOSED` (tuỳ chọn), `limit` (mặc định `ui.page_size`,
    1..`ui.max_page_size`), `offset` (>= 0); `meta.total` là số case sau khi lọc, trước khi phân trang.
  - `fixtures/sample.json` = `{"items": [{"id": "S-001", "label": "sample row 1", "value": 42}, {"id": "S-002",
    "label": "sample row 2", "value": 7}]}`.
- **File tĩnh**: khi `settings.path(ui.dist_dir)` có `index.html`, app phục vụ file trong đó; đường dẫn không bắt đầu
  bằng `/api/` và không khớp file nào → trả `index.html` (SPA fallback). Đường dẫn `/api/…` không có route → luôn là
  404 JSON. Không có `index.html` → mọi đường dẫn ngoài `/api/` trả 404 JSON; API vẫn chạy.
- **`aml ui`**: không bao giờ tự gọi `npm`. Thiếu `index.html` và không có `--api-only` → stderr, exit 1. Ngược lại in
  một dòng `ui http://<host>:<port> backend=<db.backend cấu hình> dist=<đường dẫn | none> mock=<các cờ đang bật nối
  bằng dấu phẩy | none>` rồi gọi `uvicorn.run(app, host=…, port=…)`.
- **SPA**: route `/` (chuyển sang `/cases`), `/cases`, `/cases/:caseId`, `/screening`, `/data-quality`, `/benchmark`,
  `/metrics`, `/system`, và trang 404. `/cases` hiện bảng từ `GET /api/v1/cases` (không có cột điểm); `/system` hiện
  `GET /api/v1/status` và panel `GET /api/v1/sample`; các trang còn lại là trang rỗng có tiêu đề. Header có tên
  actor + role và ô chọn người dùng (lưu ở `localStorage["aml.user"]`, gửi thành `X-AML-User`).
  - `src/api/client.ts`: `apiGet` / `apiPost` thêm prefix `/api/v1` và header; `parseEnvelope` **ném `ApiError`**
    khi thân thiếu `source` hợp lệ — response không rõ nguồn không bao giờ được hiển thị.
  - `ApiPanel` là đường duy nhất để trang lấy dữ liệu API: nó gọi `apiGet`, hiện lỗi, và hiện `SourceBadge` (chữ
    **`Dữ liệu mẫu`**) khi `source === "mock"`; khi API trả lỗi nó hiện `Chưa có dữ liệu` kèm `error.code` và
    không hiện dòng dữ liệu nào. File trong `src/pages/` không gọi `fetch` trực tiếp; chuỗi `Dữ liệu mẫu` chỉ nằm
    trong `SourceBadge.tsx`; không file nào dùng `dangerouslySetInnerHTML`.
  - Các điểm trên là **yêu cầu phải hiện thực**, không có test tự động chạy trình duyệt hay jsdom; ba quy tắc về
    mã nguồn (không `fetch(` trong `src/pages/`, không `dangerouslySetInnerHTML`, nhãn chỉ ở `SourceBadge.tsx`) được
    pytest kiểm bằng cách đọc file dưới dạng văn bản (AC8), phần còn lại kiểm tay.
- **Verify loop** (Q9, người dùng quyết): giữ `ruff check`, `ruff format --check`, `pytest -q`; chỉ thêm một bước
  `npm --prefix web run build` (kiểm kiểu bằng `tsc` + build — là build, không phải test) và bước đó phải pass.
  `pytest` vẫn xanh trên máy không có Node vì mọi AC chỉ đọc file của `web/` dưới dạng văn bản.
- **Bảo đảm "never fabricate results"**: vì không có test frontend, bảo đảm **tự động duy nhất** là phía server
  (AC7): cờ `source` và header `X-AML-Source` trên mọi response, 501 không lộ số khi cờ tắt, hàm thật không bị gọi
  khi cờ bật, tập trường `MockConfig` khớp tập fixture, và không route nào trả `mock` khi mọi cờ tắt. Việc nhãn
  `Dữ liệu mẫu` thật sự hiện trên màn hình chỉ được kiểm tay (mục "Yêu cầu giao diện").

## Tiêu chí nghiệm thu
<!-- `settings` = load_settings(environ={"DB_BACKEND": "duckdb", **env}). `client(user=None, **env)` =
TestClient(create_app(settings, db=duck)); khi có `user` thì mọi request mang header `X-AML-User: <user>`.
SCHEMA = `duck` sau `apply_schema` (chưa có lần chạy case nào). API-MINI = MINI-C của specs/case-consolidation.md
(`tests/cases/helpers.py::load_minic`) rồi `run_cases(duck, settings)` (run 1; `as_of` 2026-06-30).
DIST = thư mục tạm có `index.html` chứa chuỗi `aml-spa` và `assets/app.js` chứa `console.log("aml")`;
`AML__UI__DIST_DIR` trỏ vào đó. Mọi AC là pytest (`tests/api/`), chạy DuckDB-only, không cần Node. Không có AC nào cho
hành vi frontend trên trình duyệt (Q9) — xem mục "Yêu cầu giao diện (kiểm tay)".
Đã đo bằng prototype: thứ tự và giá trị case của API-MINI, giá trị che / không che của subject, dòng audit của
disposition. Còn lại suy ra từ thiết kế, chưa đo. -->
- AC1: Given `config.yaml`, `pyproject.toml` và `.gitignore` của repo, When gọi `load_settings(environ={})` và đọc hai file kia, Then `settings.ui.host == "127.0.0.1"`, `settings.ui.port == 8000`, `settings.ui.dist_dir == "web/dist"`, `settings.ui.users == {"analyst01": "analyst", "supervisor01": "supervisor"}`, `settings.ui.default_user == "analyst01"`, `settings.ui.page_size == 50`, `settings.ui.max_page_size == 200`, `settings.ui.mock.sample is True`; `load_settings(environ={"AML__UI__DEFAULT_USER": ""})` cho `settings.ui.default_user is None`; `AML__UI__PORT=0` raise `pydantic.ValidationError` chứa `ui port must be between 1 and 65535`; `AML__UI__PAGE_SIZE=201` raise `ValidationError` chứa `ui page_size must be between 1 and max_page_size`; `AML__UI__DEFAULT_USER=ghost` raise `ValidationError` chứa `ui default_user must be one of ui users`; `AML__UI__USERS={}` cùng `AML__UI__DEFAULT_USER=""` raise `ValidationError` chứa `ui users must not be empty`; `AML__UI__USERS={"a1": "admin"}` cùng `AML__UI__DEFAULT_USER=""` raise `ValidationError`; `AML__UI__USERS={"system": "analyst"}` cùng `AML__UI__DEFAULT_USER=""` raise `ValidationError` chứa `ui users must not contain audit.system_actor`; `AML__UI__MOCK__SAMPLE=maybe` raise `ValidationError`; `AML__UI__MOCK__NO_SUCH_FEATURE=true` raise `ValidationError`; `import fastapi` và `import uvicorn` thành công; `pyproject.toml` có `fastapi` và `uvicorn` trong `project.dependencies` và `httpx` trong `dependency-groups.dev`; và `.gitignore` có hai dòng `web/node_modules/` và `web/dist/`.
- AC2: Given SCHEMA và `client()`, When gọi các endpoint hệ thống, Then `GET /api/v1/health` trả 200 với thân bằng đúng `{"source": "live", "feature": "health", "data": {"status": "ok", "backend": "duckdb", "version": "api/v1"}, "meta": {}}` và header `X-AML-Source == "live"`; `GET /api/v1/status` trả 200 với `source == "live"`, `feature == "status"` và `data` bằng đúng `{"backend": "duckdb", "profile": "small", "seed": 42, "reference_date": "2026-06-30", "mock": {"sample": true}, "case_run": null}`; trên API-MINI thì `data.case_run == {"run_id": 1, "as_of": "2026-06-30", "cases": 5}`; `GET /api/v1/nope` trả 404 với thân bằng đúng `{"error": {"code": "not_found", "message": "no such endpoint: /api/v1/nope"}}`, không có khoá `detail` và không có header `X-AML-Source`; `POST /api/v1/health` trả 405 với `error.code == "method_not_allowed"`; Given app dựng bằng `create_app(settings, db=<Database giả có query_df raise RuntimeError("secret SQL text")>)`, Then `GET /api/v1/health` vẫn trả 200, còn `GET /api/v1/status` trả 500 với thân bằng đúng `{"error": {"code": "internal_error", "message": "internal error"}}` và chuỗi `secret SQL text` không có trong response; Given `Database` giả có `query_df` raise `ServiceUnavailableError("Oracle not reachable")`, Then `GET /api/v1/status` trả 503 với `error.code == "unavailable"`; `create_app(settings, db=duck)` gọi hai lần trả hai đối tượng khác nhau; không file `.py` nào dưới `src/aml/api/` chứa `import duckdb`, `import oracledb`, `import neo4j` hay `from neo4j`; và không file nào dưới `src/aml/api/routers/` chứa `SELECT` hay `query_df`.
- AC3: Given SCHEMA, When gọi `GET /api/v1/me` với các định danh khác nhau, Then `client()` (không header) trả 200 với `data` bằng đúng `{"actor": "analyst01", "role": "analyst", "pii": "masked", "users": [{"actor": "analyst01", "role": "analyst"}, {"actor": "supervisor01", "role": "supervisor"}]}`; `client(user="supervisor01")` trả `data.actor == "supervisor01"`, `data.role == "supervisor"`, `data.pii == "full"`; header viết thường `x-aml-user: supervisor01` cho cùng kết quả; `client(user="analyst01")` gửi thêm header `X-AML-Role: supervisor` và tham số `?role=supervisor` vẫn trả `data.role == "analyst"` và `data.pii == "masked"`; `client(user="nobody")` trả 401 với thân bằng đúng `{"error": {"code": "unknown_user", "message": "unknown user 'nobody'"}}`; với `AML__UI__DEFAULT_USER=""` và không header thì `GET /api/v1/me`, `GET /api/v1/status`, `GET /api/v1/cases`, `GET /api/v1/sample` đều trả 401 với `error.code == "missing_user"` và `error.message` chứa `X-AML-User`, còn `GET /api/v1/health` vẫn trả 200; `resolve_user(settings, None) == User("analyst01", "analyst", "masked")`; và `resolve_user(settings, "supervisor01").pii == "full"`.
- AC4: Given API-MINI và `client()`, When gọi `GET /api/v1/cases`, Then trả 200 với `source == "live"`, `feature == "cases"`, `meta == {"run_id": 1, "as_of": "2026-06-30", "total": 5, "limit": 50, "offset": 0}` và `data` có 5 phần tử với `case_id` theo đúng thứ tự `C-C01-20260531`, `C-C05-20260630`, `C-C01-20260302`, `C-C03-20260305`, `C-C04-20260305`; mỗi phần tử có đúng 13 khoá `case_id`, `golden_customer_id`, `status`, `alerts`, `rule_alerts`, `network_alerts`, `screening_alerts`, `sources`, `window_start`, `first_alert_ts`, `last_alert_ts`, `reason`, `disposition` và không có khoá `score`, `queue_rank` hay `priority`; phần tử `C-C01-20260302` bằng đúng (`golden_customer_id` `G-C01`, `status` `OPEN`, `alerts` 3, `rule_alerts` 2, `network_alerts` 1, `screening_alerts` 0, `sources` `["NETWORK", "RULE"]`, `window_start` `2026-03-02T09:00:00`, `first_alert_ts` `2026-03-02T09:00:00`, `last_alert_ts` `2026-04-20T12:00:00`, `reason` `3 alert(s) (2 RULE, 1 NETWORK, 0 SCREENING) on G-C01 between 2026-03-02 09:00:00 and 2026-04-20 12:00:00; window of 90 days from the first alert`, `disposition` `null`); phần tử đầu có `sources == ["RULE", "SCREENING"]` và `last_alert_ts == "2026-06-30T00:00:00"`; chuỗi `Nguyen` không có trong response; `GET /api/v1/cases?status=OPEN&limit=2&offset=4` trả `data` có đúng 1 phần tử `C-C04-20260305` và `meta == {"run_id": 1, "as_of": "2026-06-30", "total": 5, "limit": 2, "offset": 4}`; `?status=CLOSED` trả `data == []` và `meta.total == 0`; `?status=BOGUS`, `?limit=0`, `?limit=201` và `?offset=-1` đều trả 422 với `error.code == "invalid_request"`; với `AML__UI__PAGE_SIZE=2` thì `GET /api/v1/cases` trả 2 phần tử và `meta.limit == 2`; và Given SCHEMA (chưa có lần chạy case nào), Then `GET /api/v1/cases` trả 200 với `data == []` và `meta == {"run_id": null, "as_of": null, "total": 0, "limit": 50, "offset": 0}`.
- AC5: Given API-MINI, When gọi `GET /api/v1/cases/C-C01-20260302/subjects` bằng từng role, Then với `client(user="analyst01")` trả 200, `source == "live"`, `meta == {"pii": "masked"}`, `data` có 2 phần tử theo thứ tự `C01`, `C02`, mỗi phần tử có tập khoá bằng đúng `set(MASKED_COLUMNS)` của `aml.dba.masking` (không có `dob`, `street`, `address`, `device_id`, `ip`), phần tử `C01` có `full_name == "Nguyen T. C."`, `id_number == "****4561"`, `birth_year == 1990`, `kyc_risk == "LOW"`, các chuỗi `B1234561`, `B1234562` và `Nguyen Thi` không có trong response, và `audit_log` không thêm dòng nào; cùng request có thêm `?masked=false`, `?pii=full` và header `X-AML-Role: supervisor` vẫn trả `meta.pii == "masked"` và `id_number == "****4561"`; với `client(user="supervisor01")` trả 200, `meta == {"pii": "full"}`, phần tử `C01` có `full_name == "Nguyen Thi C01"`, `id_number == "B1234561"`, `dob == "1990-01-01"`, và `audit_log` thêm đúng 1 dòng có `module='ui'`, `entity_type='case'`, `entity_id='C-C01-20260302'`, `decision='PII_VIEWED'`, `actor='supervisor01'`, `version='api/v1'`, `reason` bằng đúng `unmasked subject data of case C-C01-20260302 shown to supervisor01 (role supervisor)` và `details.cifs == ["C01", "C02"]`; `GET /api/v1/cases/C-NOPE-20260101/subjects` trả 404 với `error.code == "not_found"` và `error.message` chứa `unknown case_id`, không ghi audit kể cả với `supervisor01`; và `client(user="nobody")` trả 401 mà không có giá trị `full_name` nào trong response.
- AC6: Given API-MINI và `client(user="analyst01")`, When gọi `POST /api/v1/cases/C-C05-20260630/disposition` với thân `{"disposition": "FALSE_POSITIVE", "reason": "name only match"}`, Then trả 201 với thân bằng đúng `{"source": "live", "feature": "cases", "data": {"disposition_id": 1, "case_id": "C-C05-20260630", "disposition": "FALSE_POSITIVE", "actor": "analyst01", "decided_on": "2026-06-30"}, "meta": {}}`; `case_dispositions` có đúng 1 dòng (`case_id` `C-C05-20260630`, `run_id` 1, `actor` `analyst01`, `origin` `HUMAN`); `audit_log` thêm đúng 1 dòng `entity_type='case'` (chỉ đếm dòng `entity_type='case'`: từ `specs/case-suppression.md` trở đi `record_disposition` còn ghi thêm dòng `entity_type='good_guy'` cho `FALSE_POSITIVE`, dòng đó không thuộc AC này), dòng ấy có `module='cases'`, `entity_id='C-C05-20260630'`, `decision='FALSE_POSITIVE'`, `actor='analyst01'`, `reason='name only match'`, `details.disposition_id = 1`; `GET /api/v1/cases` sau đó trả case đó với `status == "OPEN"` (trạng thái chỉ đổi ở lần `run_cases` kế tiếp) và `disposition == {"disposition": "FALSE_POSITIVE", "actor": "analyst01", "decided_on": "2026-06-30"}`; `client(user="supervisor01")` gửi `{"disposition": "SUSPICIOUS", "reason": "second review"}` cho cùng case trả 201 với `data.disposition_id == 2`, `data.actor == "supervisor01"` và dòng audit mới có `actor='supervisor01'`; mỗi request sau đây trả đúng mã nêu ra và để nguyên số dòng của `case_dispositions` và `audit_log`: thân có thêm `"actor": "boss"` → 422 `invalid_request`; `"reason": ""` → 422; `"reason": "   "` → 422; thiếu `reason` → 422; `"disposition": "CLOSED"` → 422; case `C-NOPE-20260101` với thân đúng → 404 `not_found` có `error.message` chứa `unknown case_id`; `DELETE /api/v1/cases/C-C05-20260630/disposition` → 405; và với `AML__UI__DEFAULT_USER=""` không header → 401 `missing_user`.
- AC7: Given SCHEMA và `client()` với cấu hình mặc định (`ui.mock.sample` bật), When gọi `GET /api/v1/sample`, Then trả 200 với thân bằng đúng `{"source": "mock", "feature": "sample", "data": {"items": [{"id": "S-001", "label": "sample row 1", "value": 42}, {"id": "S-002", "label": "sample row 2", "value": 7}]}, "meta": {"mock": {"fixture": "sample.json", "notice": "Sample data - not a measured result"}}}`, header `X-AML-Source == "mock"`, `data` bằng `json.loads` của file `src/aml/api/fixtures/sample.json`, và hai lần gọi cho thân giống hệt từng byte; với `AML__UI__MOCK__SAMPLE=false` thì trả 501 với thân bằng đúng `{"error": {"code": "not_implemented", "message": "feature 'sample' has no live implementation and ui.mock.sample is off"}}`, chuỗi `S-001` không có trong response, và `GET /api/v1/status` trả `data.mock == {"sample": false}`; `mock_or_live(settings, "sample", lambda: {"items": []})` với cờ tắt trả response có `source == "live"`, `data == {"items": []}`, `meta == {}` và header `X-AML-Source == "live"`; với cờ bật và `live_fn` raise `AssertionError` khi bị gọi thì vẫn trả `source == "mock"` (hàm thật không bị gọi); `mock_or_live(settings, "nope", None)` raise `ValueError` chứa `unknown mock feature 'nope'`; `set(MockConfig.model_fields) == set(mock.features()) == {"sample"}`; với cấu hình mặc định, mọi route `GET` dưới `/api/v1` không có tham số đường dẫn trả 200 có `source` thuộc (`live`, `mock`), có header `X-AML-Source` bằng `source` của thân, và tập đường dẫn có `source == "mock"` bằng đúng `{"/api/v1/sample"}`; khi mọi trường của `MockConfig` đều tắt thì không response nào trong số đó có `source == "mock"` hay header `X-AML-Source == "mock"`; và chuỗi `fixtures` không xuất hiện trong file `.py` nào của `src/aml/api/` ngoài `mock.py`.
- AC8: Given SCHEMA, DIST và `client(AML__UI__DIST_DIR=<DIST>)`, When gọi các đường dẫn ngoài API và chạy lệnh `aml ui` với `uvicorn.run` được monkeypatch để chỉ ghi lại tham số, Then `GET /` trả 200 có `content-type` bắt đầu bằng `text/html` và thân chứa `aml-spa`; `GET /assets/app.js` trả 200 với thân chứa `console.log("aml")`; `GET /cases/C-C01-20260302` và `GET /metrics` trả 200 với thân chứa `aml-spa` (SPA fallback); `GET /api/v1/nope` trả 404 có `error.code == "not_found"` và thân không chứa `aml-spa`; `GET /api/v1/health` trả 200; `GET /%2e%2e/config.yaml` trả thân không chứa `seed: 42`; với `AML__UI__DIST_DIR` trỏ vào thư mục không tồn tại thì `GET /` trả 404 có `error.code == "not_found"` và `error.message` chứa `web UI is not built`, còn `GET /api/v1/health` vẫn trả 200; `aml ui` (có DIST) exit code 0, `uvicorn.run` được gọi đúng 1 lần với `host == "127.0.0.1"` và `port == 8000`, stdout có một dòng chứa `ui http://127.0.0.1:8000`, `backend=duckdb` và `mock=sample`; `aml ui --host 0.0.0.0 --port 8123` gọi `uvicorn.run` với `host == "0.0.0.0"` và `port == 8123`; với `AML__UI__MOCK__SAMPLE=false` dòng đó chứa `mock=none`; khi thư mục dist không tồn tại, `aml ui` exit code 1 với stderr chứa `npm --prefix web run build` và `--api-only`, và `uvicorn.run` không được gọi; `aml ui --api-only` trong trường hợp đó exit code 0, gọi `uvicorn.run` đúng 1 lần và stdout chứa `dist=none`; `aml --help` liệt kê `ui`, `aml ui --help` exit code 0 với stdout chứa `--api-only` và không chứa `Phase 9`, còn `aml rag` vẫn exit code 1 với stderr chứa `arrives in Phase 8`; dòng target `ui` của `Makefile` chứa `npm --prefix web run build` và `$(AML) ui`; `tasks.ps1` chứa `"--prefix", "web", "run", "build"`; `web/package.json` có `scripts.dev` và `scripts.build`, và ba chuỗi `vitest`, `@testing-library`, `jsdom` không có trong file đó; `web/package-lock.json` tồn tại; `web/vite.config.ts` chứa hai chuỗi `"/api"` và `http://127.0.0.1:8000`; không file nào dưới `web/src/pages/` chứa chuỗi `fetch(`; không file nào dưới `web/src/` chứa `dangerouslySetInnerHTML`; và trong các file dưới `web/src/`, chuỗi `Dữ liệu mẫu` xuất hiện ở đúng một file là `web/src/components/SourceBadge.tsx`.

## Yêu cầu giao diện (kiểm tay)
<!-- Không có test tự động (Q9). Người dùng tự kiểm khi demo, sau `make ui` (hoặc `.\tasks.ps1 ui`) trên dữ liệu đã
`aml cases build`, cấu hình mặc định. Mỗi dòng: thao tác -> kết quả mong đợi. -->
- M1: Mở `http://127.0.0.1:8000/` -> trình duyệt chuyển sang `/cases`; menu có 6 mục dẫn tới `/cases`, `/screening`, `/data-quality`, `/benchmark`, `/metrics`, `/system`.
- M2: Ở `/cases` -> bảng liệt kê case của lần chạy mới nhất (mã case, trạng thái, số alert, nguồn, alert cuối), case có alert mới nhất đứng đầu; **không có cột điểm** và **không có nhãn `Dữ liệu mẫu`** ở đâu trên trang.
- M3: Mở `/system` -> thấy backend (`duckdb` hoặc `oracle`), danh sách cờ mock, và panel mẫu có 2 dòng `S-001`, `S-002` kèm **đúng một nhãn `Dữ liệu mẫu`** nằm ngay trên panel đó.
- M4: Dừng server, chạy lại với `AML__UI__MOCK__SAMPLE=false`, mở `/system` -> panel mẫu báo `Chưa có dữ liệu` (kèm mã `not_implemented`), **không hiện `S-001`, `S-002` hay con số nào**, không có nhãn `Dữ liệu mẫu`; phần trạng thái ghi cờ `sample` đang tắt.
- M5: Mở lần lượt `/screening`, `/data-quality`, `/benchmark`, `/metrics`, `/cases/<một mã case>` -> mỗi trang có tiêu đề và dòng `Chưa triển khai`, không có số liệu nào; trang chi tiết hiện đúng mã case trên URL.
- M6: Mở `/khong-co-trang-nay` -> trang "không tìm thấy" của SPA (không phải JSON, không phải trang trắng); tải lại (F5) ở `/metrics` vẫn ra trang đó.
- M7: Header hiện `analyst01` và role `analyst`; chọn `supervisor01` ở ô đổi người dùng -> header đổi thành `supervisor01` / `supervisor`, tải lại trang vẫn giữ lựa chọn.
- M8: Mở DevTools, tab Network, tải lại `/system` -> request `/api/v1/sample` có response header `X-AML-Source: mock`, request `/api/v1/status` có `X-AML-Source: live`, và mọi request tới `/api/v1/` mang header `X-AML-User` đúng người đang chọn.
- M9: Chạy `npm --prefix web run dev` cùng `aml ui --api-only`, mở địa chỉ Vite in ra -> M2 và M3 cho cùng kết quả (proxy `/api` hoạt động).

## Ngoài phạm vi
- **Trang có nội dung** — case detail (panel enrichment, đồ thị Cytoscape, fund-flow trace và bộ chọn backend),
  screening review và form quyết định, data quality, benchmark: `ui-live-pages`. Ở spec này chúng là trang rỗng.
- **Mọi tính năng mock cụ thể** — điểm ưu tiên và sắp xếp theo ưu tiên trên case queue, panel case summary, chat
  assistant qua SSE + draft narrative, metrics dashboard, mẫu below-the-line: `ui-mock-pages` (thêm trường vào
  `MockConfig`, fixture, router, panel). Spec này chỉ có tính năng mẫu `sample`.
- Hiện thực SSE; endpoint cho trace, đồ thị, screening, DQ, benchmark, metrics, assistant; form disposition trên UI
  (spec này chỉ có endpoint).
- Xác thực thật (mật khẩu, session, JWT, OIDC), CSRF, CORS, rate limit, HTTPS; quản lý người dùng qua UI. Header
  `X-AML-User` là lời khai, như `--actor` của CLI.
- Kết nối Oracle theo từng role (`aml_analyst_usr`, `aml_app_usr`), cấp quyền Oracle trên bảng `case*` / `audit_log`
  cho role của 2b, sửa `ROLE_GRANTS` (Q4). Che PII trong `transactions` (`counterparty_name`, `memo`, `device_id`,
  `ip`) — 2b Q9 để nguyên; `ui-live-pages` phải quyết khi hiển thị giao dịch.
- Tự chạy `run_cases` sau disposition; đổi `cases.status` từ API; sửa bất cứ thứ gì trong `src/aml/cases/`; DDL mới.
- Role thứ ba (auditor xem `audit_log`, admin); phân quyền theo từng endpoint ngoài mức PII; trang xem audit log.
- Bộ lọc case queue ngoài `status` (nguồn, khoảng ngày, risk rating, tìm theo tên); sắp xếp do người dùng chọn.
- **Test frontend tự động** (Vitest, React Testing Library, jsdom) — người dùng quyết định không làm (Q9).
- ESLint / Prettier, test end-to-end bằng trình duyệt (Playwright), kiểm thử giao diện bằng ảnh, i18n, dark mode,
  thư viện component, thư viện quản lý state, Docker image cho UI, chạy nhiều worker `uvicorn`, `--reload`.
- Ghi số liệu vào README; đo hiệu năng API trên `small` / `large`.

## Giả định
- **Đã đo** (prototype ngoài repo, mục Hiện trạng): thứ tự và mọi giá trị case của API-MINI trong AC4; giá trị che /
  không che của subject trong AC5; `record_disposition` chạy trong request của `TestClient` và dòng audit của nó
  (AC6); một `DuckDb` dùng chung cho các request tuần tự; 404 mặc định của FastAPI. **Suy ra, chưa đo** (chưa có
  code): mọi chuỗi thông điệp lỗi, output của `aml ui`, phục vụ file tĩnh và SPA fallback (AC8), mọi thứ của `web/`,
  hành vi của `yaml.safe_load("")` → `None` cho `AML__UI__DEFAULT_USER=""` (đọc từ `apply_env_overrides`), đường
  Oracle. Nếu khi hiện thực giá trị lệch do chi tiết của thư viện, cập nhật spec chứ không đổi quy ước.
- Người dùng đã đồng ý dựng UI trước 7c / 7d / Phase 8 và nới phase gate cho việc đó; ba spec UI vẫn cần duyệt riêng.
- API chạy dưới schema owner trên cả hai backend; che PII là việc của tầng ứng dụng (chọn `customers_masked`) và được
  bảo vệ bằng test, không phải bằng quyền của database. Ai tới được cổng của API đều tự khai được là `supervisor01`;
  vì thế `ui.host` mặc định là `127.0.0.1` và dữ liệu là tổng hợp.
- Các AC trên API-MINI giữ nguyên sau khi 7b-supp (`specs/case-suppression.md`) vào: lần `run_cases` đầu tiên luôn có
  0 item bị suppress (spec đó ghi rõ). Nếu 7c đổi `load_case(...).score` hay thêm bảng, hợp đồng của `GET
  /api/v1/cases` không đổi (điểm đi qua endpoint riêng của `ui-mock-pages`).
- `decided_on` của disposition qua API là mặc định của `record_disposition` (`settings.data.reference_date`), nhất quán
  với các lệnh khác không dùng đồng hồ máy; `decided_ts` và `event_ts` của audit là UTC.
- Tên role, mã lỗi, tên header, `MOCK_NOTICE`, nhãn `Dữ liệu mẫu` và danh sách route là cấu trúc (hằng trong code);
  host, cổng, người dùng demo, cỡ trang, thư mục dist và các cờ mock là cấu hình.
- Thông điệp lỗi của API, `reason` của audit và output CLI bằng tiếng Anh như các lệnh hiện có; chữ trên giao diện
  bằng tiếng Việt (Q13). Không có `data-testid` trong mã frontend (không có test nào dùng).
- `cli.py`, `config.py`, `config.yaml`, `Makefile`, `tasks.ps1` là file dùng chung với loop 7b-supp đang chạy; spec
  này chỉ thêm mục `ui` / lệnh `ui`, không đụng phần `cases`.
- Hành vi frontend trên trình duyệt (nhãn `Dữ liệu mẫu` hiện đúng chỗ, routing, ô đổi người dùng, client từ chối
  envelope thiếu `source`) **không được verify loop kiểm**; người dùng chấp nhận kiểm tay theo checklist M1–M9.
- Phiên bản thư viện frontend do `package-lock.json` ghim; React hiển thị chuỗi dưới dạng văn bản (đã escape) nên
  memo có prompt injection hay HTML không thành mã chạy được.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Xác định người dùng hiện hành thế nào khi không có auth thật? — đề xuất mặc định: header `X-AML-User: <actor>`; server tra `ui.users` trong `config.yaml` (`analyst01: analyst`, `supervisor01: supervisor`) để ra role; không có header thì dùng `ui.default_user` (`analyst01`); actor lạ → 401. UI có ô chọn người dùng ở header để demo đổi vai. Lý do: role không bao giờ do client khai, đổi vai trong demo chỉ cần một cú bấm, test truyền header là xong. Phương án thay thế: (a) một người dùng cố định trong config, đổi vai phải khởi động lại; (b) `default_user: null` — bắt buộc có header, không có "người dùng ngầm định"; (c) HTTP Basic với mật khẩu demo trong `.env`. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q2. **(cần người dùng quyết)** Có những role nào và role nào thấy PII không che? — đề xuất mặc định: hai role — `analyst` (bản che `customers_masked`, đúng brief) và `supervisor` (bản đầy đủ `customers`); cả hai đều ghi được disposition. Lý do: cần ít nhất một role không che thì mới chứng minh được che là theo role. Phương án thay thế: (a) chỉ `analyst`, không ai thấy bản đầy đủ qua UI (đơn giản nhất, nhưng không demo được khác biệt); (b) thêm `auditor` chỉ đọc `audit_log`, không ghi quyết định; (c) `supervisor` mặc định cũng thấy bản che và phải bấm "hiện đầy đủ" kèm lý do cho từng case. — Trả lời: theo đề xuất mặc định (người dùng chọn trong bảng hỏi).
- [x] Q3. Mỗi lần trả PII không che có ghi `audit_log` không? — đề xuất mặc định: **có**, 1 dòng `PII_VIEWED` (`module='ui'`, actor, case, danh sách CIF) cho mỗi response không che; response đã che không ghi gì. Lý do: cùng tinh thần với policy `AML_PII_ACCESS` của 2b và có ở cả DuckDB. Cái giá: supervisor mở một case nhiều lần sinh nhiều dòng. Phương án thay thế: không ghi (chỉ dựa vào unified auditing của Oracle, DuckDB không có gì). — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q4. **(cần người dùng quyết)** Che PII được thực thi ở tầng nào trên Oracle? — đề xuất mặc định: tầng ứng dụng — API kết nối bằng owner như mọi lệnh hiện có và chọn `customers_masked` theo role, giống hệt DuckDB; test khẳng định response của analyst không chứa giá trị gốc. Lý do: `aml_analyst` chưa có quyền trên bảng `case*` (7a AC1 khẳng định) nên kết nối theo role đòi sửa `ROLE_GRANTS`, `020_grants.sql` và test của 2b. Phương án thay thế: API mở kết nối `aml_analyst_usr` / `aml_app_usr` theo role của request (phòng thủ nhiều lớp thật sự, nhưng phải cấp quyền cho các bảng Phase 3–7 và chỉ có tác dụng trên Oracle). — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q5. Hình dạng envelope và lỗi? — đề xuất mặc định: thành công `{"source": "live" | "mock", "feature", "data", "meta"}` + header `X-AML-Source`; lỗi `{"error": {"code", "message"}}` với mã HTTP đúng nghĩa, không có `source`. Lý do: một chỗ duy nhất để frontend kiểm cờ; header phủ được SSE và file tải về. Phương án thay thế: (a) chỉ dùng header, thân là dữ liệu trần (gọn hơn nhưng dễ mất cờ khi lưu / chép JSON); (b) cờ nằm trong `meta.source`. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q6. **(cần người dùng quyết)** Trang vừa có dữ liệu thật vừa có dữ liệu mẫu (case queue + điểm ưu tiên) thì trả thế nào? — đề xuất mặc định: **mỗi response một nguồn** — `GET /api/v1/cases` luôn là dữ liệu thật và không có điểm; điểm đi qua endpoint riêng của `ui-mock-pages`, frontend ghép theo `case_id` và cột điểm mang nhãn `Dữ liệu mẫu` riêng. Lý do: không bao giờ có một con số mẫu nằm trong response gắn cờ `live`. Cái giá: hai request cho một trang và khi sắp theo điểm mẫu thì cả thứ tự của bảng là "mẫu". Phương án thay thế: một response có cờ theo từng trường (`meta.mock_fields: ["score"]`) — ít request hơn nhưng dễ sót nhãn. — Trả lời: theo đề xuất mặc định (người dùng chọn trong bảng hỏi).
- [x] Q7. **(cần người dùng quyết)** Ngữ nghĩa của cờ mock? — đề xuất mặc định: `ui.mock.<tính năng>: true` → luôn trả fixture kể cả khi đã có bản thật (để demo không cần dữ liệu); `false` + đã có bản thật → dữ liệu thật; `false` + chưa có bản thật → 501 và UI hiện lỗi chứ không hiện số. Mặc định trong `config.yaml` là `true` cho tới commit đưa bản thật vào, commit đó đổi thành `false`. Lý do: tắt cờ không bao giờ làm lộ số giả; bật cờ luôn kèm nhãn. Phương án thay thế: (a) mặc định `false`, người demo phải chủ động bật; (b) chế độ `auto` — tự dùng bản thật khi có. — Trả lời: theo đề xuất mặc định (người dùng chọn trong bảng hỏi).
- [x] Q8. Endpoint mẫu để chứng minh cơ chế là gì và có giữ lại không? — đề xuất mặc định: tính năng trung tính `sample` (`GET /api/v1/sample`, fixture 2 dòng, panel trên trang `/system`), giữ lại vĩnh viễn làm bài tự kiểm của cơ chế. Lý do: không khoá hợp đồng JSON của tính năng nào thuộc `ui-mock-pages`. Phương án thay thế: dùng luôn một tính năng thật (vd điểm ưu tiên) làm mẫu — bớt một endpoint "vô nghĩa" nhưng spec này phải định hợp đồng của 7c; hoặc `ui-mock-pages` xoá `sample` khi tính năng mock đầu tiên vào. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q9. **(cần người dùng quyết)** Test frontend chạy bằng gì và có nằm trong verify loop không? — đề xuất mặc định: Vitest + React Testing Library (jsdom); thêm hai bước vào `.claude/loop.yaml`: `npm --prefix web run build` (kiểm kiểu) và `npm --prefix web run test`; cần `npm --prefix web ci` một lần trước. `pytest` không gọi Node. Lý do: các AC frontend chỉ có nghĩa khi loop thật sự chạy chúng; nhãn `Dữ liệu mẫu` là yêu cầu "never fabricate". Lưu ý: `.claude/` đang bị git-ignore nên thay đổi này là cục bộ, người dùng tự sửa file. Phương án thay thế: (a) giữ loop như cũ, test frontend chạy tay (`make web-test`) — rủi ro hành vi frontend không được loop kiểm; (b) một test pytest gọi `npm` qua subprocess và skip khi không có `node_modules`. — Trả lời: **người dùng quyết định khác đề xuất, thay cho lựa chọn mặc định đã chọn trước đó** ("Không cần test trên FE"): không có test frontend tự động (không Vitest, không React Testing Library, không jsdom); verify loop giữ `ruff` + `pytest`, chỉ thêm `npm --prefix web run build` (kiểm kiểu `tsc`) làm điều kiện phải pass vì đó là build chứ không phải test. Hệ quả: hai AC Vitest của bản nháp trước bị bỏ; nội dung của chúng thành quy ước code ở mục Thiết kế và checklist "Yêu cầu giao diện (kiểm tay)"; AC7 là bảo đảm tự động duy nhất cho "never fabricate results".
- [x] Q10. `aml ui` và `make ui` làm gì? — đề xuất mặc định: `aml ui` chỉ khởi động uvicorn và không bao giờ gọi `npm`; thiếu `web/dist` thì exit 1 kèm lệnh cần chạy, trừ khi có `--api-only` (dùng với `npm run dev`). `make ui` / `tasks.ps1 ui` chạy `npm install` → `npm run build` → `aml ui`. Lý do: lệnh Python kiểm thử được mà không cần Node; "một lệnh" vẫn có ở lớp wrapper. Phương án thay thế: `aml ui --build` tự gọi `npm`; hoặc commit sẵn `web/dist` để chạy không cần Node. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q11. Case queue sắp xếp, lọc và phân trang thế nào khi chưa có điểm? — đề xuất mặc định: sắp theo (`last_alert_ts` giảm, `case_id` tăng); lọc `status`; `limit` / `offset` với `ui.page_size` 50, tối đa 200; đọc cả `cases_current` rồi cắt bằng pandas (`small` có khoảng 335 case). Lý do: brief ghi "sorted by priority" nhưng điểm thuộc 7c; mới nhất lên đầu là thứ tự trung tính. Phương án thay thế: sắp theo số alert giảm dần; hoặc trả hết không phân trang. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q12. Có đưa endpoint disposition vào spec nền móng không? — đề xuất mặc định: **có** — `POST /api/v1/cases/{case_id}/disposition` gọi `record_disposition` có sẵn, để quy ước "endpoint quyết định ghi audit kèm actor" được chứng minh bằng test; form trên UI thuộc `ui-live-pages`. Hệ quả cần biết: sau khi ghi, case vẫn `OPEN` cho tới lần `aml cases build` kế tiếp — UI phải hiện `disposition` riêng với `status`. Phương án thay thế: để cả endpoint cho `ui-live-pages` (spec này chỉ nêu quy ước, không có AC chứng minh); hoặc API tự chạy `run_cases` sau mỗi disposition (chậm, và đổi ảnh chụp giữa buổi demo). — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q13. Chữ trên giao diện bằng tiếng gì? — đề xuất mặc định: tiếng Việt có dấu (menu: `Hàng đợi case`, `Rà soát screening`, `Chất lượng dữ liệu`, `Benchmark`, `Chỉ số`, `Hệ thống`; nhãn `Dữ liệu mẫu`), còn dữ liệu, `reason`, mã lỗi giữ tiếng Anh như nguồn. Lý do: nhãn được yêu cầu là tiếng Việt; không có test nào bám vào chữ trên giao diện ngoài kiểm tĩnh chuỗi `Dữ liệu mẫu` (AC8). Phương án thay thế: toàn bộ tiếng Anh (nhãn thành `Sample data`) cho người phỏng vấn không đọc tiếng Việt. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q14. Thư viện frontend? — đề xuất mặc định: React + TypeScript (strict) + Vite, `react-router-dom` cho routing, `fetch` có sẵn (không axios), không thư viện state, không UI kit (CSS thuần), không ESLint (kiểm kiểu bằng `tsc`). Lý do: ít dependency, dễ dẫn người phỏng vấn đọc code; Cytoscape.js sẽ do `ui-live-pages` thêm. Phương án thay thế: thêm TanStack Query (cache, retry) và một UI kit (Mantine / MUI) để trang nội dung dựng nhanh hơn. — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
- [x] Q15. Kết nối database của API? — đề xuất mặc định: mỗi request mở `get_db(settings)` rồi đóng (đã đo 27,5 mili giây cho DuckDB); test truyền sẵn `db=duck`. Lý do: không giữ khoá file DuckDB giữa các request, nên chạy `aml cases build` ở terminal khác trong lúc UI đang mở có cơ hội thành công (chưa đo với hai tiến trình). Phương án thay thế: một kết nối sống suốt vòng đời app (nhanh hơn, nhưng khoá file DuckDB và không an toàn khi nhiều request đồng thời). — Trả lời: theo đề xuất mặc định (người dùng không đổi khi được hỏi; xác nhận khi duyệt spec).
