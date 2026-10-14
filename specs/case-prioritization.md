---
id: case-prioritization
status: approved
approved_by: pthieu
---

# Phase 7c — Chấm điểm ưu tiên case: disposition mô phỏng từ ground truth, feature, logistic regression (LightGBM tuỳ chọn), `aml score`

## Bối cảnh
Phần "Prioritization" của Phase 7 trong PROJECT_BRIEF.md (mục 8), dựng trên `specs/case-consolidation.md` (7a: case,
enrichment, `record_disposition`, `CaseView`) và `specs/case-suppression.md` (7b-supp). Spec này: (1) suy ra **disposition
mô phỏng** từ `ground_truth` cho một phần case (đóng vai investigator đã xử lý), (2) dựng **bảng feature** của case từ ảnh
chụp đã lưu, (3) huấn luyện **logistic regression** (LightGBM là tuỳ chọn) trên các case đã có disposition, có xử lý mất
cân bằng lớp, (4) ghi **điểm ưu tiên + các feature đóng góp nhiều nhất** cho mọi case hiện hành, (5) **đánh phiên bản
model, lưu metrics, ghi phiên bản vào `audit_log`** của từng điểm. Model **chỉ xếp hạng**: không đường code nào của spec
này ghi disposition, đổi trạng thái case hay suppress alert. Lệnh `aml score` thay stub trong `src/aml/cli.py` và chạy cả
chuỗi Phase 7. Người dùng: investigator (hàng đợi sắp theo điểm), kiểm soát model (phiên bản, metrics, lý do từng điểm),
Phase 7b của brief (thêm feature và model), Phase 9 (hàng đợi case).

### Hiện trạng đã kiểm (2026-10-13, seed 42)
Đo bằng script tạm ngoài repo (`uv run --with scikit-learn`, scikit-learn 1.9.1, không đổi `pyproject.toml` / `uv.lock`),
đọc `data/aml.duckdb` (`small`) read-only và một DuckDB TINY tạm; case dựng bằng prototype của 7a (cửa sổ 90 ngày).
- **Ground truth nằm ở đâu, dạng gì**: bảng `ground_truth(scenario_id, typology, is_suspicious, entity_type, entity_id,
  role, start_ts, end_ts, reason)`. Typology giao dịch (`structuring`, `rapid_movement`, `mule_ring`, `round_tripping`,
  lành tính `benign_payroll`, `benign_merchant`) gắn nhãn **tài khoản** (`entity_type = 'account'`, có `role`) và giao
  dịch bằng chứng; `sanctions_hit` / `pep_hit` gắn nhãn **cặp** khách hàng (`customer`) + `watchlist_entry` cùng
  `scenario_id` (`aml.screening.evaluate.truth_pairs` đã đọc sẵn). Không có nhãn nào ở mức case hay golden customer.
- **Mất cân bằng lớp bị đảo chiều so với thực tế** — phát hiện quan trọng nhất của spec này. Nhãn "case đáng ngờ khi có
  ít nhất một alert chạm kịch bản đáng ngờ":

  | | TINY (52 case) | `small` (335 case) |
  |---|---|---|
  | `SUSPICIOUS` / `FALSE_POSITIVE` (mọi vai trong kịch bản đều tính) | 52 / **0** | 291 / 44 (87 % đáng ngờ) |
  | nếu chỉ tính vai chính (`subject`, `collector`, `hop`, `member`) | 45 / 7 | 208 / 127 (62 %) |
  | false positive theo nguồn (`small`, mọi vai) | — | 34 case chỉ có screening, 8 case chỉ có alert cụm (người ngoài cuộc dính địa chỉ), 2 case rule |

  Lý do: rule 5a / 5c được chỉnh trên chính dữ liệu này (0 alert trên kịch bản lành tính, 2 alert nền) nên gần như mọi
  alert giao dịch là true positive; false positive chủ yếu đến từ screening. Ngoài đời tỉ lệ ngược lại (vài % alert là
  thật). Hệ quả: (a) **TINY không huấn luyện được** (một lớp); (b) trên `small` lớp thiểu số là `FALSE_POSITIVE`; (c)
  precision ở đầu hàng đợi của một thứ tự ngẫu nhiên đã là 0,87 — phải báo `prevalence` cạnh mọi metric (Q1, Q2).
- **Baseline đã chạy** (24 feature rút gọn: đếm alert theo nguồn / rule, điểm screening, log số tiền, KYC, degree /
  PageRank / cỡ cụm; logistic regression chuẩn hoá + `class_weight="balanced"`, 5-fold `StratifiedGroupKFold`): `small`
  ROC-AUC 0,968 (seed 42) / 0,970 (seed 7), PR-AUC 0,995, precision ở 10 % / 20 % / 50 % đầu hàng đợi = 1,0 / 1,0 / 1,0;
  42 trên 44 false positive nằm trong 20 % cuối. Hai lần chạy cùng seed cho điểm giống hệt. Con số này **chỉ để chọn
  thiết kế**, không phải kết quả của bộ feature trong spec.
- **Rò rỉ qua alert dùng chung**: một alert nhóm nằm trong nhiều case (29 case của một ring chung một alert). `small`: 335
  case thuộc 199 nhóm liên thông (case nối nhau khi chung `item_key`); TINY: 52 case, 18 nhóm. Chia train / test ngẫu
  nhiên theo case sẽ đặt các case gần như giống hệt nhau ở cả hai phía → phải chia theo nhóm.
- **Thiên lệch chọn mẫu**: nhãn chỉ có cho case đã có alert; khách hàng không có alert không có dòng nào. Brief giao
  phần xử lý (mẫu below-the-line) cho Phase 7b — spec này chỉ ghi nhận.
- **Dependency**: `scikit-learn` và `lightgbm` **chưa có** trong `pyproject.toml` / `uv.lock`. `numpy`, `scipy`, `pandas`
  đã có. `aml score` là stub (`arrives in Phase 7`, exit 1); `Makefile` / `tasks.ps1` đã có `score`, và `make all` gọi nó.
- `SCHEMA_SCRIPTS`: 7a `160`, 7b-supp `170` → spec này dùng **`180`**.
- **Chưa đo**: bộ 35 feature của spec; mọi giá trị TOY / MINI-C / TINY-L trong AC (suy ra từ luật; riêng
  `default_rng(42).permutation(3) == [2, 1, 0]` đã chạy); LightGBM; DDL `180`; Oracle.

