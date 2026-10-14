---
id: ml-governance
status: approved
approved_by: pthieu
---

# Phase 7b-iii — Thiên lệch chọn mẫu (mẫu below-the-line có nhãn ground truth) và quản trị model (model card, phiên bản trong audit, "không model nào tự đóng case")

## Bối cảnh
Mục 3 và 4 của "8b. Phase 7b" trong PROJECT_BRIEF.md. (1) **Thiên lệch chọn mẫu**: mô hình ưu tiên của 7c
(`specs/case-prioritization.md`) chỉ học và chỉ được đo trên **case đã có alert** — khách hàng không có alert không có dòng
nào, nên không ai biết model xếp hạng thế nào ở phía dưới đường cắt và đường cắt bỏ sót bao nhiêu. Spec này rút một
**mẫu ngẫu nhiên có seed của khách hàng không có alert** (mẫu below-the-line, viết tắt BTL), gán nhãn từ ground truth của
datagen, (a) **đo** model đang hiệu lực trên mẫu đó, (b) cho phép huấn luyện một **biến thể model mới** có thêm mẫu BTL
(phiên bản riêng `prio/<kind>+btl/<id>`, có audit — không đổi model đã lưu), và báo cáo hiệu năng **tách riêng theo quần
thể**. (2) **Quản trị model**: một **model card** cho mỗi model (ưu tiên case, phân loại memo 8d, Isolation Forest của
`specs/ml-anomaly.md`, phân loại match screening của `specs/screening-ml.md`) do lệnh CLI **sinh từ metadata đã lưu** —
không con số nào gõ tay; kiểm tra rằng **mọi dòng audit chứa điểm của model đều mang phiên bản model**; và một test
**chặn mọi đường code ML ghi disposition / đóng / clear**. Thứ tự hiện thực: 7b-i (anomaly), 7b-ii (screening ML), rồi
spec này. Người dùng: kiểm soát model / người phỏng vấn (card, báo cáo BTL), investigator (không đổi gì ở hàng đợi trừ
khi người dùng bật biến thể BTL).

### Hiện trạng đã kiểm (2026-10-14, seed 42)
Đo bằng script tạm ngoài repo (`uv run python <scratchpad>/measure_btl.py`): sinh Parquet TINY (300 CIF, 5 000 giao dịch,
cùng biến môi trường với fixture `tiny_parquet`) vào thư mục tạm, nạp vào một DuckDB tạm, chạy `run_er`, `run_screening`,
`run_monitoring`, `run_network`, `run_dq`, `run_cases` (`AML__CASES__GRAPH_FEATURES=networkx`, `as_of` 2026-06-30).
**Không đọc `data/aml.duckdb`** — mọi số `small` dưới đây là **ước lượng**, chưa chạy. Code của spec này chưa tồn tại.
- **Quần thể BTL trên TINY (đã đo)**: 300 CIF → 273 golden customer (`customer_golden` đủ 300 CIF); run 1 có 52 case của
  52 golden customer; **221** golden customer không có dòng `case_alerts` nào trong run 1 (định nghĩa Q1). Theo nhãn đề
  xuất (Q2), 60 golden customer là đáng ngờ, **8** trong số đó nằm trong quần thể BTL — cả 8 đều do tài khoản
  `rapid_movement` vai `destination` (5) / `source` (3); 54 golden customer BTL thuộc kịch bản lành tính.
- **Mẫu (đã đo)**: vị trí = `sorted(default_rng(42).choice(221, size=k, replace=False))` trên danh sách id tăng dần:
  `k = 50` → 3 đáng ngờ (`G-CIF00000201`, `G-CIF00000242`, `G-CIF00000300`), ba id đầu `G-CIF00000018`,
  `G-CIF00000019`, `G-CIF00000020`; `k = 20` → 0 đáng ngờ; `k = 100` → 3; `k = 200` → 8. `default_rng(42).choice(10,
  size=3, replace=False)` sắp tăng = `[0, 6, 9]`. Khoảng Wilson 95 % (z = 1.959964): 3/50 → (0.0206, 0.1622), 0/20 →
  (0.0, 0.1611); `round(221 × 3 / 50) = 13` khách bị bỏ sót ước lượng (thật: 8) — mẫu nhỏ, sai số lớn, phải in kèm khoảng.
- **Hệ quả thiết kế (suy ra)**: với `k = 20` mẫu không có ca đáng ngờ nào → ROC-AUC trên BTL là `None`; mọi báo cáo BTL in
  `n`, `n_suspicious`, khoảng tin cậy. Trên `small` tỉ lệ đáng ngờ BTL **chưa đo** (ước lượng vài phần nghìn đến vài phần
  trăm) → mặc định `sample_size` 200 (Q3) có thể chỉ cho 0–5 ca đáng ngờ.
- **Code hiện có (đọc tĩnh)**:
  - `src/aml/cases/labels.py` là nơi duy nhất của phase case đọc `ground_truth` (`truth_labels`, `_true_pairs`,
    `cases/truth_accounts.sql`) và là nơi duy nhất gọi `record_disposition` ngoài con người (`simulate_dispositions`,
    `origin = SIMULATED`). `src/aml/cases/chain.py` in `NOTE` / `POPULATION` = "alerted cases only; below-the-line
    customers are not sampled (Phase 7b)"; `tests/cases/test_prio_review_fixes.py` chỉ khẳng định chuỗi con
    `alerted cases only`.
  - `src/aml/metrics/samples.py` (9c) là **mẫu dashboard của phía đã có alert**: hit screening `AUTO_CLEARED` và item bị
    suppression — quần thể khác hẳn (khách hàng **có** alert nhưng bị lọc). Nó không huấn luyện, không đo model, không ghi
    gì; `specs/ui-mock-pages.md` để "mẫu below-the-line của khách hàng không alert" ngoài phạm vi. Spec này **không đổi**
    `aml.metrics`; chỉ dùng lại cách chọn `default_rng(seed).choice(..., replace=False)` qua một hàm thuần mới
    (`sample_indices` của 9c đọc `settings.metrics.sample_size` nên không dùng thẳng được).
  - Feature 7c (`aml.cases.features.case_features`) là hàm thuần của `CaseView`; khách hàng BTL không có case nên cần một
    **enrichment giả** dựng bằng chính các khối của `aml.cases.enrich` (KYC, CIF liên kết, DQ, `txn_activity`, network,
    lịch sử) với cửa sổ kết thúc ở `as_of` của lần chạy case. Feature memo dùng lại `count_memos` + truy vấn memo theo cửa
    sổ của `aml.memo.features`.
  - `fit_model` (7c) tính điểm out-of-fold bên trong và chỉ trả `metrics` gộp → cần một tham số tuỳ chọn để tách metric
    theo quần thể. `labelled_set` raise `not enough labelled cases` **trước** khi biết có mẫu BTL → biến thể BTL cần kiểm
    số lớp trên tập hợp.
  - `case_model_active` = dòng `model_id` lớn nhất; không có bước phê duyệt model (7c Q6 hoãn sang 7b).
- **Phiên bản model trên audit — rà tĩnh mọi `decision=` trong `src/aml`** (dòng chứa điểm / nhãn của model):

  | module / decision | `version` | Đủ? |
  |---|---|---|
  | `cases` / `PRIORITIZED` (mỗi case) | `prio/<kind>/<id>` + `details.model_id` | đủ |
  | `cases` / `MODEL_TRAINED`, `SCORING_RUN_COMPLETED` | phiên bản model | đủ |
  | `memo` / `MEMO_CLASSIFIED` (mỗi khoá) | `memo/v1` (phiên bản **prompt**) + `details.model` (tên LLM) | **G1**: danh tính model tách hai nơi |
  | `memo` / `MEMO_EVAL_COMPLETED` | `memo/v1`; tên LLM **chỉ trong `reason`**, `details` không có `model` | **G2**: thiếu |
  | `memo` / `MEMO_FEATURES_COMPARED` | `memo/v1`; hai model so sánh không được lưu | **G3**: chấp nhận (chỉ đo) |
  | `case_scores.model_version` | phiên bản model | đủ |
  | holdout của một lần chấm | chỉ trong `details.holdout` của `SCORING_RUN_COMPLETED` | **G4**: không có bảng; card đọc audit |
  | LLM memo | không lưu digest của model Ollama | **G5**: đổi model cùng tên không phát hiện được |

  Các dòng screening / monitoring / network là luật, không phải model. Anomaly và screening ML là của spec anh em.
- `specs/ml-anomaly.md`, `specs/screening-ml.md` **chưa có** trong `specs/` lúc kiểm; DDL cuối cùng là `190`; `200` và
  `210` để dành cho hai spec đó → spec này dùng **`220`**.
- **Chưa đo**: mọi metric ROC-AUC / PR-AUC trên BTL; giá trị feature của khách BTL; mọi thứ của `small`; Oracle; trạng
  thái run 2 của TINY-L (suy ra: run 2 vẫn chứa 52 case và item của chúng, nên quần thể BTL vẫn 221).

