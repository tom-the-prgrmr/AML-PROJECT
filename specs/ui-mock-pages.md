---
id: ui-mock-pages
status: draft
approved_by:
---

# Phase 9c — Trang dựng trước phase nguồn: điểm ưu tiên trên case queue, panel case summary, assistant (chat SSE, draft narrative, typology explainer, feedback), metrics dashboard — endpoint mock theo hợp đồng JSON cuối cùng, và tiêu chí kiểm để nối thật

## Bối cảnh
Spec thứ ba của Phase 9 (PROJECT_BRIEF.md mục 10), dựng trên `specs/ui-foundation.md` (prefix `/api/v1`, envelope
`{source, feature, data, meta}`, header `X-AML-Source`, `MockConfig`, `mock_or_live`, `ApiPanel` / `SourceBadge`) và song
song với `specs/ui-live-pages.md` (sở hữu trang case detail, ba slot và hợp đồng highlight mà spec này chỉ **gọi**). Người dùng dựng UI **trước** khi 7b-supp (`specs/case-suppression.md`), 7c
(`specs/case-prioritization.md`), 7d (`specs/case-summary.md`), Phase 7b và Phase 8 của brief xong. Spec này định **hợp
đồng JSON cuối cùng** của bốn nhóm tính năng phụ thuộc các phase đó, trả dữ liệu mẫu ở tầng API cho tới khi phase thật
xong, và — quan trọng nhất — trả lời câu hỏi của người dùng "khi Phase 7 và 8 hoàn thành có đổi sang API thật được
không" bằng **tiêu chí kiểm tự động**: một bộ kiểm hợp đồng dùng chung cho fixture và response thật, một điểm gắn hàm
thật duy nhất (`aml.api.live`), và một cờ trong `config.yaml`. Frontend không đổi khi nối thật. Quy tắc dự án "never
fabricate results": mọi response mẫu mang `source: "mock"`; không số mẫu nào vào database, `audit_log`, `results/` hay
README. Người dùng: investigator trong buổi demo; người hiện thực 7c / 7d / Phase 8 (đọc mục "Tiêu chí đã nối thật").

Theo yêu cầu của người dùng (2026-10-13): **không có test tự động cho frontend**. Mọi AC là pytest phía backend. Hành
vi giao diện nằm trong mục "Yêu cầu giao diện (kiểm tay)"; `npm --prefix web run build` (kiểm kiểu bằng `tsc`) vẫn phải
pass.

### Hiện trạng đã kiểm (2026-10-13, seed 42)
Đọc code và chạy hai script tạm ngoài repo (scratchpad): MINI-C của `tests/cases/helpers.py::load_minic` trên DuckDB
tạm, và một **bản sao** của `data/aml.duckdb` (`small`). Không file nào trong repo bị sửa.
- **Chưa có** `src/aml/api/`, `web/`, `tests/api/` (thuộc `ui-foundation`, đã duyệt, chưa hiện thực). `aml score`, `aml
  rag` vẫn là stub; `CaseView.score` luôn `None` (`src/aml/cases/view.py`); chưa có `aml.cases.narrative`,
  `aml.cases.features`, `aml.assistant`; `config.yaml` chưa có `cases.prioritization`, `cases.summary`, `ui`, `metrics`.
- **Đã đo được thật từ các phase đã xong** (đây là phần của dashboard có thể là `live` ngay):
  - Volume alert theo nguồn (`alerts_current`, `screening_current`, `small`): RULE 242 (`DORMANT_REACTIVATION` 137,
    `RAPID_MOVEMENT` 45, `STRUCTURING` 20, `FAN_OUT` 20, `HIGH_VELOCITY` 15, `FAN_IN` 5), NETWORK 25 (`NET_CYCLE` 15,
    `NET_HUB` 5, `NET_SHARED_ATTRIBUTE` 5), screening `ALERT` 41, `REVIEW` 31, `AUTO_CLEARED` 6208.
  - `aml.monitoring.evaluate.evaluate_rules(db)` (0,03 giây), `aml.graph.network.evaluate.evaluate_network(db)` (0,02
    giây), `aml.screening.evaluate.evaluate(db, settings)` (**1,79 giây**, một lần đo) trả đúng các bảng đang nằm ở
    `results/phase3/screening_eval.csv`, `results/phase5/monitor_eval.csv`, `results/phase5/network_eval.csv`. Screening:
    `fuzzy` 4436 cặp (25 true hit), `two_tier` 72 cặp (25 true hit, recall 1,0), `two_tier_alert` 41.
  - `case_runs` (7a) có 1 dòng: `items` 475, `alerts` 339, `suppressed` 0, `active` 475, `cases` 335; `cases_current` 335
    `OPEN`. `case_dispositions` **rỗng**. Bảng `good_guy_list` chưa có trong `data/aml.duckdb` (7b-supp chưa commit).
  - **Consolidation chỉ giảm 339 alert → 335 case (1,18 %)** nếu đếm theo alert phân biệt; đếm theo item (alert × golden
    customer) là 475 → 335 (Q3).
  - 6208 cặp `AUTO_CLEARED`: **0** cặp là true hit theo `truth_pairs(db)` (25 cặp).
- **Trên MINI-C** (đã đo): `run_cases` trả `items=9`, `alerts=7`, `cases=5`; `evaluate(db, settings)` raise
  `ScreeningError('watchlist is empty; run `aml load` first')` — hàm đọc metrics phải chịu được; `evaluate_network` raise
  `NetworkError` khi chưa có lần chạy network; `alert_evidence` của MINI-C: alert 1 `T01`; 2 `T05`, `T06`; 3 `T07`; 4
  `T02`, `T03`; 5 `T02`, `T03`, `T04`; `T01` có `from_account_id` null (tiền mặt).
- **Nhãn node của projection Neo4j** (`cypher/sync/merge_*.cypher`): `Customer {golden_customer_id}`, `Account
  {account_id}` (cả tài khoản ngoài), `Device` / `Phone` / `Address {key}`; cạnh `TRANSFERRED_TO {txn_id}`.
- **Chưa đo**: mọi thứ cần `src/aml/api/` (chưa có code) — chuỗi SSE, thông điệp lỗi, số sự kiện; mọi thứ của `web/`;
  đường Oracle; mọi response thật của 7c / 7d / Phase 8.

### Bảng tính năng
| feature | endpoint | nguồn lúc spec này xong | chờ | dữ liệu mẫu |
|---|---|---|---|---|
| `case_scores` | `GET /api/v1/cases/scores` | mock | 7c | builder (đọc `cases_current`) |
| `case_summary` | `GET /api/v1/cases/{case_id}/summary` | mock | 7d | builder (kiểm case tồn tại) |
| `assistant` | `POST /api/v1/assistant/chat` (SSE), `POST /api/v1/cases/{case_id}/narrative`, `GET /api/v1/cases/{case_id}/typologies`, `POST /api/v1/assistant/feedback` | mock | Phase 8 | `fixtures/assistant.json` (văn bản) + builder (ID thật của case) |
| `metrics_suppression` | `GET /api/v1/metrics/suppression` | mock | 7b-supp | `fixtures/metrics_suppression.json` (tĩnh) |
| `metrics_funnel` | `GET /api/v1/metrics/funnel` | **live** | — | — |
| `metrics_detections` | `GET /api/v1/metrics/detections` | **live** | — | — |
| `metrics_auto_cleared` | `GET /api/v1/metrics/below-the-line/auto-cleared` | **live** | — | — |

### Interface đề xuất
```python
# src/aml/common/config.py
class MockConfig(BaseModel):  # của ui-foundation; spec này thêm bốn trường
    sample: bool
    case_scores: bool
    case_summary: bool
    assistant: bool
    metrics_suppression: bool


class MetricsConfig(BaseModel):
    minutes_per_alert: int  # >= 1; giả định để ước tính giờ tiết kiệm; luôn được hiển thị
    sample_size: int  # 1..max_sample_size; cỡ mẫu below-the-line mặc định
    max_sample_size: int


class Settings(BaseModel):
    ...
    metrics: MetricsConfig


# src/aml/api/live.py — ĐIỂM NỐI THẬT DUY NHẤT. Mỗi tên là None cho tới commit của phase nguồn.
case_scores: Callable[[Database, Settings], dict[str, Any]] | None = None
case_summary: Callable[[Database, Settings, str, str], dict[str, Any]] | None = (
    None  # case_id, language
)
assistant_chat: (
    Callable[[Database, Settings, User, ChatRequest], Iterator[tuple[str, dict[str, Any]]]] | None
) = None
assistant_narrative: Callable[[Database, Settings, User, str, str], dict[str, Any]] | None = None
assistant_explainer: Callable[[Database, Settings, User, str], dict[str, Any]] | None = None
assistant_feedback: Callable[[Database, Settings, User, FeedbackRequest], dict[str, Any]] | None = (
    None
)
metrics_suppression: Callable[[Database, Settings], dict[str, Any]] | None = None


# src/aml/api/mock.py — mở rộng của ui-foundation (mục "Sửa kéo theo")
def load_fixture(
    name: str,
) -> Any: ...  # đọc fixtures/<name>.json; builder lấy văn bản mẫu qua hàm này


def mock_or_live(
    settings: Settings,
    feature: str,
    live_fn: Callable[[], Any] | None,
    *,
    mock_fn: Callable[[], Any] | None = None,  # builder; None -> đọc fixtures/<feature>.json
    status: int = 200,
    **meta: Any,
) -> JSONResponse: ...


# src/aml/api/sse.py
def encode(
    event: str, data: dict[str, Any]
) -> bytes: ...  # b"event: <event>\ndata: <JSON một dòng>\n\n"
def parse(text: str) -> list[tuple[str, dict[str, Any]]]: ...  # ngược của encode; dùng trong test
def stream_or_live(
    settings: Settings,
    feature: str,
    live_fn: Callable[[], Iterator[tuple[str, dict[str, Any]]]] | None,
    mock_fn: Callable[[], Iterator[tuple[str, dict[str, Any]]]],
) -> StreamingResponse: ...  # tự phát sự kiện `meta` đầu tiên; ApiError 501 như mock_or_live


# src/aml/api/mockdata/  (builder; thuần đọc, không ghi)
def build_case_scores(db: Database, settings: Settings) -> dict[str, Any]: ...
def build_case_summary(
    db: Database, settings: Settings, case_id: str, language: str
) -> dict[str, Any]: ...
def build_chat_events(
    db: Database, settings: Settings, req: ChatRequest
) -> list[tuple[str, dict[str, Any]]]: ...
def build_narrative(
    db: Database, settings: Settings, case_id: str, language: str
) -> dict[str, Any]: ...
def build_explainer(db: Database, settings: Settings, case_id: str) -> dict[str, Any]: ...


# src/aml/api/contracts.py  (thuần: không DB, không settings)
DRAFT_WATERMARK = "DRAFT — requires investigator review"  # dấu gạch là U+2014
CONTRACTS: tuple[
    str, ...
]  # case_scores, case_summary, assistant_answer, assistant_narrative, assistant_explainer,
# assistant_feedback, metrics_suppression, metrics_funnel, metrics_detections, metrics_auto_cleared


def check(
    contract: str, data: Any
) -> list[str]: ...  # [] = đúng hợp đồng; mỗi vi phạm một chuỗi "<đường dẫn>: <lỗi>"
def check_chat_events(events: Sequence[tuple[str, dict[str, Any]]]) -> list[str]: ...


# src/aml/metrics/  (nghiệp vụ; router chỉ gọi; KHÔNG import aml.api)
def funnel(db: Database, settings: Settings) -> dict[str, Any]: ...
def detections(db: Database, settings: Settings) -> dict[str, Any]: ...
def auto_cleared_sample(
    db: Database, settings: Settings, *, size: int | None = None
) -> dict[str, Any]: ...
```
- `config.yaml`: `ui.mock` thành `{sample: true, case_scores: true, case_summary: true, assistant: true,
  metrics_suppression: true}`; mục mới `metrics: {minutes_per_alert: 15, sample_size: 20, max_sample_size: 200}`.