### Interface đề xuất (để test, Phase 7b và Phase 9 gọi trực tiếp)
```python
# src/aml/common/config.py
class PrioritizationConfig(BaseModel):
    model: Literal["logreg", "lightgbm"]
    simulate_dispositions: bool  # aml score có chạy bước mô phỏng không
    simulate_fraction: float  # (0, 1]; phần nhóm case được mô phỏng disposition
    simulated_actor: str  # actor của disposition mô phỏng; khác audit.system_actor
    cv_folds: int  # >= 2
    top_features: int  # >= 1; số feature đóng góp ghi cho mỗi case
    top_fractions: list[
        float
    ]  # mỗi giá trị trong (0, 1]; phần đầu hàng đợi để tính precision / recall
    logreg: LogRegConfig  # c, max_iter
    lightgbm: LightGbmConfig  # n_estimators, num_leaves, learning_rate, min_child_samples


# src/aml/cases/features.py
FEATURE_VERSION = "features/v1"
FEATURES: tuple[str, ...]  # 35 tên, đúng thứ tự mục Thiết kế


def case_features(view: CaseView) -> dict[str, float]: ...  # thuần; đủ khoá FEATURES, không NaN
def write_features(
    db: Database, run_id: int
) -> int: ...  # ghi nếu run đó chưa có; trả số dòng đã ghi
def read_features(db: Database, run_id: int) -> pd.DataFrame: ...  # index case_id, cột FEATURES


# src/aml/cases/labels.py
@dataclass(frozen=True)
class TruthLabel:
    case_id: str
    disposition: str  # SUSPICIOUS | FALSE_POSITIVE
    true_alerts: int
    alerts: int
    typologies: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Simulation:
    run_id: int
    groups: int
    labelled_groups: int
    labelled: int  # disposition đã ghi trong lần gọi này
    suspicious: int
    false_positive: int
    held_out: int  # case OPEN không được mô phỏng
    skipped: int  # case đã có disposition từ trước


def case_groups(db: Database, run_id: int) -> dict[str, str]: ...  # case_id -> group_id
def truth_labels(db: Database, run_id: int | None = None) -> dict[str, TruthLabel]: ...
def simulate_dispositions(db: Database, settings: Settings) -> Simulation: ...


# src/aml/cases/model.py  (thuần: không đọc, không ghi DB)
class PrioritizationError(RuntimeError): ...


@dataclass(frozen=True)
class TrainedModel:
    kind: str  # "logreg" | "lightgbm"
    features: tuple[str, ...]
    artifact: (
        str  # logreg: JSON {features, mean, scale, coef, intercept}; lightgbm: model_to_string()
    )
    params: dict[str, Any]
    metrics: dict[str, Any]
    data_hash: str  # 16 ký tự hex


def fit_model(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    cfg: PrioritizationConfig,
    *,
    seed: int,
    kind: str | None = None,
) -> TrainedModel: ...
def predict(model: TrainedModel, X: pd.DataFrame) -> pd.DataFrame: ...
# index như X; cột score (0..1) và contributions (dict feature -> đóng góp trên thang log-odds)
def ranking_metrics(
    y: pd.Series, score: pd.Series, fractions: Sequence[float]
) -> dict[str, Any]: ...


# src/aml/cases/prioritize.py
@dataclass(frozen=True)
class TrainingRun:
    model_id: int
    version: str  # "prio/<kind>/<model_id>"
    kind: str
    cases: int
    suspicious: int
    false_positive: int
    metrics: dict[str, Any]


@dataclass(frozen=True)
class ScoringRun:
    score_run_id: int
    run_id: int  # lần chạy case được chấm
    model_id: int
    version: str
    cases: int
    queue: int  # case OPEN / REOPENED được xếp hạng
    holdout: dict[
        str, Any
    ]  # metric trên case OPEN so với ground truth; {} khi không có ground truth


def train(
    db: Database, settings: Settings, *, kind: str | None = None, actor: str | None = None
) -> TrainingRun: ...
def score(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> ScoringRun: ...
```
- `config.yaml`: `cases.prioritization: {model: logreg, simulate_dispositions: true, simulate_fraction: 0.7,
  simulated_actor: simulated_analyst, cv_folds: 5, top_features: 5, top_fractions: [0.1, 0.2, 0.5], logreg: {c: 1.0,
  max_iter: 1000}, lightgbm: {n_estimators: 100, num_leaves: 15, learning_rate: 0.1, min_child_samples: 5}}`.
- `pyproject.toml`: thêm `scikit-learn>=1.5` vào `dependencies`; thêm `[project.optional-dependencies] ml =
  ["lightgbm>=4.3"]` (cài bằng `uv sync --extra ml`); cập nhật `uv.lock`.
- DDL `sql/duckdb/ddl/180_case_prioritization.sql` và bản Oracle, sau `ddl/170_case_suppression.sql`, trước các script
  `050_*`: bảng `case_features`, `case_models`, `case_scores`; view `case_model_active`, `case_scores_current`,
  `case_queue`.
- CLI: `aml cases label [--fraction F]`, `aml cases train [--model logreg|lightgbm] [--eval-out PATH]`, và `aml score
  [--as-of YYYY-MM-DD] [--top N] [--eval-out PATH]` thay stub. `Makefile` / `tasks.ps1` không đổi.
- `load_case` (7a) điền `CaseView.score` = dòng `case_scores_current` của case (`{score, queue_rank, model_version,
  top_features}`) hoặc `None`.
- Module mới trong `src/aml/cases/`: `features.py`, `labels.py`, `model.py`, `prioritize.py`.
- **Sửa kéo theo ở phần đã duyệt — là một phần của spec này**: test của 7a (AC9) đang khẳng định `aml score` là stub
  `arrives in Phase 7` bỏ phần đó; `specs/case-consolidation.md` AC9 thêm ghi chú dẫn về spec này.

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **Nhãn từ ground truth** (`truth_labels`, trên item `ACTIVE` của từng case trong một lần chạy):
  - item `SCREENING` là **thật** khi (`cif`, `entry_id`) ∈ `truth_pairs(db)`;
  - item `RULE` / `NETWORK` là thật khi alert có ít nhất một tài khoản **thuộc golden customer của case** là dòng
    `ground_truth` `entity_type = 'account'`, `is_suspicious` đúng (vai nào cũng tính);
  - case là `SUSPICIOUS` khi có ít nhất một item thật, ngược lại `FALSE_POSITIVE`.
  - `reason`: `simulated from ground truth: {true_alerts} of {alerts} alert(s) match a suspicious scenario ({typologies})`
    (typology tăng dần, nối bằng `, `) hoặc `simulated from ground truth: none of the {alerts} alert(s) matches a suspicious scenario`.
- **Mô phỏng disposition** (`simulate_dispositions`, trên `cases_current`):
  - Nhóm (`case_groups`): thành phần liên thông của đồ thị case nối nhau khi chung `item_key` `ACTIVE`; `group_id` =
    `case_id` nhỏ nhất của nhóm.
  - Chọn nhóm: sắp `group_id` tăng dần, hoán vị bằng `numpy.random.default_rng(settings.seed).permutation(n)`, lấy
    `ceil(simulate_fraction × n)` nhóm đầu của thứ tự đã hoán vị.
  - Mỗi case **chưa từng có disposition** thuộc nhóm được chọn nhận một disposition qua `record_disposition(...,
    origin=SIMULATED, actor=simulated_actor, decided_on=as_of của lần chạy case)`. Case đã có disposition (kể cả của
    người) không bao giờ bị ghi thêm. Case không được chọn ở lại `OPEN` — đó là hàng đợi và cũng là tập holdout.
  - Vì đi qua `record_disposition`, disposition mô phỏng `FALSE_POSITIVE` cũng sinh dòng good-guy (7b-supp).
  - Bảng `ground_truth` rỗng → `PrioritizationError` chứa `no ground truth`, không ghi gì; chưa có lần `run_cases`
    nào → `CaseError` chứa ``run `aml cases build` first``.
  - Audit: mỗi disposition một dòng của 7a (`actor = simulated_analyst`, `details.origin = "SIMULATED"`), cộng 1 dòng
    `entity_type='case_run'`, `decision='DISPOSITIONS_SIMULATED'`, `details` = các trường của `Simulation`.