### Interface đề xuất (để test, CLI và Phase 9 gọi trực tiếp)
```python
# src/aml/common/config.py
class BelowTheLineConfig(BaseModel):
    enabled: bool  # aml score: rút mẫu BTL và huấn luyện biến thể +btl thay cho model 7c
    sample_size: int  # >= 1; khách hàng BTL mỗi mẫu (bị chặn bởi cỡ quần thể)


class PrioritizationConfig(BaseModel):  # 7c, thêm một trường
    below_the_line: BelowTheLineConfig


class GovernanceConfig(BaseModel):
    cards_dir: str  # thư mục card; tương đối với thư mục làm việc như memo.gold_path
    models: list[str]  # thứ tự card; mỗi phần tử thuộc MODEL_CARDS, không trùng


class MlConfig(BaseModel):  # section `ml:` của 7b-i; spec này thêm một trường
    governance: GovernanceConfig


# src/aml/cases/btl.py  (rút mẫu, gán nhãn, feature; nơi thứ hai đọc ground_truth)
BTL_VERSION = "btl/v1"
SUSPICIOUS, NOT_SUSPICIOUS = "SUSPICIOUS", "NOT_SUSPICIOUS"


def seeded_positions(seed: int, population: int, size: int) -> list[int]: ...  # thuần
def wilson_interval(
    k: int, n: int
) -> tuple[float | None, float | None]: ...  # thuần, z = 1.959964, làm tròn 4


@dataclass(frozen=True)
class BtlMember:
    golden_customer_id: str
    label: str  # SUSPICIOUS | NOT_SUSPICIOUS
    typologies: tuple[str, ...]  # tăng dần; () khi NOT_SUSPICIOUS
    reason: str


def btl_label(
    golden_customer_id: str, run_id: int, typologies: Sequence[str]
) -> BtlMember: ...  # thuần


@dataclass(frozen=True)
class BtlSample:
    sample_id: int
    run_id: int
    as_of: date
    seed: int
    requested: int  # sample_size đã yêu cầu
    population: int
    size: int  # min(requested, population)
    suspicious: int
    not_suspicious: int
    estimated_missed: int  # round(population * suspicious / size); 0 khi size = 0
    prevalence_ci95: tuple[float | None, float | None]
    members: tuple[BtlMember, ...]  # golden_customer_id tăng dần
    reused: bool  # True khi mẫu của (run_id, seed, requested) đã có


def btl_population(db: Database, run_id: int) -> list[str]: ...  # tăng dần
def draw_sample(
    db: Database, settings: Settings, *, size: int | None = None, actor: str | None = None
) -> BtlSample: ...
def write_btl_features(db: Database, settings: Settings, sample_id: int) -> int: ...
def read_btl_features(
    db: Database, settings: Settings, sample_id: int, *, memo: bool = False
) -> (
    pd.DataFrame
): ...  # index golden_customer_id tăng dần; cột FEATURES (+ MEMO_FEATURES khi memo=True)


# src/aml/cases/btl_model.py
@dataclass(frozen=True)
class BtlEvaluation:
    eval_id: int
    sample_id: int
    model_id: int
    version: str
    metrics: dict[
        str, Any
    ]  # ranking_metrics của 7c trên mẫu + {"population", "estimated_missed", "prevalence_ci95"}


@dataclass(frozen=True)
class BtlTrainingRun:
    training: TrainingRun  # của 7c; version "prio/<kind>+btl/<model_id>"
    sample_id: int
    alerted: tuple[int, int]  # (SUSPICIOUS, FALSE_POSITIVE) của case đã có disposition
    below_the_line: tuple[int, int]  # (SUSPICIOUS, NOT_SUSPICIOUS) của mẫu


def evaluate_btl(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> BtlEvaluation: ...
def train_with_btl(
    db: Database, settings: Settings, *, kind: str | None = None, actor: str | None = None
) -> BtlTrainingRun: ...


# src/aml/cases/model.py (7c) — thêm tham số tuỳ chọn, mặc định giữ nguyên hành vi
def fit_model(
    X, y, groups, cfg, *, seed, kind=None, populations: pd.Series | None = None
) -> TrainedModel: ...


# populations (index như X, giá trị "alerted" | "below_the_line") -> metrics thêm khoá
# "by_population": {tên: ranking_metrics trên điểm out-of-fold của nhóm dòng đó}


# src/aml/governance/cards.py  (render thuần + ghi file)
MODEL_CARDS = ("prioritization", "memo_classifier", "anomaly", "screening_match")
CARD_SOURCES: dict[
    str, str
]  # tên -> "module:hàm", cả bốn ở aml.governance.sources; anomaly_facts bọc dict của
# aml.ml.anomaly.card.card_facts (7b-i Q16); screening_match_facts đọc thẳng bảng screening_ml_* (7b-ii Q13).
# Mỗi adapter probe module của spec anh em (aml.ml.anomaly.card / aml.screening.ml.pipeline) qua importlib.
NEVER_ACTS = "This model never closes, clears, files or dispositions anything."


@dataclass(frozen=True)
class AuditCoverage:
    module: str
    decision: str
    rows: int  # dòng audit của decision đó
    with_version: int  # dòng mang đúng phiên bản của card


@dataclass(frozen=True)
class CardFacts:
    name: str  # một phần tử của MODEL_CARDS
    title: str
    version: str
    kind: str
    trained: str | None  # ISO UTC
    seed: int | None
    data_hash: str | None
    feature_version: str | None
    features: tuple[str, ...]
    source: str  # vd "case_models.model_id=1"
    intended_use: str
    oversight: str  # câu riêng của model, sau NEVER_ACTS
    data: tuple[str, ...]  # gạch đầu dòng
    metrics: tuple[tuple[str, str, str], ...]  # (quần thể, metric, giá trị đã định dạng)
    limitations: tuple[str, ...]
    audit: tuple[AuditCoverage, ...]


@dataclass(frozen=True)
class Skipped:
    name: str
    reason: str


@dataclass(frozen=True)
class CardReport:
    written: tuple[str, ...]  # đường dẫn
    skipped: tuple[Skipped, ...]
    stale: tuple[str, ...]  # chỉ ở chế độ check: file khác nội dung sinh ra


def render_card(facts: CardFacts) -> str: ...  # thuần, tất định
def collect_facts(
    db: Database, settings: Settings, names: Sequence[str]
) -> list[CardFacts | Skipped]: ...
def write_cards(
    db: Database,
    settings: Settings,
    *,
    out_dir: Path | None = None,
    names: Sequence[str] | None = None,
    check: bool = False,
    actor: str | None = None,
) -> CardReport: ...


# src/aml/governance/audit_check.py
@dataclass(frozen=True)
class ModelDecision:
    module: str
    decision: str
    registry: str  # "case_models" | "memo" | "anomaly_runs" | "screening_ml_models"
    rule_id: str | None = (
        None  # chỉ xét dòng có details.rule_id bằng giá trị này (ALERT của ML_ANOMALY)
    )


@dataclass(frozen=True)
class VersionGap:
    module: str
    decision: str
    entity_id: str
    event_ts: datetime
    problem: str  # "missing version" | "unknown version" | "missing details.model"


MODEL_DECISIONS: tuple[
    ModelDecision, ...
]  # 11 cặp của mục Thiết kế (6 của 7c / 8d, 2 của 7b-i, 3 của 7b-ii)


def version_gaps(db: Database, *, since: datetime | None = None) -> list[VersionGap]: ...


# src/aml/governance/guard.py
SCANNED: tuple[str, ...]  # glob tương đối với src/aml
ALLOWED_WRITERS: dict[str, str]  # module -> lý do; module trong đây không bị quét
FORBIDDEN_CALLS = (
    "record_disposition",
    "add_good_guys",
    "record_review",
    "simulate_dispositions",
    "run_cases",
)
FORBIDDEN_DECISIONS = (
    "SUSPICIOUS",
    "FALSE_POSITIVE",
    "TRUE_MATCH",
    "FALSE_MATCH",
    "AUTO_CLEARED",
    "CLOSED",
    "CLEARED",
    "STR_FILED",
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    what: str


def decision_write_violations(
    root: Path | None = None,
) -> list[Violation]: ...  # root mặc định = src/aml
```
- `config.yaml`: `cases.prioritization.below_the_line: {enabled: false, sample_size: 200}`; thêm vào section `ml:` của 7b-i:
  `ml.governance: {cards_dir: docs/models, models: [prioritization, memo_classifier, anomaly, screening_match]}`.
- DDL `sql/duckdb/ddl/220_ml_governance.sql` và bản Oracle (mỗi lệnh kết thúc bằng dòng `/`, DDL bọc `EXECUTE
  IMMEDIATE` nuốt ORA-00955), trong `SCHEMA_SCRIPTS` sau `ddl/190_memo_analysis.sql` (và sau `200` / `210` nếu đã có),
  trước các script `050_*`: bảng `btl_samples`, `btl_members`, `btl_features`, `btl_evaluations`; không UPDATE / DELETE.
- CLI: `aml cases btl [--size N] [--train] [--model logreg|lightgbm] [--eval-out PATH]`; nhóm mới `aml models` với
  `aml models card [--model NAME] [--out DIR] [--check]` và `aml models audit-check [--since YYYY-MM-DD]`.
  `Makefile` / `tasks.ps1` không đổi.
- Module mới: `src/aml/cases/btl.py`, `src/aml/cases/btl_model.py`, package `src/aml/governance/` (`cards.py`,
  `sources.py`, `audit_check.py`, `guard.py`, `cli.py`). SQL mới trong `sql/<backend>/cases/btl_*.sql` (truy vấn quần thể
  và tài khoản / CIF của kịch bản).

