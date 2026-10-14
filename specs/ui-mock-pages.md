---
id: ui-mock-pages
status: approved
approved_by: pthieu
---

# Phase 9c — Các trang còn lại trên dữ liệu thật: điểm ưu tiên (7c), case summary (7d), assistant (8c: hỏi đáp có trích dẫn, draft narrative, typology explainer, feedback), metrics dashboard (funnel có suppression của 7b-supp)

## Bối cảnh
Spec thứ ba của Phase 9 (PROJECT_BRIEF.md mục 10), dựng trên `specs/ui-foundation.md` (9a: envelope `{source, feature,
data, meta}`, header `X-AML-Source`, actor / role, che PII, `ApiPanel`) và `specs/ui-live-pages.md` (9b: trang case
detail, ba slot `slot-case-score` / `slot-case-summary` / `slot-assistant`, hợp đồng highlight `useCaseHighlight`). Bản
nháp trước (2026-10-13) viết khi 7b-supp, 7c, 7d và Phase 8 chưa có, nên định nghĩa endpoint mock, fixture,
`aml.api.live`, `contracts.py` và cờ `ui.mock.<feature>`. Nay cả bốn nguồn đã xong và merge vào `main` (3de8cb4). Theo
quyết định của người dùng (2026-10-14): **mọi endpoint của spec này đọc / gọi code thật**; bỏ toàn bộ lớp mock của bản
nháp; chỉ giữ `ui.mock.sample` của 9a. Giữ lại: shape JSON của bản nháp (8c đã chấp nhận, xem "Hợp đồng"), thiết kế
metrics và các câu hỏi người dùng đã trả lời. Người dùng: investigator trong buổi demo. Quy tắc dự án áp nguyên: số
hiển thị đều đọc từ bảng / chạy thật; mô hình chỉ xếp hạng; assistant không clear / close / file / ghi disposition;
mọi lời gọi assistant ghi `audit_log` với actor của request.

Theo quyết định của người dùng (2026-10-13): **không có test tự động cho frontend**. Mọi AC là pytest phía backend
(DuckDB, không Ollama / Neo4j / Oracle). Hành vi giao diện nằm ở "Yêu cầu giao diện (kiểm tay)"; `npm --prefix web run
build` phải pass.

### Hiện trạng đã kiểm (2026-10-14, seed 42)
Đọc code `main` và chạy prototype ngoài repo (`D:\Works\_scratch_9c\p1..p5.py`, DuckDB tạm; ổ C: đầy nên không dùng được
scratchpad). Không sửa file nào trong repo, không chạm `data/aml.duckdb`, Oracle, Neo4j.
- **API hiện có** (9a + 9b): routers mỏng, đọc qua `reads/`; lỗi qua `ApiError` và handler chung (`ServiceUnavailableError`
  → 503 `{"code": "unavailable", "message": "service unavailable"}`); `ui.mock` chỉ có `sample`. Test
  `test_live_ac10_cross_cutting.py` chỉ cho API import `load_case`, `record_disposition`, `CaseError`, `DISPOSITIONS` từ
  `aml.cases`. `test_ac7_mock.py` gọi **mọi** route `GET` không tham số đường dẫn trên SCHEMA và đòi 200. Route
  `/cases/{case_id}` của 9b sẽ nuốt `/cases/scores` nếu đăng ký trước.
- **7c** (đã đo): `case_scores_current` chỉ trả lần chấm mới nhất **của lần chạy case mới nhất** — sau một `run_cases`
  mới nó rỗng và `load_case(...).score is None`. `insert_scores` của `aml.cases.prio_store` + `load_case(db, id).score`
  trả `{score, queue_rank, model_version, top_features}` (`top_features` parse từ JSON).
- **7d** (đã đo trên API-MINI): `summarize(db, settings, "C-C01-20260302")` trả `generator "template"`, `version
  "summary/v1"`, `language "en"`, `watermark` = `TEMPLATE SUMMARY (summary/v1): generated from stored case data without an
  LLM. It is not a disposition.`, `citations` = ba `item_key`; markdown có tên **đã che** (`| C01 | Nguyen T. C. | …`).
  `language="vi"` raise `NarrativeError("language 'vi' is not available in the template generator")`.
- **8c** (đã đo với fake của `tests/assistant/an_helpers.py`):
  - `answer_question` (một lượt, trả `Answer`; `as_dict()` đúng hợp đồng UI) ghi **đúng 1** dòng `audit_log` (`ANSWERED` /
    `INSUFFICIENT_EVIDENCE` / `FAILED`, actor của tham số `actor`); retriever thật của 8b ghi thêm `RETRIEVED` (+
    `CYPHER_*`). Retriever thật cần **Neo4j** (`case_graph`) và Ollama (embed + chat). Case không tồn tại là **từ chối**
    `unknown_case`, không phải lỗi. `answer_events` chỉ phát `start` rồi `final`, và `start` có sau khi câu trả lời đã
    xong — không có `token`.
  - Lỗi (đã đo): mô hình trả JSON hỏng 2 lần (`max_retries: 1`) → `AssistantError("model output is not valid JSON after
    2 attempt(s)")` + 1 dòng `FAILED`; `LLMError` → `AssistantError("llm call failed: …")` + 1 dòng `FAILED`; Ollama tắt →
    `OllamaUnavailableError` (lớp con của `ServiceUnavailableError`), không dòng audit; Neo4j tắt →
    `RetrievalUnavailableError` (lớp con của `RetrievalError`, **không** phải `ServiceUnavailableError`), không dòng audit.
  - `draft_narrative` ghi 1 dòng `NARRATIVE_DRAFTED`; lỗi mô hình → `NarrativeError` **không** ghi audit; Ollama tắt →
    `OllamaUnavailableError`; kho tri thức hỏng → vẫn chạy, `knowledge = "unavailable"`.
  - `explain_typology` không gọi chat, không ghi audit; kho tri thức hỏng → `chunks` rỗng, `knowledge = "unavailable"`.
  - Không có hàm ghi feedback (8c Q12 giao cho Phase 9).
- **7b-supp** (đã đo trên MINI-S): run 1: `items 11`, `active 11`, `cases 5`; sau `FALSE_POSITIVE` của `C-C05-20260630`
  và run 2: `items 11`, `suppressed 1`, `active 10`, `cases 4`, 8 `item_key` `ACTIVE` phân biệt, item bị suppress
  `SCREENING|C05|WL2` (`GOOD_GUY`, `G-C05`, `SCREENING_REVIEW`).
- **Bản sao dữ liệu `small`** (`ui_check.duckdb` lúc 12:27, đọc chỉ-đọc): run 5: `items 475`, `alerts 339`, `suppressed
  36` (toàn `GOOD_GUY`), `active 439`, `cases 309`, **303** `item_key` `ACTIVE` phân biệt (< 309 case — xem Q4);
  `case_dispositions_current`: `HUMAN` 1 `SUSPICIOUS`, `SIMULATED` 200 `SUSPICIOUS` + 34 `FALSE_POSITIVE`;
  `case_scores_current` 309 dòng `prio/logreg/2`, 101 có `queue_rank`; 6208 cặp `AUTO_CLEARED`.
- **Chưa đo**: mọi thứ cần code chưa viết — router, thông điệp lỗi mới, `aml.metrics`, `record_feedback`, SQL Oracle,
  `web/`. Các giá trị đó trong AC suy ra từ thiết kế; giá trị lấy từ hàm 7c / 7d / 8c / evaluator đã đo đều ghi "(đo)".