- **Feature** (`FEATURES`, 35 giá trị số, hàm thuần của `CaseView` — tức của `case_alerts` + `case_enrichment` đã lưu;
  không đọc `ground_truth`, không đọc bảng nguồn; null → 0):
  - đếm: `alerts`, `rule_alerts`, `network_alerts`, `screening_alerts`, `distinct_rules`;
  - cờ 0/1 theo `rule_id`: `has_structuring`, `has_rapid_movement`, `has_high_velocity`, `has_fan_in`, `has_fan_out`,
    `has_dormant_reactivation`, `has_net_shared_attribute`, `has_net_cycle`, `has_net_hub`;
  - screening: `has_screening_alert`, `has_screening_review`, `has_sanctions_hit` (`details.list_type = 'SANCTIONS'`),
    `max_screening_score` (`details.final_score` lớn nhất; 0 khi không có);
  - `alert_amount_log` = `log10(1 + tổng amount_vnd của các item)`;
  - KYC / dữ liệu: `kyc_risk_level` (`LOW` 0, `MEDIUM` 1, `HIGH` 2), `cifs`, `accounts`, `dq_issues` (số phần tử của
    `dq_issues.customer`);
  - giao dịch (từ `txn_summary`): `txn_count`, `in_vnd_log`, `out_vnd_log` (`log10(1 + x)`), `cash_share` = (tiền mặt
    vào + ra) / (vào + ra), `counterparties`, `pass_through` = `min(vào, ra) / max(vào, ra)`; mẫu số 0 → 0;
  - đồ thị (từ `network.features`): `in_degree`, `out_degree`, `pagerank_ratio`, `shared_cluster_size`;
  - lịch sử: `prior_cases`, `prior_false_positives` (số `prior_cases` có `disposition = 'FALSE_POSITIVE'`).
  - Bảng `case_features(run_id, case_id, feature, value)`, PK `(run_id, case_id, feature)` — **dạng dài**: thêm feature
    (điểm bất thường, loại memo của Phase 7b) là thêm dòng, không đổi DDL; mỗi model lưu danh sách feature của riêng nó.
- **Tập huấn luyện** (`train`): mỗi `case_id` có disposition lấy disposition mới nhất và feature của **ảnh chụp mà
  disposition đó nhìn thấy** (`case_dispositions.run_id`; `write_features` tính và ghi nếu run đó chưa có) — case đã
  bị suppression đưa khỏi hàng đợi hiện hành vẫn ở trong tập huấn luyện. `y = 1` khi `SUSPICIOUS`. Nhóm = `case_groups`
  của ảnh chụp đó. Mỗi lớp cần ít nhất `cv_folds` case, nếu không → `PrioritizationError` chứa `not enough labelled
  cases: need at least {cv_folds} per class, got SUSPICIOUS={a} FALSE_POSITIVE={b}`; không ghi gì.
- **Model** (`fit_model`):
  - `logreg`: `StandardScaler` → `LogisticRegression(C=c, max_iter=max_iter, class_weight="balanced", solver="lbfgs",
    random_state=seed)`. `artifact` = JSON các mảng `mean`, `scale`, `coef`, `intercept` — chấm điểm chỉ cần NumPy.
  - `lightgbm`: `LGBMClassifier(class_weight="balanced", random_state=seed, deterministic=True, force_row_wise=True,
    n_jobs=1, verbose=-1, ...)`; chưa cài → `PrioritizationError` chứa `lightgbm is not installed: uv sync --extra ml`.
  - **Mất cân bằng lớp**: `class_weight="balanced"` (trọng số nghịch với tần suất lớp) ở cả hai model; không
    oversampling, không SMOTE.
  - **Đánh giá**: `StratifiedGroupKFold(n_splits=cv_folds, shuffle=True, random_state=seed)` theo nhóm; điểm
    out-of-fold của mọi case → `ranking_metrics`. Model cuối cùng fit trên toàn bộ tập.
  - `ranking_metrics` (thứ tự: `score` giảm, hoà thì `case_id` tăng): `{n, n_suspicious, n_false_positive, prevalence,
    roc_auc, pr_auc, precision_at: {f: …}, recall_at: {f: …}, tail_false_positive_share: {f: …}, tail_suspicious:
    {f: …}}`; top / tail của `f` = `ceil(f × n)` case đầu / cuối; `tail_false_positive_share` = false positive trong
    tail / tổng false positive; `tail_suspicious` = số case đáng ngờ trong tail; số thực làm tròn 4; `roc_auc`, `pr_auc`
    là `None` khi chỉ có một lớp; tỉ lệ có mẫu số 0 là `None`.
  - `data_hash` = 16 ký tự hex đầu của SHA-256 trên (danh sách feature, `case_id` đã sắp, ma trận làm tròn 10, nhãn).
- **Chấm điểm** (`score`): model = `model_id` chỉ định, hoặc dòng `case_model_active` (model mới nhất); chưa có model →
  `PrioritizationError` chứa ``no model: run `aml cases train` first``. Chấm **mọi** case của `cases_current`:
  - `score` làm tròn 6. `contributions`: `logreg` = `coef × (x − mean) / scale` của từng feature (tổng + `intercept` =
    log-odds); `lightgbm` = `predict(pred_contrib=True)` (cột cuối là giá trị nền).
  - `top_features` = `top_features` feature có `|đóng góp|` lớn nhất (hoà: tên tăng dần): `[{feature, value,
    contribution}]`, `contribution` làm tròn 4.
  - `queue_rank` = thứ hạng (từ 1) trong các case `OPEN` / `REOPENED` theo (`score` giảm, `case_id` tăng); case `CLOSED`
    có `queue_rank` null.
  - `holdout` = `ranking_metrics` trên các case `OPEN` / `REOPENED` so với `truth_labels` — ground truth **chỉ để đo**,
    không ghi thành disposition; bảng `ground_truth` rỗng → `{}`.
- **Bảng** (DDL `180`; không bao giờ UPDATE / DELETE):
  - `case_models(model_id PK, kind, version, feature_version, trained_ts UTC, as_of, seed, cases, suspicious,
    false_positive, features JSON, params JSON, metrics JSON, artifact CLOB, data_hash, actor)`; `params` gồm siêu tham
    số, `class_weight`, `cv_folds`, phiên bản thư viện. View `case_model_active` = dòng có `model_id` lớn nhất.
  - `case_scores(score_run_id, run_id, case_id, model_id, model_version, score, queue_rank, top_features JSON, scored_ts
    UTC)`, PK `(score_run_id, case_id)`. View `case_scores_current` = dòng của `score_run_id` lớn nhất trong các lần chấm
    cho lần chạy case hiện hành; `case_queue` = `cases_current` nối `case_scores_current`, chỉ `OPEN` / `REOPENED`.
