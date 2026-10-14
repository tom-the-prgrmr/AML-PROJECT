---
id: screening-ml
status: approved
approved_by: pthieu
---

# Phase 7b-ii — Mô hình screening học được: nhãn investigator mô phỏng, feature của cặp khớp, logistic regression, so với ngưỡng cố định ở cùng recall, `aml screen-ml`

## Bối cảnh
Mục 2 của "8b. Phase 7b" trong PROJECT_BRIEF.md (cộng mục 4 "Model governance" ở phần áp dụng cho model này). Dựng trên
screening hai tầng của Phase 3 (`specs/screening-normalize-score.md`, `specs/screening-tiers-eval.md`,
`specs/screening-oracle-incremental.md`) và ground truth của Phase 1 (`specs/datagen-watchlist-output.md`). Spec này:
(1) **mô phỏng quyết định của investigator** (`TRUE_MATCH` / `FALSE_MATCH`) trên các hit screening hiện hành, lấy từ
ground truth, đánh dấu rõ là mô phỏng và **không bao giờ ghi thành review của người**; (2) dựng **feature của từng cặp
khớp** (điểm tên, độ hiếm token, khớp năm sinh / quốc tịch / giới tính / số giấy tờ); (3) huấn luyện một
**logistic regression** nhỏ; (4) **so với logic ngưỡng cố định** (`ALERT`, `ALERT` + `REVIEW`) bằng precision ở **cùng
recall**, trên cả cross-validation lẫn một tập held-out; (5) lưu điểm theo từng hit cùng phiên bản model và audit.
Model **chỉ xếp hạng**: không đổi `decision` của Tier 2, không clear, không đóng hit nào. Người dùng: analyst screening
(thứ tự xem hit), kiểm soát model (phiên bản, metrics, dữ liệu huấn luyện → model card của `specs/ml-governance.md`),
người phỏng vấn (so sánh với ngưỡng cố định).

### Hiện trạng đã kiểm (2026-10-14, `main` aff6d91, seed 42)
Đo bằng script tạm ngoài repo (thư mục scratchpad của phiên, scikit-learn 1.9.1 đang cài), trên **bản sao** của
`data/aml.duckdb` (`small`, đã `aml screen`) và một DuckDB TINY dựng riêng bằng `aml data` / `aml load` / `aml screen` với
đúng các biến môi trường của fixture `tiny_parquet`. Không file nào trong repo bị sửa, `data/aml.duckdb` chỉ được copy.
- **Hit đang có** (`screening_current`): `small` 6280 cặp (cif, entry_id) = 41 `ALERT` + 31 `REVIEW` + 6208
  `AUTO_CLEARED`, thuộc 673 `entry_id` khác nhau; TINY 55 cặp = 5 `ALERT` + 50 `AUTO_CLEARED`, 34 `entry_id`. Chỉ cặp
  có `fuzzy >= review_threshold` mới được ghi (3b Q2) — cặp thấp hơn không có dòng, nên không thể chấm.
- **Ground truth**: `aml.screening.evaluate.truth_pairs` — `small` 25 cặp thật, TINY 5. Kết quả hiện tại
  (`results/phase3/screening_eval.csv`, `small`): `two_tier_alert` flagged 41, tp 25, precision 0,6098, recall 1,0;
  `two_tier` flagged 72, tp 25, precision 0,3472, recall 1,0. Trên TINY cả hai đều hoàn hảo (5 / 5).
  ⇒ Ngưỡng cố định **đã đạt recall 1,0** trên cả hai bộ dữ liệu: "cùng recall" thực chất là "recall 1,0", và model chỉ
  có thể thắng ở precision (ít hit phải xem hơn).
- **Cột đã lưu** trong `screening_results`: `token_set`, `jaro_winkler`, `fuzzy_score`, `coverage`, `name_score`,
  `final_score`, `dob_gap_years`, `matched_name`, `matched_name_type`, `list_type`, `decision`. **Không lưu**: token khớp,
  `common_only`, quốc tịch / giới tính hai phía. Các giá trị này tính lại được từ `customers.full_name` (chuẩn hoá) +
  `matched_name` + IDF đóng băng (`aml.screening.state.load_token_stats`, bảng `screening_token_stats`, 228 token trên
  `small`) bằng `score_names` của 3a.
- **`watchlist` không có giới tính và số giấy tờ** (3b Q1): feature `gender_mismatch`, `id_match` luôn bằng 0 trên dữ
  liệu Phase 1 (đã đo: hằng số trên cả TINY lẫn `small`).
- **Review của người trên hit đã có** (`aml.screening.review`, spec `ui-live-pages` Q1): `record_review` ghi **1 dòng
  `audit_log`** `module='screening'`, `entity_type='screening_match'`, `decision` ∈ {`TRUE_MATCH`, `FALSE_MATCH`},
  `details.origin = "HUMAN"`; `latest_reviews` đọc lại **mọi** dòng audit có đúng ba điều kiện đó và API / UI hiện nó là
  "review" của hit. ⇒ Nếu nhãn mô phỏng được ghi theo cùng khuôn đó, UI sẽ hiện chúng như quyết định của người — đây
  là lý do spec này dùng bảng riêng và `module='screening_ml'` (Q3).
- **Cách Phase 7 đã mô phỏng** (`specs/case-prioritization.md`): disposition mô phỏng đi qua `record_disposition(...,
  origin=SIMULATED, actor=simulated_analyst)`; chọn 70 % số **nhóm** bằng `default_rng(seed).permutation`, phần còn lại
  là hàng đợi + holdout; case đã có disposition của người không bị ghi đè; model lưu trong DB (`case_models`), phiên bản
  trên từng điểm và từng dòng audit. Spec này đi theo đúng khuôn đó.
- **Prototype của thiết kế dưới đây** (19 feature, logistic regression chuẩn hoá + `class_weight="balanced"`, nhóm =
  `entry_id`, `StratifiedGroupKFold` 5 fold):

  | Dữ liệu, seed, phần được gán nhãn | nhóm gán nhãn / tổng | cặp gán nhãn (thật) | held-out (thật) |
  |---|---|---|---|
  | TINY, 42, 0,7 | 24 / 34 | 39 (4) | 16 (1) |
  | TINY, 42, 1,0 | 34 / 34 | 55 (5) | 0 |
  | `small`, 42, 0,7 | 472 / 673 | 4453 (15) | 1827 (10) |
  | `small`, 7, 0,7 | 472 / 673 | 4582 (20) | 1698 (5) |

  So sánh ở recall 1,0 (số hit phải xem để thấy hết cặp thật; precision):

  | Tập | ngưỡng `ALERT` | ngưỡng `ALERT`+`REVIEW` | model |
  |---|---|---|---|
  | `small` seed 42, held-out (1827 cặp, 10 thật) | 18; 0,5556 | 30; 0,3333 | 13; 0,7692 |
  | `small` seed 42, CV trên tập gán nhãn (15 thật) | 23; 0,6522 | 42; 0,3571 | 17; 0,8824 |
  | `small` seed 7, held-out (5 thật) | 5; 1,0 | 13; 0,3846 | 5; 1,0 |
  | `small` seed 42, fraction 1,0, CV (25 thật) | 41; 0,6098 | 72; 0,3472 | 36; 0,6944 |
  | TINY seed 42, fraction 1,0, CV (5 thật) | 5; 1,0 | 5; 1,0 | 5; 1,0 |

  Hệ số lớn nhất (seed 42, 0,7): `dob_within_tolerance` +2,18, `name_score` +1,63, `coverage` +1,47,
  `token_count_gap` −1,42. **Các con số này chỉ để chọn thiết kế**, không phải kết quả của bản hiện thực và không được
  chép vào README. Điều chúng cho thấy: chỉ có 25 cặp thật, held-out có 5–10 cặp thật, nên kết quả **dao động mạnh theo
  seed** (seed 7: model chỉ hoà ngưỡng `ALERT`) — README phải báo kèm số cặp thật và seed (Q5).
- **TINY không huấn luyện được ở fraction 0,7** (4 cặp thật < 5 fold) — test huấn luyện trên TINY dùng fraction 1,0, và
  khi đó không còn held-out.