### Interface đề xuất
```python
# src/aml/common/config.py
class MetricsConfig(BaseModel):
    minutes_per_alert: int  # >= 1; giả định để ước tính giờ tiết kiệm, luôn hiển thị (Q8)
    sample_size: int  # 1..max_sample_size; cỡ mẫu mặc định của hai panel mẫu
    max_sample_size: int  # >= 1


class Settings(BaseModel):
    ...
    metrics: MetricsConfig  # config.yaml: metrics: {minutes_per_alert: 15, sample_size: 20, max_sample_size: 200}


# src/aml/assistant/feedback.py — người ghi feedback của Phase 9 (8c không có)
RATINGS = ("up", "down")
FEEDBACK_VERSION = "feedback/v1"
ANSWER_ID_RE = re.compile(r"^ans-[0-9a-f]{12}$")  # dạng `answer_id` của 8c
COMMENT_MAX = 1000


class FeedbackError(RuntimeError): ...  # answer_id không có, actor là system actor


@dataclass(frozen=True)
class Feedback:
    answer_id: str
    rating: str
    comment: str | None  # chuỗi chỉ có khoảng trắng -> None
    actor: str


def record_feedback(
    db: Database, settings: Settings, answer_id: str, rating: str, *, comment: str | None, actor: str
) -> Feedback: ...  # kiểm mọi thứ trước khi ghi; đúng 1 dòng audit ANSWER_RATED


# src/aml/metrics/  (chỉ đọc; không import aml.api, fastapi; không audit)
def funnel(db: Database, settings: Settings) -> dict[str, Any]: ...
def detections(db: Database, settings: Settings) -> dict[str, Any]: ...
def auto_cleared_sample(db: Database, settings: Settings, *, size: int | None = None) -> dict[str, Any]: ...
def suppression(db: Database, settings: Settings, *, size: int | None = None) -> dict[str, Any]: ...


# src/aml/api/reads/scores.py
def case_scores(db: Database) -> dict[str, Any]: ...  # đọc sql/common/api/case_scores.sql


# src/aml/api/assistant.py — bộ nối mỏng: gọi 7d / 8c, dịch lỗi, không SQL, không audit(
def case_summary(db: Database, settings: Settings, case_id: str, language: str | None) -> dict[str, Any]: ...
def ask(db, settings, user: User, case_id: str, question: str, language: str) -> dict[str, Any]: ...
def narrative(db, settings, user: User, case_id: str, language: str) -> tuple[dict[str, Any], str]: ...  # (data, knowledge)
def typologies(db, settings, case_id: str) -> tuple[dict[str, Any], str]: ...
def feedback(db, settings, user: User, answer_id: str, rating: str, comment: str | None) -> dict[str, Any]: ...
```
- Router mới: `routers/case_insights.py` (`/cases/scores`, `/cases/{case_id}/summary`; đăng ký **trước**
  `routers/cases.py` trong `create_app`), `routers/assistant.py` (chat, narrative, typologies, feedback),
  `routers/metrics.py`. Bộ nối **không** truyền `llm` / `retriever` / `knowledge` cho 8c: luôn dùng
  `answering.default_llm`, `answering.default_retriever`, `narrative.default_knowledge` (điểm thay thế của test, như test
  CLI của 8c).
- SQL mới: `sql/common/api/case_scores.sql`; `sql/{duckdb,oracle}/assistant/answer_known.sql` (tra `details.answer_id`:
  `json_extract_string` / `JSON_VALUE`); `sql/common/metrics/` (đếm stage, chuyển đổi, quần thể mẫu) và
  `sql/{duckdb,oracle}/metrics/suppressed_truth_accounts.sql` (bản `SUPPRESSED` của `cases/truth_accounts.sql`). Oracle:
  mỗi câu kết thúc bằng dòng `/`.
- **Không DDL. Không sửa** `src/aml/cases/`, `answering.py`, `narrative.py`, `explainer.py`. Không lệnh CLI mới.
  `ui.mock` giữ đúng `{sample}`; không file `live.py`, `contracts.py`, `sse.py`, `mockdata/`, fixture mới.
- `web/`: kiểu TypeScript mới trong `web/src/api/insightTypes.ts`; panel trong `web/src/pages/case/` (score, summary,
  assistant) và `web/src/pages/metrics/`; `web/src/components/Markdown.tsx` (nơi duy nhất import `react-markdown`);
  `package.json` thêm `react-markdown`, `remark-gfm` (Q14); nhãn tiếng Việt mới **nối thêm** vào cuối
  `web/src/i18n/enums.ts` (tên 35 feature của 7c, `stage`, `rating`, `knowledge`, mã lỗi `model_error`).

### Sửa kéo theo ở phần đã duyệt — là một phần của spec này
| # | chỗ | thay đổi | test phải cập nhật |
|---|---|---|---|
| S1 | `specs/ui-live-pages.md` AC10, `tests/api/test_live_ac10_cross_cutting.py::ALLOWED_CASES_NAMES` | thêm `summarize`, `NarrativeError` (của `aml.cases.narrative`) vào tập tên API được import | đổi hằng số thành sáu tên; phép kiểm giữ nguyên |
| S2 | `specs/ui-foundation.md` "Quy ước endpoint quyết định" | thu hẹp: áp cho `POST` ghi quyết định **về case / screening hit**. Ba `POST` của assistant (`chat`, `narrative`, `feedback`) không bắt buộc `reason`, vẫn từ chối trường `actor` (422) và vẫn ghi `audit_log` với actor của request (Q13) | không (AC6 của 9a chỉ kiểm disposition) |
| S3 | `specs/ui-foundation.md` ("luồng SSE thuộc `ui-mock-pages`", M2 "không có cột điểm", M5 "`/metrics` chưa triển khai"), `specs/ui-live-pages.md` U9 ("slot rỗng") | 9c không dùng SSE (Q2); `/cases` có cột điểm, `/metrics` có bốn panel, ba slot có nội dung. Hai spec đó thêm ghi chú dẫn về đây | không (đều là mục kiểm tay hoặc văn bản) |
| S4 | `specs/assistant-answering.md` Giả định ("lọc tài khoản ngoài khỏi `node_ids` thuộc bộ nối Phase 9") | 9c **không lọc** (Q3): đồ thị 9b có node `external_account` cùng khoá | không |
| S5 | `tests/api/test_ac7_mock.py` (9a AC7) | không đổi test; ràng buộc mới cho spec này: năm route `GET` không tham số của 9c phải trả 200 `live` trên SCHEMA | không |
| S6 | bản nháp trước của chính spec này | bỏ `aml.api.live`, `contracts.py`, `sse.py`, `mockdata/`, `fixtures/assistant.json`, `fixtures/metrics_suppression.json`, bốn cờ `ui.mock.*`, `Citation` "chỉ tài khoản nội bộ" | không (chưa có code) |

### Hợp đồng JSON của `data`
`snake_case`; tiền là số nguyên VND; mốc thời gian `YYYY-MM-DDTHH:MM:SS`; mỗi object có **đúng** các khoá nêu ra. Mọi
endpoint là `live`, cần user hợp lệ (401 như 9a), không phụ thuộc role trừ khi ghi rõ; `meta.pii = "masked"` cho mọi
role ở summary và assistant (dữ liệu nguồn của 7d / 8b luôn đã che — Q15), không ghi `PII_VIEWED`.

**`case_scores`** — `GET /api/v1/cases/scores` (feature `case_scores`; không phân trang — Q7):
- `data = {run_id: int | null, score_run_id: int | null, model_version: str | null, queue: int, scores: [Score]}`;
  `run_id` = lần chạy case mới nhất; ba trường kế lấy từ `case_scores_current`; `queue` = số `Score` có `queue_rank`.
- `Score = {"case_id": c, **load_case(db, c).score}` = `{case_id, score, queue_rank: int | null, model_version,
  top_features: [{feature, value, contribution}]}`, sắp theo (`queue_rank` tăng, null cuối, rồi `case_id`). Không có
  lần chấm cho lần chạy hiện hành → `scores == []`, `queue == 0`, `score_run_id` / `model_version` null.

**`case_summary`** — `GET /api/v1/cases/{case_id}/summary?language=` (feature `case_summary`):
- `data = dataclasses.asdict(summarize(db, settings, case_id, generator="template", language=language))` (bảy trường
  của `Narrative`, `citations` là list). Luôn bộ sinh `template` (Q6). Không ghi gì.
- `CaseError` → 404 `not_found`; `NarrativeError` → 422 `invalid_request` với thông điệp của nó.

**`assistant`** (feature `assistant`) — hợp đồng `Citation` / `Sentence` / `Answer` của bản nháp, đã được 8c chấp nhận
và hiện thực (`Answer.as_dict`, `citation_dict`, `TypologyMatch.as_dict`). Khác bản nháp (đo): `Citation.kind` ∈
`node | transaction | chunk | alert`; `label = "<kind> <id>"`; `answer_id` khớp `^ans-[0-9a-f]{12}$` (tất định theo case,
ngôn ngữ, câu hỏi, model, văn bản); `node_ids` là mọi trích dẫn `account:` / `customer:` của mục bằng chứng, **có thể**
gồm tài khoản ngoài và có thể rỗng; citation `node` có thể có nhiều `node_ids` (vd `A01` → `["A01", "G-C01"]`) hoặc
trỏ id không phải node đồ thị (`case_id`, typology). Bấm citation gọi `setHighlight(citation.node_ids)`; id không có
trên đồ thị hiện ở `graph-highlight-missing`.
- **Hỏi đáp** `POST /api/v1/assistant/chat`, thân `{case_id: str, question: str (1..1000 ký tự sau khi bỏ khoảng trắng
  hai đầu), language: "vi" | "en" = "vi"}`, khoá lạ → 422. **JSON thường, không SSE** (Q2). Thứ tự: kiểm thân (422) →
  `load_case` (404 `unknown case_id <id>`, không gọi 8c, không audit) → `answer_question(db, settings, question,
  case_id=…, language=…, actor=user.actor)` → 200, `data = Answer.as_dict()`. Không ghi audit nào ngoài dòng của 8c / 8b.