### Thiết kế (đề xuất, chờ xác nhận ở Câu hỏi mở)
- **Quần thể BTL** (`btl_population`, Q1): golden customer (`COALESCE(customer_golden.golden_customer_id, 'G-' || cif)`
  trên mọi CIF của `customers`, như `cases/truth_accounts.sql`) **không có dòng `case_alerts` nào** (bất kể `status`)
  trong lần chạy case hiện hành; trả tăng dần. Khách có item bị suppression không thuộc BTL — đó là mẫu của 9c.
- **Rút mẫu** (`draw_sample`, Q3): lần chạy case mới nhất (chưa có → `CaseError` chứa ``run `aml cases build` first``);
  bảng `ground_truth` rỗng → `PrioritizationError` chứa `no ground truth`; cả hai trước mọi lần ghi. `requested = size`
  hoặc `below_the_line.sample_size`; nếu đã có mẫu cho (`run_id`, `settings.seed`, `requested`) → trả mẫu đó với `reused =
  True`, không ghi gì. Ngược lại: thành viên = `ids[i]` với `i` ∈ `seeded_positions(seed, len(ids), requested)` =
  `sorted(default_rng(seed).choice(n, size=min(requested, n), replace=False))` (n = 0 → `[]`). `sample_id` = max + 1.
- **Nhãn** (`btl_label`, Q2; chỉ để đo và huấn luyện, không bao giờ thành disposition hay alert): `SUSPICIOUS` khi ít nhất
  một CIF của golden customer là dòng `ground_truth` `entity_type = 'customer'`, `is_suspicious`, hoặc ít nhất một tài
  khoản của các CIF đó là dòng `entity_type = 'account'`, `is_suspicious` (vai nào cũng tính — cùng định nghĩa 7c Q1);
  `typologies` = typology của các dòng đó, tăng dần, không trùng. `reason`:
  `below-the-line sample: not alerted in case run {run_id}, but in a suspicious scenario ({typologies nối bằng ", "})` hoặc
  `below-the-line sample: not alerted in case run {run_id} and in no suspicious scenario`.
- **Lưu và audit** (một giao dịch): 1 dòng `btl_samples(sample_id, run_id, as_of, seed, requested, population, size,
  suspicious, not_suspicious, estimated_missed, ci_low, ci_high, version, sampled_ts UTC, actor)`; mỗi thành viên 1 dòng
  `btl_members(sample_id, golden_customer_id, label, typologies JSON, reason)`; audit `module='cases'`, `version='btl/v1'`,
  `actor = simulated_actor` (vai người kiểm tra mô phỏng, như 7c): mỗi thành viên `entity_type='customer'`,
  `entity_id=golden_customer_id`, `decision='BTL_LABELLED'`, `reason` = `reason` của nhãn, `details = {sample_id, run_id,
  label, typologies}`; cộng 1 dòng `entity_type='btl_sample'`, `entity_id=str(sample_id)`, `decision='BTL_SAMPLED'`,
  `reason` = `sampled {size} of {population} customer(s) with no alert in case run {run_id} (seed {seed}): {suspicious} in a suspicious scenario, estimated {estimated_missed} missed (95% CI {ci_low}-{ci_high}); measurement only`,
  `details` = các trường số của `BtlSample`.
- **Feature BTL** (`write_btl_features`, Q6): đúng 35 `FEATURES` của 7c cho mỗi thành viên, hàm thuần của một
  enrichment giả: 19 feature alert (`alerts` … `alert_amount_log`) = 0; KYC, CIF / tài khoản liên kết, `dq_issues`,
  `txn_summary` (`txn_activity(db, cifs, golden_id, as_of, days=txn_summary_days, top_n=top_counterparties)` — cửa sổ
  kết thúc ở `as_of` của lần chạy case), network (cùng nguồn `choose_source` với lần chạy case), `history` (case của
  golden customer đó có `window_start` < `as_of`). Không đọc `ground_truth`. Bảng `btl_features(sample_id,
  golden_customer_id, feature, value)` dạng dài, giá trị làm tròn 10; ghi một lần cho mỗi mẫu. Cột memo (`memo=True`):
  `count_memos` của 8d trên giao dịch của các CIF trong cùng cửa sổ; một memo chưa có nhãn → `None` cho cả mẫu (như
  `decided_memo_features`). Khối enrichment dùng chung được tách khỏi `enrich_cases` thành một hàm theo golden customer —
  hành vi của 7a không đổi (test 7a là lưới an toàn).
- **Đo model hiệu lực trên BTL** (`evaluate_btl`): model = `model_id` hoặc `case_model_active` (chưa có →
  `PrioritizationError` chứa ``no model: run `aml cases train` first``, trước mọi lần ghi, kể cả rút mẫu); mẫu =
  `draw_sample` (dùng lại nếu có); điểm = `predict` của 7c trên `read_btl_features` (model có cột memo mà mẫu chưa có nhãn
  memo → cột memo = 0, ghi `memo_features: "zeros"` vào details, như `score`); `metrics` = `ranking_metrics(y, score,
  top_fractions)` (`y = 1` khi `SUSPICIOUS`; khoá `n_false_positive` ở đây nghĩa là số `NOT_SUSPICIOUS`) cộng
  `population`, `estimated_missed`, `prevalence_ci95`. Bảng `btl_evaluations(eval_id, sample_id, model_id, model_version,
  metrics JSON, scores JSON {golden_customer_id: score làm tròn 6}, evaluated_ts UTC, actor)`; audit 1 dòng
  `entity_type='model'`, `entity_id=version`, `decision='BTL_EVALUATED'`, **`version` = phiên bản model**, `reason` =
  `measured {version} on below-the-line sample {sample_id}: {n} customer(s), {n_suspicious} suspicious, ROC-AUC {roc_auc}, PR-AUC {pr_auc}; measurement only`,
  `details = {eval_id, sample_id, model_id, metrics}`. Không ghi `case_scores`, không đổi hàng đợi.
- **Biến thể huấn luyện có BTL** (`train_with_btl`, Q4, Q5): tập = case đã có disposition (đúng như `train` của 7c,
  ảnh chụp của disposition, nhóm `case_groups`) ∪ thành viên mẫu của lần chạy hiện hành (index và nhóm =
  `btl:<golden_customer_id>`, mỗi khách một nhóm; `y = 1` khi `SUSPICIOUS`); cột memo dùng khi **cả hai** phần có nhãn memo
  đủ, ngược lại 35 cột. Kiểm số lớp trên **tập hợp** trước mọi lần ghi: mỗi lớp < `cv_folds` → `PrioritizationError` chứa
  `not enough labelled rows: need at least {cv_folds} per class, got SUSPICIOUS={a} NOT_SUSPICIOUS={b}`. Không trọng số
  mẫu (Q5); `class_weight="balanced"` như 7c; `fit_model(..., populations=...)` → `metrics` gộp + `by_population`.
  Lưu vào `case_models` (bảng 7c, dòng mới, không đụng dòng cũ): `kind` = `logreg` / `lightgbm`, **`version` =
  `prio/<kind>+btl/<model_id>`**, `cases` = số dòng huấn luyện (case + khách BTL), `suspicious` / `false_positive` = số
  dòng nhãn 1 / 0, `params.population = {alerted: [S, FP], below_the_line: [S, N], btl_sample_id}`. Model mới nhất là model
  hiệu lực (7c Q6) — nên sau `train_with_btl`, `score` chấm bằng biến thể này và mọi dòng `PRIORITIZED` mang phiên bản
  `+btl`. Audit `MODEL_TRAINED` (một giao dịch với dòng `case_models`): `reason` =
  `trained {kind} on {a} labelled cases ({s} SUSPICIOUS, {f} FALSE_POSITIVE) and {b} below-the-line customers ({bs} SUSPICIOUS, {bn} NOT_SUSPICIOUS; sample {sample_id}; class_weight balanced): cross-validated ROC-AUC alerted {x}, below-the-line {y}; ranking only`,
  `details = {model_id, data_hash, metrics, features, population}`.
- **`aml cases btl`**: in `btl sample_id= run_id= population= size= suspicious= not_suspicious= estimated_missed=
  ci95=<lo>-<hi> reused=`; rồi `btl-eval model= n= n_suspicious= roc_auc= pr_auc= prevalence=` hoặc `btl-eval skipped:
  no model: run `aml cases train` first`; với `--train`: dòng `model version= rows= roc_auc= pr_auc= prevalence=`, dòng
  `by-population alerted n= roc_auc= below_the_line n= roc_auc=`, rồi `btl-eval` lần nữa cho model mới; dòng cuối bằng
  đúng `below-the-line sample is measurement only: no customer was alerted, closed or cleared`. `--eval-out` ghi JSON
  `{sample, evaluation}` (+ `model` khi `--train`). `CaseError` / `PrioritizationError` → stderr, exit 1.
- **`aml score`** (7c): `below_the_line.enabled = false` (mặc định) → chuỗi như 7c, chỉ đổi `NOTE` thành `note metrics
  cover alerted cases only; below-the-line sample: run `aml cases btl``; `POPULATION` vẫn bắt đầu bằng `alerted cases
  only`. `enabled = true` → bước `train` được thay bằng `train_with_btl`, thêm dòng `btl …` trước dòng `model` và dòng
  `btl-eval …` sau dòng `holdout`; `--eval-out` thêm khoá `below_the_line = {sample, evaluation}`.