- File mới: `src/aml/api/live.py`, `sse.py`, `contracts.py`, `mockdata/{case_scores,case_summary,assistant}.py`,
  `fixtures/assistant.json`, `fixtures/metrics_suppression.json`, `routers/{scores,summary,assistant,metrics}.py`,
  `reads/evidence.py` + `sql/common/api/case_evidence.sql` (giao dịch bằng chứng của các alert `RULE` / `NETWORK` của
  một case); gói `src/aml/metrics/`; test ở `tests/api/` và `tests/metrics/`.
- `web/`: `src/api/types.ts` (kiểu TypeScript chép tay từ hợp đồng dưới đây), `src/api/client.ts` thêm `apiStream`,
  `src/components/Markdown.tsx` (nơi duy nhất import `react-markdown`), các panel trong `src/components/` cho từng
  tính năng, `src/pages/` của `/cases`, `/cases/:caseId`, `/metrics`. `package.json` thêm `react-markdown`,
  `remark-gfm`.
- **Không DDL. Không sửa `src/aml/cases/`** — chỉ gọi `load_case` (7a). Không lệnh CLI mới.
- Các panel của spec này nằm trong `web/src/components/`; panel assistant import `useCaseHighlight` từ
  `web/src/pages/caseHighlight.ts` (của `ui-live-pages`) và không tự giữ trạng thái highlight.

### Sửa kéo theo ở phần đã duyệt — là một phần của spec này
`specs/ui-foundation.md` đã được duyệt nguyên trạng. Các thay đổi dưới đây vào code và test của nền móng là **một phần
của spec này** (cùng kiểu `specs/case-prioritization.md` làm với test stub của 7a); spec nền móng thêm ghi chú dẫn về
đây ở từng chỗ bị đổi. Không thay đổi nào làm yếu một bảo đảm của nền móng.

| # | chỗ của `ui-foundation` | thay đổi | test của nền móng phải cập nhật |
|---|---|---|---|
| S1 | `MockConfig`, `config.yaml` (`ui.mock`) | thêm bốn trường `case_scores`, `case_summary`, `assistant`, `metrics_suppression` (mặc định `true`) | AC2: `data.mock` của `GET /status` từ `{"sample": true}` thành dict năm khoá của AC1 spec này. AC7: `GET /status` với `AML__UI__MOCK__SAMPLE=false` trả dict năm khoá có `sample == false` và bốn khoá kia `true`; `set(MockConfig.model_fields) == set(mock.features())` bằng tập năm tên thay cho `{"sample"}`. AC1 của nền móng (`settings.ui.mock.sample is True`, khoá lạ → lỗi) giữ nguyên |
| S2 | `mock.features()` | nghĩa đổi từ "tính năng có file fixture" thành "mọi trường của `MockConfig`", kể cả tính năng dùng builder không có file | như S1 (AC7) |
| S3 | tập đường dẫn mock (AC7) | trong các route `GET` không tham số đường dẫn, tập có `source == "mock"` từ `{"/api/v1/sample"}` thành `{"/api/v1/sample", "/api/v1/cases/scores", "/api/v1/metrics/suppression"}`; ba route metrics live của spec này cũng nằm trong phép quét và trả 200 trên SCHEMA | AC7: đổi tập mong đợi. Mệnh đề "mọi cờ tắt → không response nào `mock`" giữ nguyên, nhưng phép quét khi mọi cờ tắt phải chấp nhận 501 cho ba route mock chưa có bản thật |
| S4 | dòng in của `aml ui` | danh sách cờ đang bật sắp tăng dần theo tên | AC8: `mock=sample` thành `mock=assistant,case_scores,case_summary,metrics_suppression,sample`; trường hợp `mock=none` phải đặt cả năm cờ `false` (chỉ tắt `sample` cho `mock=assistant,case_scores,case_summary,metrics_suppression`) |
| S5 | `mock_or_live(settings, feature, live_fn, **meta)` | thêm hai tham số chỉ-theo-tên `mock_fn` (builder; `None` → đọc `fixtures/<feature>.json` như cũ) và `status`; thêm `load_fixture(name)`; lời gọi cũ không đổi nghĩa | không (các lời gọi của AC7 vẫn đúng) |
| S6 | mục Thiết kế, "builder là hàm thuần của `settings.seed` và tham số request" | builder được **đọc** database (không ghi): `cases_current`, `load_case`, giao dịch bằng chứng — để dữ liệu mẫu khớp `case_id` / id node thật. Vẫn không đồng hồ, không ngẫu nhiên không seed. AC10 của spec này kiểm không-ghi | không |
| S7 | `meta.mock.fixture` = "tên file" | với builder là `builder:<tên hàm>` | không (`sample` vẫn `sample.json`) |
| S8 | SSE ("luồng mở đầu bằng `event: meta`") | hiện thực bằng module mới `src/aml/api/sse.py` (`encode`, `parse`, `stream_or_live`); `mock_or_live` vẫn chỉ trả `JSONResponse` | không |
| S9 | quy ước endpoint quyết định ("mọi `POST` ghi một quyết định của người … bắt buộc `reason`") | thu hẹp phạm vi: áp cho `POST` ghi quyết định **về case / screening hit**. Ba `POST` của assistant (`chat`, `narrative`, `feedback`) không phải endpoint quyết định: không bắt buộc `reason`, vẫn từ chối trường `actor` (422), và khi là bản thật vẫn ghi `audit_log` với actor của request (Q13) | không (AC6 của nền móng chỉ kiểm disposition) |
| S10 | `web/src/api/client.ts`, `ApiPanel` ("gọi `apiGet`", "đường duy nhất") | `client.ts` thêm `apiStream(path, body, onEvent)` (đọc luồng `fetch`, ném `ApiError` khi sự kiện `meta` thiếu `source` hợp lệ); `ApiPanel` nhận thêm `method` / `body` để dùng cho `POST` narrative; `SourceBadge` được export để panel chat hiện nhãn theo `source` của sự kiện `meta`. Ba quy tắc mã nguồn của nền móng (không `fetch(` trong `src/pages/`, không `dangerouslySetInnerHTML`, chuỗi `Dữ liệu mẫu` chỉ ở `SourceBadge.tsx`) giữ nguyên và áp cho mọi file của spec này | không (AC8 của nền móng vẫn xanh) |
| S11 | SPA: "`/cases` không có cột điểm", "`/metrics` là trang rỗng" | `/cases` có cột điểm ghép từ `GET /cases/scores`; `/metrics` có bốn panel. `GET /api/v1/cases` **không đổi** (vẫn 13 khoá, không `score`) | không (AC4 của nền móng giữ nguyên); mục kiểm tay tương ứng của nền móng dẫn về M1, M6 |

Không cần sửa: trạng thái lỗi của `ApiPanel` — nền móng đã quy định panel hiện `Chưa có dữ liệu` kèm `error.code` và
không hiện dòng dữ liệu nào cho mọi lỗi API, đủ cho 501 (M7 dùng đúng chữ đó).

### Quy ước dữ liệu mẫu
- Định danh **do mock tự đặt** luôn mang tiền tố: phiên bản / model `mock-…` (`mock-prio/logreg/0`, `mock-summary/v0`,
  `mock-llm`, `mock-prompt/v0`), `answer_id` `mock-<12 hex>`, thực thể không có thật `MOCK-…` (`MOCK-CHUNK-001`,
  `MOCK-CIF-001`), `run_id` / `score_run_id` bằng `0` (id thật bắt đầu từ 1). Câu văn mẫu bắt đầu bằng `[MẪU]` (tiếng
  Việt) hoặc `[SAMPLE]` (tiếng Anh). Bộ kiểm hợp đồng **không** dựa vào các tiền tố này.
- Định danh **của case** trong response mẫu là thật, đọc từ database lúc request (`case_id`, `golden_customer_id`,
  `account_id`, `txn_id` và dòng giao dịch bằng chứng) để trang lai ghép và highlight được. Mock không sinh thuộc tính
  khách hàng nào (tên, giấy tờ, ngày sinh).
- Builder là hàm của (`settings.seed`, tham số request, **nội dung database lúc đọc**): không đồng hồ, không ngẫu nhiên
  không seed, không mạng, không Ollama, không ghi gì. `meta.mock.fixture` là tên file JSON (`assistant.json`,
  `metrics_suppression.json`) hoặc `builder:<tên hàm>` khi không có file.
- Endpoint mock **không ghi** bảng nào, kể cả `audit_log` (Q13 là ngoại lệ đã cân nhắc và từ chối). Không module nào
  ngoài `src/aml/api/` import `aml.api.mock` / `aml.api.mockdata`; `src/aml/metrics/` không import `aml.api`.

### Hợp đồng JSON của `data`
Tên trường `snake_case`; tiền là số nguyên VND; mốc thời gian `YYYY-MM-DDTHH:MM:SS`; ngày `YYYY-MM-DD`. Mọi object có
**đúng** các khoá nêu ra (khoá thừa là vi phạm hợp đồng).

**`case_scores`** — shape lấy từ `specs/case-prioritization.md` (`CaseView.score`, `case_scores_current`):
- `data = {run_id: int | null, score_run_id: int | null, model_version: str | null, queue: int, scores: [Score]}`.
- `Score = {case_id: str, score: float trong (0, 1) tối đa 6 chữ số thập phân, queue_rank: int >= 1 | null,
  model_version: str, top_features: [{feature: str, value: float, contribution: float}]}`.
- Bất biến: `scores` sắp theo (`queue_rank` tăng, null ở cuối; rồi `case_id` tăng); các `queue_rank` khác null là hoán
  vị của `1..queue`; `score` không tăng theo `queue_rank`; `|contribution|` không tăng trong `top_features`; `feature`
  không trùng trong một case. Chưa có lần chấm nào → `scores == []`, `queue == 0`, ba trường đầu null.
- Mock (`build_case_scores`): mỗi case của `cases_current` có `score = round(0.05 + 0.9 * h / 2**32, 6)` với `h` = số
  nguyên từ 8 ký tự hex đầu của `sha256("{seed}|case_scores|{case_id}")`; `queue_rank` = hạng trong các case `OPEN` /
  `REOPENED` theo (`score` giảm, `case_id` tăng), case `CLOSED` null; `model_version = "mock-prio/logreg/0"`,
  `score_run_id = 0`, `run_id` = lần chạy case hiện hành; `top_features` cố định cho mọi case: `network_alerts` (1.0,
  1.5), `alerts` (1.0, 1.0), `max_screening_score` (0.0, -0.75), `cash_share` (0.0, -0.5), `kyc_risk_level` (0.0, 0.25)
  — năm tên thuộc `FEATURES` của 7c.

**`case_summary`** — đúng 7 trường của `Narrative` trong `specs/case-summary.md`:
- `data = {case_id, markdown, generator, version, language, watermark, citations: [str]}`; `meta = {pii: "masked"}`
  cho mọi role (`summarize` của 7d luôn dùng dữ liệu đã che; Q15).
- Bất biến (chính là phép kiểm hợp đồng của `summarize`): `case_id` bằng case được hỏi; `markdown`, `watermark`,
  `generator`, `version`, `language` khác rỗng; `watermark` xuất hiện nguyên văn trong `markdown`.
- Tham số `language` (tuỳ chọn, mặc định `en`). Case không tồn tại → 404 `not_found` (`unknown case_id`); ngôn ngữ mà bộ
  sinh không có → 422 `invalid_request`.
- Mock (`build_case_summary`): `generator = "mock"`, `version = "mock-summary/v0"`, `language = "en"`, `citations = []`,
  `watermark = "SAMPLE SUMMARY (mock-summary/v0): placeholder text, not generated from case data."`; `markdown` = dòng
  `# Case {case_id}`, dòng trống, `> {watermark}`, rồi bảy khối `## <tiêu đề>` theo đúng `SECTION_TITLES` của 7d, mỗi
  khối một dòng `[SAMPLE] Placeholder text for section <tiêu đề>.`; khối `Alerts` có thêm một bảng GFM hai cột một
  dòng dữ liệu (để giao diện render bảng). Ngoài `case_id`, markdown mẫu không chứa dữ liệu nào của case.