- **Draft narrative** `POST /api/v1/cases/{case_id}/narrative`, thân `{language: "vi" | "en" = "vi"}` → 200, `data =
  {narrative: asdict(d.narrative), citations: [Citation]}` với `d = draft_narrative(..., actor=user.actor)`, `meta =
  {pii, knowledge: d.knowledge}`. Không lưu bản nháp; dòng audit duy nhất là `NARRATIVE_DRAFTED` của 8c.
- **Typology explainer** `GET /api/v1/cases/{case_id}/typologies` → 200, `data = explain_typology(db, settings,
  case_id).as_dict()`, `meta = {pii, knowledge}`. Không ghi gì.
- **Feedback** `POST /api/v1/assistant/feedback`, thân `{answer_id: khớp ANSWER_ID_RE, rating: "up" | "down", comment:
  str | null (≤ 1000)}` → 201, `data = {answer_id, rating, actor}`. `record_feedback`: actor là system actor →
  `FeedbackError("feedback needs a human actor")`; `answer_id` không là `details.answer_id` của dòng `module='assistant'`,
  `decision IN ('ANSWERED', 'INSUFFICIENT_EVIDENCE')` → `FeedbackError("unknown answer_id <id>")` → 404 (Q5); hợp lệ →
  đúng 1 dòng `audit_log` `module='assistant'`, `entity_type='answer'`, `entity_id=answer_id`, `decision='ANSWER_RATED'`,
  `reason="answer <id> rated <rating> by <actor>"`, `version='feedback/v1'`, `actor`, `details={answer_id, rating,
  comment}`. Chấm lại là thêm dòng mới (append-only).
- **Lỗi của assistant** (Q9): `ServiceUnavailableError` (Ollama tắt) và `RetrievalUnavailableError` (Neo4j tắt / đồ thị
  cũ) → 503 `{"code": "unavailable", "message": "service unavailable"}`; `AssistantError` không phải lỗi đầu vào và
  `NarrativeError` → 502 `model_error` với thông điệp của exception; `AssistantInputError` → 422. Explainer không cần
  chat nên không bao giờ 503 vì Ollama (chỉ `knowledge = "unavailable"`).
- Feature `assistant` **không có** endpoint nào ghi disposition, đổi trạng thái case, clear, close hay file.

**`metrics_funnel`** — `GET /api/v1/metrics/funnel` (`aml.metrics.funnel`):
- `data = {case_run: {run_id, as_of} | null, minutes_per_alert, stages: [Stage × 3], total_hours_saved: float | null,
  conversion: {alert_to_case: {alerts, items, cases, cases_per_alert}, case_to_suspicious: {decided, suspicious,
  false_positive, rate, by_origin: {HUMAN: {decided, suspicious, false_positive}, SIMULATED: {…}}}}, unavailable: [{part,
  message}]}`.
- `Stage = {tool, before_label, after_label, before, after, removed, reduction_pct, hours_saved}`; `removed = before −
  after`; `reduction_pct = round(100 * removed / before, 2)` (null khi `before == 0`); `hours_saved = round(removed *
  minutes_per_alert / 60, 1)` (Python `round`). Không tính được → năm số null + một dòng `unavailable`.
  - `screening_tuning`: `fuzzy` → `two_tier` của `evaluate(db, settings)` (`flagged`); nhãn `fuzzy baseline pairs` /
    `two-tier ALERT + REVIEW pairs`; `ScreeningError` → `unavailable` với thông điệp của nó.
  - `suppression`: `case_runs.items` → `case_runs.active` của lần chạy mới nhất; nhãn `alert items` / `active alert items`.
  - `consolidation`: `case_runs.active` → `case_runs.cases`; nhãn `active alert items` / `cases` (Q4).
  - Chưa có lần chạy case → hai stage sau `unavailable` với ``no case run yet: run `aml cases build` first``.
- `total_hours_saved` = `round` 1 chữ số của tổng `hours_saved` các stage tính được; null khi không stage nào.
- `alert_to_case`: `alerts` = số `item_key` `ACTIVE` phân biệt của `case_alerts_current`, `items` = `case_runs.active`,
  `cases`, `cases_per_alert = round(cases / alerts, 4)`; chưa có lần chạy → bốn null. `case_to_suspicious` đếm
  `case_dispositions_current`; `rate = round(suspicious / decided, 4)`, null khi `decided == 0`; tách `origin` (Q16).

**`metrics_detections`** — `GET /api/v1/metrics/detections`: như bản nháp (Q10). `data = {rows: [Row], unavailable}`;
`Row = {source, detection, baseline, target_typology, alerts, true_positives, false_positives, fp_rate, precision, recall,
scenarios, detected}`. `RULE` / `NETWORK`: một dòng cho mỗi dòng của `evaluate_rules` / `evaluate_network` (giữ thứ tự),
`true_positives = target_hits + other_suspicious` (null tính là 0), `false_positives = benign + unlabelled`, `precision =
precision_suspicious`; `SCREENING`: một dòng mỗi method (`alerts = flagged`, `scenarios = tp + fn`, `detected = tp`,
`baseline` đúng với `exact`, `fuzzy`). `fp_rate = round(false_positives / alerts, 4)`, null khi `alerts == 0`. Mọi NaN →
null, số đếm là `int`. `NetworkError` / `ScreeningError` → không dòng của phần đó, một dòng `unavailable` (`network` /
`screening`).

**`metrics_auto_cleared`** — `GET /api/v1/metrics/below-the-line/auto-cleared?size=` (1..`max_sample_size`, mặc định
`sample_size`): như bản nháp. `data = {population, ground_truth_available, true_hits_in_population, seed, sample_size,
sample: [{cif, entry_id, list_type, final_score, reason, truth: "TRUE_HIT" | "NOT_A_HIT" | null}]}`; quần thể =
`screening_current` có `decision = 'AUTO_CLEARED'` sắp theo (`cif`, `entry_id`); mẫu = các dòng ở chỉ số
`sorted(numpy.random.default_rng(settings.seed).choice(n, size=min(size, n), replace=False))`; `truth` theo
`truth_pairs(db)`, rỗng → `ground_truth_available = false` và ba trường truth null. Không tên khách hàng.

**`metrics_suppression`** — `GET /api/v1/metrics/suppression?size=` (live; thay mock của bản nháp):
- `data = {case_run, minutes_per_alert, stage: Stage (tool "suppression", như funnel), by_rule: {GOOD_GUY, HIBERNATION} |
  null, population, ground_truth_available, suspicious_suppressed: int | null, seed, sample_size, sample: [{item_key,
  golden_customer_id, source, rule_id, suppression_rule, suppression_reason, truth: "SUSPICIOUS" | "NOT_SUSPICIOUS" |
  null}], unavailable}`. Quần thể = dòng `SUPPRESSED` của `case_alerts_current` sắp theo (`item_key`,
  `golden_customer_id`); mẫu chọn như auto-cleared (Q11). Bất biến: `population == stage.removed ==
  by_rule.GOOD_GUY + by_rule.HIBERNATION`.
- `truth` của một item theo luật nhãn item của 7c: `SCREENING` → cặp (`cif`, `entry_id`) thuộc `truth_pairs`;
  `RULE` / `NETWORK` → một tài khoản của alert thuộc chính golden customer của item nằm trong kịch bản `is_suspicious`.
  `suspicious_suppressed` = số item `SUSPICIOUS` của **cả quần thể**.

### Yêu cầu giao diện (kiểm tay)
Không phải AC. Mọi panel lấy dữ liệu qua `ApiPanel` (GET) hoặc `apiPost` của `web/src/api/client.ts` từ một component;
mọi giá trị mã hoá hiện qua `web/src/i18n/`; câu do backend sinh (reason, definition, thông điệp lỗi, câu của mô hình)
hiện nguyên văn dạng chữ.
- M0. Trên `/cases/:caseId` nội dung của spec này chỉ nằm trong ba slot của 9b: `slot-case-score` (điểm định dạng
  `formatNumber`, hạng, model, bảng `top_features` với tên feature tiếng Việt; không có điểm → `—` và dòng `Chưa chấm
  điểm cho lần chạy này`), `slot-case-summary` (M2), `slot-assistant` (M3–M5).