- **Audit** (`module='cases'`):
  - huấn luyện: `entity_type='model'`, `entity_id=version`, `decision='MODEL_TRAINED'`, `version=version`, `reason` =
    `trained {kind} on {cases} labelled cases ({suspicious} SUSPICIOUS, {false_positive} FALSE_POSITIVE; class_weight balanced): cross-validated ROC-AUC {roc_auc}, PR-AUC {pr_auc}, prevalence {prevalence}; ranking only`,
    `details = {model_id, data_hash, metrics, features}`;
  - mỗi case được chấm: `entity_type='case'`, `entity_id=case_id`, `decision='PRIORITIZED'`, **`version` = phiên bản
    model**, `reason` = `priority score {score:.4f} from {version}, queue rank {rank} of {queue}; top factors: {feature} {contribution:+.2f}, …; ranking only, no disposition`
    (case `CLOSED`: `not in the queue (CLOSED)` thay cho phần rank), `details = {score_run_id, run_id, model_id, score,
    queue_rank, top_features}`;
  - mỗi lần chấm: `entity_type='case_run'`, `decision='SCORING_RUN_COMPLETED'`, `details` = các trường của `ScoringRun`.
- **`aml score`** (thay stub): `run_cases` → nếu `simulate_dispositions`: `simulate_dispositions` → `run_cases` lần nữa
  (cập nhật trạng thái và suppression theo disposition vừa có) → `train` → `score` → in. Lỗi `CaseError` /
  `PrioritizationError` → stderr, exit 1 (các bước trước đó đã ghi vẫn giữ). Output: một dòng cho mỗi bước (`cases
  run_id= …`, `labels labelled= SUSPICIOUS= FALSE_POSITIVE= held_out=`, `model version= cases= roc_auc= pr_auc=
  prevalence=`, `scored cases= queue= model=`, `holdout n= roc_auc= pr_auc= prevalence=`), rồi `--top` (mặc định 10)
  dòng đầu hàng đợi `rank score case_id top=<feature>,<feature>,<feature>`, và dòng cuối `ranking only: no case was
  closed or cleared by the model`. `--eval-out` ghi JSON `{model, cv, holdout}`.

## Tiêu chí nghiệm thu
<!-- settings, as_of, MINI-C, `tiny_cases` như specs/case-consolidation.md; seed 42.
MINI-GT = MINI-C + ground_truth: ('GT-STR-0001', 'structuring', TRUE, 'account', 'A01', 'subject'),
  ('GT-RND-0001', 'round_tripping', TRUE, 'account', 'A03', 'hop'), ('GT-PAY-0001', 'benign_payroll', FALSE, 'account',
  'A04', 'employer'), ('GT-SAN-0001', 'sanctions_hit', TRUE, 'customer', 'C05', 'subject'), ('GT-SAN-0001',
  'sanctions_hit', TRUE, 'watchlist_entry', 'WL2', 'listed_entry'); đã `run_cases` (run 1, 5 case).