**`assistant`** — **ĐỀ XUẤT**: Phase 8 chưa có spec. Spec Phase 8 phải chấp nhận hợp đồng này hoặc sửa nó; nếu sửa thì
sửa cả spec này, `contracts.py`, `fixtures/assistant.json` và `web/src/api/types.ts` trong cùng thay đổi (Q9–Q12).
**Phase 8 đã quyết (`specs/assistant-answering.md`, đã duyệt, S3; ghi 2026-10-14 khi merge Phase 8):** chấp nhận hợp
đồng này với một thay đổi — `Citation.kind` có thêm giá trị `alert` (`id` = khoá alert `RULE|ACCOUNT|TIME`,
`txn_ids = []`, `excerpt = null`); `DRAFT_WATERMARK` của `aml.api.contracts` lấy từ `aml.assistant.narrative`. Phase 8
**chưa** sửa `contracts.py`, `fixtures/assistant.json` hay `web/src/api/types.ts`: việc đó làm cùng bước nối assistant
thật vào API (Phase 9).
- `NodeId` = **khoá tự nhiên, không tiền tố**, trùng `id` của node trong `GET /cases/{id}/graph` của `ui-live-pages`
  và khoá Neo4j: `account_id` hoặc `golden_customer_id` (vd `A01`, `G-C01`).
- `Citation = {n: int >= 1, kind: "node" | "transaction" | "chunk", id: str, label: str, node_ids: [NodeId], txn_ids:
  [str], excerpt: str | null}`. `node`: `id` là `NodeId`, `node_ids = [id]`, `txn_ids = []`. `transaction`: `id` là
  `txn_id`, `txn_ids = [id]` (để hiển thị và để Phase 8 kiểm chứng), `node_ids` **phải chứa sẵn** `account_id` của tài
  khoản nguồn rồi tài khoản đích, chỉ lấy tài khoản nội bộ (có trong bảng `accounts`; bỏ đầu null và tài khoản ngoài),
  và không rỗng. `chunk`: `id` là id chunk, `node_ids = []`, `txn_ids = []`, `excerpt` là đoạn trích. Trong một danh
  sách, `n` là `1..k` tăng dần. Đồ thị của `ui-live-pages` gộp cạnh `transfer` nên **không highlight theo `txn_id`**:
  bấm citation luôn gọi `setHighlight(citation.node_ids)`; `node_ids` rỗng → không highlight.
- `Sentence = {text: str, supported: bool, citations: [int]}`; `supported` đúng ⇒ `citations` khác rỗng; mọi số trong
  `citations` là `n` của một `Citation` cùng response.
- `Answer = {answer_id, case_id, question, language: "vi" | "en", status: "answered" | "insufficient_evidence",
  sentences: [Sentence], citations: [Citation], retrievers: [str], validation: {sentences: int, supported: int,
  unsupported: int}, model: str, prompt_version: str}`; `validation` khớp với `sentences`; `insufficient_evidence` ⇒
  `sentences == []` và `citations == []`.
- **Chat** `POST /api/v1/assistant/chat`, thân `{case_id: str, question: str (1..1000 ký tự sau khi bỏ khoảng trắng),
  language: "vi" | "en" = "vi"}`, khoá lạ → 422. Lỗi trước khi mở luồng (422, 404 `unknown case_id`, 501) là envelope
  lỗi JSON thường. Thành công: `200`, `content-type: text/event-stream`, header `X-AML-Source`, thân là các sự kiện
  `event: <tên>\ndata: <JSON một dòng, UTF-8 không escape>\n\n` theo đúng thứ tự: `meta` `{source, feature}` → `start`
  `{answer_id, case_id, language}` → 0 hoặc nhiều `token` `{text}` → `final` `{answer: Answer}` → `done` `{}`. Lỗi giữa
  luồng: `error` `{code, message}` rồi kết thúc, không có `final`. `final` là bản có hiệu lực; `token` chỉ là văn bản
  tạm chưa kiểm chứng (Q9). Một lượt hỏi, không có lịch sử hội thoại phía server.
- **Draft narrative** `POST /api/v1/cases/{case_id}/narrative`, thân `{language: "vi" | "en" = "vi"}` → envelope JSON,
  `data = {narrative: <7 trường Narrative>, citations: [Citation]}`; `narrative.watermark == DRAFT_WATERMARK` và nằm
  nguyên văn trong `narrative.markdown`; `narrative.citations[i] == citations[i].id` (chuỗi id trần, cùng thứ tự);
  trong markdown, `[n]` trỏ tới `Citation` có `n` đó. Năm khối
  `## Subject`, `## Activity timeline`, `## Matched typologies`, `## Red flags`, `## Suggested next step` (brief).
- **Typology explainer** `GET /api/v1/cases/{case_id}/typologies` → `data = {case_id, typologies: [{typology: str,
  rule_ids: [str], definition: str, transactions: [{txn_id, txn_ts, from_account_id, to_account_id, amount_vnd,
  channel}], chunks: [{chunk_id, title, excerpt}], citations: [Citation]}]}`, sắp theo `typology`; không khớp typology
  nào → `typologies == []`. Không có `memo`, `counterparty_name`.
- **Feedback** `POST /api/v1/assistant/feedback`, thân `{answer_id: str (1..100), rating: "up" | "down", comment: str |
  null (tối đa 1000)}` → `data = {answer_id, rating, recorded: bool}`. Mock: 200, `recorded = false`, không ghi gì.
  Thật: 201, `recorded = true`, đúng 1 dòng `audit_log` có `actor` của request (Q13).
- Tính năng `assistant` **không có** endpoint nào ghi disposition, đổi trạng thái case, clear, close hay file.
- Mock: văn bản trong `fixtures/assistant.json` (hai ngôn ngữ, có chỗ trống `{case_id}`, `{customer}`, `{account}`,
  `{txn}`; danh sách `insufficient_questions`); builder điền ID thật của case: `customer` = `golden_customer_id`,
  `account` = `account_id` nhỏ nhất trong `enrichment.linked_cifs.accounts`, `txn` = `txn_id` nhỏ nhất trong giao dịch
  bằng chứng của các alert `RULE` / `NETWORK` của case (không có → bỏ câu và citation đó), chunk = `MOCK-CHUNK-001`.
    Citation node dùng id trần (`G-C01`, `A01`); `node_ids` của citation giao dịch đọc từ `transactions` + `accounts`.
  - Chat: `answer_id = "mock-" + 12 hex đầu của sha256("{seed}|assistant|{case_id}|{language}|{q}")` với `q` = câu hỏi
    đã gộp khoảng trắng và `casefold()`. `q` thuộc `insufficient_questions` → `insufficient_evidence`, không có
    `token`. Còn lại → 5 câu (4 câu có citation lần lượt tới customer, account, giao dịch, chunk; câu cuối `supported =
    false`); các `token` là từng từ của các câu nối bằng một dấu cách, mỗi từ kèm dấu cách sau trừ từ cuối. Không trễ
    nhân tạo. `retrievers = ["mock"]`, `model = "mock-llm"`, `prompt_version = "mock-prompt/v0"`.
  - Narrative: `generator = "mock-llm"`, `version = "mock-narrative/v0"`. Explainer: một mục cho mỗi `target_typology`
    của các `rule_id` trong alert của case (`aml.monitoring.rules.RULES`, `aml.graph.network.rules.NETWORK_RULES`),
    `transactions` là giao dịch bằng chứng thật của các alert đó, `definition` và `chunks` là văn bản mẫu.

**`metrics_funnel`** (live; `aml.metrics.funnel`):
- `data = {case_run: {run_id, as_of} | null, minutes_per_alert: int, stages: [Stage, Stage], total_hours_saved: float |
  null, conversion: {alert_to_case: {alerts, items, cases, cases_per_alert}, case_to_suspicious: {decided, suspicious,
  false_positive, rate, by_origin: {HUMAN: {decided, suspicious, false_positive}, SIMULATED: {…cùng ba khoá}}}},
  unavailable: [{part, message}]}`.
- `Stage = {tool, before_label, after_label, before, after, removed, reduction_pct, hours_saved}`; `removed = before -
  after`; `reduction_pct = round(100 * removed / before, 2)`; `hours_saved = round(removed * minutes_per_alert / 60,
  1)`; không tính được → cả năm số là null và có một dòng trong `unavailable`.
  - `screening_tuning`: `before` = `flagged` của `fuzzy`, `after` = `flagged` của `two_tier` trong `evaluate(db,
    settings)`; nhãn `fuzzy baseline pairs` / `two-tier ALERT + REVIEW pairs`. `ScreeningError` → không tính được.
  - `consolidation`: `before` = số `item_key` phân biệt có `status = 'ACTIVE'` trong `case_alerts_current`, `after` =
    `case_runs.cases` của lần chạy mới nhất; nhãn `active alerts` / `cases` (Q3). Chưa có lần chạy → không tính được.
- `alert_to_case`: `alerts` (như `before` ở trên), `items` (số dòng `ACTIVE`), `cases`, `cases_per_alert = round(cases /
  alerts, 4)`. `case_to_suspicious`: đếm trên `case_dispositions_current`; `rate = round(suspicious / decided, 4)`, null
  khi `decided == 0`; tách theo `origin` để disposition mô phỏng của 7c không bị đọc thành quyết định của người (Q5).
- Đã đo trên `small`: `screening_tuning` 4436 → 72 (`removed` 4364, 98.38 %, 1091.0 giờ với 15 phút); `consolidation`
  339 → 335 (4, 1.18 %, 1.0 giờ); `alerts` 339, `items` 475, `cases` 335, `cases_per_alert` 0.9882; `decided` 0.

**`metrics_detections`** (live; `aml.metrics.detections`):
- `data = {rows: [Row], unavailable: [{part, message}]}`; `Row = {source: str, detection: str, baseline: bool,
  target_typology: str | null, alerts: int, true_positives: int, false_positives: int, fp_rate: float | null,
  precision: float | null, recall: float | null, scenarios: int | null, detected: int | null}`.
- `RULE` / `NETWORK`: một dòng cho mỗi dòng của `evaluate_rules` / `evaluate_network`, giữ thứ tự; `true_positives =
  target_hits + other_suspicious`, `false_positives = benign + unlabelled`, `precision = precision_suspicious`.
  `SCREENING`: một dòng cho mỗi method của `evaluate` (`alerts = flagged`, `scenarios = tp + fn`, `detected = tp`);
  `baseline` đúng với `exact`, `fuzzy`. `fp_rate = round(false_positives / alerts, 4)`, null khi `alerts == 0` (Q4).
  `NetworkError` / `ScreeningError` → không có dòng của phần đó, có một dòng `unavailable`.
- Đã đo trên `small` (ánh xạ trên áp vào ba evaluator): `RAPID_MOVEMENT` 45 alert, `fp_rate` 0.0222, recall 1.0;
  `DORMANT_REACTIVATION` 137, 0.0073, recall null; `two_tier` 72, 0.6528, recall 1.0; `fuzzy` 4436, 0.9944.

**`metrics_auto_cleared`** (live; `aml.metrics.auto_cleared_sample`; tham số `size` 1..`metrics.max_sample_size`):
- `data = {population: int, ground_truth_available: bool, true_hits_in_population: int | null, seed: int, sample_size:
  int, true_hits_in_sample: int | null, sample: [{cif, entry_id, list_type, final_score, reason, truth: "TRUE_HIT" |
  "NOT_A_HIT" | null}]}`. Quần thể = `screening_current` có `decision = 'AUTO_CLEARED'`, sắp theo (`cif`, `entry_id`);
  mẫu = các dòng ở chỉ số `sorted(numpy.random.default_rng(settings.seed).choice(n, size=min(size, n),
  replace=False))`; `truth` theo `truth_pairs(db)`; `truth_pairs` rỗng → `ground_truth_available = false` và ba trường
  về truth là null. Không có tên khách hàng. Đã đo trên `small`: `population` 6208, `true_hits_in_population` 0.