- M1. `/cases`: thêm cột `Điểm ưu tiên`, `Hạng`, `Yếu tố chính` (feature đầu của `top_features`); có điểm → bảng sắp theo
  `queue_rank`, case không hạng ở cuối theo thứ tự của 9a; trang nạp hết các trang `GET /cases` (`limit =
  max_page_size`) và `GET /cases/scores` rồi ghép phía client (Q7). Dòng chú thích `Mô hình chỉ xếp hạng, không đóng
  case`. Không nút nào dựa trên điểm.
- M2. `slot-case-summary`: markdown qua `Markdown.tsx` (bảng GFM thành bảng; HTML thô hiện thành chữ; không phần tử
  `img`; liên kết thành chữ — Q14); dòng `generator` + `version` dưới panel; không highlight.
- M3. Hỏi đáp: ô câu hỏi + nút `Hỏi`; **không** tự gửi khi mở trang; trong lúc chờ hiện `Đang hỏi trợ lý…`; câu
  `supported = false` có nền cảnh báo và chữ `Chưa kiểm chứng`; `insufficient_evidence` hiện `Không đủ bằng chứng`;
  `[n]` bấm được: `node_ids` khác rỗng → `setHighlight(node_ids)`; `chunk` mở đoạn trích; `transaction` / `alert` hiện
  `id` dạng chữ; nút `Bỏ highlight` gọi `clearHighlight()`. Feedback: hai nút chữ `Hữu ích` / `Chưa đúng` + ô ghi chú
  tuỳ chọn; 201 → `Đã ghi phản hồi`. 503 → `Trợ lý chưa sẵn sàng (cần Ollama và Neo4j)`; 502 → nhãn của `model_error`
  kèm thông điệp.
- M4. Draft narrative: nút `Soạn bản nháp` (không tự chạy); dải chữ cố định `DRAFT — requires investigator review` và
  `Bản nháp — cần investigator xem lại` do giao diện tự vẽ trên markdown; `meta.knowledge = "unavailable"` → dòng
  `Không tra được tài liệu tham chiếu`. Typology explainer nạp bằng `ApiPanel`: mỗi typology một khối (rule qua
  `RuleLabel`, `definition` nguyên văn, bảng giao dịch, đoạn trích), nút `Highlight` gọi `setHighlight` với hợp các
  `node_ids` của khối.
- M5. `slot-assistant` không có nút `Close`, `Clear`, `File STR`, `Đóng case`, `Áp dụng`; form disposition không tự điền
  từ câu trả lời.
- M6. `/metrics`: bốn panel độc lập — funnel (ba stage, chuyển đổi tách `Người quyết định` / `Mô phỏng từ ground truth`,
  dòng `Giả định: {minutes_per_alert} phút / alert` cạnh mọi số giờ, chữ `ước tính`), detections (bảng; dòng baseline
  tách riêng; null → `—`), auto-cleared (quần thể + `seed` + bảng mẫu), suppression (stage, theo rule, số item đáng ngờ
  bị suppress, bảng mẫu). Mỗi dòng `unavailable` hiện `part` (tiếng Việt) + `message`. Không cộng số giữa các panel.
- M7. Mọi lỗi API → trạng thái lỗi của `ApiPanel` (hoặc khối lỗi cùng kiểu cho `POST`), không hiện số nào.
- M8. `npm --prefix web run build` pass.