- **Dependency**: `scikit-learn>=1.5` đã có trong `dependencies`; `lightgbm` nằm ở extra `ml`. Không cần thêm gói.
- **CLI**: `aml screen` là **một lệnh** (không phải nhóm), có `--as-of`, `--eval-out`, `--incremental`; `aml
  screen-compare` là lệnh riêng. Biến `screen` thành nhóm lệnh sẽ phá AC của 3b / 3c → spec này thêm nhóm mới
  `aml screen-ml` (Q10).
- **Cấu hình**: `config_hash` của screening (3b) băm **toàn bộ** `settings.screening` (trừ `sql_length_band`); 3c từ chối
  chạy incremental khi hash đổi. Đặt tham số ML bên trong `screening` sẽ đổi hash và buộc chạy FULL lại → tham số ML nằm ở
  mục `ml.screening` (Q11; section `ml:` dùng chung với 7b-i).
- `SCHEMA_SCRIPTS` (`src/aml/dba/schema.py`): số cuối đang dùng là `190`; `200` dành cho anomaly (7b-i), `220` cho
  governance → spec này dùng **`210`**. Spec anomaly chưa có trong `specs/`; `specs/ml-governance.md` (draft) xuất
  hiện trong lúc soạn spec này và đã được đối chiếu (mục Tác động lên spec khác).
- **Chưa đo**: mã hiện thực; DDL `210`; Oracle; mọi giá trị của TOY / PAIRS trong AC (suy ra bằng số học từ luật); thời
  gian chạy trên `small`.

### Interface đề xuất (để test và `specs/ml-governance.md` gọi trực tiếp)
```python
# src/aml/common/config.py
class ScreeningMlLogRegConfig(BaseModel):
    c: float  # > 0
    max_iter: int  # >= 1


class ScreeningMlConfig(BaseModel):
    simulate_fraction: float  # (0, 1]; phần nhóm (entry_id) được mô phỏng nhãn
    simulated_actor: str  # actor của nhãn mô phỏng; khác audit.system_actor
    use_human_reviews: (
        bool  # review TRUE_MATCH / FALSE_MATCH của người được dùng làm nhãn (thắng nhãn mô phỏng)
    )
    cv_folds: int  # >= 2
    top_features: int  # >= 1; số feature đóng góp ghi cho mỗi hit
    logreg: ScreeningMlLogRegConfig


class MlConfig(BaseModel):  # section `ml:` của 7b-i (specs/ml-anomaly.md); spec này thêm một trường
    screening: ScreeningMlConfig  # KHÔNG nằm trong `screening` (config_hash của 3b không đổi)


# src/aml/screening/ml/features.py
FEATURE_VERSION = "screening-ml-features/v1"
FEATURES: tuple[str, ...]  # 19 tên, đúng thứ tự mục Thiết kế


def match_features(
    customer_norm: str,
    list_norm: str,
    customer: Identifiers,
    entry: Identifiers,
    *,
    name_type: str,
    list_type: str | None,
    stats: TokenStats,
    cfg: ScreeningConfig,
    as_of: date,
) -> dict[str, float]: ...  # thuần; đủ khoá FEATURES, giá trị float hữu hạn


def write_features(
    db: Database, settings: Settings
) -> int: ...  # cho dòng screening_current chưa có; trả số cặp đã ghi
def read_features(db: Database) -> pd.DataFrame: ...


# index (result_run_id, cif, entry_id) của mọi dòng screening_current, tăng dần; cột FEATURES


# src/aml/screening/ml/labels.py
@dataclass(frozen=True)
class LabelSimulation:
    groups: int  # số entry_id khác nhau trong screening_current
    labelled_groups: int
    labelled: int  # nhãn đã ghi trong lần gọi này
    true_match: int
    false_match: int
    held_out: int  # cặp hiện hành không có nhãn nào sau lần gọi
    skipped: int  # cặp thuộc nhóm được chọn nhưng đã có nhãn (mô phỏng hoặc review của người)


def simulate_labels(db: Database, settings: Settings) -> LabelSimulation: ...
def training_labels(db: Database, settings: Settings) -> pd.DataFrame: ...


# index (cif, entry_id) tăng dần; cột label (1 = TRUE_MATCH), origin (SIMULATED | HUMAN); chỉ cặp hiện hành


# src/aml/screening/ml/model.py  (thuần: không đọc, không ghi DB)
class ScreeningMlError(RuntimeError): ...


@dataclass(frozen=True)
class MatchModel:
    features: tuple[str, ...]
    artifact: str  # JSON {features, mean, scale, coef, intercept}
    params: dict[str, Any]
    metrics: dict[str, Any]  # {n, n_true, n_false, prevalence, roc_auc, pr_auc, comparison}
    data_hash: str  # 16 ký tự hex


def fit_match_model(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    rule: pd.Series,
    cfg: ScreeningMlConfig,
    *,
    seed: int,
) -> MatchModel: ...  # rule = decision của Tier 2 cho cùng index; chỉ dùng để tính comparison
def predict(model: MatchModel, X: pd.DataFrame) -> pd.DataFrame: ...
# index như X; cột score (0..1) và contributions (dict feature -> đóng góp trên thang log-odds)
def compare_at_recall(y: pd.Series, score: pd.Series, rule: pd.Series) -> pd.DataFrame: ...


# cột: baseline, pairs, positives, rule_flagged, rule_tp, rule_precision, rule_recall,
#      model_flagged, model_tp, model_precision, model_recall, flagged_reduction_pct
# dòng (đúng thứ tự): "two_tier_alert", "two_tier"


# src/aml/screening/ml/pipeline.py
@dataclass(frozen=True)
class MatchTrainingRun:
    model_id: int
    version: str  # "scrml/logreg/<model_id>"
    pairs: int
    true_match: int
    false_match: int
    human_labels: int
    metrics: dict[str, Any]


@dataclass(frozen=True)
class MatchScoringRun:
    score_run_id: int
    model_id: int
    version: str
    scored: int
    holdout: list[
        dict[str, Any]
    ]  # các dòng compare_at_recall trên cặp không có nhãn; [] khi không có cặp nào


def train(db: Database, settings: Settings, *, actor: str | None = None) -> MatchTrainingRun: ...
def score(
    db: Database, settings: Settings, *, model_id: int | None = None, actor: str | None = None
) -> MatchScoringRun: ...
```
- `config.yaml`, thêm vào section `ml:` của 7b-i: `ml.screening: {simulate_fraction: 0.7, simulated_actor: simulated_analyst,
  use_human_reviews: true, cv_folds: 5, top_features: 3, logreg: {c: 1.0, max_iter: 1000}}`.
- DDL `sql/duckdb/ddl/210_screening_ml.sql` và `sql/oracle/ddl/210_screening_ml.sql` (Oracle: kiểu SQL*Plus, mỗi câu kết
  thúc bằng dòng `/`, `EXECUTE IMMEDIATE` + nuốt ORA-00955), thêm vào `SCHEMA_SCRIPTS` của cả hai backend **sau**
  `ddl/190_memo_analysis.sql` (và sau `ddl/200_*` nếu spec anomaly đã thêm), **trước** các script `050_*`.
- Truy vấn đọc / ghi ngoài DDL nằm trong `sql/<backend>/screening_ml/*.sql` hoặc `sql/common/screening_ml/*.sql`
  (qua `sql_file`), không viết SQL thô trong module trừ câu đếm / chèn bằng `insert_df`.
- Package mới `src/aml/screening/ml/` (`__init__.py`, `features.py`, `labels.py`, `model.py`, `pipeline.py`), thêm
  `src/aml/screening/ml/cli.py` nếu cần cho gọn `cli.py` (như `aml.memo.cli`).
- CLI nhóm mới `aml screen-ml` gồm `label [--fraction F]`, `train`, `score [--top N]` và `run [--fraction F] [--top N]
  [--eval-out PATH]` (= `label` → `train` → `score` → in so sánh). `aml screen`, `aml screen-compare` không đổi.
  `Makefile` / `tasks.ps1` không đổi.

### Thiết kế (đề xuất, chờ xác nhận ở Câu hỏi mở)
- **Đơn vị**: một dòng `screening_current` = một cặp (cif, entry_id), khoá đầy đủ `(result_run_id, cif, entry_id)` với
  `result_run_id` = `screening_current.run_id`. Nhãn gắn với cặp (cif, entry_id) — **không** với lần chạy — nên chạy lại
  `aml screen` không làm mất nhãn.