**`metrics_suppression`** (mock; file tĩnh):
- `data = {case_run: {run_id, as_of}, minutes_per_alert: int, stage: Stage (tool = "suppression"), by_rule: {GOOD_GUY:
  int, HIBERNATION: int}, ground_truth_available: bool, suspicious_suppressed: int | null, sample_size: int, sample:
  [{item_key, source, rule_id, golden_customer_id, suppression_rule, suppression_reason, truth: "SUSPICIOUS" |
  "NOT_SUSPICIOUS" | null}]}`; bất biến: `stage.removed == by_rule.GOOD_GUY + by_rule.HIBERNATION`; công thức `Stage`
  như trên với `minutes_per_alert` của chính response.
- `fixtures/metrics_suppression.json`: `case_run = {run_id: 0, as_of: "2026-06-30"}`, `minutes_per_alert = 15`, `stage =
  {tool: "suppression", before_label: "alert items", after_label: "active alert items", before: 100, after: 88,
  removed: 12, reduction_pct: 12.0, hours_saved: 3.0}`, `by_rule = {GOOD_GUY: 10, HIBERNATION: 2}`,
  `ground_truth_available = true`, `suspicious_suppressed = 0`, `sample_size = 2`, `sample` = hai dòng có `item_key`
  `SCREENING|MOCK-CIF-001|MOCK-WL-001` (`GOOD_GUY`) và `HIGH_VELOCITY|MOCK-ACC-001|2026-01-01T00:00:00`
  (`HIBERNATION`), `golden_customer_id` `MOCK-G-001` / `MOCK-G-002`, `suppression_reason` bắt đầu bằng `[SAMPLE]`,
  `truth = "NOT_SUSPICIOUS"`.

### Tiêu chí đã nối thật
Thủ tục chung cho mọi tính năng mock, làm trong **một commit** của phase nguồn: (1) gán hàm thật vào tên tương ứng trong
`src/aml/api/live.py`; (2) đổi `ui.mock.<feature>` thành `false` trong `config.yaml` và dòng tương ứng của AC1; (3) thêm
test `tests/api/test_live_<feature>.py` chạy **cùng** `contracts.check` trên response thật; (4) AC2–AC6, AC9 của spec
này vẫn xanh nguyên văn (chúng đặt cờ tường minh qua `environ`). Không file nào trong `web/`, `routers/`, `contracts.py`
đổi; nếu phải đổi thì hợp đồng đã lệch và spec này phải được sửa + duyệt lại.

| feature | phải xong | hàm thật (`live.<tên>`) | test hợp đồng trên response thật |
|---|---|---|---|
| `case_scores` | `specs/case-prioritization.md` AC1–AC8 xanh | đọc `case_scores_current` nối `case_runs` (SQL trong `sql/common/api/`), `top_features` parse từ JSON | trên TINY-L đã `train` + `score`: `check("case_scores", data) == []`; 52 phần tử, `queue == 14`; mọi `model_version` khớp `^prio/(logreg|lightgbm)/\d+$`; mọi `feature` thuộc `FEATURES`; từng phần tử bằng `load_case(db, case_id).score` cộng `case_id`; không chuỗi `mock-` trong response |
| `case_summary` | `specs/case-summary.md` AC1–AC5 xanh | `dataclasses.asdict(summarize(db, settings, case_id, language=language))`; `CaseError` → 404, `NarrativeError` về ngôn ngữ / tên bộ sinh → 422 | trên MINI-N: `check("case_summary", data) == []`; `data.markdown == summarize(...).markdown`; `data.watermark == TEMPLATE_WATERMARK`; `audit_log` không thêm dòng |
| `assistant` | spec Phase 8 được duyệt và đã chấp nhận / sửa hợp đồng này; Phase 8 xong | bốn hàm của `aml.assistant`; chat là generator phát (`start`, `token`, `final`); narrative đi qua `NarrativeGenerator` đã `register_generator("llm", …)` | với một LLM giả sau interface của Phase 8 (không cần Ollama): `check_chat_events(events) == []`, `check("assistant_narrative" / "assistant_explainer" / "assistant_feedback", data) == []`; mọi `node_ids` / `txn_ids` được trích tồn tại trong database; `narrative.watermark == DRAFT_WATERMARK`; mỗi câu hỏi và mỗi feedback thêm dòng `audit_log` `module='assistant'` có `actor` của request; số dòng `case_dispositions` không đổi |
| `metrics_suppression` | `specs/case-suppression.md` AC1–AC8 xanh và đã commit | `aml.metrics.suppression(db, settings)`: `case_runs.items` / `active` / `suppressed`, `case_alerts_current` theo `suppression_rule`; `truth` của item theo luật nhãn item của 7c (`SCREENING`: cặp thuộc `truth_pairs`; `RULE` / `NETWORK`: tài khoản của golden customer nằm trong kịch bản `is_suspicious`) | trên MINI-S sau run 2 của AC3 (7b-supp): `check("metrics_suppression", data) == []`; `stage.before == 11`, `stage.after == 10`, `by_rule == {"GOOD_GUY": 1, "HIBERNATION": 0}`; `sample[0].item_key == "SCREENING|C05|WL2"` |

### Yêu cầu giao diện (kiểm tay)
Không phải AC. Người dùng tự kiểm khi demo; mọi panel lấy dữ liệu qua `ApiPanel` (JSON) hoặc `apiStream` + `SourceBadge`
(SSE) của `ui-foundation`, trang không tự vẽ nhãn và không tự gọi `fetch`.
- M0. Vị trí: trên `/cases/:caseId` nội dung của spec này chỉ nằm trong ba slot của `ui-live-pages` (U9) —
  `slot-case-score` (điểm, hạng, `model_version`, bảng `top_features` của case này, lấy từ `GET /cases/scores` theo
  `case_id`; case chưa có điểm hiện `—`), `slot-case-summary` (M2), `slot-assistant` (M3–M5).
- M1. `/cases`: bảng có thêm cột `Điểm ưu tiên`, `Hạng`, `Model`, `Yếu tố chính` (feature đầu của `top_features`), ghép
  từ `GET /cases/scores` theo `case_id`. Có điểm → bảng sắp theo `queue_rank` tăng, case không có hạng ở cuối theo thứ
  tự của `ui-foundation`; trang nạp hết các trang của `GET /cases` rồi sắp phía client (Q7). Tiêu đề cột điểm mang
  nhãn `Dữ liệu mẫu` khi nguồn là mock. Không có nút đóng / clear nào dựa trên điểm.
- M2. `slot-case-summary`: markdown render qua `Markdown.tsx` (bảng GFM hiển thị thành bảng; HTML thô, ảnh và
  liên kết không thành phần tử HTML; Q14); dưới panel có dòng `generator` + `version`.
- M3. `slot-assistant`, chat: câu hỏi → văn bản tạm hiện dần (kiểu chữ mờ, ghi `đang kiểm chứng`) → khi có `final` thay
  bằng các câu; câu `supported = false` có nền cảnh báo và chữ `Chưa có bằng chứng`; `insufficient_evidence` hiện đúng
  chữ `Không đủ bằng chứng`; số citation `[n]` bấm được: `node` / `transaction` gọi
  `useCaseHighlight().setHighlight(citation.node_ids)` (thay tập đang highlight; id không có trong đồ thị do trang
  graph liệt kê ở `graph-highlight-missing`), citation giao dịch hiện thêm `txn_ids` dạng chữ; `chunk` mở đoạn trích và
  không gọi highlight. Có nút `Bỏ highlight` gọi `clearHighlight()`. Nút feedback 👍 / 👎; khi `recorded = false` hiện
  `Phản hồi không được lưu ở chế độ mẫu`.
- M4. `slot-assistant`, draft narrative: dải chữ cố định `DRAFT — requires investigator review` do giao diện tự vẽ phía
  trên markdown (không phụ thuộc nội dung markdown), cộng nhãn `Dữ liệu mẫu` khi mock. Typology explainer: mỗi typology
  một khối có định nghĩa, bảng giao dịch, đoạn trích, nút `Highlight` gọi `setHighlight` với hợp các `node_ids` của mọi
  citation trong khối.
- M5. `slot-assistant` không có nút `Close`, `Clear`, `File STR`, `Đóng case`, `Áp dụng`; form disposition (của
  `ui-live-pages`) nằm ngoài slot này và không tự điền từ câu trả lời.
- M6. `/metrics`: bốn panel độc lập — funnel (hai stage, chuyển đổi, dòng `Giả định: {minutes_per_alert} phút / alert`
  hiển thị cạnh mọi số giờ, chữ `ước tính`), detections (bảng; dòng `baseline` tách riêng; null hiện `—`), below-the-line
  auto-cleared (đếm quần thể + bảng mẫu + `seed`), suppression (stage, theo rule, mẫu). Không cộng số giữa hai panel.
- M7. Với mọi panel: `ui.mock.<feature>: false` khi chưa có bản thật (501) → panel hiện `Chưa có dữ liệu` kèm
  `not_implemented` (trạng thái lỗi của `ApiPanel` nền móng) và **không hiện số nào**, không hiện nhãn `Dữ liệu mẫu`. Mỗi response mock → đúng panel đó có nhãn `Dữ liệu mẫu`.
- M8. `npm --prefix web run build` pass (kiểu của `web/src/api/types.ts` khớp hợp đồng trên).

**Dùng của `ui-live-pages` (spec đó sở hữu, spec này chỉ gọi)**: ba slot `slot-case-score`, `slot-case-summary`,
`slot-assistant` (U9); `useCaseHighlight(): { highlightIds, setHighlight(ids: string[]), clearHighlight() }` từ
`web/src/pages/caseHighlight.ts` (U11, Q8) với id là khoá tự nhiên. Spec này không định nghĩa lại và không thêm yêu cầu
nào lên hợp đồng đó. `Narrative.citations` của bản summary template (7d) là `item_key` của alert, không phải id node:
panel summary **không** gọi highlight (Ngoài phạm vi).