## Tiêu chí nghiệm thu
<!-- `settings`, `client(user=None, **env)`, SCHEMA, API-MINI như specs/ui-foundation.md (API-MINI = MINI-C + `run_cases`,
run 1, 5 case). MINI-GT = MINI-C + `insert_truth` (MINI_TRUTH của tests/cases/prio_helpers.py) + `run_cases`.
MINI-S = `load_minis` của tests/cases/supp_helpers.py + `run_cases` + `dispose(…, "C-C05-20260630")` (FALSE_POSITIVE,
analyst01) + `run_cases` (run 2). SCORED = API-MINI + `insert_scores(duck, score_run_id=1, run_id=1, model_id=1,
version="prio/logreg/1", rows=R5)` với R5 = (C-C03-20260305, 0.912345, 1, [{network_alerts, 1.0, 1.5}, {alerts, 2.0,
0.4}]), (C-C01-20260302, 0.8, 2, [{network_alerts, 1.0, 1.5}]), (C-C04-20260305, 0.8, 3, []), (C-C05-20260630, 0.2, 4,
[]), (C-C01-20260531, 0.1, 5, []). FAKES(llm, retriever, knowledge) = monkeypatch `aml.assistant.answering.default_llm`,
`.default_retriever`, `aml.assistant.narrative.default_knowledge` trả các fake của tests/assistant/an_helpers.py (R4, R0,
K3, LLM, RaisingLLM, FakeRetriever, FakeKnowledge, J, S_OK1, S_AMOUNT, S_OK2, N_OK). Q = "  Tài khoản A01 nhận tiền gì?  ".
ROWS(db) = tổng số dòng các bảng thường. C1 = C-C01-20260302, C5 = C-C05-20260630, NOPE = C-NOPE-20260101.
Mọi AC là pytest trong tests/api/ hoặc tests/metrics/, DuckDB-only. "(đo)" = giá trị đã đo bằng hàm thật trong prototype;
còn lại suy ra từ thiết kế. -->
- AC1: Given `config.yaml` của repo, SCHEMA và `client()`, When gọi `load_settings(environ={})`, duyệt `app.routes` và gọi mọi route mới, Then `settings.metrics.minutes_per_alert == 15`, `sample_size == 20`, `max_sample_size == 200`; `AML__METRICS__MINUTES_PER_ALERT=0` raise `pydantic.ValidationError` chứa `metrics minutes_per_alert must be >= 1`, `AML__METRICS__SAMPLE_SIZE=201` raise `ValidationError` chứa `metrics sample_size must be between 1 and max_sample_size`; `set(MockConfig.model_fields) == {"sample"}`; tập (method, đường dẫn) của app chứa đúng mười route mới `GET /api/v1/cases/scores`, `GET /api/v1/cases/{case_id}/summary`, `POST /api/v1/cases/{case_id}/narrative`, `GET /api/v1/cases/{case_id}/typologies`, `POST /api/v1/assistant/chat`, `POST /api/v1/assistant/feedback`, `GET /api/v1/metrics/funnel`, `GET /api/v1/metrics/detections`, `GET /api/v1/metrics/below-the-line/auto-cleared`, `GET /api/v1/metrics/suppression` ngoài các route của 9a / 9b, và không route nào khác bắt đầu bằng `/api/v1/assistant` hay `/api/v1/metrics`; trên SCHEMA năm route `GET` không tham số trên trả 200 với `source == "live"`, header `X-AML-Source == "live"`, và `GET /api/v1/cases/scores` có `feature == "case_scores"` (không bị route `/cases/{case_id}` bắt); `test_ac7_mock.py` vẫn xanh nguyên văn; với `client(user="nobody")` cả mười route (thân hợp lệ cho `POST`) trả 401 `unknown_user`, với `AML__UI__DEFAULT_USER=""` và không header trả 401 `missing_user`, và số dòng `audit_log` không đổi.
- AC2: Given SCORED, When gọi `GET /api/v1/cases/scores` bằng `analyst01` rồi `supervisor01`, Then cả hai trả 200, thân giống hệt từng byte, `feature == "case_scores"`, `meta == {}`; `data.run_id == 1`, `data.score_run_id == 1`, `data.model_version == "prio/logreg/1"`, `data.queue == 5`; (`case_id`, `score`, `queue_rank`) của `data.scores` theo thứ tự là (`C-C03-20260305`, 0.912345, 1), (`C-C01-20260302`, 0.8, 2), (`C-C04-20260305`, 0.8, 3), (`C-C05-20260630`, 0.2, 4), (`C-C01-20260531`, 0.1, 5); phần tử đầu bằng đúng `{"case_id": "C-C03-20260305", "score": 0.912345, "queue_rank": 1, "model_version": "prio/logreg/1", "top_features": [{"feature": "network_alerts", "value": 1.0, "contribution": 1.5}, {"feature": "alerts", "value": 2.0, "contribution": 0.4}]}` (đo, qua `load_case`); với mọi phần tử `s`, `s == {"case_id": s["case_id"], **load_case(duck, s["case_id"]).score}`; `ROWS(duck)` không đổi; sau `insert_scores` lần chấm 2 (`score_run_id=2`) với cùng R5 trừ `C-C05-20260630` có `score = 0.95`, `queue_rank = None` và `C-C01-20260531` có hạng 4, thì `data.score_run_id == 2`, `data.queue == 4` và phần tử cuối là `C-C05-20260630` với `queue_rank is None`; sau `run_cases` (run 2) thì `data == {"run_id": 2, "score_run_id": null, "model_version": null, "queue": 0, "scores": []}` (đo: view rỗng); và Given SCHEMA, Then `data == {"run_id": null, "score_run_id": null, "model_version": null, "queue": 0, "scores": []}`.
- AC3: Given API-MINI, When gọi `GET /api/v1/cases/C-C01-20260302/summary`, Then trả 200 với `source == "live"`, `feature == "case_summary"`, `meta == {"pii": "masked"}` và `data` bằng đúng `dataclasses.asdict(summarize(duck, settings, C1))` với `citations` là list: `generator == "template"`, `version == "summary/v1"`, `language == "en"`, `watermark == TEMPLATE_WATERMARK`, `citations == ["STRUCTURING|A01|2026-03-02T09:00:00", "NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00", "RAPID_MOVEMENT|A02|2026-04-20T08:00:00"]` (đo), markdown bắt đầu bằng `# Case C-C01-20260302\n\n> TEMPLATE SUMMARY (summary/v1): generated from stored case data without an LLM. It is not a disposition.\n` và chứa `| C01 | Nguyen T. C. |` (đo) nhưng không chứa `customers.full_name` của `C01`; `client(user="supervisor01")` trả cùng thân, `meta.pii == "masked"` và `audit_log` không thêm dòng nào; `?language=en` cho cùng `data`; `?language=vi` trả 422 `invalid_request` với `message == "language 'vi' is not available in the template generator"` (đo); `GET …/C-C05-20260630/summary` có `data.citations == ["SCREENING|C05|WL2"]` (đo); `GET …/C-NOPE-20260101/summary` trả 404 `not_found` chứa `unknown case_id`; với `AML__CASES__SUMMARY__GENERATOR=llm` và FAKES(llm=`RaisingLLM(AssertionError())`) vẫn trả `generator == "template"` và LLM giả không nhận lời gọi nào; và `ROWS(duck)` trước và sau mọi lời gọi trên bằng nhau.
- AC4: Given API-MINI và FAKES(llm=`LLM(J(S_OK1, S_AMOUNT, S_OK2))`, retriever=`R4()`), When `POST /api/v1/assistant/chat` với `{"case_id": "C-C01-20260302", "question": Q}`, Then trả 200 với `content-type` bắt đầu bằng `application/json`, `source == "live"`, `feature == "assistant"`, `meta == {"pii": "masked"}`, và `data` (đo) có `answer_id == "ans-9504e4efe5dd"`, `case_id == "C-C01-20260302"`, `question == "Tài khoản A01 nhận tiền gì?"`, `language == "vi"`, `status == "answered"`, `[s["supported"] for s in sentences] == [true, false, true]`, `[s["citations"] for s in sentences] == [[1], [1], [2]]`, `citations` bằng đúng `[{"n": 1, "kind": "transaction", "id": "T01", "label": "transaction T01", "node_ids": ["A01"], "txn_ids": ["T01"], "excerpt": null}, {"n": 2, "kind": "chunk", "id": "KB-TYP-001#003", "label": "chunk KB-TYP-001#003", "node_ids": [], "txn_ids": [], "excerpt": "Structuring: repeated cash deposits just under the reporting threshold of 400,000,000 VND."}]`, `retrievers == ["case_graph", "knowledge", "text2cypher"]`, `validation == {"sentences": 3, "supported": 2, "unsupported": 1}`, `model == "fake-chat"`, `prompt_version == "answer/v1"`; retriever giả được gọi đúng 1 lần với `case_id="C-C01-20260302"` và `actor="analyst01"`; `audit_log` thêm đúng 1 dòng: `module='assistant'`, `entity_type='case'`, `entity_id='C-C01-20260302'`, `decision='ANSWERED'`, `actor='analyst01'`, `details.answer_id == "ans-9504e4efe5dd"`; bằng `supervisor01` dòng đó có `actor='supervisor01'`; với retriever `R0()` và câu `Ai là người hưởng lợi?` trả 200 với `answer_id == "ans-10ef7b070a8a"`, `status == "insufficient_evidence"`, `sentences == []`, `citations == []` (đo) và 1 dòng `INSUFFICIENT_EVIDENCE`; mỗi thân `"question": "   "`, thiếu `question`, `question` 1001 ký tự, `"language": "fr"`, thiếu `case_id`, thêm `"actor": "boss"` trả 422 `invalid_request`; `"case_id": "C-NOPE-20260101"` trả 404 `not_found` chứa `unknown case_id`; trong bảy trường hợp lỗi đó retriever giả không được gọi và `audit_log` không đổi; LLM `LLM("nope", "nope again")` trả 502 với thân bằng đúng `{"error": {"code": "model_error", "message": "model output is not valid JSON after 2 attempt(s)"}}` và đúng 1 dòng mới `decision='FAILED'` (của 8c, đo); `RaisingLLM(OllamaUnavailableError("cannot reach Ollama"))` và retriever `FakeRetriever(error=RetrievalUnavailableError("neo4j not available: x"))` mỗi cái trả 503 với thân bằng đúng `{"error": {"code": "unavailable", "message": "service unavailable"}}` và `audit_log` không đổi (đo: 8c không ghi); và số dòng `case_dispositions`, `cases`, `case_runs` không đổi qua mọi lời gọi.
- AC5: Given API-MINI và FAKES(llm=`LLM(N_OK)`, knowledge=`K3()`), When `POST /api/v1/cases/C-C01-20260302/narrative` với `{}` và `GET /api/v1/cases/C-C01-20260302/typologies`, Then narrative trả 200 với `feature == "assistant"`, `meta == {"pii": "masked", "knowledge": "ok"}`, `data` có đúng hai khoá `narrative`, `citations`; `data.narrative` có đúng bảy khoá với `case_id == "C-C01-20260302"`, `generator == "llm"`, `version == "narrative/v1"`, `language == "vi"`, `watermark == "DRAFT — requires investigator review"` (bằng `aml.assistant.narrative.DRAFT_WATERMARK`), `citations == ["G-C01", "STRUCTURING|A01|2026-03-02T09:00:00", "A01"]` (đo) và bằng `[c["id"] for c in data["citations"]]`; `[c["kind"] for c in data["citations"]] == ["node", "alert", "node"]`, citation `alert` có `node_ids == []`, citation `A01` có `node_ids == ["A01", "G-C01"]` (đo); markdown bắt đầu bằng `# Case C-C01-20260302\n\n> DRAFT — requires investigator review\n`, các dòng `## ` theo thứ tự là `## Subject`, `## Activity timeline`, `## Matched typologies`, `## Red flags`, `## Suggested next step`, chứa dòng `- [CHƯA KIỂM CHỨNG] Ngày 2026-03-09 tài khoản A01 nhận 999,000,000 VND. [2]` và dòng `Draft narrative/v1; model fake-chat; case run 1; 4 of 5 sentence(s) verified.` (đo); `audit_log` thêm đúng 1 dòng `decision='NARRATIVE_DRAFTED'`, `actor='analyst01'`; thân `{"language": "fr"}` và `{"disposition": "SUSPICIOUS"}` trả 422, case NOPE trả 404, cả ba không thêm dòng audit; LLM `LLM("x", "y")` trả 502 `model_error` với `message == "narrative model output is not valid JSON after 2 attempt(s)"` và không thêm dòng audit (đo); `RaisingLLM(OllamaUnavailableError("x"))` trả 503 `unavailable`; knowledge `FakeKnowledge(error=RetrievalUnavailableError("x"))` vẫn trả 200 với `meta.knowledge == "unavailable"`; typologies trả 200 với `meta == {"pii": "masked", "knowledge": "ok"}` và `data` bằng đúng `explain_typology(duck, settings, C1, llm=…, knowledge=K3()).as_dict()` (đo): `[t["typology"] for t in typologies] == ["rapid_movement", "round_tripping", "structuring"]`, `rule_ids` lần lượt `["RAPID_MOVEMENT"]`, `["NET_CYCLE"]`, `["STRUCTURING"]`, `txn_id` lần lượt `["T05", "T06"]`, `["T02", "T03", "T04"]`, `["T01"]`, dòng `T01` bằng `{"txn_id": "T01", "txn_ts": "2026-03-02T09:00:00", "from_account_id": null, "to_account_id": "A01", "amount_vnd": 390000000, "channel": "CASH"}`, citation `T05` có `node_ids == ["EXT-01", "A02"]` (tài khoản ngoài giữ nguyên — Q3), mỗi khối có đúng 1 `chunks` với `chunk_id == "KB-TYP-001#003"`; LLM giả của typologies không nhận lời gọi `chat` nào; typologies của C5 trả `typologies == []`, của NOPE trả 404; knowledge hỏng cho 200 với mọi `chunks == []` và `meta.knowledge == "unavailable"` (đo); và typologies không thêm dòng `audit_log` nào.
- AC6: Given API-MINI sau lời gọi chat đầu tiên của AC4 (`ans-9504e4efe5dd`), When `POST /api/v1/assistant/feedback` và gọi `record_feedback` trực tiếp, Then thân `{"answer_id": "ans-9504e4efe5dd", "rating": "down", "comment": "câu 2 sai số tiền"}` trả 201 với `source == "live"`, `feature == "assistant"`, `data == {"answer_id": "ans-9504e4efe5dd", "rating": "down", "actor": "analyst01"}` và `audit_log` thêm đúng 1 dòng `module='assistant'`, `entity_type='answer'`, `entity_id='ans-9504e4efe5dd'`, `decision='ANSWER_RATED'`, `reason='answer ans-9504e4efe5dd rated down by analyst01'`, `version='feedback/v1'`, `actor='analyst01'`, `details == {"answer_id": "ans-9504e4efe5dd", "rating": "down", "comment": "câu 2 sai số tiền"}`; gửi lại với `"rating": "up", "comment": "   "` bởi `supervisor01` trả 201 và thêm dòng thứ hai có `details.comment is None`, `actor='supervisor01'`; `"answer_id": "ans-000000000000"` trả 404 `not_found` với `message == "unknown answer_id ans-000000000000"`; `answer_id` của một lời gọi chỉ có dòng `FAILED` (AC4) cũng trả 404; `"rating": "meh"`, `"answer_id": "x"`, `comment` 1001 ký tự, thiếu `answer_id`, thêm `"actor": "boss"` trả 422; các lời gọi lỗi không thêm dòng audit nào; `record_feedback(duck, settings, "ans-9504e4efe5dd", "up", comment=None, actor=settings.audit.system_actor)` raise `FeedbackError` chứa `feedback needs a human actor`; và số dòng `case_dispositions`, `cases` không đổi.
- AC7: Given MINI-GT, When gọi `GET /api/v1/metrics/funnel` và `aml.metrics.funnel(duck, settings)`, Then response trả 200 với `feature == "metrics_funnel"` và `data` bằng đúng kết quả của hàm; `data.case_run == {"run_id": 1, "as_of": "2026-06-30"}`; `minutes_per_alert == 15`; `[s["tool"] for s in stages] == ["screening_tuning", "suppression", "consolidation"]`; stage `suppression` bằng đúng `{"tool": "suppression", "before_label": "alert items", "after_label": "active alert items", "before": 9, "after": 9, "removed": 0, "reduction_pct": 0.0, "hours_saved": 0.0}`; stage `consolidation` bằng đúng `{"tool": "consolidation", "before_label": "active alert items", "after_label": "cases", "before": 9, "after": 5, "removed": 4, "reduction_pct": 44.44, "hours_saved": 1.0}`; stage `screening_tuning` có năm số null và `unavailable == [{"part": "screening_tuning", "message": "watchlist is empty; run `aml load` first"}]` (đo); `total_hours_saved == 1.0`; `alert_to_case == {"alerts": 7, "items": 9, "cases": 5, "cases_per_alert": 0.7143}` (đo); `case_to_suspicious` có `decided == 0`, `rate is None` và cả hai `by_origin` bằng `{"decided": 0, "suspicious": 0, "false_positive": 0}`; với `AML__METRICS__MINUTES_PER_ALERT=30` stage `consolidation` có `hours_saved == 2.0`; sau `POST /api/v1/cases/C-C05-20260630/disposition` `{"disposition": "FALSE_POSITIVE", "reason": "name only match"}` bởi `analyst01` và `record_disposition(duck, settings, "C-C03-20260305", "SUSPICIOUS", reason="sim", actor="simulated_analyst", origin="SIMULATED")` thì `case_to_suspicious == {"decided": 2, "suspicious": 1, "false_positive": 1, "rate": 0.5, "by_origin": {"HUMAN": {"decided": 1, "suspicious": 0, "false_positive": 1}, "SIMULATED": {"decided": 1, "suspicious": 1, "false_positive": 0}}}`; Given MINI-S, Then stage `suppression` có `before == 11`, `after == 10`, `removed == 1`, `reduction_pct == 9.09`, `hours_saved == 0.2` và stage `consolidation` có `before == 10`, `after == 4`, `removed == 6`, `reduction_pct == 60.0`, `hours_saved == 1.5` (số đếm đo); Given `evaluate` được monkeypatch trả bảng của `results/phase3/screening_eval.csv`, Then stage `screening_tuning` bằng đúng `{"tool": "screening_tuning", "before_label": "fuzzy baseline pairs", "after_label": "two-tier ALERT + REVIEW pairs", "before": 4436, "after": 72, "removed": 4364, "reduction_pct": 98.38, "hours_saved": 1091.0}`; Given SCHEMA, Then trả 200 với `case_run is None`, ba stage đều có năm số null, `total_hours_saved is None`, `alert_to_case` bốn null và `unavailable` bằng đúng `[{"part": "screening_tuning", "message": "customers is empty; run `aml load` first"}, {"part": "suppression", "message": "no case run yet: run `aml cases build` first"}, {"part": "consolidation", "message": "no case run yet: run `aml cases build` first"}]`; và `ROWS(duck)` trước và sau các lời gọi `GET` bằng nhau.
- AC8: Given MINI-GT, When gọi `GET /api/v1/metrics/detections`, Then trả 200 với `feature == "metrics_detections"`, `data` bằng đúng `aml.metrics.detections(duck, settings)`; `rows` có đúng 9 phần tử với (`source`, `detection`) theo thứ tự (`RULE`, `STRUCTURING`), (`RULE`, `RAPID_MOVEMENT`), (`RULE`, `HIGH_VELOCITY`), (`RULE`, `FAN_IN`), (`RULE`, `FAN_OUT`), (`RULE`, `DORMANT_REACTIVATION`), (`NETWORK`, `NET_SHARED_ATTRIBUTE`), (`NETWORK`, `NET_CYCLE`), (`NETWORK`, `NET_HUB`); dòng `STRUCTURING` bằng đúng `{"source": "RULE", "detection": "STRUCTURING", "baseline": false, "target_typology": "structuring", "alerts": 1, "true_positives": 1, "false_positives": 0, "fp_rate": 0.0, "precision": 1.0, "recall": 1.0, "scenarios": 1, "detected": 1}`; dòng `RAPID_MOVEMENT` có `alerts == 1`, `true_positives == 0`, `false_positives == 1`, `fp_rate == 1.0`, `precision == 0.0`, `recall is None`, `scenarios == 0`; dòng `HIGH_VELOCITY` có `alerts == 0`, `fp_rate`, `precision`, `recall`, `scenarios`, `target_typology` đều null; dòng `FAN_OUT` có `true_positives == 1`, `fp_rate == 0.0`; dòng `NET_CYCLE` có `alerts == 1`, `true_positives == 0`, `false_positives == 1`, `recall == 0.0`, `scenarios == 1`, `detected == 0` (đầu vào đo); mọi số đếm là `int` và không giá trị nào là NaN; `unavailable == [{"part": "screening", "message": "watchlist is empty; run `aml load` first"}]`; Given `evaluate` monkeypatch trả bảng của `results/phase3/screening_eval.csv`, Then `rows` có 13 phần tử, bốn phần tử cuối có `source == "SCREENING"` và `detection` lần lượt `exact`, `fuzzy`, `two_tier_alert`, `two_tier`, dòng `fuzzy` bằng đúng `{"source": "SCREENING", "detection": "fuzzy", "baseline": true, "target_typology": null, "alerts": 4436, "true_positives": 25, "false_positives": 4411, "fp_rate": 0.9944, "precision": 0.0056, "recall": 1.0, "scenarios": 25, "detected": 25}`, dòng `two_tier` có `baseline == false`, `alerts == 72`, `false_positives == 47`, `fp_rate == 0.6528`, và `unavailable == []`; và Given SCHEMA, Then trả 200 với 6 dòng `RULE` có `alerts == 0` và `unavailable == [{"part": "network", "message": "no network run yet; run `aml network` first"}, {"part": "screening", "message": "customers is empty; run `aml load` first"}]` (đo).
- AC9: Given MINI-GT, When gọi `GET /api/v1/metrics/below-the-line/auto-cleared` và `GET /api/v1/metrics/suppression`, Then auto-cleared trả 200 với `feature == "metrics_auto_cleared"` và `data == {"population": 1, "ground_truth_available": true, "true_hits_in_population": 0, "seed": 42, "sample_size": 1, "true_hits_in_sample": 0, "sample": [{"cif": "C06", "entry_id": "WL3", "list_type": "PEP", "final_score": 60.0, "reason": "test reason", "truth": "NOT_A_HIT"}]}` (đo); `?size=0` và `?size=201` trả 422 `invalid_request`; thêm hai dòng `ground_truth` (`GT-PEP-0001`, `pep_hit`, đúng, `customer`, `C06`) và (`GT-PEP-0001`, `pep_hit`, đúng, `watchlist_entry`, `WL3`) → `true_hits_in_population == 1`, `sample[0].truth == "TRUE_HIT"`; trên API-MINI (không ground truth) → `ground_truth_available == false`, ba trường truth null; thêm 30 dòng `AUTO_CLEARED` (`cif` `X01`..`X30`, `entry_id` `WL9`, cùng `run_id` với dòng hiện hành) → `?size=5` trả `population == 31` và `[r["cif"] for r in sample] == ["X02", "X13", "X18", "X21", "X30"]` (đo: `sorted(default_rng(42).choice(31, 5, replace=False)) == [2, 13, 18, 21, 30]`), hai lần gọi giống hệt từng byte, `AML__SEED=7` cho `data.seed == 7`; suppression trên MINI-GT trả 200 với `feature == "metrics_suppression"`, `population == 0`, `sample == []`, `by_rule == {"GOOD_GUY": 0, "HIBERNATION": 0}`, `suspicious_suppressed == 0`; Given MINI-S, Then suppression có `case_run == {"run_id": 2, "as_of": "2026-06-30"}`, `stage` bằng stage `suppression` của funnel cùng DB, `by_rule == {"GOOD_GUY": 1, "HIBERNATION": 0}`, `population == 1`, `ground_truth_available == false`, `suspicious_suppressed is None` và `sample == [{"item_key": "SCREENING|C05|WL2", "golden_customer_id": "G-C05", "source": "SCREENING", "rule_id": "SCREENING_REVIEW", "suppression_rule": "GOOD_GUY", "suppression_reason": "good-guy list: C05 x WL2 cleared on 2026-06-30 by analyst01 (case C-C05-20260630); valid until 2027-06-30; customer and watchlist entry unchanged", "truth": null}]` (đo); Given MINI-S + `insert_truth`, Then `ground_truth_available == true`, `suspicious_suppressed == 1` và `sample[0].truth == "SUSPICIOUS"` (đo: cặp `C05` × `WL2` thuộc `truth_pairs`); Given SCHEMA, Then suppression trả 200 với `case_run is None`, `by_rule is None`, `population == 0` và `unavailable == [{"part": "suppression", "message": "no case run yet: run `aml cases build` first"}]`; và `ROWS(duck)` trước và sau mọi lời gọi `GET` bằng nhau.
- AC10: Given mã nguồn của repo và API-MINI, When đọc file dạng văn bản, chạy subprocess import và gọi mọi route `GET` của spec này bằng `analyst01` lẫn `supervisor01`, Then số dòng của `audit_log`, `cases`, `case_alerts`, `case_dispositions`, `case_runs`, `case_scores` trước và sau bằng nhau; `import aml.metrics, aml.assistant.feedback` trong subprocess không nạp `fastapi`; không file nào dưới `src/aml/metrics/` chứa `aml.api`, `audit(`, `insert_df`, `.execute(` hay `run_script`; không file nào dưới `src/aml/api/routers/` chứa `audit(`, `record_disposition` hay `run_cases`; `src/aml/api/routers/assistant.py` và `src/aml/api/assistant.py` không chứa `record_disposition`, `run_cases`, `disposition` hay `status =`; `src/aml/api/fixtures/` chỉ có `sample.json` và không tồn tại `src/aml/api/live.py`, `contracts.py`, `sse.py`, `mockdata/`; `web/package.json` có `react-markdown` và `remark-gfm` trong `dependencies` và không có `rehype-raw`; chỉ `web/src/components/Markdown.tsx` chứa chuỗi `react-markdown`; không file nào dưới `web/src/` chứa `dangerouslySetInnerHTML`, `innerHTML` hay `rehype-raw`; không file nào dưới `web/src/pages/` chứa `fetch(` hay `EventSource`; chuỗi `Dữ liệu mẫu` chỉ có trong `web/src/components/SourceBadge.tsx`; bốn `data-testid` `slot-case-score`, `slot-case-summary`, `slot-assistant`, `graph-highlight-missing` vẫn có trong `web/src/`; `useCaseHighlight` xuất hiện trong ít nhất một file dưới `web/src/pages/case/` ngoài `CaseGraphPanel.tsx` và `TracePanel.tsx`; và các tên kiểu `CaseScores`, `Answer`, `Citation`, `DraftNarrative`, `Funnel`, `DetectionRow`, `SuppressionMetrics` xuất hiện trong `web/src/api/insightTypes.ts`.