- **Feature** (`FEATURES`, 19 giá trị số, theo thứ tự; `match_features` tính lại `score_names(customer_norm, list_norm,
  stats, cfg)` → `n`):
  - tên: `token_set` = `n.token_set`, `jaro_winkler` = `n.jaro_winkler`, `fuzzy_score` = `n.fuzzy`, `coverage` =
    `n.coverage`, `name_score` = `n.score`;
  - token: `matched_tokens` = `len(n.matched)`, `token_count_gap` = `|số token customer_norm − số token list_norm|`,
    `rare_matched` = số phần tử của `n.matched` có `stats.is_rare(t, cfg.rare_token_max_df_rate)`, `max_matched_idf` =
    `max(stats.idf(t))` trên `n.matched` (0 khi rỗng), làm tròn 6, `common_only` = 1 khi `n.common_only`;
  - năm sinh (cùng quy tắc với `decide` của 3b: phía khách hàng dùng được khi `dob` khác null và `dob <= as_of`, phía
    danh sách khi `dob_year` khác null): `dob_known` = 1 khi cả hai dùng được, `dob_gap_years` = `min(gap, 50)` (0 khi
    không biết), `dob_within_tolerance` = 1 khi biết và `gap <= cfg.dob_tolerance_years`;
  - quốc tịch: `nationality_match` / `nationality_mismatch` = 1 khi hai phía đều khác null và bằng / khác nhau (cả hai 0
    khi thiếu một phía);
  - `gender_mismatch` = 1 khi hai phía đều khác null và khác nhau; `id_match` = 1 khi số giấy tờ hai phía khác rỗng và
    bằng nhau sau khi viết hoa, bỏ ký tự không phải chữ / số (cùng quy tắc `ID number match` của 3b);
  - `alias_match` = 1 khi `name_type != "PRIMARY"`; `sanctions_list` = 1 khi `list_type == "SANCTIONS"`.
  - **Không dùng** đầu ra của luật (`final_score`, `decision`, `reason`) làm feature (Q6). Mọi giá trị là `float`.
  - `write_features`: `as_of` = `screening_runs.as_of` của `result_run_id`; `stats` = `load_token_stats(db)`; `None` →
    `ScreeningMlError` chứa ``run `aml screen` first``. Bảng dạng dài `screening_ml_features(result_run_id, cif, entry_id,
    feature, value)`, PK 4 cột đầu; dòng đã có thì không ghi lại.
- **Nhãn mô phỏng** (`simulate_labels`, trên `screening_current`):
  - Nhóm = `entry_id` (mọi CIF của cùng một người và mọi người trùng tên với cùng một entry rơi vào một nhóm — tránh rò
    rỉ giữa train và held-out). Sắp `entry_id` tăng dần, hoán vị bằng `numpy.random.default_rng(settings.seed)
    .permutation(n)`, lấy `ceil(simulate_fraction × n)` nhóm đầu (làm tròn tích trước khi `ceil`, như `slice_size` của 7c).
  - Mỗi cặp hiện hành thuộc nhóm được chọn, **mọi `decision` kể cả `AUTO_CLEARED`** (Q1), chưa có nhãn mô phỏng nào và
    chưa có review của người (`latest_reviews`) nhận một dòng `screening_ml_labels`: `label` = `TRUE_MATCH` khi
    (cif, entry_id) ∈ `truth_pairs(db)`, ngược lại `FALSE_MATCH`; `origin = 'SIMULATED'`, `actor = simulated_actor`,
    `reason` = `simulated from ground truth: planted {typology} true match` hoặc `simulated from ground truth: not a
    planted true match`. Cặp còn lại ở nguyên — đó là tập **held-out**.
  - Bảng `ground_truth` rỗng → `ScreeningMlError` chứa `no ground truth`; `screening_current` rỗng hoặc chưa có →
    `ScreeningMlError` chứa ``run `aml screen` first``; cả hai không ghi gì.
  - **Không bao giờ** gọi `record_review`, không ghi `module='screening'`, không đổi `screening_results`.
- **Nhãn huấn luyện** (`training_labels`): với mỗi cặp hiện hành, review mới nhất của người (`latest_reviews`) nếu
  `use_human_reviews` và có, ngược lại nhãn mô phỏng mới nhất của cặp; cặp không có cả hai thì không có nhãn.
- **Model** (`fit_match_model`): `StandardScaler` → `LogisticRegression(C=c, max_iter=max_iter, class_weight="balanced",
  solver="lbfgs", random_state=seed)`; mỗi lớp cần ít nhất `cv_folds` cặp, nếu không → `ScreeningMlError` chứa `not
  enough labelled pairs: need at least {cv_folds} per class, got TRUE_MATCH={a} FALSE_MATCH={b}`. Đánh giá:
  `StratifiedGroupKFold(n_splits=cv_folds, shuffle=True, random_state=seed)` theo nhóm `entry_id`, điểm out-of-fold →
  `metrics` (`roc_auc`, `pr_auc` làm tròn 4; `comparison` = `compare_at_recall(y, oof, rule)` dạng list các dict). Model
  cuối fit trên toàn bộ tập. `artifact` = JSON `{features, mean, scale, coef, intercept}` (chấm điểm chỉ cần NumPy;
  cột hằng có `scale = 1`, `coef = 0`). `params` = `{c, max_iter, class_weight: "balanced", solver: "lbfgs", cv_folds,
  seed, sklearn: <phiên bản>}`. `data_hash` = 16 ký tự hex đầu của SHA-256 trên (danh sách feature, khoá đã sắp, ma trận
  làm tròn 10, nhãn).
- **So sánh ở cùng recall** (`compare_at_recall`; `rule` là `decision` của Tier 2): với `two_tier_alert` cờ của luật là
  `decision = 'ALERT'`, với `two_tier` là `decision IN ('ALERT', 'REVIEW')`. `positives = sum(y)`; `rule_tp`,
  `rule_flagged`; `rule_precision = rule_tp / rule_flagged`, `rule_recall = rule_tp / positives`. Model: sắp theo (`score`
  giảm, index tăng), `model_flagged` = **k nhỏ nhất** sao cho top-k chứa ít nhất `rule_tp` cặp thật (0 khi `rule_tp = 0`),
  `model_tp` = số cặp thật trong top-k, `model_precision = model_tp / k`, `model_recall = model_tp / positives`;
  `flagged_reduction_pct = round(100 × (1 − model_flagged / rule_flagged), 2)`. Tỉ lệ làm tròn 4; mẫu số 0 → `None`.
  Model không "gắn cờ" gì thật — top-k chỉ là cách đo.
- **Chấm điểm** (`score`): model = `model_id` chỉ định hoặc dòng `screening_ml_model_active` (model mới nhất); chưa có →
  `ScreeningMlError` chứa ``no model: run `aml screen-ml train` first``; `model_id` không tồn tại → chứa `unknown
  model_id`. Chấm **mọi** dòng `screening_current` (`write_features` trước): `score` làm tròn 6; `score_rank` = thứ hạng
  từ 1 theo (`score` giảm, `cif` tăng, `entry_id` tăng); `top_features` = `top_features` feature có `|đóng góp|` lớn nhất
  (hoà: tên tăng dần) `[{feature, value, contribution}]`, `contribution` = `coef × (x − mean) / scale` làm tròn 4.
  `holdout` = `compare_at_recall` trên các cặp **không có nhãn huấn luyện**, `y` lấy từ `truth_pairs` — ground truth chỉ
  để đo, không ghi thành nhãn; không có cặp nào hoặc `ground_truth` rỗng → `[]`.
- **Bảng** (DDL `210`; chỉ INSERT, không UPDATE / DELETE):
  - `screening_ml_labels(label_id PK, cif, entry_id, label, origin, actor, reason, labelled_ts UTC)`; `label_id` =
    `MAX + 1`.
  - `screening_ml_features` (trên).
  - `screening_ml_models(model_id PK, version, feature_version, kind, trained_ts UTC, seed, pairs, true_match,
    false_match, human_labels, features JSON, params JSON, metrics JSON, artifact CLOB, data_hash, actor)`; view
    `screening_ml_model_active` = dòng `model_id` lớn nhất.
  - `screening_ml_training(model_id, result_run_id, cif, entry_id, label, origin)`, PK `(model_id, cif, entry_id)` —
    đúng tập đã huấn luyện, để model card truy lại.
  - `screening_ml_scores(score_run_id, result_run_id, cif, entry_id, model_id, model_version, score, score_rank,
    top_features JSON, scored_ts UTC)`, PK `(score_run_id, cif, entry_id)`; view `screening_ml_scores_current` = dòng của
    `score_run_id` lớn nhất mà (`result_run_id`, `cif`, `entry_id`) vẫn có trong `screening_current`. Không cột nào tên
    `decision` hay `status`.