## Tiêu chí nghiệm thu
<!-- `settings`, `client(user=None, **env)`, SCHEMA, API-MINI như specs/ui-foundation.md (API-MINI = MINI-C + `run_cases`,
run 1, 5 case). MINI-GT = MINI-C + 5 dòng ground_truth của specs/case-prioritization.md, rồi `run_cases`.
ON = mọi cờ `ui.mock.*` đặt `true` tường minh qua environ; OFF(f) = như ON nhưng `AML__UI__MOCK__<F>=false`.
ROWS(db) = tổng số dòng của mọi bảng thường (không tính view) trong `information_schema.tables`.
C1 = `C-C01-20260302`, C5 = `C-C05-20260630`. `events(resp)` = `aml.api.sse.parse(resp.text)`.
Mọi AC là pytest (`tests/api/`, `tests/metrics/`), DuckDB-only, không cần Node / Ollama / Neo4j / Oracle.
Đã đo bằng prototype ngoài repo: điểm mẫu của 5 case (seed 42 và 7), ba `answer_id`, mọi số của MINI-GT trong AC7–AC9,
`alert_evidence` của MINI-C. Còn lại suy ra từ thiết kế, chưa đo (chưa có `src/aml/api/`). -->
- AC1: Given `config.yaml` của repo, SCHEMA và `client()`, When gọi `load_settings(environ={})`, `GET /api/v1/status` và duyệt `app.routes`, Then `settings.ui.mock` có đúng năm trường `sample`, `case_scores`, `case_summary`, `assistant`, `metrics_suppression` và cả năm là `True`; `set(MockConfig.model_fields) == set(mock.features())`; `settings.metrics.minutes_per_alert == 15`, `settings.metrics.sample_size == 20`, `settings.metrics.max_sample_size == 200`; `AML__METRICS__MINUTES_PER_ALERT=0` raise `pydantic.ValidationError` chứa `metrics minutes_per_alert must be >= 1`; `AML__METRICS__SAMPLE_SIZE=201` raise `ValidationError` chứa `metrics sample_size must be between 1 and max_sample_size`; `AML__UI__MOCK__ASSISTANT=maybe` raise `ValidationError`; `GET /api/v1/status` trả `data.mock == {"sample": true, "case_scores": true, "case_summary": true, "assistant": true, "metrics_suppression": true}`; tập (method, đường dẫn) của app chứa đúng mười route của bảng tính năng; trong các route `GET` dưới `/api/v1` không có tham số đường dẫn, mọi route trả 200 có header `X-AML-Source` bằng `source` của thân, và tập đường dẫn có `source == "mock"` bằng đúng `{"/api/v1/sample", "/api/v1/cases/scores", "/api/v1/metrics/suppression"}`; ba đường dẫn `/api/v1/metrics/funnel`, `/api/v1/metrics/detections`, `/api/v1/metrics/below-the-line/auto-cleared` trả `source == "live"` và `"mock" not in meta`; khi cả năm cờ đặt `false` thì không response nào có `source == "mock"` và `GET /api/v1/cases/scores`, `GET /api/v1/metrics/suppression` trả 501; lệnh `aml ui --api-only` (với `uvicorn.run` được monkeypatch) in một dòng chứa `mock=assistant,case_scores,case_summary,metrics_suppression,sample`, còn với `AML__UI__MOCK__SAMPLE=false` dòng đó chứa `mock=assistant,case_scores,case_summary,metrics_suppression` và không chứa `none`; và mọi tên trong `aml.api.live` (`case_scores`, `case_summary`, `assistant_chat`, `assistant_narrative`, `assistant_explainer`, `assistant_feedback`, `metrics_suppression`) là `None`.
- AC2: Given API-MINI và `client(**ON)`, When gọi `GET /api/v1/cases/scores` hai lần, Then cả hai trả 200 với thân giống hệt từng byte, `source == "mock"`, `feature == "case_scores"`, header `X-AML-Source == "mock"`, `meta.mock == {"fixture": "builder:build_case_scores", "notice": "Sample data - not a measured result"}`; `data.run_id == 1`, `data.score_run_id == 0`, `data.model_version == "mock-prio/logreg/0"`, `data.queue == 5`; `data.scores` có 5 phần tử theo đúng thứ tự (`case_id`, `score`, `queue_rank`) = (`C-C03-20260305`, 0.907756, 1), (`C-C04-20260305`, 0.890333, 2), (`C-C01-20260531`, 0.731282, 3), (`C-C05-20260630`, 0.545496, 4), (`C-C01-20260302`, 0.52796, 5); mỗi phần tử có đúng năm khoá `case_id`, `score`, `queue_rank`, `model_version`, `top_features`, có `model_version == "mock-prio/logreg/0"` và `top_features` bằng đúng `[{"feature": "network_alerts", "value": 1.0, "contribution": 1.5}, {"feature": "alerts", "value": 1.0, "contribution": 1.0}, {"feature": "max_screening_score", "value": 0.0, "contribution": -0.75}, {"feature": "cash_share", "value": 0.0, "contribution": -0.5}, {"feature": "kyc_risk_level", "value": 0.0, "contribution": 0.25}]`; tập `case_id` bằng tập `case_id` của `GET /api/v1/cases`; `contracts.check("case_scores", data) == []`; `ROWS(duck)` trước và sau hai lần gọi bằng nhau; với `load_settings(environ={"DB_BACKEND": "duckdb", "AML__SEED": "7", **ON})` thì `C-C01-20260531` có `score == 0.833908` và `queue_rank == 1`, còn `C-C03-20260305` có `score == 0.077824` và `queue_rank == 5`; sau `record_disposition(duck, settings, "C-C03-20260305", "SUSPICIOUS", reason="x", actor="analyst01")` và `run_cases` (run 2) thì `data.run_id == 2`, `data.queue == 4`, phần tử `C-C03-20260305` có `queue_rank is None` và đứng cuối, `C-C04-20260305` có `queue_rank == 1`; Given SCHEMA (chưa có lần chạy case), Then trả 200 với `data == {"run_id": null, "score_run_id": null, "model_version": null, "queue": 0, "scores": []}` và `source == "mock"`; và với `client(**OFF("case_scores"))` trả 501 có thân bằng đúng `{"error": {"code": "not_implemented", "message": "feature 'case_scores' has no live implementation and ui.mock.case_scores is off"}}`, không có header `X-AML-Source`, và thân không chứa `mock-` hay `0.907756`.
- AC3: Given API-MINI và `client(**ON)`, When gọi `GET /api/v1/cases/C-C01-20260302/summary`, Then trả 200 với `source == "mock"`, `feature == "case_summary"`, header `X-AML-Source == "mock"`, `meta.pii == "masked"`, `meta.mock.fixture == "builder:build_case_summary"`; `data` có đúng bảy khoá `case_id`, `markdown`, `generator`, `version`, `language`, `watermark`, `citations` với `case_id == "C-C01-20260302"`, `generator == "mock"`, `version == "mock-summary/v0"`, `language == "en"`, `citations == []`, `watermark` bằng đúng `SAMPLE SUMMARY (mock-summary/v0): placeholder text, not generated from case data.`; `data.markdown` bắt đầu bằng đúng `# Case C-C01-20260302\n\n> SAMPLE SUMMARY (mock-summary/v0): placeholder text, not generated from case data.\n`; các dòng bắt đầu bằng `## ` của markdown theo thứ tự là đúng `## Subject`, `## Alerts`, `## Priority factors`, `## Activity`, `## Network`, `## Data quality`, `## History`; markdown chứa đúng dòng `[SAMPLE] Placeholder text for section Subject.` và một dòng bắt đầu bằng `|---`; thân response không chứa `Nguyen`, `G-C01`, `B1234561` hay `TEMPLATE SUMMARY`; `contracts.check("case_summary", data) == []`; hai lần gọi cho thân giống hệt từng byte; `client(user="supervisor01", **ON)` trả cùng `data`, `meta.pii == "masked"` và `audit_log` không thêm dòng nào; `?language=en` cho cùng `data`; `?language=vi` trả 422 với `error.code == "invalid_request"` và `error.message` chứa `language 'vi' is not available`; `GET /api/v1/cases/C-NOPE-20260101/summary` trả 404 với `error.code == "not_found"` và `error.message` chứa `unknown case_id`; `ROWS(duck)` trước và sau mọi lời gọi trên bằng nhau; và với `client(**OFF("case_summary"))` thì `GET /api/v1/cases/C-C01-20260302/summary` trả 501 có `error.message` bằng đúng `feature 'case_summary' has no live implementation and ui.mock.case_summary is off` và thân không chứa `SAMPLE`.
- AC4: Given API-MINI và `client(**ON)`, When gọi `POST /api/v1/assistant/chat` với thân `{"case_id": "C-C01-20260302", "question": "  Tài khoản nào   nhận tiền? "}` hai lần, Then cả hai trả 200 với `content-type` bắt đầu bằng `text/event-stream`, header `X-AML-Source == "mock"` và thân giống hệt từng byte; `events(resp)` có đúng 56 phần tử với tên theo thứ tự `meta`, `start`, 52 lần `token`, `final`, `done`; sự kiện đầu có dữ liệu bằng đúng `{"source": "mock", "feature": "assistant"}`; `start` bằng đúng `{"answer_id": "mock-e6ca683c4f7b", "case_id": "C-C01-20260302", "language": "vi"}`; `done` bằng `{}`; `answer = final["answer"]` có `status == "answered"`, `question == "Tài khoản nào   nhận tiền?"`, `language == "vi"`, `retrievers == ["mock"]`, `model == "mock-llm"`, `prompt_version == "mock-prompt/v0"`, `validation == {"sentences": 5, "supported": 4, "unsupported": 1}`; `answer.sentences[0]` bằng đúng `{"text": "[MẪU] Khách hàng G-C01 là chủ thể của case C-C01-20260302.", "supported": true, "citations": [1]}`, ba câu kế có `citations` lần lượt `[2]`, `[3]`, `[4]` và `supported` đúng, câu thứ năm có `supported == false` và `citations == []`, và cả năm `text` bắt đầu bằng `[MẪU]`; `answer.citations` bằng đúng `[{"n": 1, "kind": "node", "id": "G-C01", "label": "G-C01", "node_ids": ["G-C01"], "txn_ids": [], "excerpt": null}, {"n": 2, "kind": "node", "id": "A01", "label": "A01", "node_ids": ["A01"], "txn_ids": [], "excerpt": null}, {"n": 3, "kind": "transaction", "id": "T01", "label": "T01", "node_ids": ["A01"], "txn_ids": ["T01"], "excerpt": null}, {"n": 4, "kind": "chunk", "id": "MOCK-CHUNK-001", "label": "MOCK-SOP-001", "node_ids": [], "txn_ids": [], "excerpt": "[MẪU] Đoạn trích mẫu của một tài liệu quy trình."}]`; citation giao dịch có `node_ids` khác rỗng, citation chunk có `node_ids == []`, không `node_ids` nào chứa dấu `:`, và mọi phần tử của mọi `node_ids` hoặc là `golden_customer_id` của case hoặc là một `account_id` có trong bảng `accounts`; chuỗi nối `text` của 52 sự kiện `token` bằng đúng `" ".join(s["text"] for s in answer["sentences"])`; `contracts.check_chat_events(events(resp)) == []`; thân `{"case_id": "C-C05-20260630", "question": "Tài khoản nào nhận tiền?"}` cho `start.answer_id == "mock-a1f21a5eb08a"`, 4 câu, `validation == {"sentences": 4, "supported": 3, "unsupported": 1}` và `[c["id"] for c in answer["citations"]] == ["G-C05", "A05", "MOCK-CHUNK-001"]`; thân `{"case_id": "C-C01-20260302", "question": "Ai là người hưởng lợi cuối cùng?"}` cho đúng 4 sự kiện `meta`, `start`, `final`, `done` với `start.answer_id == "mock-010b5c5a2743"`, `answer.status == "insufficient_evidence"`, `answer.sentences == []`, `answer.citations == []`, `answer.validation == {"sentences": 0, "supported": 0, "unsupported": 0}`; `"language": "en"` cho các câu bắt đầu bằng `[SAMPLE]` và một `answer_id` khác; mỗi thân sau đây trả đúng mã nêu ra dưới dạng envelope lỗi JSON (không phải luồng sự kiện): `"question": "   "` → 422, thiếu `question` → 422, `question` dài 1001 ký tự → 422, `"language": "fr"` → 422, thêm khoá `"actor": "boss"` → 422, `"case_id": "C-NOPE-20260101"` → 404 có `error.message` chứa `unknown case_id`; `ROWS(duck)` trước và sau mọi lời gọi trên bằng nhau; và với `client(**OFF("assistant"))` cùng thân hợp lệ trả 501 có `content-type` bắt đầu bằng `application/json`, `error.code == "not_implemented"`, không có header `X-AML-Source` và thân không chứa `event:` hay `MẪU`.
- AC5: Given API-MINI và `client(**ON)`, When gọi `POST /api/v1/cases/C-C01-20260302/narrative` với thân `{}`, `GET /api/v1/cases/C-C01-20260302/typologies` và `POST /api/v1/assistant/feedback`, Then narrative trả 200 với `source == "mock"`, `feature == "assistant"`, header `X-AML-Source == "mock"`, `meta.mock.fixture == "assistant.json"`, `data` có đúng hai khoá `narrative`, `citations`; `data.narrative` có đúng bảy khoá của `Narrative` với `case_id == "C-C01-20260302"`, `generator == "mock-llm"`, `version == "mock-narrative/v0"`, `language == "vi"`, `watermark == "DRAFT — requires investigator review"` (bằng `contracts.DRAFT_WATERMARK`), `citations == ["G-C01", "A01", "T01", "MOCK-CHUNK-001"]` (bằng `[c["id"] for c in data["citations"]]`); `data.narrative.markdown` chứa đúng dòng `> DRAFT — requires investigator review`, các dòng bắt đầu bằng `## ` theo thứ tự là đúng `## Subject`, `## Activity timeline`, `## Matched typologies`, `## Red flags`, `## Suggested next step`, chứa các chuỗi `[1]`, `[2]`, `[3]`, `[4]` và không chứa `Nguyen`; `data.citations` bằng đúng `answer.citations` của câu trả lời đầu ở AC4; `contracts.check("assistant_narrative", data) == []`; narrative của `C-C05-20260630` có `narrative.citations == ["G-C05", "A05", "MOCK-CHUNK-001"]`; thân `{"language": "fr"}` → 422, thân `{"disposition": "SUSPICIOUS"}` → 422, case `C-NOPE-20260101` → 404; typologies của `C-C01-20260302` trả 200 với `source == "mock"`, `data.case_id == "C-C01-20260302"`, `[t["typology"] for t in data["typologies"]] == ["rapid_movement", "round_tripping", "structuring"]`, `rule_ids` lần lượt `["RAPID_MOVEMENT"]`, `["NET_CYCLE"]`, `["STRUCTURING"]`, `[x["txn_id"] for x in transactions]` lần lượt `["T05", "T06"]`, `["T02", "T03", "T04"]`, `["T01"]`; dòng giao dịch `T01` bằng đúng `{"txn_id": "T01", "txn_ts": "2026-03-02T09:00:00", "from_account_id": null, "to_account_id": "A01", "amount_vnd": 390000000, "channel": "CASH"}`; mục `round_tripping` có `citations` gồm ba citation `transaction` (`T02`, `T03`, `T04`; citation `T02` có `node_ids == ["A01", "A03"]` và `txn_ids == ["T02"]`) rồi một citation `chunk` `MOCK-CHUNK-001` có `node_ids == []`, mục `rapid_movement` có citation `T05` (từ `EXT-01` tới `A02`) với `node_ids == ["A02"]` và citation `T06` (từ `A02` tới `EXT-02`) với `node_ids == ["A02"]`, và `definition` bắt đầu bằng `[MẪU]`; `contracts.check("assistant_explainer", data) == []`; typologies của `C-C05-20260630` trả `data.typologies == []`; typologies của `C-NOPE-20260101` trả 404; feedback với thân `{"answer_id": "mock-e6ca683c4f7b", "rating": "up", "comment": null}` trả 200 với `source == "mock"` và `data` bằng đúng `{"answer_id": "mock-e6ca683c4f7b", "rating": "up", "recorded": false}`; feedback với `"rating": "meh"` → 422, thiếu `answer_id` → 422, thêm khoá `"actor": "boss"` → 422; `ROWS(duck)` và số dòng `audit_log` trước và sau mọi lời gọi trên bằng nhau; và với `client(**OFF("assistant"))` cả ba endpoint trả 501 có `error.message` bằng đúng `feature 'assistant' has no live implementation and ui.mock.assistant is off`.
- AC6: Given module thuần `aml.api.contracts`, các `data` mẫu của AC2–AC5 và AC9, và các hàm thật giả lập gắn vào `aml.api.live` bằng monkeypatch, When gọi `contracts.check`, `contracts.check_chat_events` và các endpoint với cờ tắt, Then `set(contracts.CONTRACTS)` bằng đúng `{"case_scores", "case_summary", "assistant_answer", "assistant_narrative", "assistant_explainer", "assistant_feedback", "metrics_suppression", "metrics_funnel", "metrics_detections", "metrics_auto_cleared"}`; `check` trả `[]` cho từng `data` mẫu với contract tương ứng và cho `data` của ba endpoint metrics live trên MINI-GT; `check("nope", {})` raise `ValueError` chứa `unknown contract 'nope'`; với `data` của AC2: xoá khoá `queue_rank` của một phần tử cho danh sách có một chuỗi chứa `queue_rank`, thêm khoá `priority` cho một chuỗi chứa `priority`, đặt `score = 1.5` cho một chuỗi chứa `score`, đổi chỗ hai phần tử đầu cho một chuỗi chứa `queue_rank`, đặt hai `contribution` đầu thành `0.1`, `0.9` cho một chuỗi chứa `contribution`; với `data` của AC3: đặt `watermark = "X"` cho một chuỗi chứa `watermark`, đặt `markdown = ""` cho một chuỗi chứa `markdown`; với `answer` của AC4: đặt `sentences[0].citations = []` cho một chuỗi chứa `supported`, đặt `sentences[0].citations = [9]` cho một chuỗi chứa `citations`, đặt `status = "cleared"` cho một chuỗi chứa `status`, đặt `validation.supported = 5` cho một chuỗi chứa `validation`, đặt `citations[2].kind = "url"` cho một chuỗi chứa `kind`, đặt `citations[2].node_ids = []` (citation giao dịch) cho một chuỗi chứa `node_ids`, đặt `citations[3].node_ids = ["A01"]` (citation chunk) cho một chuỗi chứa `node_ids`; với `data` narrative của AC5: đặt `narrative.watermark = "DRAFT"` cho một chuỗi chứa `watermark`, bỏ phần tử cuối của `narrative.citations` cho một chuỗi chứa `citations`; với các sự kiện của AC4: bỏ sự kiện `meta` cho một chuỗi chứa `meta`, bỏ `final` cho một chuỗi chứa `final`, đặt một `token` sau `final` cho một chuỗi chứa `token`, còn dãy `meta`, `start`, `error`, không có `final` thì trả `[]`; mã nguồn của `aml.api.contracts` không chứa `Database`, `Settings` hay `mock-`; Given `live.case_scores = lambda db, settings: STUB` với `STUB = {"run_id": 1, "score_run_id": 3, "model_version": "prio/logreg/1", "queue": 1, "scores": [{"case_id": "C-C01-20260302", "score": 0.9, "queue_rank": 1, "model_version": "prio/logreg/1", "top_features": []}]}` và `client(**OFF("case_scores"))`, Then `GET /api/v1/cases/scores` trả 200 với `source == "live"`, header `X-AML-Source == "live"`, `data == STUB`, `"mock" not in meta` và `check("case_scores", data) == []`, còn với `client(**ON)` cùng monkeypatch vẫn trả `source == "mock"` và hàm giả lập không bị gọi; Given `live.assistant_chat` là generator phát lần lượt (`start`, `{"answer_id": "a-1", "case_id": "C-C01-20260302", "language": "vi"}`), (`final`, `{"answer": A}`) với `A` là `answer` của AC4 đã đổi `answer_id` thành `a-1`, và `client(**OFF("assistant"))`, Then `POST /api/v1/assistant/chat` trả luồng có đúng 4 sự kiện `meta`, `start`, `final`, `done`, sự kiện đầu bằng `{"source": "live", "feature": "assistant"}`, header `X-AML-Source == "live"` và `check_chat_events` trả `[]`, trong khi `POST /api/v1/cases/C-C01-20260302/narrative` trên cùng client vẫn trả 501 (hàm của nó còn `None`); và Given `live.case_summary` raise `CaseError("unknown case_id C-NOPE-20260101")` với `client(**OFF("case_summary"))`, Then `GET /api/v1/cases/C-NOPE-20260101/summary` trả 404 với `error.code == "not_found"`.
- AC7: Given MINI-GT và `client(**ON)`, When gọi `GET /api/v1/metrics/funnel` và `aml.metrics.funnel(duck, settings)`, Then response trả 200 với `source == "live"`, `feature == "metrics_funnel"`, header `X-AML-Source == "live"`, `"mock" not in meta` và `data` bằng đúng kết quả của hàm; `data.case_run == {"run_id": 1, "as_of": "2026-06-30"}`; `data.minutes_per_alert == 15`; `data.stages` có đúng hai phần tử theo thứ tự `tool` `screening_tuning`, `consolidation`; stage `consolidation` bằng đúng `{"tool": "consolidation", "before_label": "active alerts", "after_label": "cases", "before": 7, "after": 5, "removed": 2, "reduction_pct": 28.57, "hours_saved": 0.5}`; stage `screening_tuning` có `before`, `after`, `removed`, `reduction_pct`, `hours_saved` đều null và `data.unavailable` bằng đúng `[{"part": "screening_tuning", "message": "watchlist is empty; run `aml load` first"}]`; `data.total_hours_saved == 0.5`; `data.conversion.alert_to_case == {"alerts": 7, "items": 9, "cases": 5, "cases_per_alert": 0.7143}`; `data.conversion.case_to_suspicious == {"decided": 0, "suspicious": 0, "false_positive": 0, "rate": null, "by_origin": {"HUMAN": {"decided": 0, "suspicious": 0, "false_positive": 0}, "SIMULATED": {"decided": 0, "suspicious": 0, "false_positive": 0}}}`; với `AML__METRICS__MINUTES_PER_ALERT=30` thì `data.minutes_per_alert == 30` và stage `consolidation` có `hours_saved == 1.0`; sau `POST /api/v1/cases/C-C05-20260630/disposition` với thân `{"disposition": "FALSE_POSITIVE", "reason": "name only match"}` bởi `analyst01` và `record_disposition(duck, settings, "C-C03-20260305", "SUSPICIOUS", reason="sim", actor="simulated_analyst", origin="SIMULATED")` thì `case_to_suspicious` có `decided == 2`, `suspicious == 1`, `false_positive == 1`, `rate == 0.5`, `by_origin.HUMAN == {"decided": 1, "suspicious": 0, "false_positive": 1}` và `by_origin.SIMULATED == {"decided": 1, "suspicious": 1, "false_positive": 0}`; `contracts.check("metrics_funnel", data) == []`; `ROWS(duck)` trước và sau các lời gọi `GET` bằng nhau; Given SCHEMA, Then `GET /api/v1/metrics/funnel` trả 200 với `data.case_run is None`, cả hai stage có năm số null, `data.total_hours_saved is None`, `alert_to_case == {"alerts": null, "items": null, "cases": null, "cases_per_alert": null}` và `[u["part"] for u in data["unavailable"]] == ["screening_tuning", "consolidation"]`; và Given `evaluate` được monkeypatch trả bảng của `results/phase3/screening_eval.csv`, Then stage `screening_tuning` bằng đúng `{"tool": "screening_tuning", "before_label": "fuzzy baseline pairs", "after_label": "two-tier ALERT + REVIEW pairs", "before": 4436, "after": 72, "removed": 4364, "reduction_pct": 98.38, "hours_saved": 1091.0}`.
- AC8: Given MINI-GT và `client(**ON)`, When gọi `GET /api/v1/metrics/detections`, Then trả 200 với `source == "live"`, `feature == "metrics_detections"`, `data` bằng đúng `aml.metrics.detections(duck, settings)`; `data.rows` có đúng 9 phần tử với (`source`, `detection`) theo thứ tự (`RULE`, `STRUCTURING`), (`RULE`, `RAPID_MOVEMENT`), (`RULE`, `HIGH_VELOCITY`), (`RULE`, `FAN_IN`), (`RULE`, `FAN_OUT`), (`RULE`, `DORMANT_REACTIVATION`), (`NETWORK`, `NET_SHARED_ATTRIBUTE`), (`NETWORK`, `NET_CYCLE`), (`NETWORK`, `NET_HUB`); dòng `STRUCTURING` bằng đúng `{"source": "RULE", "detection": "STRUCTURING", "baseline": false, "target_typology": "structuring", "alerts": 1, "true_positives": 1, "false_positives": 0, "fp_rate": 0.0, "precision": 1.0, "recall": 1.0, "scenarios": 1, "detected": 1}`; dòng `RAPID_MOVEMENT` có `alerts == 1`, `true_positives == 0`, `false_positives == 1`, `fp_rate == 1.0`, `precision == 0.0`, `recall is None`, `scenarios == 0`; dòng `HIGH_VELOCITY` có `alerts == 0`, `fp_rate is None`, `precision is None`, `recall is None`, `scenarios is None`, `target_typology is None`; dòng `DORMANT_REACTIVATION` có `true_positives == 1`, `fp_rate == 0.0`, `recall is None`; dòng `NET_CYCLE` có `alerts == 1`, `true_positives == 0`, `false_positives == 1`, `fp_rate == 1.0`, `recall == 0.0`, `scenarios == 1`, `detected == 0`; `data.unavailable` bằng đúng `[{"part": "screening", "message": "watchlist is empty; run `aml load` first"}]`; `contracts.check("metrics_detections", data) == []`; Given `evaluate` được monkeypatch trả bảng của `results/phase3/screening_eval.csv`, Then `data.rows` có 13 phần tử, bốn phần tử cuối có `source == "SCREENING"` và `detection` lần lượt `exact`, `fuzzy`, `two_tier_alert`, `two_tier`, dòng `fuzzy` bằng đúng `{"source": "SCREENING", "detection": "fuzzy", "baseline": true, "target_typology": null, "alerts": 4436, "true_positives": 25, "false_positives": 4411, "fp_rate": 0.9944, "precision": 0.0056, "recall": 1.0, "scenarios": 25, "detected": 25}`, dòng `two_tier` có `baseline == false`, `alerts == 72`, `false_positives == 47`, `fp_rate == 0.6528`, `recall == 1.0`, và `data.unavailable == []`; Given SCHEMA (chưa có lần chạy network), Then trả 200 với 6 dòng `RULE` có `alerts == 0` và `[u["part"] for u in data["unavailable"]] == ["network", "screening"]`; và Given `tiny_cases` của `tests/cases/`, Then với mỗi dòng `r` của `evaluate_rules(db)` dòng `RULE` cùng `rule_id` có `alerts == r.alerts` và `false_positives == r.benign + r.unlabelled`, bốn dòng `SCREENING` có `alerts` bằng cột `flagged` của `evaluate(db, settings)`, và `data.unavailable == []`.
- AC9: Given MINI-GT và `client(**ON)`, When gọi `GET /api/v1/metrics/below-the-line/auto-cleared` và `GET /api/v1/metrics/suppression`, Then auto-cleared trả 200 với `source == "live"`, `feature == "metrics_auto_cleared"` và `data` bằng đúng `{"population": 1, "ground_truth_available": true, "true_hits_in_population": 0, "seed": 42, "sample_size": 1, "true_hits_in_sample": 0, "sample": [{"cif": "C06", "entry_id": "WL3", "list_type": "PEP", "final_score": 60.0, "reason": "test reason", "truth": "NOT_A_HIT"}]}`; thân response không chứa `Nguyen`; `?size=0` và `?size=201` trả 422 với `error.code == "invalid_request"`; sau khi thêm hai dòng `ground_truth` (`GT-PEP-0001`, `pep_hit`, đúng, `customer`, `C06`) và (`GT-PEP-0001`, `pep_hit`, đúng, `watchlist_entry`, `WL3`) thì `true_hits_in_population == 1`, `true_hits_in_sample == 1` và `sample[0].truth == "TRUE_HIT"`; trên API-MINI (bảng `ground_truth` rỗng) thì `ground_truth_available == false`, `true_hits_in_population is None`, `true_hits_in_sample is None` và `sample[0].truth is None`; Given 30 dòng `AUTO_CLEARED` thêm vào `screening_results` cho các `cif` `X01`..`X30` với `entry_id` `WL9`, Then `?size=5` trả `population == 31`, `sample_size == 5`, 5 dòng có (`cif`, `entry_id`) tăng dần bằng đúng các dòng ở chỉ số `sorted(numpy.random.default_rng(42).choice(31, size=5, replace=False))` của quần thể đã sắp, hai lần gọi cho thân giống hệt từng byte, còn với `AML__SEED=7` thì `data.seed == 7`; `contracts.check("metrics_auto_cleared", data) == []`; suppression trả 200 với `source == "mock"`, `feature == "metrics_suppression"`, header `X-AML-Source == "mock"`, `meta.mock.fixture == "metrics_suppression.json"`, `data` bằng `json.loads` của file `src/aml/api/fixtures/metrics_suppression.json`, `data.case_run == {"run_id": 0, "as_of": "2026-06-30"}`, `data.stage` bằng đúng `{"tool": "suppression", "before_label": "alert items", "after_label": "active alert items", "before": 100, "after": 88, "removed": 12, "reduction_pct": 12.0, "hours_saved": 3.0}`, `data.by_rule == {"GOOD_GUY": 10, "HIBERNATION": 2}`, `data.suspicious_suppressed == 0`, `data.sample` có 2 phần tử mà mọi `item_key` chứa `MOCK-` và mọi `suppression_reason` bắt đầu bằng `[SAMPLE]`; `contracts.check("metrics_suppression", data) == []`; đổi `stage.removed` thành `11` cho `check` trả một chuỗi chứa `removed`; `ROWS(duck)` trước và sau các lời gọi `GET` bằng nhau; và với `client(**OFF("metrics_suppression"))` thì `GET /api/v1/metrics/suppression` trả 501 có `error.message` bằng đúng `feature 'metrics_suppression' has no live implementation and ui.mock.metrics_suppression is off` và thân không chứa `MOCK-`, trong khi ba endpoint metrics live vẫn trả 200 với `source == "live"`.
- AC10: Given mã nguồn của repo và API-MINI với `client(**ON)`, When đọc file dưới dạng văn bản và gọi lần lượt mọi endpoint mock của spec này (scores, summary, chat, narrative, typologies, feedback, suppression) bằng cả `analyst01` lẫn `supervisor01`, Then số dòng của từng bảng `audit_log`, `cases`, `case_alerts`, `case_dispositions`, `case_runs`, `case_enrichment` trước và sau bằng nhau và `ROWS(duck)` không đổi; không file `.py` nào dưới `src/aml/` nằm ngoài `src/aml/api/` chứa `aml.api.mock`, `aml.api.mockdata` hay `aml.api.fixtures`; không file nào dưới `src/aml/metrics/` chứa `aml.api`; không file nào dưới `src/aml/api/mockdata/` chứa `audit(`, `audit_many`, `insert_df`, `.execute(`, `run_script`, `record_disposition`, `datetime.now`, `time.time`, `import random`, `ollama`, `httpx` hay `requests`; file `src/aml/api/routers/assistant.py` không chứa `record_disposition`, `run_cases`, `disposition` hay `status =`; app không có route nào bắt đầu bằng `/api/v1/assistant` ngoài `/api/v1/assistant/chat` và `/api/v1/assistant/feedback`; chuỗi `fixtures` không xuất hiện trong file `.py` nào của `src/aml/api/` ngoài `mock.py`; mọi chuỗi trong `src/aml/api/fixtures/assistant.json` ở các khoá văn bản bắt đầu bằng `[MẪU]` hoặc `[SAMPLE]`; không file nào dưới thư mục `results/` và không dòng nào của `README.md` chứa `mock-prio`, `mock-summary`, `MOCK-` hay `[MẪU]`; `web/package.json` có `react-markdown` và `remark-gfm` trong `dependencies` và không có `rehype-raw`; không file nào dưới `web/src/` chứa `dangerouslySetInnerHTML`, `rehype-raw` hay `innerHTML`; chỉ file `web/src/components/Markdown.tsx` chứa chuỗi `react-markdown`; không file nào dưới `web/src/pages/` chứa `fetch(` hay `EventSource`; trong các file dưới `web/src/`, chuỗi `Dữ liệu mẫu` xuất hiện ở đúng một file là `web/src/components/SourceBadge.tsx`; chuỗi `useCaseHighlight` xuất hiện trong ít nhất một file dưới `web/src/components/`; và file `web/src/api/types.ts` chứa các tên kiểu `CaseScores`, `Narrative`, `Answer`, `Citation`, `Funnel`, `DetectionRow`.