## Ngoài phạm vi
- Mọi mock / fixture / cờ `ui.mock.*` mới, `aml.api.live`, `contracts.py`, SSE và sự kiện `token` (Q2).
- Test tự động cho frontend (Vitest, Playwright, `npm test`) — quyết định của người dùng.
- Trang và thành phần của 9b (bố cục case detail, đồ thị, highlight, trace, screening review, DQ, benchmark); highlight
  theo `txn_id`; highlight từ `citations` (`item_key`) của summary template.
- Hiện memo category của 8d trong bảng giao dịch và nút relabel memo (Q12 — spec riêng).
- Mọi hành động của assistant hay mô hình lên case: tự đóng, clear, file STR, đề xuất disposition bấm-một-lần, tự điền
  form, lọc case điểm thấp khỏi hàng đợi.
- Assistant: hội thoại nhiều lượt, lưu bản nháp narrative, hiển thị Cypher đã sinh, chọn retriever / mode từ UI, hỏi
  không gắn case, trang đánh giá golden set (8e), đọc lại feedback (chỉ ghi).
- Dashboard: metrics của mô hình ưu tiên (ROC-AUC, model card), Isolation Forest / screening học được (Phase 7b), mẫu
  below-the-line của khách hàng không alert, xu hướng theo thời gian, xuất CSV / PDF, cache `evaluate`, ghi số dashboard
  vào README hay `results/` (số README vẫn do lệnh CLI của từng phase sinh ra).