- **Audit** (`module='screening_ml'` — tách hẳn khỏi `module='screening'` mà `latest_reviews` và test 3b / 3c đếm):
  - mỗi nhãn mô phỏng: `entity_type='screening_label'`, `entity_id='<cif>:<entry_id>'`, `decision='SIMULATED_LABEL'`
    (**không** dùng `TRUE_MATCH` / `FALSE_MATCH` làm `decision` — guard của `specs/ml-governance.md` cấm hai giá trị đó
    trong `screening/ml/**`), `actor = simulated_actor`, `version='screening-ml/v1'`, `reason` như cột `reason`,
    `details = {label_id, label, origin: "SIMULATED", result_run_id}`; mỗi lần gọi 1 dòng
    `entity_type='screening_label_run'`, `decision='LABELS_SIMULATED'`, `version='screening-ml/v1'`, `details` = các
    trường của `LabelSimulation`;
  - huấn luyện: `entity_type='model'`, `entity_id=version`, `decision='MODEL_TRAINED'`, `version=version`, `reason` =
    `trained logreg on {pairs} labelled screening pairs ({true_match} TRUE_MATCH, {false_match} FALSE_MATCH, {human_labels} from human reviews; class_weight balanced): cross-validated ROC-AUC {roc_auc}, PR-AUC {pr_auc}; ranking only`,
    `details = {model_id, data_hash, metrics, features}`; dòng `screening_ml_models` + `screening_ml_training` + audit
    trong một `db.transaction()`;
  - mỗi cặp được chấm: `entity_type='screening_ml_score'`, `entity_id='<cif>:<entry_id>'`, `decision='ML_SCORED'`,
    **`version` = phiên bản model**, `reason` = `match score {score:.4f} from {version}, rank {rank} of {n}; system decision {decision} unchanged; top factors: {feature} {contribution:+.2f}, {feature} {contribution:+.2f}, {feature} {contribution:+.2f}; ranking only, no clearance`,
    `details = {score_run_id, model_id, result_run_id, score, score_rank, system_decision, top_features}`; mỗi lần chấm 1
    dòng `entity_type='screening_ml_run'`, `decision='ML_SCORING_COMPLETED'`, **`version` = phiên bản model**, `details` =
    các trường của `MatchScoringRun` (gồm `holdout`);
    `screening_ml_scores` + audit trong một `db.transaction()`.
- **`aml screen-ml run`**: `label` (luôn chạy; `--fraction` ghi đè `simulate_fraction`) → `train` → `score` → in: `labels groups= labelled_groups= labelled=
  TRUE_MATCH= FALSE_MATCH= held_out= skipped=`, `model version= pairs= TRUE_MATCH= FALSE_MATCH= human= roc_auc= pr_auc=`,
  mỗi dòng `comparison` của CV và của held-out dạng `<cv|holdout> <baseline> pairs= positives= rule_flagged=
  rule_precision= model_flagged= model_precision= recall= reduction=`, `scored pairs= model=`, `--top` (mặc định 10) dòng
  `rank score cif:entry_id decision top=<f>,<f>,<f>`, và dòng cuối bằng đúng `ranking only: no screening hit was cleared
  or closed by the model`. `ScreeningMlError` → stderr, exit 1 (bước đã ghi vẫn giữ). `--eval-out PATH` ghi JSON `{model,
  cv, holdout}`.

## Tiêu chí nghiệm thu
<!-- settings = load_settings(environ={}); seed 42; as_of = date(2026, 6, 30).
TINY-S = fixture `tiny_parquet` nạp bằng `load_parquet` vào DuckDB tạm rồi `run_screening` (run 1: 55 cặp, 5 ALERT,
  50 AUTO_CLEARED, 34 entry_id — đã đo).
BASE / STATS như spec 3b AC2 (8 tên, `rare_token_max_df_rate = 0.25`); C = Identifiers(dob=date(1971, 2, 15),
  dob_year=1971, nationality="VN"); E(year, nat="VN") = Identifiers(dob_year=year, nationality=nat).
F(cn, ln, c, e, name_type="PRIMARY", list_type="PEP") = match_features(cn, ln, c, e, name_type=name_type,
  list_type=list_type, stats=STATS, cfg=cfg 0.25, as_of=as_of).
TOY = X 40 dòng, index f"P{i:02d}", cột FEATURES; `name_score` = 100.0 khi i chẵn, 60.0 khi i lẻ; mọi cột khác 0.0;
  y = 1 khi i chẵn; groups = f"WL{i:03d}"; rule = "ALERT" khi i chẵn hoặc i chia hết cho 5, ngược lại "AUTO_CLEARED".
PAIRS = 10 cặp index p0..p9, y = [1,1,1,0,0,0,0,0,0,0], rule = ALERT cho p0,p1,p3,p4, REVIEW cho p2,p5, AUTO_CLEARED còn
  lại; score = [0.9, 0.7, 0.8, 0.5, 0.4, 0.3, 0.6, 0.2, 0.1, 0.05].