TOY = X có 40 dòng, index case_id = f"C-T{i:02d}-20260101" (i = 0..39), cột = FEATURES; `network_alerts` = 1 khi i chẵn,
  ngược lại 0; `alerts` = 1 + (i // 2) % 4; mọi cột khác 0.0; y = 1 khi i chẵn; groups = chính case_id.
TINY-L = `tiny_cases` đã `run_cases` (run 1, 52 case), rồi `record_disposition(..., actor="analyst01")`:
  FALSE_POSITIVE cho 11 case có sources = 'RULE', SUSPICIOUS cho 27 case có sources = 'NETWORK'; rồi `run_cases` (run 2).
Test LightGBM dùng `pytest.importorskip("lightgbm")`. Mọi giá trị suy ra từ luật, trừ khi ghi "đã đo". -->
- AC1: Given `config.yaml`, `pyproject.toml`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS` và gọi `apply_schema(duck)` hai lần, Then `settings.cases.prioritization` có `model == "logreg"`, `simulate_dispositions is True`, `simulate_fraction == 0.7`, `simulated_actor == "simulated_analyst"`, `cv_folds == 5`, `top_features == 5`, `top_fractions == [0.1, 0.2, 0.5]`, `logreg.c == 1.0`, `logreg.max_iter == 1000`; `load_settings(environ={"AML__CASES__PRIORITIZATION__MODEL": "xgboost"})` raise `pydantic.ValidationError`, `AML__CASES__PRIORITIZATION__SIMULATE_FRACTION=0` raise `ValidationError` chứa `simulate_fraction must be in (0, 1]`, `AML__CASES__PRIORITIZATION__CV_FOLDS=1` raise `ValidationError` chứa `cv_folds must be >= 2`, `AML__CASES__PRIORITIZATION__SIMULATED_ACTOR=system` raise `ValidationError` chứa `simulated_actor must differ from audit.system_actor`; `import sklearn` thành công; `pyproject.toml` có `scikit-learn` trong `project.dependencies` và `lightgbm` chỉ trong `project.optional-dependencies.ml`; `ddl/180_case_prioritization.sql` có trong `SCHEMA_SCRIPTS` của cả hai backend, sau `ddl/170_case_suppression.sql` và trước các script `050_*`; `apply_schema` không raise; `SELECT COUNT(*)` trên `case_features`, `case_models`, `case_scores`, `case_model_active`, `case_scores_current`, `case_queue` đều trả 0; `len(FEATURES) == 35`, không tên nào trùng, `FEATURE_VERSION == "features/v1"`; và tập tên cột của `case_scores` không chứa `disposition` hay `status`.
- AC2: Given MINI-GT, When gọi `case_features(load_case(duck, case_id))` và `write_features(duck, 1)`, Then với `C-C01-20260302` kết quả có đúng 35 khoá bằng `FEATURES`, trong đó `alerts = 3`, `rule_alerts = 2`, `network_alerts = 1`, `screening_alerts = 0`, `distinct_rules = 3`, `has_structuring = 1`, `has_rapid_movement = 1`, `has_net_cycle = 1`, `has_fan_out = 0`, `has_screening_alert = 0`, `max_screening_score = 0`, `alert_amount_log` cách 9.350248 không quá 1e-6 (tổng 2 240 000 000), `kyc_risk_level = 2`, `cifs = 2`, `accounts = 2`, `txn_count = 5`, `in_vnd_log` cách 9.068186 không quá 1e-6, `out_vnd_log` cách 8.892095 không quá 1e-6, `cash_share = 0.2`, `counterparties = 4`, `pass_through` cách 0.666667 không quá 1e-6, `in_degree = 0`, `pagerank_ratio = 0`, `prior_cases = 0`, `prior_false_positives = 0`; với `C-C01-20260531`: `has_fan_out = 1`, `has_screening_alert = 1`, `has_sanctions_hit = 1`, `max_screening_score = 100`, `prior_cases = 1`; với `C-C05-20260630`: `alerts = 1`, `screening_alerts = 1`, `has_screening_review = 1`, `has_sanctions_hit = 0`, `max_screening_score = 80`, `txn_count = 0`, `cash_share = 0`, `pass_through = 0`, `kyc_risk_level = 0`, `cifs = 1`; mọi giá trị là `float` hữu hạn; `write_features(duck, 1)` trả 175 và `case_features` có 175 dòng `run_id = 1`, gọi lần hai trả 0 và bảng vẫn 175 dòng; `read_features(duck, 1)` trả frame 5 × 35 có index tăng dần và cột đúng thứ tự `FEATURES`; sau `record_disposition(duck, settings, "C-C01-20260302", "FALSE_POSITIVE", reason="x", actor="analyst01")` và `run_cases` (run 2), `case_features(load_case(duck, "C-C01-20260531"))["prior_false_positives"] == 1` trong khi `read_features(duck, 1)` không đổi (ảnh chụp cũ không bị tính lại); và mã nguồn của `aml.cases.features` không chứa chuỗi `ground_truth`.
- AC3: Given MINI-GT, When gọi `truth_labels(duck)`, `case_groups(duck, 1)` rồi `simulate_dispositions` với các `simulate_fraction` khác nhau, Then `truth_labels` trả 5 phần tử: `C-C01-20260302` → `SUSPICIOUS`, `true_alerts = 2`, `alerts = 3`, `typologies = ("structuring",)`, `reason` bằng đúng `simulated from ground truth: 2 of 3 alert(s) match a suspicious scenario (structuring)`; `C-C01-20260531` → `SUSPICIOUS` với `true_alerts = 1` (R3 trên A01; cặp `C02` × `WL1` không phải true hit); `C-C03-20260305` → `SUSPICIOUS`, `true_alerts = 2`, `typologies = ("round_tripping",)`; `C-C04-20260305` → `FALSE_POSITIVE`, `true_alerts = 0`, `reason` bằng đúng `simulated from ground truth: none of the 1 alert(s) matches a suspicious scenario` (A04 chỉ thuộc kịch bản lành tính; A01 và A03 trong cùng alert không thuộc `G-C04`); `C-C05-20260630` → `SUSPICIOUS`, `typologies = ("sanctions_hit",)`; `case_groups` trả 3 nhóm: `C-C01-20260302`, `C-C03-20260305`, `C-C04-20260305` cùng nhóm `C-C01-20260302`, hai case còn lại mỗi case một nhóm; với `AML__CASES__PRIORITIZATION__SIMULATE_FRACTION=0.5`, `simulate_dispositions` trả `Simulation(run_id=1, groups=3, labelled_groups=2, labelled=2, suspicious=2, false_positive=0, held_out=3, skipped=0)` và `case_dispositions` có đúng 2 dòng cho `C-C05-20260630` và `C-C01-20260531` (đã đo: `default_rng(42).permutation(3) == [2, 1, 0]`), cả hai `origin = 'SIMULATED'`, `actor = 'simulated_analyst'`, `decided_on = 2026-06-30`, `run_id = 1`, `reason` bắt đầu bằng `simulated from ground truth:`; gọi lại lần hai trả `labelled = 0`, `skipped = 2` và bảng vẫn 2 dòng; Given MINI-GT mới với `simulate_fraction = 1.0` và `record_disposition(duck, settings, "C-C04-20260305", "SUSPICIOUS", reason="manual", actor="analyst01")` gọi trước, Then `simulate_dispositions` trả `labelled = 4`, `suspicious = 4`, `false_positive = 0`, `skipped = 1`, `held_out = 0` và `case_dispositions_current` của `C-C04-20260305` vẫn là dòng của `analyst01`; còn khi không có lời gọi tay đó thì `C-C04-20260305` nhận disposition mô phỏng `FALSE_POSITIVE` (`labelled = 5`, `suspicious = 4`, `false_positive = 1`); `audit_log` có mỗi disposition mô phỏng một dòng `actor='simulated_analyst'`, `details.origin = "SIMULATED"` và mỗi lần gọi 1 dòng `decision='DISPOSITIONS_SIMULATED'`; Given `tiny_cases` đã `run_cases` với `simulate_fraction = 1.0`, Then `simulate_dispositions` trả `groups = 18`, `labelled = 52`, `suspicious = 52`, `false_positive = 0` (đã đo), còn với `simulate_fraction = 0.7` trả `labelled_groups = 13`, `labelled + held_out == 52`, mọi case của cùng một nhóm hoặc cùng có disposition hoặc cùng không, và hai DuckDB dựng độc lập cho cùng tập `case_id` được gán; và Given bảng `ground_truth` rỗng, Then `simulate_dispositions` raise `PrioritizationError` chứa `no ground truth`.
- AC4: Given hàm thuần `fit_model`, `predict`, `ranking_metrics`, cấu hình mặc định và TOY, When gọi `m = fit_model(X, y, groups, cfg, seed=42)` rồi `p = predict(m, X)`, Then `m.kind == "logreg"`, `m.features == FEATURES`, `m.metrics` có `n = 40`, `n_suspicious = 20`, `n_false_positive = 20`, `prevalence = 0.5`, `roc_auc = 1.0`, `pr_auc = 1.0`, `precision_at = {0.1: 1.0, 0.2: 1.0, 0.5: 1.0}`, `recall_at = {0.1: 0.2, 0.2: 0.4, 0.5: 1.0}`, `tail_false_positive_share = {0.1: 0.2, 0.2: 0.4, 0.5: 1.0}`, `tail_suspicious = {0.1: 0, 0.2: 0, 0.5: 0}`; `m.params["class_weight"] == "balanced"` và `m.params["cv_folds"] == 5`; `json.loads(m.artifact)` có đúng các khoá `features`, `mean`, `scale`, `coef`, `intercept` với ba mảng dài 35; mọi `score` của dòng có i chẵn lớn hơn 0.5 và của dòng có i lẻ nhỏ hơn 0.5; với mọi dòng, `1 / (1 + exp(-(intercept + sum(contributions.values()))))` cách `score` không quá 1e-9; feature có `|contribution|` lớn nhất của mọi dòng là `network_alerts`, và `contributions` của mọi feature hằng (vd `has_net_hub`) bằng 0.0; gọi `fit_model` lần hai với cùng đầu vào cho `artifact`, `metrics` và `data_hash` giống hệt, còn đảo thứ tự dòng của `X`, `y`, `groups` cho cùng `data_hash`; đổi một ô của `X` cho `data_hash` khác; `ranking_metrics(pd.Series([1, 1, 0, 0]), pd.Series([0.9, 0.8, 0.7, 0.1]), [0.5])` trả `precision_at = {0.5: 1.0}`, `recall_at = {0.5: 1.0}`, `roc_auc = 1.0`, còn với `y` toàn 1 trả `roc_auc is None`, `pr_auc is None`, `prevalence = 1.0`, `tail_false_positive_share = {0.5: None}`; `fit_model` với `y` toàn 1 raise `PrioritizationError` chứa `need at least 5 per class, got SUSPICIOUS=40 FALSE_POSITIVE=0`; với TOY mà chỉ 4 dòng có `y = 0` raise `PrioritizationError` chứa `FALSE_POSITIVE=4`; và mã nguồn của `aml.cases.model` không chứa `import duckdb`, `Database` hay `record_disposition`.
- AC5: Given TINY-L (38 case có disposition: 27 `SUSPICIOUS`, 11 `FALSE_POSITIVE`; run 2 có `cases = 52`, `closed = 38`, `suppressed = 0`), When gọi `t = train(db, settings, actor="analyst01")` rồi gọi lần hai, Then `t.model_id = 1`, `t.version == "prio/logreg/1"`, `t.kind == "logreg"`, `t.cases = 38`, `t.suspicious = 27`, `t.false_positive = 11`, `t.metrics["n"] = 38`, `t.metrics["prevalence"] = 0.7105`, `t.metrics["roc_auc"] >= 0.9` (hai lớp tách nhau theo `network_alerts`), mọi giá trị của `precision_at`, `recall_at` nằm trong [0, 1]; `case_models` có 1 dòng với `version = 'prio/logreg/1'`, `feature_version = 'features/v1'`, `seed = 42`, `cases = 38`, `suspicious = 27`, `false_positive = 11`, `features` là mảng 35 tên bằng `FEATURES`, `params.class_weight = "balanced"`, `params.cv_folds = 5`, `params.sklearn` bắt đầu bằng phiên bản đang cài, `data_hash` dài 16 ký tự hex, `actor = 'analyst01'`; `case_features` có dòng cho `run_id = 1` (ảnh chụp mà 38 disposition nhìn thấy); `audit_log` có 1 dòng `decision='MODEL_TRAINED'`, `entity_type='model'`, `entity_id='prio/logreg/1'`, `version='prio/logreg/1'`, `actor='analyst01'`, `reason` bắt đầu bằng `trained logreg on 38 labelled cases (27 SUSPICIOUS, 11 FALSE_POSITIVE; class_weight balanced)` và kết thúc bằng `ranking only`, `details.data_hash` bằng cột `data_hash`; lần hai trả `model_id = 2`, `version == "prio/logreg/2"` với `data_hash`, `artifact` và `metrics` bằng đúng lần một, và `case_model_active` trả dòng `model_id = 2`; số dòng `case_dispositions`, `cases`, `case_alerts` trước và sau hai lần `train` bằng nhau; Given `tiny_cases` đã `run_cases` nhưng chưa có disposition, When gọi `train`, Then raise `PrioritizationError` chứa `not enough labelled cases: need at least 5 per class, got SUSPICIOUS=0 FALSE_POSITIVE=0` và `case_models` rỗng; và Given `tiny_cases` với `simulate_dispositions` ở `simulate_fraction = 1.0`, Then `train` raise `PrioritizationError` chứa `got SUSPICIOUS=52 FALSE_POSITIVE=0`.
- AC6: Given TINY-L đã `train` (model 1), When gọi `s = score(db, settings, actor="analyst01")` rồi gọi lần hai, Then `s.score_run_id = 1`, `s.run_id = 2`, `s.model_id = 1`, `s.version == "prio/logreg/1"`, `s.cases = 52`, `s.queue = 14`; `case_scores` có 52 dòng `score_run_id = 1`, mọi `score` trong (0, 1) với đúng 6 chữ số thập phân trở xuống, mọi dòng có `model_version = 'prio/logreg/1'`; 14 case `OPEN` có `queue_rank` là hoán vị của 1..14 và `score` không tăng theo `queue_rank` (hoà thì `case_id` tăng), 38 case `CLOSED` có `queue_rank` null; mỗi `top_features` là mảng đúng 5 phần tử `{feature, value, contribution}` với `feature` ∈ `FEATURES`, không trùng, `|contribution|` không tăng; với mọi case, `score` bằng (sai số 1e-6) điểm tính lại từ `artifact` của `case_models` và dòng `read_features(db, 2)` của case đó chỉ bằng NumPy; `case_queue` trả đúng 14 dòng sắp theo `queue_rank`; `load_case(db, "C-CIF00000189-20260413").score` có các khoá `score`, `queue_rank`, `model_version`, `top_features` và `model_version == "prio/logreg/1"`; `audit_log` có đúng 52 dòng `decision='PRIORITIZED'` với `entity_type='case'`, **`version='prio/logreg/1'`**, `details.model_id = 1`, `details.score` bằng `score` của bảng, mỗi `reason` bắt đầu bằng `priority score` và kết thúc bằng `ranking only, no disposition`, dòng của một case `CLOSED` chứa `not in the queue (CLOSED)`, cộng 1 dòng `decision='SCORING_RUN_COMPLETED'`; `s.holdout["n"] = 14`, `s.holdout["n_suspicious"] = 14`, `s.holdout["prevalence"] = 1.0`, `s.holdout["roc_auc"] is None` (14 case còn mở của TINY đều đáng ngờ — đã đo); trước và sau `score`: số dòng và nội dung của `case_dispositions`, `cases`, `case_alerts`, `good_guy_list` không đổi và `cases_current` vẫn có 14 dòng `OPEN`; mã nguồn của `aml.cases.prioritize` và `aml.cases.model` không chứa `record_disposition`; lần hai trả `score_run_id = 2` với cột `score`, `queue_rank`, `top_features` giống hệt lần một và `case_scores_current` chỉ trả 52 dòng `score_run_id = 2`; `score(db, settings, model_id=99)` raise `PrioritizationError` chứa `unknown model_id`; và Given `tiny_cases` đã `run_cases` nhưng chưa `train`, When gọi `score`, Then raise `PrioritizationError` chứa ``no model: run `aml cases train` first`` và `case_scores` rỗng.
- AC7: Given `lightgbm` đã cài (`pytest.importorskip`), TOY và TINY-L, When gọi `m = fit_model(X, y, groups, cfg, seed=42, kind="lightgbm")` và `train(db, settings, kind="lightgbm")`, Then `m.kind == "lightgbm"`, `m.metrics["roc_auc"] = 1.0`, `m.params["class_weight"] == "balanced"`, `m.artifact` là chuỗi bắt đầu bằng `tree`; `predict(m, X)` cho mọi dòng i chẵn điểm cao hơn mọi dòng i lẻ và feature đóng góp lớn nhất của mọi dòng là `network_alerts`; gọi `fit_model` hai lần cho `artifact` giống hệt; `train` trả `version == "prio/lightgbm/1"` (model đầu tiên của DB đó) và `score` sau đó ghi `model_version = 'prio/lightgbm/1'` vào `case_scores` và vào `version` của 52 dòng audit `PRIORITIZED`; và Given `lightgbm` **không** import được (monkeypatch `sys.modules["lightgbm"] = None`), When gọi `fit_model(X, y, groups, cfg, seed=42, kind="lightgbm")`, Then raise `PrioritizationError` chứa `lightgbm is not installed: uv sync --extra ml` trong khi `kind="logreg"` vẫn chạy.
- AC8: Given `tiny_env` đã `aml load`, `aml er`, `aml screen`, `aml monitor`, `aml network`, When chạy `aml score`, Then exit code 1, stdout có một dòng bắt đầu bằng `cases` chứa `cases=52` và một dòng bắt đầu bằng `labels` chứa `FALSE_POSITIVE=0`, stderr chứa `not enough labelled cases`, `case_models` và `case_scores` rỗng, còn `case_runs` có 2 dòng và mọi dòng `case_dispositions` có `origin = 'SIMULATED'`; Given một `tiny_env` khác được đưa về trạng thái TINY-L bằng lời gọi hàm, có `AML__CASES__PRIORITIZATION__SIMULATE_DISPOSITIONS=false`, When chạy `aml score --top 3 --eval-out <tmp>/prio.json`, Then exit code 0; stdout có đúng một dòng bắt đầu bằng `cases` (chứa `cases=52`, `closed=38`), không có dòng bắt đầu bằng `labels`, một dòng bắt đầu bằng `model` chứa `version=prio/logreg/1`, `cases=38` và `prevalence=0.71`, một dòng bắt đầu bằng `scored` chứa `cases=52`, `queue=14`, `model=prio/logreg/1`, một dòng bắt đầu bằng `holdout` chứa `n=14`, đúng 3 dòng hàng đợi bắt đầu lần lượt bằng `1 `, `2 `, `3 ` và mỗi dòng chứa `top=`, và dòng cuối bằng đúng `ranking only: no case was closed or cleared by the model`; file `prio.json` có ba khoá `model`, `cv`, `holdout` với `model.version == "prio/logreg/1"` và `cv.n == 38`; `aml cases train` trên cùng DB exit code 0 với stdout chứa `version=prio/logreg/2`; `aml cases label --fraction 1.0` exit code 0 với stdout chứa `labelled=14`, `skipped=38`; `aml cases train --model xgboost` exit code 2; `aml score --as-of 2026-13-01` exit code 2; `aml --help` vẫn liệt kê `score` và không lệnh nào trong `score`, `cases label`, `cases train` in `arrives in Phase 7`; và Given DuckDB chỉ mới `aml load`, When chạy `aml score`, Then exit code 1 với stderr chứa ``run `aml er` first``.
- AC9: [oracle] Given TINY nạp vào cả Oracle và một DuckDB tạm, cả hai đưa về trạng thái TINY-L, When gọi `train` rồi `score` trên hai backend, Then `cases`, `suspicious`, `false_positive` và `data_hash` của hai `TrainingRun` / hai dòng `case_models` bằng nhau; `metrics` bằng nhau; mảng `coef` của hai `artifact` lệch nhau không quá 1e-9; cột `score` của 52 case lệch không quá 1e-6 và `queue_rank` bằng nhau giữa hai backend; `read_features` của lần chạy hiện hành cho hai frame bằng nhau (sai số 1e-9); trên Oracle `user_tables` có `CASE_FEATURES`, `CASE_MODELS`, `CASE_SCORES` và `user_views` có `CASE_MODEL_ACTIVE`, `CASE_SCORES_CURRENT`, `CASE_QUEUE`; 52 dòng audit `PRIORITIZED` của lần chấm trên Oracle đều có `version` bằng `version` của model trên Oracle; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- **Phase 7b của brief**: Isolation Forest / điểm bất thường làm nguồn alert và feature; mô hình screening học được; **mẫu below-the-line** và báo cáo thiên lệch chọn mẫu; **model card**; phân loại memo bằng LLM làm feature. Điểm mở rộng để lại: `case_features` dạng dài + `FEATURES` / `FEATURE_VERSION` (thêm feature không đổi DDL), `case_models.kind` nhận model mới, `case_models.metrics` / `params` là JSON, `model_version` nằm trên mọi dòng `case_scores` và mọi dòng audit `PRIORITIZED`.
- Mẫu below-the-line và model card được xây ở `specs/ml-governance.md` (2026-10-14).
- **Tự đóng / tự clear / tự suppress theo điểm**: không ngưỡng điểm nào sinh disposition, không lọc case điểm thấp khỏi hàng đợi, không đổi `cases.status`. Model chỉ sắp thứ tự.
- Tinh chỉnh siêu tham số, chọn feature tự động, calibration xác suất, ensemble, giải thích bằng thư viện `shap`, giám sát drift, tự huấn luyện lại theo lịch, champion / challenger, phê duyệt model trước khi kích hoạt (model mới nhất là model hiệu lực).
- Disposition mô phỏng có nhiễu / lỗi của investigator, độ trễ xử lý, nhiều mức (`ESCALATED`, `STR_FILED`); nhãn theo từng alert; trọng số theo mức độ nghiêm trọng của typology.
- Sửa generator Phase 1 hay ngưỡng rule 5a / 5c để có thêm false positive (Q2).
- Feature đọc thẳng từ Neo4j, từ memo, từ tên khách hàng; feature dùng `ground_truth`.
- Lưu model dạng pickle / file ngoài database; phục vụ model qua API (Phase 9 đọc `case_queue`).
- Quyền Oracle trên ba bảng mới cho role của 2b; đo trên `large`; ghi số liệu vào README (bước demo: `aml score --eval-out results/phase7/prioritization.json` trên `small`).

## Giả định
- **Đã xác nhận (2026-10-13, xem Câu hỏi mở)**: case đáng ngờ khi có ít nhất một alert thật, vai nào cũng tính — `small` 291 / 44 (Q1 — người dùng xác nhận trực tiếp); chấp nhận dữ liệu 87 % đáng ngờ, nói thẳng trong metric và README, không sửa generator hay ngưỡng rule (Q2 — người dùng xác nhận trực tiếp); mô phỏng disposition cho 70 % số nhóm có seed, phần còn lại là hàng đợi + holdout (Q3); `StratifiedGroupKFold` 5 fold + `class_weight="balanced"` (Q4); LightGBM là tuỳ chọn trong extra `ml` (Q5); model lưu trong database, model mới nhất có hiệu lực (Q6); `aml score` chạy cả chuỗi Phase 7 (Q7).
- **Đã đo** (prototype ngoài repo): bảng nhãn TINY / `small`, số nhóm (18 / 199), baseline 24 feature, tính tất định của logistic regression, `default_rng(42).permutation(3)`, và việc 14 case còn mở của TINY-L đều đáng ngờ. **Suy ra, chưa chạy**: giá trị feature của MINI-GT (số học trên enrichment của 7a), TOY (tách hoàn toàn theo một feature nên ROC-AUC = 1,0 — nếu khi hiện thực một fold cho thứ tự khác thì xem lại fixture, không nới AC), TINY-L (`roc_auc >= 0.9` dựa trên việc hai lớp khác nhau ở `network_alerts`), AC7–AC9.
- Số liệu TINY-L là của một bộ nhãn **dựng tay cho test** (case chỉ có rule = false positive), không phản ánh ground truth; không được dùng làm kết quả trong README.
- Kết quả tất định với cùng dữ liệu, cấu hình, `settings.seed`, cùng phiên bản scikit-learn / NumPy trên cùng nền tảng; giữa Oracle và DuckDB cho phép lệch số thực cỡ 1e-9 (đường đọc JSON / số).
- Disposition mô phỏng là **dữ liệu demo**: luôn mang `origin = 'SIMULATED'` và actor riêng, phân biệt được với quyết định của người ở mọi bảng và mọi dòng audit; không noise, đúng tuyệt đối theo ground truth — nên metric là cận trên so với nhãn thật của investigator.
- Chọn nhóm để mô phỏng được tính lại mỗi lần gọi trên tập nhóm hiện hành; khi có case mới, tập nhóm đổi và một số case trước đây để mở có thể được mô phỏng ở lần sau.
- Điểm là thứ tự tương đối trong một lần chấm, **không phải xác suất đã hiệu chỉnh** (trọng số lớp làm lệch xác suất); `reason` nói rõ `ranking only`.
- `aml score` chạy dưới schema owner; `reason`, lỗi, output bằng tiếng Anh; test [oracle] để lại dữ liệu như các phase trước.
- Bổ sung sau review (2026-10-13): `train` ghi dòng `case_models` và audit `MODEL_TRAINED` trong một giao dịch (`db.transaction()`), `score` ghi `case_scores` và các dòng audit `PRIORITIZED` trong một giao dịch — không có model hay điểm nào tồn tại mà thiếu audit. Phần tính top feature, thứ hạng hàng đợi, holdout và sự kiện audit của từng case nằm ở `src/aml/cases/scoring.py`.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Một case là "đáng ngờ" theo ground truth khi nào? — đề xuất mặc định: khi có ít nhất một alert **thật** — screening hit là cặp true hit, hoặc alert giao dịch / mạng lưới có tài khoản của chính khách hàng đó nằm trong kịch bản `is_suspicious`, **vai nào cũng tính** (cùng định nghĩa với đánh giá của 5a / 5c). Đã đo: `small` 291 / 44, TINY 52 / 0. Lý do: nhất quán — alert đã được 5a tính là true positive không thể thành false positive ở đây; không phải tự đặt ra vai nào "đủ nặng". Phương án thay thế: chỉ vai chính (`subject`, `collector`, `hop`, `member`) là đáng ngờ, `source` / `destination` là false positive → 208 / 127 trên `small` (cân bằng hơn, nhưng là một phán đoán nghiệp vụ cần anh/chị chốt). — Trả lời: theo đề xuất mặc định (người dùng xác nhận trực tiếp, 2026-10-13).
- [x] Q2. **(cần người dùng quyết)** Dữ liệu tổng hợp cho 87 % case đáng ngờ (ngoài đời vài %) và TINY không có false positive nào — chấp nhận hay tạo thêm nhiễu? — đề xuất mặc định: **chấp nhận và nói thẳng**: huấn luyện trên `small`, lớp thiểu số là `FALSE_POSITIVE`, mọi bảng metric có cột `prevalence`, thêm hai số "false positive bị đẩy xuống cuối hàng đợi" (`tail_false_positive_share`, `tail_suspicious`), và README ghi rõ hạn chế này. Test dùng fixture dựng tay (TOY, TINY-L). Lý do: sửa Phase 1 / nới ngưỡng rule để ra tỉ lệ "giống thật" là chỉnh dữ liệu theo kết quả mong muốn. Phương án thay thế: một spec riêng thêm hành vi nền gây alert giả vào generator rồi chạy lại Phase 5–6 (đụng nhiều spec đã duyệt và mọi số liệu đã ghim). — Trả lời: theo đề xuất mặc định (người dùng xác nhận trực tiếp, 2026-10-13).
- [x] Q3. **(cần người dùng quyết)** Case nào được mô phỏng disposition, case nào để mở cho hàng đợi? — đề xuất mặc định: chọn ngẫu nhiên có seed **70 % số nhóm** (nhóm = các case chung alert) để mô phỏng; 30 % còn lại ở trạng thái `OPEN`, được chấm điểm và dùng làm holdout (so với ground truth chỉ để đo). Lý do: nếu mô phỏng hết thì không còn hàng đợi nào để xếp hạng trong UI; chia theo nhóm tránh rò rỉ giữa các thành viên của cùng một ring. Phương án thay thế: chia theo thời gian (case trước một ngày là đã xử lý) — sát thực tế hơn, nhưng đã đo: mọi screening hit có mốc 2026-06-30 nên toàn bộ false positive screening sẽ rơi vào phía chưa xử lý và model không học được chúng. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q4. Chia fold và xử lý mất cân bằng thế nào? — đề xuất mặc định: `StratifiedGroupKFold` 5 fold theo nhóm, metric tính trên điểm out-of-fold; mất cân bằng xử lý bằng `class_weight="balanced"`, không oversampling. Lý do: 29 case của một ring chung một alert — chia theo case sẽ thổi phồng metric; trọng số lớp tất định và giải thích được trong một câu. Hệ quả: điểm không phải xác suất đã hiệu chỉnh. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q5. **(cần người dùng quyết)** LightGBM có làm trong phase này không? — đề xuất mặc định: có, nhưng là **tuỳ chọn thật sự**: nằm trong extra `ml` (không cài mặc định), chọn bằng `--model lightgbm` / `cases.prioritization.model`; logistic regression là mặc định và là model của mọi số liệu README trừ khi anh/chị chạy cả hai. Lý do: brief ghi "optionally LightGBM"; với khoảng 235 case huấn luyện, model tuyến tính đủ và dễ trình bày từng hệ số; LightGBM kéo thêm wheel ~1,5 MB và một AC tự skip khi chưa cài. Phương án thay thế: bỏ hẳn khỏi Phase 7, để Phase 7b. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q6. Model và phiên bản lưu ở đâu, "model hiệu lực" là gì? — đề xuất mặc định: lưu **trong database** (`case_models`: hệ số / chuỗi model, feature, tham số, metrics, `data_hash`), phiên bản `prio/<kind>/<model_id>`, model mới nhất là model hiệu lực; phiên bản được ghi vào từng dòng `case_scores` và cột `version` của từng dòng audit `PRIORITIZED`. Lý do: không có file pickle ngoài luồng kiểm soát; truy được mỗi điểm về đúng model và đúng dữ liệu huấn luyện. Phương án thay thế: thêm bước phê duyệt model (cột trạng thái + người duyệt) trước khi dùng — đúng với model governance thật, đề xuất làm cùng model card ở Phase 7b. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q7. `aml score` làm gì? — đề xuất mặc định: chạy cả chuỗi Phase 7 (`cases build` → mô phỏng disposition → `cases build` lại → huấn luyện → chấm điểm) để `make score` / `make all` chạy một lệnh; từng bước vẫn gọi riêng được qua `aml cases …`. Hệ quả: trên dữ liệu chỉ có một lớp (TINY) lệnh dừng ở bước huấn luyện với exit 1 và thông điệp rõ. Phương án thay thế: `aml score` chỉ chấm điểm bằng model đã có, không tự mô phỏng hay huấn luyện. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