- DDL mới; sửa `src/aml/cases/` hay module 8c; lệnh CLI mới; AC trên Oracle (endpoint chạy được trên Oracle nhờ SQL
  theo backend nhưng không có AC); đo trên `large`.

## Giả định
- **Đã đo** (prototype ngoài repo, 2026-10-14): mọi giá trị đánh dấu "(đo)"; số liệu Hiện trạng; các thông điệp lỗi của
  7d / 8c / evaluator; `round(0.25, 1) == 0.2`, `round(100 * 4 / 9, 2) == 44.44`, `round(100 / 11, 2) == 9.09`.
  **Suy ra, chưa đo**: mọi hành vi router (mã HTTP, `meta`, thân lỗi mới `model_error`, thứ tự route), `aml.metrics`
  (các ánh xạ từ evaluator / bảng đã đo), `record_feedback` và SQL tra `answer_id`, SQL Oracle, AC10, mọi thứ của
  `web/`. Lệch khi hiện thực do chi tiết thư viện → cập nhật spec, không đổi quy ước.
- Số `small` (bản sao `ui_check.duckdb`) chỉ để định hướng thiết kế, không vào README.
- Tên trong summary là bản đã che của `customers_masked` (7d); không cần `PII_VIEWED`.
- Câu hỏi và ghi chú feedback do investigator gõ là đầu vào tin cậy, lưu nguyên văn trong `details` (như 8c lưu
  `question`); không bao giờ vào `reason`.
- Demo thật của chat / narrative cần Ollama và (chat) Neo4j đang chạy; khi tắt, UI hiện 503 rõ ràng — không có đường
  thay thế bằng dữ liệu mẫu.
- `funnel` / `detections` gọi `evaluate` mỗi request (1,79 giây trên `small`, đo ở bản nháp); chấp nhận cho demo.
- Disposition mô phỏng của 7c (`origin = 'SIMULATED'`) là dòng thật; hiển thị tách theo `origin`.
- Thông điệp lỗi, `reason`, nhãn stage bằng tiếng Anh như nguồn; chữ giao diện tiếng Việt (Q13 của 9a).