## Ngoài phạm vi
- **Hiện thực thật** của 7b-supp, 7c, 7d, Phase 7b, Phase 8: mô hình, `summarize`, retriever, Text2Cypher, LLM,
  post-validation, knowledge base. Spec này chỉ định hợp đồng, dữ liệu mẫu và tiêu chí nối thật.
- **Test tự động cho frontend** (Vitest, React Testing Library, Playwright) và bước `npm test` trong verify loop — theo
  quyết định của người dùng. Hành vi giao diện là checklist kiểm tay.
- Trang và thành phần của `ui-live-pages`: bố cục case detail và ba slot, panel enrichment, alert, form disposition,
  đồ thị Cytoscape, hợp đồng và hiện thực highlight (`caseHighlight.ts`); highlight theo `txn_id`; highlight từ
  `citations` (`item_key`) của bản summary template; fund-flow trace, screening review, DQ, benchmark.
- Mọi hành động của assistant hay của model lên case: tự đóng, clear, file STR, đề xuất disposition bấm-một-lần, tự
  điền form disposition, lọc case điểm thấp khỏi hàng đợi.
- Assistant: lịch sử hội thoại nhiều lượt phía server, lưu bản nháp narrative, hiển thị Cypher đã sinh, chọn retriever
  từ UI, phân loại memo, trang đánh giá golden set, so sánh vector RAG và GraphRAG.