- **Model card** (`aml models card`, Q7, Q8): mỗi tên trong `governance.models` (hoặc `--model`) → `collect_facts` gọi
  hàm trong `CARD_SOURCES` qua `importlib`; module không import được → `Skipped(name, "{module} is not implemented yet
  (specs/{spec}.md)")`; hàm trả `Skipped` khi chưa có model đã lưu. `render_card` (tiếng Anh, không có dấu thời gian sinh
  file, LF, kết thúc bằng một `\n`) theo đúng thứ tự:
  `# Model card: {title}`; dòng `> Generated by `aml models card` from {source}. Do not edit by hand: rerun the command.`;
  bảng `| Field | Value |` với các hàng `Model`, `Version`, `Kind`, `Trained`, `Seed`, `Data hash`, `Feature set`
  (`{feature_version} ({len(features)} features)`; `None` in là `-`); rồi các mục `## Intended use`, `## Human oversight`
  (dòng đầu bằng đúng `NEVER_ACTS`, rồi `oversight`), `## Data` (gạch đầu dòng), `## Features` (một dòng, tên nối bằng
  `, `), `## Metrics` (bảng `| Population | Metric | Value |`), `## Limitations` (gạch đầu dòng), `## Audit trail` (mỗi
  `AuditCoverage` một dòng `- {module}/{decision}: {with_version} of {rows} row(s) carry version {version}`). File
  `{cards_dir}/{name}.md`; ghi chỉ khi nội dung khác; mỗi card đã ghi 1 dòng audit `module='governance'`,
  `entity_type='model_card'`, `entity_id=name`, `decision='MODEL_CARD_WRITTEN'`, `version` = phiên bản của card,
  `reason` = `wrote the model card of {version} to {path} from {source}`, `details = {path, sha256, source}`. `--check`:
  không ghi gì (file, audit), liệt kê file thiếu hoặc khác.
  - `prioritization`: model hiệu lực (`case_model_active`); `Skipped` ``no stored model: run `aml cases train` first``.
    Metrics: CV (`case_models.metrics`: `n`, `prevalence`, `roc_auc`, `pr_auc`, `precision_at`, `recall_at`), holdout
    (dòng `SCORING_RUN_COMPLETED` mới nhất có `version` của model: `details.holdout`; không có → `not scored yet`),
    `by_population` nếu là biến thể `+btl`, BTL (dòng `btl_evaluations` mới nhất của `model_id`; không có → `not measured:
    run `aml cases btl``). Limitations cố định + dòng số liệu (`prevalence` CV; "labels are simulated from synthetic ground
    truth"; "scores are rankings, not calibrated probabilities"; "active model = newest, no approval step"). Audit:
    `cases/PRIORITIZED`, `cases/MODEL_TRAINED`, `cases/BTL_EVALUATED`.
  - `memo_classifier`: phiên bản `memo/v1` + `settings.ollama.llm_model`; nguồn = dòng `memo_runs` mới nhất của cặp đó
    (`Skipped` ``no memo run: run `aml memo classify` first``). Data: số khoá theo `method` (`RULE`, `LLM`, `FALLBACK`,
    `HUMAN`) của nhãn hiệu lực. Metrics: dòng `MEMO_EVAL_COMPLETED` mới nhất có `details.model` = model (accuracy, n,
    correct, accuracy theo nhóm); không có → `not evaluated: run `aml memo eval``. Limitations gồm G5 (không lưu digest
    model). Audit: `memo/MEMO_CLASSIFIED` (đếm dòng có `version='memo/v1'` và `details.model` = model).
  - `anomaly`: `anomaly_facts` import `aml.ml.anomaly.card` và bọc dict `card_facts(db, settings)` thành `CardFacts`
    (`AnomalyError` chưa có lần chạy → `Skipped` ``no anomaly run: run `aml anomaly run` first``). Audit:
    `monitoring/ALERT` (chỉ `details.rule_id = 'ML_ANOMALY'`, phiên bản `ML_ANOMALY/<model_version>`),
    `ml_anomaly/ANOMALY_RUN_COMPLETED`.
  - `screening_match`: `screening_match_facts` import `aml.screening.ml.pipeline` rồi đọc `screening_ml_model_active`,
    `screening_ml_training`, audit `ML_SCORING_COMPLETED` mới nhất của model (held-out); chưa có model → `Skipped`
    ``no model: run `aml screen-ml train` first``. Audit: `screening_ml/MODEL_TRAINED`, `screening_ml/ML_SCORED`,
    `screening_ml/ML_SCORING_COMPLETED`.
- **Kiểm phiên bản trên audit** (`version_gaps`, Q9): `MODEL_DECISIONS` = (`cases`, `PRIORITIZED`), (`cases`,
  `MODEL_TRAINED`), (`cases`, `SCORING_RUN_COMPLETED`), (`cases`, `BTL_EVALUATED`) với registry `case_models` — `version`
  rỗng → `missing version`, không có trong `case_models.version` → `unknown version`; (`memo`, `MEMO_CLASSIFIED`),
  (`memo`, `MEMO_EVAL_COMPLETED`) với registry `memo` — `version` rỗng → `missing version`, khác `MEMO_VERSION` đã biết
  (`memo/v1`) → `unknown version`, `details.model` rỗng → `missing details.model`; (`monitoring`, `ALERT`, `rule_id = 'ML_ANOMALY'`) và (`ml_anomaly`,
  `ANOMALY_RUN_COMPLETED`) với registry `anomaly_runs` — `version` phải bằng `ML_ANOMALY/<model_version>` (ALERT) hoặc
  `<model_version>` của một dòng `anomaly_runs`; (`screening_ml`, `MODEL_TRAINED`), (`screening_ml`, `ML_SCORED`),
  (`screening_ml`, `ML_SCORING_COMPLETED`) với registry `screening_ml_models` — `version` phải có trong
  `screening_ml_models.version`; bảng của spec anh em chưa tồn tại → cặp đó bỏ qua (0 dòng). `since` lọc `event_ts >= since`.
  Sửa G2 (thay đổi cộng thêm vào 8d): `details` của `MEMO_EVAL_COMPLETED` thêm `"model": <tên LLM>`; dòng cũ được báo là
  `missing details.model` — trung thực, không sửa audit cũ. `aml models audit-check`: không có gap → exit 0, stdout
  `audit versions ok: {n} row(s) checked`; có gap → exit 1, mỗi gap một dòng `{module}/{decision} {entity_id} {problem}`.
- **"Không model nào tự đóng case"** (`decision_write_violations`, Q11): quét AST mọi file `.py` khớp `SCANNED` =
  `cases/model.py`, `cases/features.py`, `cases/prioritize.py`, `cases/scoring.py`, `cases/prio_store.py`,
  `cases/btl.py`, `cases/btl_model.py`, `memo/**/*.py`, `ml/**/*.py`, `screening/ml/**/*.py`, `governance/**/*.py`, trừ
  module trong `ALLOWED_WRITERS` (= `{"aml.cases.labels": "simulates investigator dispositions from ground truth (origin SIMULATED); never reads a score"}`;
  spec anh em thêm module mô phỏng của mình kèm lý do). Vi phạm: (1) import hoặc gọi tên trong `FORBIDDEN_CALLS`; (2)
  từ khoá `decision=` có hằng chuỗi thuộc `FORBIDDEN_DECISIONS`; (3) hằng chuỗi khớp (không phân biệt hoa thường)
  `INSERT\s+INTO\s+(case_dispositions|good_guy_list|cases|case_alerts|screening_results)\b` hoặc
  `(UPDATE|DELETE\s+FROM)\s+(cases|case_alerts|case_dispositions|good_guy_list|alerts|screening_results)\b`; (4) gọi
  `insert_df` với đối số đầu là một trong sáu bảng đó. Cùng các regex (3) áp lên file `.sql` trong `sql/*/cases/btl_*.sql`,
  `sql/*/memo/`, `sql/*/ml/`, `sql/*/governance/`.

## Tiêu chí nghiệm thu
<!-- Mọi test pin AML__CASES__GRAPH_FEATURES=networkx; seed 42. TINY-B = `tiny_cases` (7a) đã `run_cases` (run 1, 52 case),
settings có AML__CASES__PRIORITIZATION__BELOW_THE_LINE__SAMPLE_SIZE=50. TINY-L = như specs/case-prioritization.md (run 2
hiện hành, 38 disposition: 27 SUSPICIOUS, 11 FALSE_POSITIVE), cùng SAMPLE_SIZE=50. STUB(RISK) = stub LLM của
specs/memo-analysis.md. Giá trị TINY "đã đo" lấy ở mục Hiện trạng; còn lại suy ra từ luật — nếu khi hiện thực lệch, xem lại
suy luận, không nới AC. Test Oracle: không khẳng định số phụ thuộc lịch sử (id, số dòng audit tích luỹ); lấy id từ giá trị
trả về, lọc audit theo id / mốc thời gian vừa tạo; dọn disposition mình ghi trong finally như test_prio_oracle.py. -->
- AC1: Given `config.yaml`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS` và gọi `apply_schema(duck)` hai lần, Then `settings.cases.prioritization.below_the_line.enabled is False`, `below_the_line.sample_size == 200`, `settings.ml.governance.cards_dir == "docs/models"`, `settings.ml.governance.models == ["prioritization", "memo_classifier", "anomaly", "screening_match"]`; `AML__CASES__PRIORITIZATION__BELOW_THE_LINE__SAMPLE_SIZE=0` raise `pydantic.ValidationError` chứa `below_the_line sample_size must be >= 1`, `AML__ML__GOVERNANCE__MODELS=[foo]` raise `ValidationError` chứa `unknown model card 'foo'`, `AML__ML__GOVERNANCE__MODELS=[memo_classifier, memo_classifier]` raise `ValidationError` chứa `governance models must not repeat`; `ddl/220_ml_governance.sql` có trong `SCHEMA_SCRIPTS` của cả hai backend, sau `ddl/190_memo_analysis.sql` (và sau `ddl/200_*` / `ddl/210_*` nếu có) và trước mọi script `050_*`; cả hai file DDL tồn tại và trong bản Oracle mọi lệnh kết thúc bằng một dòng chỉ có `/`; `apply_schema` không raise; `SELECT COUNT(*)` trên `btl_samples`, `btl_members`, `btl_features`, `btl_evaluations` đều trả 0; và tập tên cột của `btl_members` không chứa `disposition` hay `status`.
- AC2: Given các hàm thuần và TINY-B, When gọi `seeded_positions`, `wilson_interval`, `btl_label`, rồi `s1 = draw_sample(db, settings)` hai lần và `draw_sample(db, settings, size=300)`, Then `seeded_positions(42, 10, 3) == [0, 6, 9]`, `seeded_positions(42, 5, 9) == [0, 1, 2, 3, 4]`, `seeded_positions(42, 0, 3) == []`; `wilson_interval(3, 50) == (0.0206, 0.1622)`, `wilson_interval(0, 20) == (0.0, 0.1611)`, `wilson_interval(0, 0) == (None, None)`; `btl_label("G-X", 1, [])` có `label == "NOT_SUSPICIOUS"`, `typologies == ()`, `reason == "below-the-line sample: not alerted in case run 1 and in no suspicious scenario"`, còn `btl_label("G-X", 1, ["rapid_movement", "mule_ring", "rapid_movement"])` có `label == "SUSPICIOUS"`, `typologies == ("mule_ring", "rapid_movement")`, `reason == "below-the-line sample: not alerted in case run 1, but in a suspicious scenario (mule_ring, rapid_movement)"`; `s1` có `run_id = 1`, `seed = 42`, `requested = 50`, `population = 221`, `size = 50`, `suspicious = 3`, `not_suspicious = 47`, `estimated_missed = 13`, `prevalence_ci95 == (0.0206, 0.1622)`, `reused is False` (đã đo); `s1.members` tăng dần theo `golden_customer_id`, ba phần tử đầu là `G-CIF00000018`, `G-CIF00000019`, `G-CIF00000020`, và các thành viên `SUSPICIOUS` đúng là `G-CIF00000201`, `G-CIF00000242`, `G-CIF00000300`, mỗi người `typologies == ("rapid_movement",)` (đã đo); không thành viên nào có dòng trong `case_alerts` của run 1; `btl_samples` có 1 dòng, `btl_members` có 50 dòng; `audit_log` có đúng 50 dòng `decision='BTL_LABELLED'` (`entity_type='customer'`, `actor='simulated_analyst'`, `version='btl/v1'`, `reason` bằng `reason` của thành viên) và 1 dòng `BTL_SAMPLED` có `reason` bắt đầu bằng `sampled 50 of 221 customer(s) with no alert in case run 1 (seed 42): 3 in a suspicious scenario, estimated 13 missed` và kết thúc bằng `measurement only`; lần gọi thứ hai trả cùng `sample_id`, cùng thành viên, `reused is True` và số dòng của ba bảng lẫn `audit_log` không đổi; `size=300` trả `sample_id` mới với `requested = 300`, `size = 221`, `suspicious = 8` (đã đo); hai DuckDB dựng độc lập từ TINY cho cùng danh sách thành viên; số dòng và nội dung của `cases`, `case_alerts`, `case_dispositions`, `alerts` trước và sau không đổi; Given bảng `ground_truth` rỗng, Then `draw_sample` raise `PrioritizationError` chứa `no ground truth` và `btl_samples` rỗng; và Given DuckDB chưa có lần `run_cases` nào, Then raise `CaseError` chứa ``run `aml cases build` first``.
- AC3: Given TINY-B đã `draw_sample` (mẫu 50), When gọi `write_btl_features(db, settings, sample_id)` hai lần và `read_btl_features(db, settings, sample_id)`, Then lần một trả 1750 và `btl_features` có 1750 dòng của mẫu, lần hai trả 0 và bảng không đổi; frame có shape 50 × 35, index bằng danh sách `golden_customer_id` của mẫu (tăng dần), cột đúng thứ tự `FEATURES`, mọi giá trị là số thực hữu hạn; 19 cột từ `alerts` đến `alert_amount_log` bằng 0.0 ở mọi dòng; với mọi thành viên, `txn_count` bằng `txn_activity(db, cifs, golden_id, date(2026, 6, 30), days=90, top_n=5).summary["txn_count"]` và `kyc_risk_level` bằng mức `kyc_risk` cao nhất (`LOW` 0, `MEDIUM` 1, `HIGH` 2) của các CIF thuộc golden customer đó; `prior_cases` bằng 0 ở mọi dòng (TINY-B chỉ có run 1); số dòng `case_features` và `case_enrichment` trước và sau không đổi; mã nguồn của các hàm feature trong `aml.cases.btl` (mọi hàm trừ phần gán nhãn) không đọc bảng `ground_truth` (kiểm bằng cách gọi `write_btl_features` trên một bản sao TINY-B đã `DROP TABLE ground_truth` sau `draw_sample` — vẫn trả 1750); `read_btl_features(db, settings, sample_id, memo=True)` trước khi phân loại memo trả `None`, còn sau `classify_memos(db, settings, STUB(RISK))` trả frame 50 × 41 với 6 cột `MEMO_FEATURES` ở cuối và mỗi giá trị bằng `count_memos` của 8d trên memo các giao dịch của thành viên trong cửa sổ [2026-04-02, 2026-06-30]; và test 7a / 7c hiện có vẫn qua (enrichment dùng chung không đổi hành vi).
- AC4: Given TINY-L đã `train` (model 1, `prio/logreg/1`), When gọi `e = evaluate_btl(db, settings, actor="analyst01")` rồi gọi lần hai, Then `e.model_id == 1`, `e.version == "prio/logreg/1"`, `e.metrics["n"] == 50`, `e.metrics["n_suspicious"] == 3`, `e.metrics["n_false_positive"] == 47`, `e.metrics["prevalence"] == 0.06`, `e.metrics["population"] == 221`, `e.metrics["estimated_missed"] == 13`, `e.metrics["roc_auc"]` và `e.metrics["pr_auc"]` là số trong [0, 1]; `btl_evaluations` có 1 dòng với `model_version = 'prio/logreg/1'`, `scores` là JSON 50 khoá bằng thành viên mẫu, mỗi điểm bằng (sai số 1e-6) `predict` của 7c trên `read_btl_features` với model 1; `audit_log` có 1 dòng `decision='BTL_EVALUATED'`, `entity_type='model'`, `entity_id='prio/logreg/1'`, **`version='prio/logreg/1'`**, `actor='analyst01'`, `reason` bắt đầu bằng `measured prio/logreg/1 on below-the-line sample` và kết thúc bằng `measurement only`; lần hai trả `eval_id` mới với `metrics` giống hệt và không rút mẫu mới (`btl_samples` vẫn 1 dòng); số dòng `case_scores`, `case_models`, `case_dispositions`, `cases` trước và sau không đổi; và Given TINY-B chưa có model, When gọi `evaluate_btl`, Then raise `PrioritizationError` chứa ``no model: run `aml cases train` first`` và `btl_samples`, `btl_evaluations` đều rỗng.
- AC5: Given TINY-L đã `train` (model 1), When gọi `r = train_with_btl(db, settings, actor="analyst01")`, rồi `score(db, settings)`, rồi `train_with_btl` lần hai, rồi `train` của 7c, Then `r.training.model_id == 2`, `r.training.version == "prio/logreg+btl/2"`, `r.training.kind == "logreg"`, `r.training.cases == 88`, `r.training.suspicious == 30`, `r.training.false_positive == 58`, `r.alerted == (27, 11)`, `r.below_the_line == (3, 47)`; `r.training.metrics` có `n = 88`, `prevalence = 0.3409`, `by_population.alerted.n = 38`, `by_population.alerted.prevalence = 0.7105`, `by_population.below_the_line.n = 50`, `by_population.below_the_line.n_suspicious = 3`, `by_population.below_the_line.prevalence = 0.06`; dòng `case_models` 1 (`version`, `artifact`, `metrics`, `data_hash`) giống hệt trước khi gọi; dòng 2 có `params.population == {"alerted": [27, 11], "below_the_line": [3, 47], "btl_sample_id": r.sample_id}` và `params.class_weight == "balanced"`; `case_model_active` trả `model_id = 2`; `audit_log` có 1 dòng `MODEL_TRAINED` với `version='prio/logreg+btl/2'`, `reason` bắt đầu bằng `trained logreg on 38 labelled cases (27 SUSPICIOUS, 11 FALSE_POSITIVE) and 50 below-the-line customers (3 SUSPICIOUS, 47 NOT_SUSPICIOUS; sample` và kết thúc bằng `ranking only`; `score` sau đó ghi 52 dòng `case_scores` với `model_version = 'prio/logreg+btl/2'` và 52 dòng audit `PRIORITIZED` có `version='prio/logreg+btl/2'`, `queue` vẫn là 14 và `case_dispositions`, `cases` không có dòng mới ngoài lần chạy case; lần `train_with_btl` thứ hai trả `version == "prio/logreg+btl/3"` với `data_hash`, `artifact`, `metrics` bằng lần một; `train` của 7c sau đó trả `version == "prio/logreg/4"` với `data_hash` bằng của model 1; `fit_model` gọi không có `populations` cho `metrics` không có khoá `by_population` và cùng `data_hash` như trước spec này; Given `tiny_cases` đã `run_cases`, `simulate_dispositions` với `simulate_fraction = 1.0` (52 SUSPICIOUS, 0 FALSE_POSITIVE) và mẫu 50, Then `train` của 7c vẫn raise `got SUSPICIOUS=52 FALSE_POSITIVE=0` còn `train_with_btl` trả `cases == 102`, `suspicious == 55`, `false_positive == 47` và `metrics.by_population.alerted.roc_auc is None`; và với `AML__CASES__PRIORITIZATION__BELOW_THE_LINE__SAMPLE_SIZE=20` trên trạng thái đó (mẫu 0 đáng ngờ, 20 không), `train_with_btl` vẫn chạy (`SUSPICIOUS=52`, `NOT_SUSPICIOUS=20`), còn trên TINY-B chưa có disposition nào với mẫu 20 thì raise `PrioritizationError` chứa `not enough labelled rows: need at least 5 per class, got SUSPICIOUS=0 NOT_SUSPICIOUS=20` và `case_models` rỗng.
- AC6: Given một `tiny_env` được đưa về TINY-L (chưa `train`) bằng lời gọi hàm, có `AML__CASES__PRIORITIZATION__SIMULATE_DISPOSITIONS=false`, When chạy lần lượt `aml cases btl --size 50 --eval-out <tmp>/btl.json`, `aml cases btl --size 50 --train`, `aml score --top 3` với cấu hình mặc định, rồi `aml score --top 3 --eval-out <tmp>/prio.json` với `AML__CASES__PRIORITIZATION__BELOW_THE_LINE__ENABLED=true` và `AML__CASES__PRIORITIZATION__BELOW_THE_LINE__SAMPLE_SIZE=50`, Then lệnh thứ nhất exit code 0, stdout có một dòng bắt đầu bằng `btl ` chứa `population=221`, `size=50`, `suspicious=3`, `estimated_missed=13`, `ci95=0.0206-0.1622`, `reused=False`, một dòng bắt đầu bằng `btl-eval skipped:` chứa ``no model: run `aml cases train` first``, và dòng cuối bằng đúng `below-the-line sample is measurement only: no customer was alerted, closed or cleared`; `btl.json` có khoá `sample` và `evaluation` với `sample.population == 221`; lệnh thứ hai exit code 0, dòng `btl ` chứa `reused=True`, có một dòng bắt đầu bằng `model version=prio/logreg+btl/1`, một dòng bắt đầu bằng `by-population` chứa `alerted n=38` và `below_the_line n=50`, và một dòng bắt đầu bằng `btl-eval model=prio/logreg+btl/1` chứa `n=50` và `prevalence=0.06`; `aml score` mặc định exit code 0, không dòng nào bắt đầu bằng `btl`, dòng bắt đầu bằng `model` chứa `version=prio/logreg/2` và không chứa `+btl`, dòng áp chót bằng đúng chuỗi `NOTE` mới của mục Thiết kế (bắt đầu bằng `note metrics cover alerted cases only; below-the-line sample: run`) và dòng cuối bằng đúng `ranking only: no case was closed or cleared by the model`; lần `aml score` với `ENABLED=true` exit code 0, dòng `model` chứa `version=prio/logreg+btl/3`, có một dòng bắt đầu bằng `btl ` và một dòng bắt đầu bằng `btl-eval model=prio/logreg+btl/3`, và `prio.json` có đúng bốn khoá `model`, `cv`, `holdout`, `below_the_line`; `aml cases btl --model xgboost` exit code 2; `aml cases btl --size 0` exit code 2; và Given DuckDB chỉ mới `aml load`, When chạy `aml cases btl`, Then exit code 1 với stderr chứa ``run `aml cases build` first``.
- AC7: Given một `CardFacts` dựng tay (FACTS) và TINY-L đã `train`, `score`, `evaluate_btl`, `classify_memos(db, settings, STUB(RISK))`, với `sys.modules["aml.ml.anomaly.card"] = None` và `sys.modules["aml.screening.ml.pipeline"] = None` (monkeypatch), When gọi `render_card(FACTS)` hai lần, `rep = write_cards(db, settings, out_dir=tmp)` hai lần, `write_cards(db, settings, out_dir=tmp, check=True)` trước và sau khi sửa một chữ số trong `tmp/prioritization.md`, rồi chạy `aml models card --out <tmp2>`, `aml models card --model anomaly --out <tmp2>` và `aml models card --model foo`, Then `render_card(FACTS)` cho hai chuỗi giống hệt, dòng đầu bằng `# Model card: {FACTS.title}`, các tiêu đề `##` theo đúng thứ tự `Intended use`, `Human oversight`, `Data`, `Features`, `Metrics`, `Limitations`, `Audit trail`, dòng đầu sau `## Human oversight` bằng đúng `This model never closes, clears, files or dispositions anything.`, chuỗi kết thúc bằng đúng một `\n` và không chứa `\r`; `rep.written` là hai đường dẫn `tmp/prioritization.md`, `tmp/memo_classifier.md`; `rep.skipped` là `Skipped("anomaly", "aml.ml.anomaly.card is not implemented yet (specs/ml-anomaly.md)")` và `Skipped("screening_match", "aml.screening.ml.pipeline is not implemented yet (specs/screening-ml.md)")`; `prioritization.md` chứa `| Version | prio/logreg/1 |`, `| Data hash | {data_hash của case_models model 1} |`, `| Feature set | features/v1 (35 features) |`, chuỗi `str(metrics["roc_auc"])` của `case_models.metrics` model 1, một hàng holdout có `n` = 14, một hàng below-the-line có `n` = 50 và dòng `- cases/PRIORITIZED: 52 of 52 row(s) carry version prio/logreg/1`; `memo_classifier.md` chứa `| Version | memo/v1 + qwen2.5:3b-instruct |` và ``not evaluated: run `aml memo eval` ``; lần `write_cards` thứ hai không đổi byte nào của hai file và không ghi audit mới; lần một ghi đúng 2 dòng `decision='MODEL_CARD_WRITTEN'` với `version` lần lượt `prio/logreg/1` và `memo/v1 + qwen2.5:3b-instruct`, `details.sha256` bằng SHA-256 của file; `check=True` trên file chưa sửa trả `stale == ()`, sau khi sửa trả `stale == (tmp/prioritization.md,)`, và cả hai lần không ghi file hay audit; `aml models card --out <tmp2>` exit code 0 với một dòng `card prioritization -> ` và một dòng bắt đầu bằng `skipped anomaly: `; `--model anomaly` exit code 1; `--model foo` exit code 2; và Given `tiny_cases` chỉ mới `run_cases`, When gọi `write_cards`, Then `rep.written == ()`, `prioritization` bị bỏ qua với lý do ``no stored model: run `aml cases train` first``, `memo_classifier` với ``no memo run: run `aml memo classify` first`` và thư mục đích không có file nào.
- AC8: Given TINY-L đã `train`, `score`, `evaluate_btl`, `train_with_btl`, `score` lần nữa, `classify_memos(db, settings, STUB(RISK))` và `run_memo_eval` của 8d với một stub trên file nhãn vàng G6, When gọi `version_gaps(db)`, rồi ghi thêm bằng `audit()` ba dòng — `cases`/`PRIORITIZED` với `version=None`, `cases`/`PRIORITIZED` với `version="prio/logreg/999"`, `memo`/`MEMO_CLASSIFIED` với `version="memo/v1"` và `details={"category": "other"}` — rồi gọi lại `version_gaps(db)`, `version_gaps(db, since=<thời điểm ngay trước ba dòng>)` và `aml models audit-check`, Then lần đầu trả `[]`; dòng `MEMO_EVAL_COMPLETED` vừa ghi có `details.model == "qwen2.5:3b-instruct"` (sửa G2) và `reason` của nó giữ nguyên như AC11 của specs/memo-analysis.md; `MODEL_DECISIONS` chứa đúng 11 cặp (`cases`, `PRIORITIZED`), (`cases`, `MODEL_TRAINED`), (`cases`, `SCORING_RUN_COMPLETED`), (`cases`, `BTL_EVALUATED`), (`memo`, `MEMO_CLASSIFIED`), (`memo`, `MEMO_EVAL_COMPLETED`), (`monitoring`, `ALERT`, `rule_id='ML_ANOMALY'`), (`ml_anomaly`, `ANOMALY_RUN_COMPLETED`), (`screening_ml`, `MODEL_TRAINED`), (`screening_ml`, `ML_SCORED`), (`screening_ml`, `ML_SCORING_COMPLETED`); Given TINY-L đã thêm `run_anomaly` (7b-i) và `simulate_labels` (`1.0`) → `train` → `score` của 7b-ii, When gọi `version_gaps(db)`, Then trả `[]`, và một dòng `ALERT` giả có `details.rule_id = 'ML_ANOMALY'` với `version='ML_ANOMALY/anomaly/v1/999'` cho 1 gap `unknown version` trong khi một dòng `ALERT` giả có `details.rule_id = 'STRUCTURING'` và `version=None` không cho gap nào; lần hai trả đúng 3 `VersionGap` với `problem` lần lượt `missing version`, `unknown version`, `missing details.model`; lần có `since` trả cùng 3 gap, còn `since` sau cả ba dòng trả `[]`; `aml models audit-check` exit code 1 với 3 dòng, mỗi dòng chứa module/decision và `problem` tương ứng; và trên DuckDB trước ba dòng giả, `aml models audit-check` exit code 0 với stdout bắt đầu bằng `audit versions ok:`.
- AC9: Given mã nguồn của repo và một thư mục tạm `root` chứa bản sao cấu trúc `src/aml` gồm các file cài vi phạm, When gọi `decision_write_violations()` và `decision_write_violations(root)`, rồi chạy chuỗi `draw_sample` → `evaluate_btl` → `train_with_btl` → `score` → `write_cards` trên TINY-L, Then `decision_write_violations()` trên repo trả `[]`; tập file đã quét gồm mọi file `.py` dưới `src/aml/memo/`, `src/aml/governance/`, `src/aml/ml/` và `src/aml/screening/ml/` (khi tồn tại) và bảy file `cases/model.py`, `cases/features.py`, `cases/prioritize.py`, `cases/scoring.py`, `cases/prio_store.py`, `cases/btl.py`, `cases/btl_model.py`, nhưng không gồm `cases/labels.py`; `ALLOWED_WRITERS` có khoá `aml.cases.labels` với lý do không rỗng và mọi khoá là module import được; trên `root`, một file `ml/x.py` chứa `from aml.cases.dispositions import record_disposition` cho đúng 1 `Violation` với `path` kết thúc bằng `ml/x.py`, đúng số dòng và `what` chứa `record_disposition`; một file `memo/y.py` chứa `db.execute("update cases set status = 'CLOSED'")` cho 1 vi phạm có `what` chứa `UPDATE cases`; một file `governance/z.py` chứa `db.insert_df("case_dispositions", frame)` cho 1 vi phạm; một file `screening/ml/w.py` chứa `audit(db, decision="FALSE_POSITIVE", reason="r")` cho 1 vi phạm có `what` chứa `FALSE_POSITIVE`; một file `sql/duckdb/cases/btl_bad.sql` chứa `DELETE FROM case_alerts` cho 1 vi phạm; còn một file `memo/ok.py` chỉ chứa `"SELECT case_id FROM case_dispositions_current"` cho 0 vi phạm; và sau chuỗi trên TINY-L, số dòng và nội dung của `case_dispositions`, `good_guy_list`, `cases` (cột `status` theo `run_id`), `case_alerts`, `alerts`, `screening_results` bằng đúng trước khi chạy.
- AC10: [oracle] Given TINY nạp vào cả Oracle và một DuckDB tạm, cả hai đưa về TINY-L (`AML__CASES__GRAPH_FEATURES=networkx`, mẫu 50), When gọi `draw_sample`, `write_btl_features`, `evaluate_btl`, `train_with_btl`, `write_cards` (thư mục tạm riêng cho từng backend) và `version_gaps(db, since=<mốc bắt đầu test>)` trên hai backend, Then hai `BtlSample` có cùng `population` (221), `size`, `suspicious` (3), `estimated_missed` và cùng danh sách thành viên với cùng `label`, `typologies`, `reason`; `read_btl_features` của hai mẫu bằng nhau (sai số 1e-9); `metrics` của hai `BtlEvaluation` bằng nhau (sai số 1e-9) và `scores` lệch không quá 1e-6; `data_hash`, `metrics` của hai dòng `case_models` của `train_with_btl` bằng nhau (sai số 1e-9) và cả hai `version` khớp mẫu `prio/logreg+btl/<số>`; card `prioritization.md` của Oracle chứa cùng dòng bắt đầu bằng `| Data hash |` như card của DuckDB; `version_gaps` trên Oracle trả `[]`; `user_tables` của Oracle có `BTL_SAMPLES`, `BTL_MEMBERS`, `BTL_FEATURES`, `BTL_EVALUATIONS`; các dòng audit `BTL_LABELLED`, `BTL_SAMPLED`, `BTL_EVALUATED`, `MODEL_TRAINED` của lần chạy (lọc theo `sample_id` / `model_id` vừa trả về) có đúng số lượng 50 / 1 / 1 / 1; gọi `apply_schema` trên Oracle lần hai không raise; và test dọn các disposition, dòng good-guy nó đã ghi trong `finally` để chạy lại được.

## Ngoài phạm vi
- Mẫu BTL làm thay đổi hàng đợi hay sinh alert: khách BTL đáng ngờ **không** được tạo alert, case hay disposition; nhãn
  BTL chỉ để đo và huấn luyện. Báo cáo "đường cắt bỏ sót bao nhiêu" là ước lượng có khoảng tin cậy, không phải hành động.
- Trọng số nghịch xác suất chọn mẫu (IPW), mẫu phân tầng, rút mẫu lặp theo thời gian, hiệu chỉnh xác suất, đo drift (Q5).
- Bước phê duyệt model / champion-challenger / chặn model chưa duyệt (Q10); `case_model_active` giữ quy tắc "mới nhất".
- Sửa định dạng `version` của `MEMO_CLASSIFIED` hay ghi lại audit cũ (Q9); lưu digest model Ollama (G5 — ghi vào
  limitation của card).
- Card trên UI / dashboard 9c, API cho card, xuất PDF; card cho luật (screening, monitoring, network) — không phải model.
- Hiện thực model anomaly và screening ML (spec anh em, hiện thực **trước** spec này); spec này dựng adapter card cho
  chúng trong `aml.governance.sources` và đăng ký cặp audit của chúng vào `MODEL_DECISIONS`.
- Đổi `aml.metrics` (mẫu dashboard 9c); quyền Oracle cho bốn bảng mới; đo trên `large`; ghi số vào README (bước demo:
  `aml cases btl --train --eval-out results/phase7b/btl.json` và `aml models card` trên `small`, chạy thật rồi mới ghi).

## Tác động lên spec khác
- `specs/case-prioritization.md` (7c, đã duyệt): `fit_model` thêm tham số tuỳ chọn `populations` (mặc định giữ đúng
  kết quả cũ, AC5 khẳng định); `insert_model` nhận phiên bản biến thể `prio/<kind>+btl/<id>`; `PrioritizationConfig` thêm
  `below_the_line`; `NOTE` của `aml score` đổi chữ (không test 7c nào khẳng định chuỗi này; `POPULATION` vẫn bắt đầu bằng
  `alerted cases only`); `aml score` thêm dòng khi `enabled = true`. Mục "Ngoài phạm vi" của 7c về mẫu BTL / model card
  được thực hiện ở đây — thêm ghi chú dẫn sang spec này.
- `specs/case-consolidation.md` (7a): tách khối enrichment theo golden customer khỏi `enrich_cases` để dùng lại; hành vi
  và test 7a không đổi.
- `specs/memo-analysis.md` (8d): `details` của `MEMO_EVAL_COMPLETED` thêm khoá `model` (cộng thêm; `reason` không đổi);
  hàm đọc memo theo cửa sổ (`_case_memos`) được công khai để BTL dùng lại.
- `specs/ml-anomaly.md` (7b-i) và `specs/screening-ml.md` (7b-ii), hiện thực trước spec này — đã đối chiếu (2026-10-14):
  (1) bảng model: `anomaly_runs` (`model_version`, `kind`, `run_ts`, `seed`, `features`, `params`, `metrics`, `data_hash`,
  `actor`) và `screening_ml_models` (đủ cột); (2) mọi dòng audit chứa điểm mang phiên bản model — 7b-i: `ALERT` với
  `details.rule_id = 'ML_ANOMALY'` (`version = ML_ANOMALY/<model_version>`), `ANOMALY_RUN_COMPLETED`; 7b-ii: `MODEL_TRAINED`,
  `ML_SCORED`, `ML_SCORING_COMPLETED` (`module='screening_ml'`) — cả 5 cặp nằm trong `MODEL_DECISIONS` của spec này;
  (3) 7b-i cung cấp `aml.ml.anomaly.card:card_facts` trả **dict** (7b-i Q16), 7b-ii không có module card (7b-ii Q13) — spec
  này bọc / đọc trong `aml.governance.sources`; (4) code dưới `src/aml/ml/` / `src/aml/screening/ml/` bị quét bởi AC9;
  `aml.screening.ml.labels` qua guard mà không cần `ALLOWED_WRITERS` (7b-ii AC9: `decision='SIMULATED_LABEL'`, không gọi
  `record_review`); (5) alert ANOMALY là **ghi alert mới** qua `record_run` của `aml.monitoring` (không bị quét), 7b-i AC12
  cấm `UPDATE ` / `DELETE ` dưới `src/aml/ml/`.
- `specs/ui-mock-pages.md` (9c): không đổi; "mẫu below-the-line của khách hàng không alert" trên dashboard vẫn ngoài phạm vi.

## Giả định
- Golden customer (ER của Phase 3) là đơn vị của quần thể BTL, cùng đơn vị với case; CIF không có dòng
  `customer_golden` dùng `G-<cif>` như `cases/truth_accounts.sql`.
- Kết quả tất định với cùng dữ liệu, cấu hình, `settings.seed`, cùng phiên bản NumPy / scikit-learn trên cùng nền tảng;
  Oracle và DuckDB lệch số thực tối đa 1e-9 (feature, metric) / 1e-6 (điểm).
- Nhãn BTL là dữ liệu demo từ ground truth tổng hợp, đúng tuyệt đối, không nhiễu — metric BTL là cận trên.
- Mọi khách BTL có `alerts = 0` trong khi mọi case có `alerts >= 1`, nên biến thể `+btl` tách hai quần thể gần như hoàn
  toàn theo các feature alert; metric **gộp** của nó vì thế bị thổi phồng — chỉ `by_population` mới có ý nghĩa, và card
  ghi rõ điều này trong Limitations.
- `reason`, output CLI, card bằng tiếng Anh như phần còn lại của repo; spec bằng tiếng Việt.
- Card được commit vào `docs/models/` sau khi chạy thật trên `small` (như số README); test chỉ sinh card vào thư mục tạm.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Quần thể "below-the-line" là ai? — đề xuất mặc định: golden customer **không có dòng
  `case_alerts` nào** (kể cả item bị suppression) trong lần chạy case hiện hành; đã đo TINY: 221 / 273. Lý do: khách có item
  bị suppression đã có mẫu riêng ở 9c (`metrics/samples.py`); "không có alert" là đúng nghĩa thiên lệch mà brief mô tả.
  Phương án thay thế: (a) tính cả khách chỉ có item `SUPPRESSED` (quần thể lớn hơn, chồng lấn với 9c); (b) loại thêm khách
  từng có case ở lần chạy trước (sạch hơn, nhưng phụ thuộc lịch sử chạy). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q2. **(cần người dùng quyết)** Nhãn của khách BTL? — đề xuất mặc định: `SUSPICIOUS` khi bất kỳ CIF nào là subject
  sanctions / PEP hoặc bất kỳ tài khoản nào nằm trong kịch bản `is_suspicious`, **vai nào cũng tính** (cùng định nghĩa 7c
  Q1); đã đo TINY: 8 / 221 đáng ngờ, đều là `rapid_movement` vai `source` / `destination`. Lý do: nhất quán với nhãn đã duyệt
  ở 7c. Phương án thay thế: chỉ vai chính (`subject`, `collector`, `hop`, `member`) — trên TINY sẽ còn 0 ca BTL đáng ngờ
  (suy ra từ số đo), mẫu mất ý nghĩa. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q3. **(cần người dùng quyết)** Cỡ mẫu và cách rút? — đề xuất mặc định: ngẫu nhiên đơn giản có seed,
  `sample_size: 200` (chặn bởi quần thể), một mẫu cho mỗi (lần chạy case, seed, cỡ). Test dùng 50. Lý do: brief nói
  "random sample"; 200 dòng giữ chi phí enrichment nhỏ (200 lượt `txn_activity`). Rủi ro: trên `small` tỉ lệ đáng ngờ BTL
  chưa đo (ước lượng thấp) nên 200 có thể chỉ cho vài ca dương → ROC-AUC BTL dao động mạnh; vì thế luôn in `n`,
  `n_suspicious` và khoảng Wilson. Phương án thay thế: 500 hoặc 1 000; hoặc phân tầng theo `kyc_risk` (không còn là "random"). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q4. **(cần người dùng quyết)** Mẫu BTL dùng thế nào và có làm đổi model hiệu lực không? — đề xuất mặc định: (a)
  luôn **đo** model hiệu lực trên mẫu (`evaluate_btl`, chỉ đo); (b) huấn luyện **biến thể mới** `prio/<kind>+btl/<id>` chỉ
  khi được yêu cầu rõ (`aml cases btl --train` hoặc `below_the_line.enabled: true`, mặc định `false`); khi đã huấn luyện,
  biến thể là model mới nhất nên **thành model hiệu lực** (quy tắc 7c Q6) và mọi điểm mang phiên bản `+btl`. Lý do: không
  đổi `aml score` mặc định và test 7c đã duyệt; không có gì thay đổi âm thầm — phiên bản riêng, audit riêng. Phương án thay
  thế: biến thể chỉ là challenger, không bao giờ hiệu lực (phải đổi view `case_model_active` của DDL 180); hoặc bật
  `enabled: true` mặc định (phải sửa AC8 của 7c). — Trả lời: theo đề xuất mặc định (người dùng chọn trực tiếp, 2026-10-14).
- [x] Q5. Có dùng trọng số chọn mẫu (IPW = quần thể / cỡ mẫu) khi huấn luyện không? — đề xuất mặc định: **không**; báo
  cáo `estimated_missed` và khoảng Wilson thay vào đó. Lý do: với 221 / 50 trọng số ≈ 4,4 sẽ làm khách BTL áp đảo, cộng với
  `class_weight="balanced"` khó giải thích trong một câu. Phương án thay thế: `sample_weight` = IPW, `class_weight` tắt. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q6. Feature của khách BTL? — đề xuất mặc định: đúng 35 feature của 7c, 19 feature alert = 0, cửa sổ giao dịch 90
  ngày kết thúc ở `as_of`; cột memo khi mọi memo đã có nhãn. Lý do: cùng một hàm feature cho hai quần thể, model chấm được
  cả hai. Phương án thay thế: bỏ feature alert khỏi biến thể `+btl` (tránh tách quần thể tầm thường, nhưng model không còn
  dùng được thông tin alert khi chấm case). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q7. **(cần người dùng quyết)** Card ở đâu, định dạng gì? — đề xuất mặc định: `docs/models/<model>.md` do `aml
  models card` sinh từ bảng / audit đã lưu, tiếng Anh, không có dấu thời gian sinh file (chạy lại cho cùng byte),
  `--check` báo file lệch; card được commit sau lần chạy thật trên `small`. Lý do: không con số nào gõ tay; diff git cho
  thấy model đổi gì. Phương án thay thế: lưu card trong bảng database và chỉ xuất ra khi cần; hoặc card tiếng Việt. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q8. Model của spec anh em chưa hiện thực thì sao? — đề xuất mặc định: bỏ qua với thông điệp
  `{module} is not implemented yet (specs/{spec}.md)`; `aml models card` (tất cả) vẫn exit 0, còn `--model <tên>` bị bỏ
  qua thì exit 1. Lý do: spec này chạy được trước / sau 7b-i, 7b-ii mà không cần cờ. Phương án thay thế: ghi card khung
  với "not implemented". — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q9. **(cần người dùng quyết)** Xử lý các gap phiên bản trên audit? — đề xuất mặc định: sửa **G2** (thêm `model` vào
  `details` của `MEMO_EVAL_COMPLETED`, thay đổi cộng thêm vào code 8d đã duyệt); **G1** giữ nguyên — danh tính model memo =
  (`version` prompt `memo/v1`, `details.model`), kiểm tra bắt buộc cả hai; **G3** chấp nhận (đo, không lưu model); **G4**
  card đọc `details.holdout`; **G5** (digest Ollama) ghi vào limitation. Dòng audit cũ thiếu trường được báo là gap, không
  sửa (audit append-only). Phương án thay thế: đổi `version` của `MEMO_CLASSIFIED` thành `memo/v1@<model>` (phá AC của 8d,
  các dòng cũ thành "unknown version"). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q10. **(cần người dùng quyết — hoãn từ 7c Q6)** Có thêm bước phê duyệt model trước khi hiệu lực không? —
  đề xuất mặc định: **không** trong spec này; card ghi rõ "active = newest, no approval step". Lý do: giữ đủ nhỏ; card +
  phiên bản + audit đã đủ để truy vết. Phương án thay thế: bảng `model_approvals` trong DDL 220, `case_model_active` chỉ
  lấy model đã được người duyệt (đổi view 7c, thêm AC). — Trả lời: theo đề xuất mặc định (người dùng chọn trực tiếp, 2026-10-14).
- [x] Q11. Thực thi "không model nào tự đóng case" thế nào? — đề xuất mặc định: test tĩnh (AST + regex SQL) trên danh sách
  module ML tường minh, danh sách cho phép có lý do (`aml.cases.labels` — mô phỏng), cộng kiểm tra động số dòng bảng quyết
  định trước / sau chuỗi ML. Lý do: kiểm theo đồ thị import sẽ báo sai (`prioritize` → `labels` → `record_disposition`).
  Phương án thay thế: chỉ kiểm động (không bắt được đường code chưa chạy tới). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q12. **(cần người dùng quyết)** Spec có 10 AC trải trên hai mục của brief — tách không? — đề xuất mặc định: giữ một
  spec, hiện thực theo thứ tự AC1–AC6 (BTL) rồi AC7–AC10 (governance). Lý do: card của mô hình ưu tiên cần số BTL; một
  DDL. Phương án thay thế: tách `specs/btl-sample.md` (AC1–AC6) và `specs/model-governance.md` (AC7–AC10) để vòng lặp
  ngắn hơn. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