## Câu hỏi mở
<!-- [x] = người dùng đã trả lời ở bản nháp 2026-10-13, mang sang nguyên ý. Bản nháp Q1, Q6, Q8, Q16 (mock suppression, builder mock, số cờ mock, kịch bản mock) không còn áp dụng: bỏ. -->
- [x] Q1. Giữ `id: ui-mock-pages` và tên file, hay đổi tên (vd `ui-insight-pages`)? — đề xuất mặc định: **giữ id và tên file**, chỉ đổi tiêu đề. Lý do: `ui-foundation`, `ui-live-pages`, `assistant-answering` dẫn tới `ui-mock-pages` ở nhiều chỗ; đổi tên phải sửa ba spec đã duyệt mà không thêm gì. Phương án thay thế: đổi tên + sửa các dẫn chiếu trong cùng commit. — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q2. Chat stream (SSE) hay JSON? — đề xuất mặc định: **JSON thường** (`POST` → envelope, `data = Answer`). Lý do (đo): `answer_events` của 8c chỉ phát `start` rồi `final`, và `start` chỉ có sau khi câu trả lời đã xong, nên SSE không cho người dùng thấy gì sớm hơn mà thêm `sse.py`, `apiStream`, và một đường lỗi giữa luồng. Bản nháp Q9 (SSE + `token`) đã được trả lời "cho bản mock; Phase 8 xác nhận hoặc sửa" — Phase 8 chọn không có `token`. Phương án thay thế: giữ SSE theo hợp đồng bản nháp với 0 sự kiện `token` (để sau này stream từng câu đã kiểm chứng mà không đổi frontend). — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q3. Có lọc `Citation.node_ids` chỉ còn tài khoản nội bộ như bản nháp yêu cầu không? — đề xuất mặc định: **không lọc**, trả nguyên `node_ids` của 8c. Lý do (đo): đồ thị của 9b vẽ node `external_account` với `id` = `account_id` (vd `EXT-01`), nên highlight tài khoản ngoài đúng nghĩa; id ngoài khung (bị cắt bởi `graph_max_counterparties`) đã có `graph-highlight-missing`. Phương án thay thế: bộ nối lọc theo bảng `accounts` (cần đọc DB, và citation tiền mặt / ra ngoài có thể còn `node_ids` rỗng). — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q4. **(cần người dùng quyết — xung đột với câu trả lời Q3 của bản nháp)** Stage consolidation đếm theo gì? Bản nháp chọn **alert phân biệt** (`small` lúc đó 339 → 335). Đo lại trên bản sao `small` sau 7b-supp: 303 `item_key` `ACTIVE` phân biệt → **309 case** — `removed = −6`, vì một alert network thuộc nhiều golden customer và case là theo golden customer. — đề xuất mặc định: **đếm item** (alert × golden customer, `case_runs.active`): 439 → 309 (giảm 29,61 %), và funnel nối liền 475 → 439 → 309 cùng đơn vị với stage suppression; `alerts` vẫn có trong `alert_to_case`. Phương án thay thế: giữ alert phân biệt và hiện số âm trung thực (dễ bị đọc thành "consolidation làm tăng việc"); hoặc bỏ số giờ của stage này. — Trả lời: **đếm item** (người dùng chọn 2026-10-14, thay câu trả lời Q3 của bản nháp).
- [x] Q5. `record_feedback` có kiểm `answer_id` tồn tại không? — đề xuất mặc định: **có**: phải là `details.answer_id` của một dòng `ANSWERED` / `INSUFFICIENT_EVIDENCE` của 8c, không thì 404; chấm lại được (mỗi lần một dòng, không sửa dòng cũ); `comment` ≤ 1000 ký tự, lưu ở `details`. Lý do: audit không được trỏ tới câu trả lời không có thật; SQL tra theo backend vì hàm JSON khác nhau. Phương án thay thế: chỉ kiểm dạng `^ans-[0-9a-f]{12}$` (không cần SQL theo backend, nhưng chấp nhận id bịa). — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q6. Panel summary dùng bộ sinh nào khi `cases.summary.generator` khác `template`? — đề xuất mặc định: **luôn `template`** cho `GET …/summary`; bản nháp của LLM chỉ đi qua `POST …/narrative` (có audit `NARRATIVE_DRAFTED`, có nút bấm). Lý do: `summarize(generator="llm")` của 7d không ghi audit và một `GET` tự gọi LLM khi mở trang. Phương án thay thế: theo config. — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q7. Bảng case sắp theo điểm thế nào khi `GET /cases` phân trang theo thời gian? — Trả lời (bản nháp): trang nạp hết các trang `GET /cases` (`limit = max_page_size`) và toàn bộ `GET /cases/scores`, ghép và sắp phía client theo `queue_rank`; phân trang hiển thị phía client.
- [x] Q8. Giả định phút-mỗi-alert? — Trả lời (bản nháp): một giá trị `metrics.minutes_per_alert: 15` cho mọi đơn vị bị loại, luôn hiện cạnh số giờ kèm chữ `ước tính`.
- [x] Q9. Mã lỗi khi Ollama / Neo4j tắt và khi mô hình hỏng? — đề xuất mặc định: tắt dịch vụ → **503 `unavailable`** (`service unavailable`, dùng handler chung của 9a; `RetrievalUnavailableError` được bộ nối dịch sang cùng mã); mô hình trả JSON hỏng / `LLMError` → **502 `model_error`** kèm thông điệp của 8c (không chứa PII). Lý do: tách "chưa bật dịch vụ" (người demo bật Ollama / Neo4j) khỏi "mô hình trả sai" (thử lại). Phương án thay thế: cả hai là 503; hoặc lỗi mô hình là 500. — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q10. "FP rate" của một detection? — Trả lời (bản nháp): (`benign` + `unlabelled`) / `alerts` với rule / network, `fp` / `flagged` với screening.
- [x] Q11. Mẫu của panel suppression chọn thế nào và `truth` của item `RULE` / `NETWORK` lấy từ đâu? — đề xuất mặc định: chọn như auto-cleared (`default_rng(seed).choice` trên quần thể sắp theo `item_key`, `golden_customer_id`); `truth` theo đúng luật nhãn item của 7c (`truth_labels`) áp cho item `SUPPRESSED` (SQL mới, bản `SUPPRESSED` của `cases/truth_accounts.sql`). Đường `RULE` / `NETWORK` chưa đo được (fixture không có item rule bị suppress có ground truth). Phương án thay thế: `n` item đầu theo thứ tự, và `truth` chỉ cho `SCREENING` (null cho rule / network). — Trả lời: theo đề xuất mặc định (người dùng xác nhận khi duyệt spec, 2026-10-14).
- [x] Q12. Có đưa memo category của 8d (`memo_labels_current`) vào bảng giao dịch của case và nút relabel (`relabel_memo`, cần actor + reason, audit `MEMO_RELABELLED`) vào 9c không? — đề xuất mặc định: **không**, làm spec nhỏ riêng (9d). Lý do: spec này đã đủ 10 AC; relabel là một endpoint quyết định mới (reason bắt buộc) và nối `txn_id` → `memo_key` cần lại phép chuẩn hoá memo của 8d; bản sao `small` hiện chưa có bảng memo. Phương án thay thế: thêm một cột chỉ-đọc `memo_category` vào `GET /cases/{id}/transactions` (đổi AC của 9b) ở 9c, relabel để sau. — Trả lời: **không**, làm spec riêng 9d sau 9c (người dùng chọn 2026-10-14).
- [x] Q13. Feedback có theo quy ước endpoint quyết định không? — Trả lời (bản nháp): bản thật trả 201 + 1 dòng audit có actor của request; **không** bắt buộc `reason` (ngoại lệ ghi ở S2); trường `actor` trong thân → 422.
- [x] Q14. Render markdown bằng gì? — Trả lời (bản nháp): `react-markdown` + `remark-gfm`, không `rehype-raw`; HTML thô thành chữ; không `img`; liên kết thành chữ.
- [x] Q15. Supervisor có thấy summary không che? — Trả lời (bản nháp): không; `meta.pii == "masked"` mọi role, không `PII_VIEWED`. Áp luôn cho hỏi đáp, narrative, explainer (8b / 8c chỉ đưa dữ liệu đã che).
- [x] Q16. Chuyển đổi case → suspicious có tính disposition mô phỏng? — Trả lời (bản nháp Q5): live, đọc `case_dispositions_current`, tách `HUMAN` / `SIMULATED`.
- [x] Q17. Giữ các phép kiểm quy ước `web/` bằng pytest đọc văn bản? — Trả lời (bản nháp): giữ (nửa sau của AC10).
- [x] Q18. "Không đủ bằng chứng" và hội thoại nhiều lượt? — Trả lời (bản nháp Q11, 8c đã hiện thực): `status = "insufficient_evidence"` với `sentences` / `citations` rỗng, giao diện hiện `Không đủ bằng chứng`; mỗi request một câu hỏi, không lịch sử.
- [x] Q19. Draft narrative đi qua đâu? — Trả lời (bản nháp Q12, 8c đã hiện thực `draft_narrative`): endpoint riêng `POST /cases/{case_id}/narrative`, trả `Narrative` 7 trường + `citations` chi tiết; không stream, không lưu.