- Dashboard: panel metrics của mô hình ưu tiên (`case_models.metrics`: ROC-AUC, precision ở đầu hàng đợi, prevalence),
  model card, dòng detection của Isolation Forest, so sánh mô hình screening học được, mẫu below-the-line của khách
  hàng không có alert cho mô hình (brief 8b mục 3) — thêm khi 7c / Phase 7b xong, bằng spec riêng. `metrics_detections`
  nhận thêm dòng có `source` mới mà không đổi hợp đồng.
- Tổng "giờ tiết kiệm" cộng qua nhiều panel; biểu đồ xu hướng theo thời gian; xuất CSV / PDF; ghi số liệu dashboard vào
  README hay `results/` (số README vẫn do lệnh CLI của từng phase sinh ra).
- Trễ nhân tạo cho luồng mock; cache kết quả `evaluate` (1,79 giây mỗi request trên `small`); phân trang cho
  `GET /cases/scores`; sắp xếp theo điểm phía server.
- DDL mới; sửa `src/aml/cases/`; lệnh CLI mới; quyền Oracle; đo trên `large`; đường Oracle của các endpoint này.

## Giả định
- **Đã đo** (prototype ngoài repo): số liệu `small` ở mục Hiện trạng và trong hợp đồng metrics; mọi giá trị MINI-GT /
  API-MINI của AC7–AC9 (hàm ánh xạ chạy trên ba evaluator thật); điểm mẫu của 5 case với seed 42 và 7; ba `answer_id`;
  `alert_evidence` và `linked_cifs.accounts` của MINI-C. **Suy ra, chưa đo** (chưa có `src/aml/api/`): số 56 / 52 sự kiện
  của AC4 (đếm tay số từ của năm câu mẫu), mọi chuỗi thông điệp lỗi, hành vi `StreamingResponse` dưới `TestClient`, toàn
  bộ AC6 và AC10, mọi thứ của `web/`. Lệch khi hiện thực do chi tiết thư viện → cập nhật spec, không đổi quy ước.
- `ui-foundation` (đã duyệt) được hiện thực trước, rồi các thay đổi S1–S11 của mục "Sửa kéo theo" được áp cùng spec
  này. `ui-live-pages` (U9, U11) được hiện thực trước các panel của `slot-*`; phần backend của spec này không phụ thuộc
  nó.
- "Tài khoản nội bộ" của `Citation.node_ids` = có dòng trong bảng `accounts`. Đồ thị của `ui-live-pages` cũng vẽ node
  `external_account`, nhưng theo quyết định của coordinator citation giao dịch chỉ mang tài khoản nội bộ.
- Hợp đồng `case_scores` và `case_summary` chép từ hai spec đã duyệt; nếu 7c / 7d khi hiện thực lệch khỏi spec của
  chính nó thì test hợp đồng trên response thật sẽ đỏ và phải sửa ở phía lệch, không nới `contracts.py` lặng lẽ.
- Hợp đồng `assistant` là đề xuất; spec Phase 8 có quyền sửa. Chi phí sửa: `contracts.py`, `fixtures/assistant.json`,
  `mockdata/assistant.py`, `web/src/api/types.ts` và các panel assistant.
- Dữ liệu mẫu chứa ID thật của case và dòng giao dịch bằng chứng thật (để highlight khớp); đó không phải "số liệu đo"
  và panel vẫn mang nhãn `Dữ liệu mẫu`. Mock không chứa thuộc tính khách hàng nên không cần che PII.
- `metrics_funnel` gọi `evaluate(db, settings)` mỗi request (1,79 giây trên `small`, một lần đo); chấp nhận cho demo.
- Disposition mô phỏng của 7c (`origin = 'SIMULATED'`) là dòng thật trong database; hiển thị tách theo `origin` không
  phải là mock.
- `config.py`, `config.yaml` là file dùng chung với loop 7b-supp đang chạy; spec này chỉ thêm mục `metrics` và bốn
  trường của `ui.mock`.