Giá trị ghi "đã đo" lấy từ prototype; còn lại suy ra từ luật. Test [oracle] dùng @pytest.mark.oracle. -->
- AC1: Given `config.yaml`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS` và gọi `apply_schema(duck)` hai lần, Then `settings.ml.screening` có `simulate_fraction == 0.7`, `simulated_actor == "simulated_analyst"`, `use_human_reviews is True`, `cv_folds == 5`, `top_features == 3`, `logreg.c == 1.0`, `logreg.max_iter == 1000`; `AML__ML__SCREENING__SIMULATE_FRACTION=0` raise `pydantic.ValidationError` chứa `simulate_fraction must be in (0, 1]`, `AML__ML__SCREENING__CV_FOLDS=1` raise chứa `cv_folds must be >= 2`, `AML__ML__SCREENING__SIMULATED_ACTOR=system` raise chứa `simulated_actor must differ from audit.system_actor`, `AML__ML__SCREENING__LOGREG__C=0` raise `ValidationError`; `config_hash(load_settings(environ={"AML__ML__SCREENING__CV_FOLDS": "3"}))` bằng `config_hash(settings)` (hàm của `aml.screening.recording`); `ddl/210_screening_ml.sql` có trong `SCHEMA_SCRIPTS` của cả hai backend, sau `ddl/190_memo_analysis.sql` và trước mọi script `050_*`, và resolve qua `sql_file` về `sql/<backend>/`; `apply_schema` không raise; `SELECT COUNT(*)` trên `screening_ml_labels`, `screening_ml_features`, `screening_ml_models`, `screening_ml_model_active`, `screening_ml_training`, `screening_ml_scores`, `screening_ml_scores_current` đều trả 0; tập tên cột của `screening_ml_scores` không chứa `decision` hay `status`; `len(FEATURES) == 19`, không trùng tên, `FEATURE_VERSION == "screening-ml-features/v1"`, và `FEATURES` không chứa `final_score`.
- AC2: Given STATS, cfg với `rare_token_max_df_rate = 0.25` và hàm thuần `match_features`, When gọi F với các đầu vào dưới đây, Then `F("NGUYEN VAN AN", "NGUYEN VAN AN", C, E(1971))` trả đúng 19 khoá bằng `FEATURES` với `token_set = 100.0`, `jaro_winkler = 100.0`, `fuzzy_score = 100.0`, `coverage = 1.0`, `name_score = 100.0`, `matched_tokens = 3`, `token_count_gap = 0`, `rare_matched = 1`, `max_matched_idf = 1.504077`, `common_only = 0`, `dob_known = 1`, `dob_gap_years = 0`, `dob_within_tolerance = 1`, `nationality_match = 1`, `nationality_mismatch = 0`, `gender_mismatch = 0`, `id_match = 0`, `alias_match = 0`, `sanctions_list = 0`; `F("NGUYEN VAN AN", "NGUYEN VAN", C, E(1971))` có `name_score = 46.42`, `coverage = 0.5188`, `matched_tokens = 2`, `token_count_gap = 1`, `rare_matched = 0`, `max_matched_idf = 0.81093`, `common_only = 1`; `F("TRAN VAN LONG", "TRAN HUU LONG", C, E(1971))` có `fuzzy_score = 74.88`, `name_score = 44.45`, `rare_matched = 2`, `max_matched_idf = 1.098612` (đã đo bằng `score_names`); với `ln = cn = "NGUYEN VAN AN"`: entry `E(1973)` cho `dob_gap_years = 2`, `dob_within_tolerance = 0`, `dob_known = 1`; entry `E(2031)` cho `dob_gap_years = 50` (chặn trên); entry `E(None)` cho `dob_known = 0`, `dob_gap_years = 0`, `dob_within_tolerance = 0`; khách hàng `Identifiers(dob=date(2033, 1, 20), dob_year=2033, nationality="VN")` (sau `as_of`) với `E(1971)` cho `dob_known = 0`; `E(1971, "RU")` cho `nationality_match = 0`, `nationality_mismatch = 1`; khách hàng có `nationality=None` cho cả hai bằng 0; khách hàng `gender="M"` với entry `gender="F"` cho `gender_mismatch = 1`, entry `gender=None` cho 0; khách hàng `id_number="B1234567"` với entry `id_number="b-1234567"` cho `id_match = 1`, với `"C7654321"` cho 0; `name_type="AKA"` cho `alias_match = 1`; `list_type="SANCTIONS"` cho `sanctions_list = 1`, `list_type=None` cho 0; mọi giá trị là `float` hữu hạn; và mã nguồn của `aml.screening.ml.features` không chứa chuỗi `ground_truth`.
- AC3: Given TINY-S, When gọi `write_features(duck, settings)` hai lần rồi `read_features(duck)`, Then lần một trả 55 và `screening_ml_features` có 1045 dòng (55 × 19), lần hai trả 0 và bảng vẫn 1045 dòng; `read_features` trả frame 55 × 19 với index `(result_run_id, cif, entry_id)` tăng dần và cột đúng thứ tự `FEATURES`; với cả 55 cặp, `token_set`, `jaro_winkler`, `fuzzy_score`, `coverage`, `name_score` bằng (sai số 1e-9) các cột cùng tên của `screening_current` (`fuzzy_score` ↔ `fuzzy_score`), và `dob_gap_years` bằng `min(dob_gap_years của screening_current, 50)` khi cột đó khác null, bằng 0 khi null; dòng (`CIF00000214`, `WL000099`) có `name_score = 78.09`, `dob_known = 1`, `dob_gap_years = 38`, `dob_within_tolerance = 0`, `token_count_gap = 1`, `nationality_match = 1`, `sanctions_list = 1`; dòng (`CIF00000104`, `WL000158`) có `name_score = 100.0`, `dob_known = 0`, `alias_match = 0`; dòng (`CIF00000032`, `WL000084`) có `alias_match = 1`, `dob_known = 1`, `dob_within_tolerance = 1`, `sanctions_list = 0`; cột `gender_mismatch` và `id_match` bằng 0 ở cả 55 dòng; và Given DuckDB đã `load_parquet` TINY nhưng chưa `run_screening`, When gọi `write_features`, Then raise `ScreeningMlError` chứa ``run `aml screen` first``.
- AC4: Given TINY-S, When gọi `simulate_labels` với `AML__ML__SCREENING__SIMULATE_FRACTION` khác nhau, Then với `0.7` kết quả là `LabelSimulation(groups=34, labelled_groups=24, labelled=39, true_match=4, false_match=35, held_out=16, skipped=0)` (đã đo) và `screening_ml_labels` có 39 dòng, mọi dòng `origin = 'SIMULATED'`, `actor = 'simulated_analyst'`, `reason` bắt đầu bằng `simulated from ground truth:`, mọi cặp của cùng một `entry_id` hoặc cùng có nhãn hoặc cùng không; gọi lại lần hai trả `labelled = 0`, `skipped = 39` và bảng vẫn 39 dòng; hai DuckDB TINY-S dựng độc lập cho đúng cùng tập (cif, entry_id) được gán nhãn; `audit_log` có đúng 39 dòng `module='screening_ml'`, `entity_type='screening_label'`, `decision='SIMULATED_LABEL'`, `actor='simulated_analyst'`, `details.origin = "SIMULATED"`, `details.label` ∈ {`TRUE_MATCH`, `FALSE_MATCH`} (4 dòng `TRUE_MATCH`), không dòng nào của `module='screening_ml'` có `decision` là `TRUE_MATCH` hay `FALSE_MATCH` và mỗi lần gọi 1 dòng `decision='LABELS_SIMULATED'`; `latest_reviews(duck)` trả dict rỗng; số dòng `module='screening'` của `audit_log` và toàn bộ nội dung `screening_results` trước và sau bằng nhau; Given TINY-S mới với `simulate_fraction = 1.0`, Then trả `labelled = 55`, `true_match = 5`, `false_match = 50`, `held_out = 0` và năm dòng `TRUE_MATCH` đúng là `truth_pairs(duck)`; Given TINY-S mới, `simulate_fraction = 1.0` và `record_review(duck, settings, "CIF00000214", "WL000099", "TRUE_MATCH", reason="manual", actor="analyst01")` gọi trước, Then `simulate_labels` trả `labelled = 54`, `skipped = 1`, `screening_ml_labels` không có dòng nào cho cặp đó, và `training_labels(duck, settings)` có 55 dòng với dòng (`CIF00000214`, `WL000099`) là `label = 1`, `origin = "HUMAN"` và tổng `label` = 6, còn với `AML__ML__SCREENING__USE_HUMAN_REVIEWS=false` thì `training_labels` có 54 dòng và không có cặp đó; Given bảng `ground_truth` rỗng, Then raise `ScreeningMlError` chứa `no ground truth` và không ghi dòng nào.
- AC5: Given hàm thuần `fit_match_model`, `predict`, `compare_at_recall`, cấu hình mặc định, TOY và PAIRS, When gọi `m = fit_match_model(X, y, groups, rule, cfg, seed=42)`, `p = predict(m, X)` và `compare_at_recall` trên PAIRS, Then `m.metrics` có `n = 40`, `n_true = 20`, `n_false = 20`, `prevalence = 0.5`, `roc_auc = 1.0`, `pr_auc = 1.0`; `m.params["class_weight"] == "balanced"`, `m.params["cv_folds"] == 5`, `m.params["seed"] == 42`; `json.loads(m.artifact)` có đúng các khoá `features`, `mean`, `scale`, `coef`, `intercept` với ba mảng dài 19; mọi `score` của dòng i chẵn lớn hơn mọi `score` của dòng i lẻ; với mọi dòng, `1 / (1 + exp(-(intercept + sum(contributions.values()))))` cách `score` không quá 1e-9; feature có `|contribution|` lớn nhất của mọi dòng là `name_score` và `contributions` của mọi cột hằng bằng 0.0; gọi lần hai cho `artifact`, `metrics`, `data_hash` giống hệt, đảo thứ tự dòng cho cùng `data_hash`, đổi một ô cho `data_hash` khác; `compare_at_recall` trên PAIRS trả đúng 2 dòng: `two_tier_alert` với (`pairs`, `positives`, `rule_flagged`, `rule_tp`, `rule_precision`, `rule_recall`, `model_flagged`, `model_tp`, `model_precision`, `model_recall`, `flagged_reduction_pct`) = (10, 3, 4, 2, 0.5, 0.6667, 2, 2, 1.0, 0.6667, 50.0) và `two_tier` = (10, 3, 6, 3, 0.5, 1.0, 3, 3, 1.0, 1.0, 50.0); với `y` toàn 0 trên PAIRS trả `rule_recall is None`, `model_flagged = 0`, `model_precision is None`; với TOY mà `y = 1` chỉ ở i ∈ {0, 2, 4, 6} (còn lại 0), `fit_match_model` raise `ScreeningMlError` chứa `not enough labelled pairs: need at least 5 per class, got TRUE_MATCH=4 FALSE_MATCH=36`; và mã nguồn của `aml.screening.ml.model` không chứa `Database`, `import duckdb`, `record_review` hay `audit`.
- AC6: Given TINY-S đã `simulate_labels` với `simulate_fraction = 1.0`, When gọi `t = train(duck, settings, actor="analyst01")` rồi gọi lần hai, Then `t.model_id = 1`, `t.version == "scrml/logreg/1"`, `t.pairs = 55`, `t.true_match = 5`, `t.false_match = 50`, `t.human_labels = 0`, `t.metrics["prevalence"] = 0.0909`, và dòng `two_tier_alert` của `t.metrics["comparison"]` có `rule_flagged = 5`, `rule_tp = 5`, `model_flagged = 5`, `model_precision = 1.0` (đã đo); `screening_ml_models` có 1 dòng với `version = 'scrml/logreg/1'`, `kind = 'logreg'`, `feature_version = 'screening-ml-features/v1'`, `seed = 42`, `pairs = 55`, `features` là mảng 19 tên bằng `FEATURES`, `params.sklearn` bằng phiên bản đang cài, `data_hash` dài 16 ký tự hex, `actor = 'analyst01'`; `screening_ml_training` có 55 dòng `model_id = 1` với tổng `label` = 5 và mọi `origin = 'SIMULATED'`; `audit_log` có 1 dòng `module='screening_ml'`, `decision='MODEL_TRAINED'`, `entity_id='scrml/logreg/1'`, `version='scrml/logreg/1'`, `actor='analyst01'`, `reason` bắt đầu bằng `trained logreg on 55 labelled screening pairs (5 TRUE_MATCH, 50 FALSE_MATCH, 0 from human reviews; class_weight balanced)` và kết thúc bằng `ranking only`, `details.data_hash` bằng cột `data_hash`; lần hai trả `model_id = 2` với `artifact`, `metrics`, `data_hash` giống lần một và `screening_ml_model_active` trả `model_id = 2`; nội dung `screening_results` và `screening_ml_labels` trước và sau bằng nhau; Given TINY-S đã `simulate_labels` với `0.7`, When gọi `train`, Then raise `ScreeningMlError` chứa `got TRUE_MATCH=4 FALSE_MATCH=35` (đã đo) và `screening_ml_models` rỗng.
- AC7: Given TINY-S đã `simulate_labels` (`1.0`) và `train` (model 1), When gọi `s = score(duck, settings, actor="analyst01")` rồi gọi lần hai, Then `s.score_run_id = 1`, `s.model_id = 1`, `s.version == "scrml/logreg/1"`, `s.scored = 55`, `s.holdout == []`; `screening_ml_scores` có 55 dòng `score_run_id = 1`, mỗi dòng `model_version = 'scrml/logreg/1'`, `score` trong (0, 1) với tối đa 6 chữ số thập phân, `score_rank` là hoán vị của 1..55 và `score` không tăng theo `score_rank`; mỗi `top_features` là mảng đúng 3 phần tử `{feature, value, contribution}` với `feature` ∈ `FEATURES`, không trùng, `|contribution|` không tăng; với mọi cặp, `score` bằng (sai số 1e-6) điểm tính lại từ `artifact` của `screening_ml_models` và dòng `read_features` của cặp đó chỉ bằng NumPy; 5 cặp của `truth_pairs(duck)` có `score_rank` từ 1 đến 5 (suy ra: prototype đã đo điểm out-of-fold xếp 5 cặp thật lên đầu; ở đây model chấm chính tập đã huấn luyện); `audit_log` có đúng 55 dòng `module='screening_ml'`, `decision='ML_SCORED'`, `entity_type='screening_ml_score'`, `version='scrml/logreg/1'`, `details.score` bằng `score` của bảng, `details.system_decision` bằng `decision` của `screening_current`, mỗi `reason` chứa `unchanged` và kết thúc bằng `ranking only, no clearance`, cộng 1 dòng `decision='ML_SCORING_COMPLETED'` với `version='scrml/logreg/1'`; trước và sau `score`: nội dung của `screening_results`, `screening_runs`, `screening_ml_labels`, số dòng `module='screening'` trong `audit_log` và kết quả `latest_reviews(duck)` không đổi; lần hai trả `score_run_id = 2` với `score`, `score_rank`, `top_features` giống lần một và `screening_ml_scores_current` chỉ trả 55 dòng `score_run_id = 2`; sau khi `run_screening` chạy lại (run 2), `screening_ml_scores_current` trả 0 dòng cho tới lần `score` kế tiếp; `score(duck, settings, model_id=99)` raise `ScreeningMlError` chứa `unknown model_id`; Given TINY-S chưa `train`, When gọi `score`, Then raise chứa ``no model: run `aml screen-ml train` first`` và `screening_ml_scores` rỗng; và Given một TINY-S khác đã `simulate_labels` với `0.7` (39 cặp có nhãn, 16 cặp held-out trong đó 1 cặp thật — đã đo) rồi `train` với `AML__ML__SCREENING__CV_FOLDS=2`, When gọi `score`, Then `holdout` có đúng 2 dòng theo thứ tự `two_tier_alert`, `two_tier`, cả hai có `pairs = 16`, `positives = 1`, `rule_flagged = 1`, `rule_tp = 1`, `rule_recall = 1.0`, `model_tp = 1`, `model_flagged >= 1`.
- AC8: Given `tiny_env` đã `aml load` và `aml screen`, When chạy `aml screen-ml run --fraction 1.0 --top 3 --eval-out <tmp>/scrml.json`, Then exit code 0; stdout có đúng một dòng bắt đầu bằng `labels` chứa `labelled=55`, `TRUE_MATCH=5`, `FALSE_MATCH=50`; một dòng bắt đầu bằng `model` chứa `version=scrml/logreg/1` và `pairs=55`; một dòng bắt đầu bằng `cv two_tier_alert ` và một dòng bắt đầu bằng `cv two_tier ` (có dấu cách); không dòng nào bắt đầu bằng `holdout` (không còn cặp chưa gán nhãn); một dòng bắt đầu bằng `scored` chứa `pairs=55`; đúng 3 dòng xếp hạng bắt đầu lần lượt bằng `1 `, `2 `, `3 ` mỗi dòng chứa `top=`; dòng cuối bằng đúng `ranking only: no screening hit was cleared or closed by the model`; file `scrml.json` có ba khoá `model`, `cv`, `holdout` với `model.version == "scrml/logreg/1"`, `cv` là list 2 phần tử và `holdout == []`; When chạy `aml screen-ml run` trên một `tiny_env` khác cùng trạng thái (fraction mặc định 0.7), Then exit code 1, stdout có dòng `labels` chứa `TRUE_MATCH=4`, stderr chứa `not enough labelled pairs`; `aml screen-ml label --fraction 0` exit code 2; `aml screen-ml train` trên DB của lần chạy thành công exit code 0 với stdout chứa `version=scrml/logreg/2`; `aml screen --help` và `aml screen-compare --help` vẫn chạy (exit 0); và Given DuckDB chỉ mới `aml load`, When chạy `aml screen-ml run`, Then exit code 1 với stderr chứa ``run `aml screen` first``.
- AC9: Given mã nguồn của package `aml.screening.ml`, When đọc toàn bộ file `.py` của package, Then không file nào chứa `UPDATE screening_results`, `INSERT INTO screening_results`, `record_review`, `record_disposition`, `simulate_dispositions`, `good_guy`, `decision="TRUE_MATCH"`, `decision="FALSE_MATCH"`, `decision="AUTO_CLEARED"` hay `module="screening"` (chỉ `module="screening_ml"`), và `aml.screening.decision.decide` cùng `aml.screening.recording` không import gì từ `aml.screening.ml`.
- AC10: [oracle] Given TINY nạp vào Oracle (full refresh như các test Oracle hiện có) và vào một DuckDB tạm, cả hai đã `run_screening`, When gọi `simulate_labels` (`simulate_fraction = 1.0`), `train` rồi `score` trên hai backend, Then trên Oracle `labelled + skipped == 55` (bảng nhãn là append-only nên lần chạy trước có thể đã gán nhãn), `training_labels` của hai backend bằng nhau (55 cặp, tổng `label` = 5); `MatchTrainingRun.pairs`, `true_match`, `false_match` và `data_hash` của hai lần `train` bằng nhau; mảng `coef` của hai `artifact` lệch không quá 1e-9; `score` của 55 cặp lệch không quá 1e-6 và `score_rank` bằng nhau; `read_features` của hai backend bằng nhau (sai số 1e-9); trên Oracle `user_tables` có `SCREENING_ML_LABELS`, `SCREENING_ML_FEATURES`, `SCREENING_ML_MODELS`, `SCREENING_ML_TRAINING`, `SCREENING_ML_SCORES` và `user_views` có `SCREENING_ML_MODEL_ACTIVE`, `SCREENING_ML_SCORES_CURRENT`; số dòng audit `ML_SCORED` có `details.score_run_id` bằng `score_run_id` của lần chấm trên Oracle là 55 và đều có `version` bằng `version` của model đó; mọi so sánh ID trên Oracle là tương đối (`model_id` mới lớn hơn `MAX(model_id)` trước khi gọi), không khẳng định `model_id = 1`; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- **Đổi quyết định Tier 2 theo điểm model**: không ngưỡng điểm nào đổi `ALERT` / `REVIEW` / `AUTO_CLEARED`, không clear,
  không đóng, không thêm vào good-guy list, không lọc hit khỏi danh sách. `decide`, `run_screening`, `run_incremental`
  giữ nguyên.
- Hiển thị điểm model trên trang screening / API (`/api/v1/screening/hits`) và Phase 9 UI (Q2) — một spec nhỏ riêng nếu
  được chọn.
- Dùng điểm screening ML làm feature của model ưu tiên case (`specs/case-prioritization.md`) — spec 7b mục 3 hoặc sau.
- **Model card** và định dạng `docs/models/` — `specs/ml-governance.md`; phê duyệt model, champion / challenger, giám sát
  drift, huấn luyện lại theo lịch.
- LightGBM / model cây, tinh chỉnh siêu tham số, calibration xác suất, `shap`.
- Nhãn mô phỏng có nhiễu / lỗi của investigator; mẫu below-the-line riêng cho screening (Q1 phương án thay thế).
- Chấm các cặp Tier 1 không được ghi nhận (`fuzzy < review_threshold`); thay blocking hay ngưỡng của Phase 3.
- Thêm `gender` / số giấy tờ vào `watchlist` của Phase 1 (feature tương ứng luôn 0 trên dữ liệu hiện có).
- Quyền Oracle trên các bảng `screening_ml_*` cho role của 2b; purge / retention; đo trên `large`; target `Makefile` /
  `tasks.ps1`.
- Ghi số liệu vào README: bước demo chạy `uv run aml screen-ml run --eval-out results/phase7b/screening_ml.json` trên
  `small` và chép đúng output của lần chạy đó, kèm seed và số cặp thật.

## Giả định
- Dữ liệu Phase 1 giữ các tính chất ở mục "Hiện trạng" (seed 42); số TINY trong AC chỉ cam kết cho TINY seed 42 và cho
  đúng cách chọn nhóm của mục Thiết kế. Số "đã đo" đến từ prototype ngoài repo dùng đúng 19 feature và cách chọn nhóm đó;
  nếu bản hiện thực cho khác, xem lại prototype trước khi nới AC.
- Nhãn mô phỏng là **dữ liệu demo**, đúng tuyệt đối theo ground truth → metric là cận trên so với nhãn thật của
  investigator; luôn mang `origin = 'SIMULATED'`, actor riêng, `module='screening_ml'`, và không xuất hiện ở bất kỳ chỗ nào
  đọc review của người.
- Nhãn gắn với cặp (cif, entry_id) và tồn tại qua các lần `aml screen` / `aml load`; trên Oracle dùng chung, nhãn của lần
  test trước vẫn còn (TINY seed 42 cho cùng ground truth nên không mâu thuẫn).
- Điểm là thứ tự tương đối trong một lần chấm, **không phải xác suất đã hiệu chỉnh** (trọng số lớp làm lệch xác suất).
- Kết quả tất định với cùng dữ liệu, cấu hình, `settings.seed`, cùng phiên bản scikit-learn / NumPy trên cùng nền tảng;
  giữa Oracle và DuckDB cho phép lệch số thực cỡ 1e-9.
- Lệnh chạy dưới schema owner; `reason`, lỗi, output CLI bằng tiếng Anh; `*_ts` là UTC; ID cấp bằng `MAX + 1`, không chạy
  đồng thời.

## Tác động lên spec khác
- **`specs/ml-governance.md`** (draft, DDL `220`, hiện thực **sau** spec này): spec này chỉ cam kết **lưu đủ để dựng model
  card** — dữ liệu huấn luyện (`screening_ml_training` + `data_hash` + `screening_ml_labels`), feature (`features`,
  `feature_version`), metrics (`metrics` gồm CV và bảng so sánh; held-out nằm ở `details.holdout` của audit
  `ML_SCORING_COMPLETED` và ở `--eval-out`), tham số (`params`), phiên bản (`version`, `trained_ts`, `seed`, `actor`).
  Các điểm khớp nối với spec đó:
  - Card `screening_match` do spec governance dựng trong `aml.governance.sources` (đọc `screening_ml_models`,
    `screening_ml_training` và audit `ML_SCORING_COMPLETED`); spec này **không** tạo `card.py` (Q13).
  - `MODEL_DECISIONS` của nó cần thêm (`screening_ml`, `MODEL_TRAINED`), (`screening_ml`, `ML_SCORED`), (`screening_ml`,
    `ML_SCORING_COMPLETED`) với registry `screening_ml_models.version` — cả ba loại dòng đều mang `version` = phiên bản
    model theo spec này.
  - Guard AST của nó quét `screening/ml/**/*.py` và cấm `decision=` là `TRUE_MATCH` / `FALSE_MATCH` / `AUTO_CLEARED`, cấm
    gọi `record_review`, cấm ghi `screening_results`. Spec này được thiết kế để **qua guard mà không cần `ALLOWED_WRITERS`**
    (nhãn mô phỏng dùng `decision='SIMULATED_LABEL'`, AC9); nếu governance muốn ghi nhận `aml.screening.ml.labels` là
    module mô phỏng (như `aml.cases.labels`) thì thêm ở spec đó.
- **`specs/screening-tiers-eval.md`, `specs/screening-oracle-incremental.md`**: không đổi hành vi; `config_hash` không đổi
  vì tham số nằm ở `ml.screening` (AC1). Mục "Ngoài phạm vi" của 3b đã dẫn tới phase này.
- **`specs/ui-live-pages.md`**: `latest_reviews` / API review không đổi; nhãn mô phỏng không bao giờ hiện như review (AC4).
- **Spec anomaly (7b-i, DDL `200`)**: độc lập; nếu được hiện thực trước thì `210` đứng sau `200` trong `SCHEMA_SCRIPTS`.
- **`specs/case-summary.md`** (7d): AC1 của 7d ghim danh sách script giữa `180` và `050` →
  `tests/cases/test_summary_unit.py::test_ac1_no_new_schema_script` nhận thêm `ddl/210_screening_ml.sql` (đã sửa khi
  hiện thực, 2026-10-14).
- Module phụ không có trong Interface: `src/aml/screening/ml/store.py` (chạy file SQL theo tên, cấp id `MAX + 1`, đọc
  CLOB / JSON) và `sql/common/screening_ml/truth_typologies.sql` (cùng điều kiện với `truth_pairs`, thêm cột typology
  cho `reason` của nhãn) — thêm khi hiện thực.
- `sql/common/assistant_eval/decision_tables.sql` (8e) không đổi; có thể thêm `screening_ml_labels` vào danh sách bảng
  quyết định trong spec sau.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Investigator mô phỏng gán nhãn cho những hit nào? — đề xuất mặc định: **mọi cặp đã
  ghi nhận** (`ALERT`, `REVIEW` **và** `AUTO_CLEARED`) thuộc các nhóm được chọn. Lý do: trên `small` chỉ có 25 cặp thật;
  nếu chỉ gán nhãn `ALERT` + `REVIEW` (72 cặp), model chỉ học cách sắp lại 72 hit đó và không bao giờ thấy loại false
  positive mà luật đã tự loại; prototype cho thấy đặc trưng mạnh nhất (`dob_within_tolerance`) học được chính từ các cặp
  `AUTO_CLEARED`. Cái giá: giả định investigator xem cả hit đã auto-clear (giống một đợt QA), lạc quan hơn thực tế; README
  phải nói rõ. Phương án thay thế: chỉ `ALERT` + `REVIEW` cộng một mẫu ngẫu nhiên có seed các cặp `AUTO_CLEARED` (mẫu
  below-the-line, cùng ý tưởng với 7b mục 3) — thực tế hơn, thêm một tham số và ít nhãn hơn. — Trả lời: theo đề xuất mặc định (người dùng chọn trực tiếp, 2026-10-14).
- [x] Q2. **(cần người dùng quyết)** Điểm model chỉ báo cáo, hay lưu theo từng hit và hiện ra? — đề xuất mặc định: **lưu
  theo từng hit** (`screening_ml_scores`, có `model_version`) và audit từng điểm, in top N ở CLI; **không** đổi `decision`
  của Tier 2 và **không** đưa vào API / UI trong spec này. Lý do: brief yêu cầu phiên bản model trên mọi điểm ghi vào
  `audit_log`; lưu điểm để truy được; UI Phase 9 đã đóng — thêm cột là một spec nhỏ riêng. Phương án thay thế: (a) chỉ báo
  cáo (không bảng điểm, không audit từng hit); (b) như mặc định và thêm `ml_score` / `ml_rank` vào `/api/v1/screening/hits`
  cùng cột trên trang screening ngay trong spec này. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q3. Nhãn mô phỏng lưu ở đâu để không bị coi là review của người? — đề xuất mặc định: bảng riêng
  `screening_ml_labels` (`origin = 'SIMULATED'`, actor `simulated_analyst`) + audit `module='screening_ml'`,
  `entity_type='screening_label'`. Lý do: `latest_reviews` coi **mọi** dòng `module='screening'`, `entity_type=
  'screening_match'`, `decision` `TRUE_MATCH` / `FALSE_MATCH` là review và UI hiện nó; tách module bảo đảm không rò; bảng
  riêng cho model card truy được tập nhãn. Phương án thay thế: thêm tham số `origin` cho `record_review` (như
  `record_disposition` của 7a) và sửa `latest_reviews` để lọc `origin = "HUMAN"` — ít bảng hơn nhưng sửa module đã duyệt
  của `ui-live-pages`. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q4. **(cần người dùng quyết)** Review thật của người (`TRUE_MATCH` / `FALSE_MATCH` từ UI) có được dùng làm nhãn
  huấn luyện không? — đề xuất mặc định: **có**, và **thắng** nhãn mô phỏng (cặp đã có review thì không mô phỏng; nhãn
  huấn luyện lấy review mới nhất), tắt được bằng `use_human_reviews: false`. Lý do: đúng vòng phản hồi thật; cùng quy tắc
  "không ghi đè quyết định của người" của 7c. Phương án thay thế: chỉ dùng nhãn mô phỏng để số liệu demo không phụ thuộc
  việc ai đã bấm gì trên UI. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q5. **(cần người dùng quyết)** "Held-out split" là gì, và báo số nào? — đề xuất mặc định: chọn có seed **70 % số
  nhóm `entry_id`** để gán nhãn; 30 % còn lại là **held-out** (chấm điểm, so với ground truth chỉ để đo); báo **cả** CV 5
  fold theo nhóm trên tập gán nhãn **và** held-out, mỗi bảng kèm `positives`. Lý do: giống 7c Q3; chia theo `entry_id` tránh
  rò giữa các CIF của cùng một người. Rủi ro đã đo: held-out chỉ có 5–10 cặp thật, kết quả đổi theo seed (seed 42: model 13
  hit / precision 0,77 so với 18 / 0,56 của ngưỡng `ALERT`; seed 7: hoà). Phương án thay thế: (a) chỉ CV out-of-fold trên
  toàn bộ cặp (`fraction = 1.0`, cả 25 cặp thật đều được đo một lần: 36 / 0,69 so với 41 / 0,61); (b) lặp chia held-out
  với nhiều seed và báo trung bình ± độ lệch. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q6. Bộ feature có dùng đầu ra của luật không? — đề xuất mặc định: **không** — 19 feature thô (điểm tên, độ hiếm,
  năm sinh, quốc tịch, giới tính, số giấy tờ, alias, loại danh sách); không `final_score`, `decision`. Giữ `gender_mismatch`
  và `id_match` dù luôn bằng 0 trên dữ liệu Phase 1 (hệ số 0, ghi rõ ở model card). Lý do: so sánh "model học được vs ngưỡng
  cố định" chỉ có nghĩa khi model không đọc kết quả của luật. Phương án thay thế: thêm `final_score` (model thành "lớp xếp
  hạng chồng lên luật"). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q7. "Precision ở cùng recall" tính thế nào? — đề xuất mặc định: với mỗi baseline (`ALERT`; `ALERT` + `REVIEW`), lấy
  k nhỏ nhất để top-k của model chứa ít nhất số cặp thật mà luật bắt được, báo `model_flagged`, `model_precision` và
  `flagged_reduction_pct` cạnh số của luật. Lý do: một con số dễ đọc ("cần xem 13 hit thay vì 18 để thấy cả 10 cặp
  thật"); hoà điểm phá bằng (`cif`, `entry_id`) nên tất định. Phương án thay thế: đường precision-recall đầy đủ hoặc chọn
  ngưỡng điểm trên tập CV rồi áp lên held-out (thực tế hơn nhưng recall trên held-out có thể không bằng). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q8. Model nào? — đề xuất mặc định: chỉ logistic regression, `class_weight="balanced"`, artifact JSON, đóng góp
  tuyến tính. Lý do: brief ghi "small classifier"; 25 cặp thật; hệ số đọc được trước người phỏng vấn. Phương án thay thế:
  thêm LightGBM tuỳ chọn như 7c. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q9. Mức chi tiết audit? — đề xuất mặc định: 1 dòng cho mỗi nhãn mô phỏng, 1 dòng cho mỗi điểm (có `version` của
  model), 1 dòng tổng kết mỗi lần gán nhãn / huấn luyện / chấm. Hệ quả (ước tính, chưa đo): mỗi lần `run` trên `small`
  thêm khoảng 4,4 nghìn dòng nhãn (lần đầu) + 6,3 nghìn dòng điểm. Lý do: brief "store the model version on every score
  written to `audit_log`"; giống 7c. Phương án thay thế: chỉ dòng tổng kết, điểm từng hit chỉ nằm trong
  `screening_ml_scores`. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q10. Hình dạng CLI? — đề xuất mặc định: nhóm mới `aml screen-ml` với `label`, `train`, `score`, `run`. Lý do: `aml
  screen` đang là một lệnh có test 3b / 3c; biến nó thành nhóm sẽ phá các test đã khoá. Phương án thay thế: thêm cờ
  `aml screen --ml` (một lệnh làm cả screening lẫn ML) hoặc đặt dưới nhóm `aml ml ...` dùng chung với anomaly. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q11. Tham số nằm ở đâu? — đề xuất mặc định: `ml.screening` trong section `ml:` dùng chung của 7b-i (`MlConfig`). Lý do:
  `config_hash` của 3b băm cả `settings.screening`; để tham số ML ở đó thì đổi `cv_folds` cũng buộc chạy FULL screening lại.
  Phương án thay thế: `screening.ml` và thêm `ml` vào danh sách loại trừ của `config_hash` (sửa module đã duyệt 3b / 3c). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q12. Actor của nhãn mô phỏng? — đề xuất mặc định: `simulated_analyst` (cùng tên với 7c), cấu hình riêng ở
  `ml.screening.simulated_actor`, phải khác `audit.system_actor`. Lý do: một "investigator mô phỏng" duy nhất cho cả demo;
  phân biệt bằng `module`. Phương án thay thế: tên riêng `simulated_screening_analyst`. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q13. Ai dựng dữ kiện model card cho `screening_match`? — đề xuất mặc định: **spec governance** (hiện thực sau
  spec này) viết adapter trong `aml.governance.sources`, đọc `screening_ml_models`, `screening_ml_training`, audit
  `ML_SCORING_COMPLETED`; spec này chỉ lưu dữ liệu, không có `aml.screening.ml.card`. Lý do: `CardFacts` là kiểu của spec governance, chưa tồn tại khi 7b-ii
  được hiện thực; tránh phụ thuộc vòng. Phương án thay thế: hiện thực governance trước rồi thêm `card.py` + một AC vào spec
  này. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