- Thông điệp lỗi, `reason`, nhãn stage bằng tiếng Anh như nguồn; chữ trên giao diện và câu mẫu tiếng Việt theo Q13 của
  `ui-foundation`.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Panel suppression là mock tới khi 7b-supp commit, hay live ngay? — đề xuất mặc định: **mock** tới khi 7b-supp commit (đúng phân công ban đầu); lý do: trước đó `case_runs.suppressed` luôn là 0 theo cấu trúc và nghĩa của `suppression_rule` thuộc spec 7b-supp. Phương án thay thế: live ngay — các cột `case_runs.suppressed`, `case_alerts.status`, `suppression_rule` đã có từ 7a nên hàm đọc viết được bây giờ và sẽ hiện trung thực "0 item bị suppress"; bớt một mock nhưng panel trống trong demo. — Trả lời: theo đề xuất mặc định (người dùng chọn trong bảng hỏi).
- [x] Q2. **(cần người dùng quyết)** Giả định phút-mỗi-alert là bao nhiêu và có tách theo loại không? — đề xuất mặc định: một giá trị `metrics.minutes_per_alert: 15` cho mọi đơn vị bị loại (cặp screening, alert), luôn hiển thị cạnh số giờ kèm chữ `ước tính`. Con số 15 là giả định của tôi, chưa có nguồn — anh/chị cần chốt. Phương án thay thế: tách `screening_pair` / `alert` / `case` (ba khoá config); hoặc không quy ra giờ cho stage screening vì baseline `fuzzy` là cấu hình không ai triển khai (4364 cặp × 15 phút = 1091 giờ là con số dễ bị chất vấn). — Trả lời: theo đề xuất mặc định (người dùng chọn trong bảng hỏi).
- [x] Q3. **(cần người dùng quyết)** "Volume trước consolidation" đếm theo gì? — đề xuất mặc định: **alert phân biệt** (`item_key` `ACTIVE`): `small` 339 → 335 case, giảm 1,18 %. Lý do: đúng nghĩa "alert volume", thận trọng. Phương án thay thế: đếm theo item (alert × golden customer): 475 → 335, giảm 29,5 % — phản ánh việc một alert nhóm phải xem cho từng khách hàng, nhưng dễ bị coi là thổi phồng. Dù chọn gì, cả `alerts` lẫn `items` đều có trong response. — Trả lời: theo đề xuất mặc định (người dùng chọn trong bảng hỏi).
- [x] Q4. "FP rate" của một detection định nghĩa thế nào? — đề xuất mặc định: tỉ lệ alert không rơi vào kịch bản đáng ngờ = (`benign` + `unlabelled`) / `alerts` với rule / network (bằng 1 − `precision_suspicious`), `fp` / `flagged` với screening. Lý do: đây là nghĩa vận hành trong AML ("bao nhiêu phần alert là giả"), tính được từ ba evaluator có sẵn. Phương án thay thế: FP rate thống kê (FP / tổng thực thể âm) — mẫu số là mọi tài khoản không đáng ngờ, luôn gần 0 và không nói gì về khối lượng việc. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q5. **(cần người dùng quyết)** Chuyển đổi case → suspicious có là live ngay và có tính disposition mô phỏng không? — đề xuất mặc định: **live ngay**, đọc `case_dispositions_current` (hiện 0 dòng → `rate` null, giao diện hiện `—`), tách `HUMAN` / `SIMULATED`. Lý do: không cần mock cho thứ đã có bảng thật; sau 7c số mô phỏng xuất hiện nhưng không lẫn với quyết định của người. Hệ quả: với thiết kế này **không phần nào của dashboard phải chờ 7c hay Phase 7b** — chỉ suppression chờ 7b-supp. Phương án thay thế: một feature mock riêng cho chuyển đổi tới khi 7c xong. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q6. Builder của mock có được đọc database không, và `mock_or_live` gọi builder thế nào? — đề xuất mặc định: **được đọc, không được ghi** (`cases_current`, `load_case`, giao dịch bằng chứng) vì dữ liệu mẫu phải khớp `case_id` / id node thật; `mock_or_live` thêm tham số `mock_fn`; `meta.mock.fixture` là `builder:<tên hàm>`; SSE đi qua `sse.stream_or_live`. Đây là thay đổi vào phần nền móng **đã duyệt** — liệt kê ở S5–S8 của mục "Sửa kéo theo" (nền móng ghi builder là "hàm thuần của `settings.seed` và tham số request" và `mock_or_live` chưa có đường cho builder / SSE); duyệt spec này là duyệt các thay đổi đó. Phương án thay thế: client gửi danh sách `case_id` trong request để builder không cần database — không cho được `queue_rank` toàn cục và không có ID giao dịch. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q7. Bảng case sắp theo điểm thế nào khi `GET /cases` phân trang phía server theo thời gian? — đề xuất mặc định: khi có điểm, trang nạp hết các trang của `GET /cases` (`limit = max_page_size`; `small` 335 case = 2 request) và toàn bộ `GET /cases/scores`, ghép và sắp phía client theo `queue_rank`; phân trang hiển thị phía client. Lý do: giữ "một response một nguồn" và frontend không đổi khi nối thật. Hệ quả: khi điểm là mẫu thì thứ tự của cả bảng là mẫu — nhãn nằm ở tiêu đề cột điểm. Phương án thay thế: (a) điểm mẫu chỉ hiện cột, bảng giữ thứ tự thời gian tới khi điểm là thật; (b) `GET /cases?sort=priority` phía server khi 7c xong (frontend phải đổi lúc nối thật). — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q8. Assistant dùng một cờ hay bốn? — đề xuất mặc định: **một** cờ `ui.mock.assistant` cho cả bốn endpoint; khi tắt, endpoint nào đã có hàm thật thì chạy thật, endpoint chưa có trả 501. Lý do: Phase 8 là một phase; ít cấu hình. Phương án thay thế: bốn cờ (`assistant_chat`, …) để vừa chat thật vừa narrative mẫu trong cùng buổi demo. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q9. **(Phase 8 phải xác nhận)** Luồng chat: giao thức và việc hiện văn bản chưa kiểm chứng? — đề xuất mặc định: `POST` + `fetch` đọc luồng (không dùng `EventSource` vì nó chỉ có `GET`, câu hỏi sẽ nằm trong URL và log); sự kiện `meta` → `start` → `token`* → `final` → `done`; `token` là văn bản tạm hiển thị mờ, `final` (đã post-validation) thay thế toàn bộ. Phương án thay thế: không phát `token`, chỉ phát từng câu **sau** khi đã kiểm chứng (không bao giờ có chữ chưa kiểm trên màn hình, nhưng người dùng chờ lâu hơn trước khi thấy gì). — Trả lời: theo đề xuất mặc định cho bản mock; là đề xuất mà spec Phase 8 phải chấp nhận hoặc sửa (xác nhận khi duyệt spec).
- [x] Q10. **(Phase 8 phải xác nhận)** Mô hình citation và không gian ID node? — đề xuất mặc định: `Citation {n, kind: node | transaction | chunk, id, label, node_ids, txn_ids, excerpt}`; id node là **khoá tự nhiên không tiền tố** (`account_id`, `golden_customer_id`) — đã chốt ở Q8 của `ui-live-pages`, Phase 8 trích thẳng khoá Neo4j; citation giao dịch **phải** mang sẵn `account_id` nội bộ của hai đầu trong `node_ids` (đồ thị gộp cạnh nên không highlight theo `txn_id`), `txn_ids` giữ để hiển thị và kiểm chứng. Điểm dễ đổi nhất: Phase 8 có thể muốn trích dẫn theo cụm từ (span) thay vì theo câu, hoặc trích alert / case khác làm node. — Trả lời: theo đề xuất mặc định cho bản mock; là đề xuất mà spec Phase 8 phải chấp nhận hoặc sửa (xác nhận khi duyệt spec).
- [x] Q11. **(Phase 8 phải xác nhận)** "Không đủ bằng chứng" và hội thoại nhiều lượt? — đề xuất mặc định: `status = "insufficient_evidence"` với `sentences` và `citations` rỗng, giao diện hiện chữ cố định `Không đủ bằng chứng`; mỗi request một câu hỏi, không gửi lịch sử. Phương án thay thế: cho phép câu giải thích "thiếu gì" (không citation); thêm `history: [{question, answer_id}]` vào request. — Trả lời: theo đề xuất mặc định cho bản mock; là đề xuất mà spec Phase 8 phải chấp nhận hoặc sửa (xác nhận khi duyệt spec).
- [x] Q12. **(Phase 8 phải xác nhận)** Draft narrative đi qua đâu? — đề xuất mặc định: endpoint riêng `POST /cases/{case_id}/narrative` trả `Narrative` 7 trường của 7d (bộ sinh `llm` đăng ký qua `register_generator`) cộng `citations` chi tiết; không stream, không lưu. Lý do: dùng lại đúng interface 7d đã duyệt và phép kiểm watermark của `summarize`. Phương án thay thế: `GET /cases/{case_id}/summary?generator=llm` (một endpoint, nhưng trộn hai tính năng hai nguồn); hoặc stream như chat. — Trả lời: theo đề xuất mặc định cho bản mock; là đề xuất mà spec Phase 8 phải chấp nhận hoặc sửa (xác nhận khi duyệt spec).
- [x] Q13. Feedback ở chế độ mock có ghi `audit_log` không, và có theo quy ước "endpoint quyết định" không? — đề xuất mặc định: **không ghi** khi mock (`recorded = false`, giao diện nói rõ) vì dòng audit sẽ trỏ tới một `answer_id` không tồn tại; khi thật: 201 + 1 dòng audit có actor. Feedback **không** bắt buộc `reason` (nó không quyết định gì về case) — ngoại lệ đối với quy ước endpoint quyết định của `ui-foundation`, ghi ở S9 của mục "Sửa kéo theo". Phương án thay thế: ghi audit cả khi mock với `details.source = "mock"`. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q14. Render markdown bằng gì và xử lý liên kết / ảnh thế nào? — đề xuất mặc định: `react-markdown` + `remark-gfm` (bảng), không `rehype-raw`; HTML thô hiện thành văn bản; **không** render phần tử `img` (tránh tải tài nguyên ngoài) và liên kết hiện thành chữ thường. Lý do: nội dung chứa `reason` do người gõ và tên phía watchlist — dữ liệu không tin cậy; template của 7d không có liên kết. Chưa đo (chưa có `web/`). Phương án thay thế: cho liên kết `http(s)` với `rel="noopener noreferrer"`. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q15. Supervisor có thấy summary không che không? — đề xuất mặc định: **không** — `summarize` của 7d luôn dùng `customers_masked`; `meta.pii == "masked"` với mọi role, không ghi `PII_VIEWED`. Phương án thay thế: thêm đường không che cho supervisor — phải sửa spec 7d đã duyệt. — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q16. Mock chat chọn kịch bản "không đủ bằng chứng" bằng cách nào? — đề xuất mặc định: câu hỏi (đã chuẩn hoá) nằm trong `insufficient_questions` của fixture (`ai là người hưởng lợi cuối cùng?`, `who is the ultimate beneficiary?`) → `insufficient_evidence`; mọi câu khác → kịch bản 5 câu. Lý do: tất định và demo được cả hai trạng thái. Phương án thay thế: mọi câu hỏi lạ đều trả `insufficient_evidence` (trung thực hơn với một mock, nhưng người demo phải gõ đúng câu mẫu mới thấy citation). — Trả lời: theo đề xuất mặc định (xác nhận khi duyệt spec).
- [x] Q17. Có giữ các phép kiểm quy ước `web/` bằng pytest đọc văn bản (nửa sau của AC10) không? — đề xuất mặc định: **giữ** — chúng không cần Node, không phải test frontend, và là thứ duy nhất tự động bảo vệ "trang không tự `fetch`, không tự vẽ nhãn, markdown không qua HTML thô". Phương án thay thế: bỏ, chuyển hết sang checklist kiểm tay. — Trả lời: giữ, theo quyết định của người dùng ở spec nền móng (`ui-foundation` AC8 đã dùng đúng kiểu kiểm này).
