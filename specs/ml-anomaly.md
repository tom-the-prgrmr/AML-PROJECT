---
id: ml-anomaly
status: approved
approved_by: pthieu
---

# Phase 7b-i — Phát hiện bất thường không giám sát (Isolation Forest) theo khách hàng-tháng: nguồn alert thứ tư và feature xếp hạng case, `aml anomaly`

## Bối cảnh
PROJECT_BRIEF.md mục "8b. Phase 7b", ý 1 (và ý 4 áp cho mô hình này): dựng feature hành vi theo khách hàng (velocity, tỉ lệ
tiền mặt, số đối tác, tỉ lệ giao dịch ban đêm, độ lệch so với baseline 90 ngày của chính khách hàng, feature đồ thị của
Phase 5c/6), huấn luyện Isolation Forest, dùng điểm bất thường làm (a) **một nguồn alert thêm** đi vào gộp case như RULE /
NETWORK / SCREENING và (b) **một feature thêm** cho mô hình ưu tiên case (7c), rồi **báo cáo mô hình bắt được bao nhiêu
typology cài sẵn mà luật bỏ sót**. Quản trị mô hình: phiên bản mô hình nằm trên mọi điểm và mọi dòng audit của điểm; mô
hình chỉ phát tín hiệu để người xem, **không bao giờ đóng, clear hay suppress gì**. Spec này phát dữ liệu cho model card;
định dạng card thuộc `specs/ml-governance.md` (spec anh em, đang soạn). Người dùng: investigator (thấy alert `ANOMALY` với
lý do đọc được trong case), kiểm soát mô hình (đánh giá trên ground truth, card), người phỏng vấn (đối chiếu trung thực:
trên dữ liệu tổng hợp, luật đã phủ hết scenario đáng ngờ — xem Hiện trạng).

### Hiện trạng đã kiểm (2026-10-14, `main` aff6d91, seed 42)
Ba nguồn số đo, ghi rõ ở từng mục: (a) **đọc code** của repo; (b) **dữ liệu `small` hiện có** (`data/aml.duckdb`, mở
`read_only=True`, không ghi gì); (c) **nguyên mẫu** — script tạm trong scratchpad, không thuộc repo, cài đúng định nghĩa
feature / mô hình / ngưỡng của spec này (mục Thiết kế) với scikit-learn 1.9.1, NumPy 2.4.6; TINY được dựng lại trong thư
mục tạm bằng đúng env của `tests/datagen/conftest.py::tiny_parquet` rồi `load` → `er` → `screen` → `monitor` → `network` →
`dq` → `run_cases` (52 case, khớp `tiny_cases`). Code của spec này chưa tồn tại; không số nào dưới đây là kết quả của nó.
- **Phụ thuộc đã có** (a): `scikit-learn>=1.5` đã là dependency chính trong `pyproject.toml` (không cần extra; `lightgbm`
  mới nằm trong extra `ml`). `sklearn.ensemble.IsolationForest` có sẵn, chưa module nào dùng. Thư mục `src/aml/ml/` **chưa
  tồn tại**. DDL cuối là `ddl/190_memo_analysis.sql` → spec này dùng **`200`**; spec anh em lấy `210` (screening ML) và `220`
  (governance / selection bias).
- **Đường ghi alert dùng chung** (a): `aml.monitoring.recording.record_run(db, *, as_of, source, rules, alerts)` cấp
  `run_id` / `alert_id`, ghi `alerts`, `alert_accounts`, `alert_evidence`, `monitoring_runs` (cuối cùng) và audit
  (`ALERT` mỗi alert với `version = f"{rule_id}/{rule_version}"`, `MONITORING_RUN_COMPLETED` với
  `version = f"monitoring/{source.lower()}"`). Phase 5c đã tái dùng nó cho `source = "NETWORK"`. `alerts_current` = mỗi
  `rule_id` lấy lần chạy mới nhất của nó. Không có CHECK constraint nào trên `source` / `subject_type` ở cả hai backend;
  độ rộng: `alerts.source` 20, `rule_version` 20, `subject_type` 20, `case_alerts.source` **10**, `cases.sources` 40.
- **Chỗ đang liệt kê cứng các nguồn** (a) — phải sửa để nguồn mới đi vào case: `sql/{duckdb,oracle}/cases/items.sql`
  (`WHERE a.source IN ('RULE', 'NETWORK')`), `sql/{duckdb,oracle}/cases/truth_accounts.sql` (nhãn ground truth của 7c),
  `src/aml/cases/runner.py::_SOURCES` + chuỗi `reason` của case, `src/aml/cases/summary_template.py::_header`
  (`by_source[alert.source] += 1` sẽ **KeyError** với nguồn lạ). Chuỗi `reason` dạng `3 alert(s) (2 RULE, 1 NETWORK, 0
  SCREENING) on G-C01 …` bị ghim nguyên văn bởi `tests/cases/test_run_mini.py` và `tests/api/test_ac4_cases.py`. Các chỗ
  **cố ý giữ nguyên**: `cases/hibernation.py::_HIBERNATING_SOURCES = ("RULE", "NETWORK")`, `sql/common/api/case_transactions.sql`,
  `sql/*/metrics/suppressed_truth_accounts.sql`, `assistant/explainer.py::ALERT_SOURCES`.
- **Feature đồ thị** (a): `aml.cases.enrich_network.choose_source(db, mode, as_of)` / `load_features(db, source)` đọc
  `nx_account_features_current` hoặc `gds_account_features_current` theo `cases.graph_features` (`auto` chọn GDS khi GDS
  cùng `as_of`). Bốn cột có ở cả hai nguồn: `in_degree`, `out_degree`, `pagerank_ratio`, `shared_cluster_size`. Trên `small`
  (b): cả hai view đều có 8 958 dòng (= số account).
- **Cách 7c / 8d nhận feature mới** (a): `case_features` (35 feature, `features/v1`) ghim bởi test đã duyệt; 8d thêm 6 cột
  memo bằng bảng riêng `case_memo_features`, tính muộn, "tất cả hoặc không", và `fit_guarded(X, y, groups, cfg, *, seed,
  kind, non_negative)` (loại cột rủi ro có hệ số âm rồi fit lại; LightGBM loại trước). `case_models.feature_version` là
  `VARCHAR(20)` (Oracle `VARCHAR2(20 CHAR)`); `features/v1+memo/v1` dài 19, `features/v1+memo/v1+anom/v1` dài **27** — không
  vừa trên Oracle. DuckDB không ép độ dài `VARCHAR(n)` (đã thử: chèn `'abcdef'` vào `VARCHAR(3)` thành công; `ALTER … TYPE`
  cũng chạy khi có view phụ thuộc).
- **Dữ liệu `small`** (b): 306 000 giao dịch từ 2026-01-01 00:02:54 tới 2026-06-30 23:56:20 (giờ địa phương, naive);
  5 000 customer, 8 958 account. `alerts_current`: RULE 242 (`DORMANT_REACTIVATION` 137, `RAPID_MOVEMENT` 45, `FAN_OUT` 20,
  `STRUCTURING` 20, `HIGH_VELOCITY` 15, `FAN_IN` 5), NETWORK 25 (`NET_CYCLE` 15, `NET_HUB` 5, `NET_SHARED_ATTRIBUTE` 5).
  Ground truth: `structuring` 20, `rapid_movement` 20, `mule_ring` 5, `round_tripping` 15 scenario đáng ngờ; `benign_payroll`
  5, `benign_merchant` 5. Run case hiện hành: 309 case.
- **Giờ giao dịch** (a): nền sinh theo trọng số giờ (đêm 22h–5h trọng số 1–3, ngày 8h–20h trọng số 8–14); **mọi typology
  cài sẵn đều ban ngày** (structuring / scenario start 8h–16h, payroll 8h–10h). → `night_ratio` theo đúng brief nhưng dữ liệu
  không cài tín hiệu đêm; kỳ vọng nó gần như không góp gì (ghi vào hạn chế của card).
- **Nguyên mẫu trên `small`** (c): **27 589** mẫu (cif, tháng) cho 5 000 cif (4 561–4 639 mẫu mỗi tháng, 2026-01 … 2026-06);
  dựng feature ~70 giây bằng vòng lặp pandas đơn giản (code thật phải vector hoá); fit + chấm 0,5 giây; hai lần fit cùng seed
  cho điểm **giống hệt**. Điểm (= `-score_samples`) từ 0,3568 tới 0,7600, trung vị 0,4227. Với `alert_top_fraction` 0,005:
  **138 alert** trên 138 cif, ngưỡng (điểm của mẫu thứ 138) 0,6526; theo scenario trùng tháng: `mule_ring` 70,
  `benign_merchant` 38, `rapid_movement` 16, `structuring` 9, `round_tripping` 4, không thuộc scenario nào 1; 95 / 138 cif đã
  có alert RULE / NETWORK.
- **"Bắt được mà luật bỏ sót"** (c): RULE + NETWORK hiện hành đã chạm **mọi** scenario đáng ngờ của `small` (60 / 60, tính
  như `network_coverage.flagged_any`: ít nhất một account của scenario có trong `alert_accounts` của alert hiện hành) → **ở
  mức scenario, số mới của mô hình bằng 0** ở mọi ngưỡng đã thử (0,005 / 0,01 / 0,02). Ở mức account (account của scenario
  đáng ngờ mà luật không chạm, cif của nó bị cờ trong tháng trùng scenario): 4 account ở 0,005 (1 `mule_ring`, 3
  `rapid_movement`), 13 ở 0,01 (1 / 12). Mô hình cờ `benign_merchant` 5 / 5 scenario ở 0,005 (38 account) — false positive mà
  luật không có. Trên TINY (c): 1 334 mẫu, 300 cif; luật chạm mọi scenario đáng ngờ (2 / 2 / 1 / 2) → số mới cũng 0.
- **Nguyên mẫu trên MINI-C** (c, 6 mẫu, đồ thị rỗng): giá trị feature ở AC2 và điểm / thứ hạng ở AC3, AC4, AC8 là của nguyên
  mẫu này (seed 42; seed 7 cho thứ hạng khác ở vị trí 5–6).
- **Chưa đo**: mọi thứ trên Oracle (DDL `200`, `ALTER … MODIFY` của `case_models.feature_version`, parity số thực); thời gian
  chạy của code thật; ảnh hưởng của feature bất thường lên chỉ số ưu tiên (CV ROC-AUC / PR-AUC) — cần code của spec này;
  `large`; GDS làm nguồn đồ thị.

### Interface đề xuất (để test, 7c, spec governance và Phase 9 gọi trực tiếp)
```python
# src/aml/common/config.py
class AnomalyConfig(BaseModel):  # Phase 7b-i
    baseline_days: int  # >= 1; cửa sổ baseline trước tháng đang xét
    min_baseline_days: int  # 0..baseline_days; baseline ngắn hơn -> 3 feature độ lệch = 0
    night_start_hour: int  # 0..23; giờ >= start hoặc < end là "đêm"
    night_end_hour: int  # 0..23, khác night_start_hour
    n_estimators: int  # 10..2000
    max_samples: int  # >= 2; dùng min(max_samples, số mẫu)
    alert_top_fraction: float  # (0, 0.1]; alert = ceil(fraction * số mẫu) mẫu điểm cao nhất
    min_samples: int  # >= 2; ít mẫu hơn -> AnomalyError trước khi ghi
    top_deviations: int  # 1..14; số feature lệch nhất ghi vào lý do
    features: Literal["auto", "off"]  # auto: 7c dùng 2 cột bất thường khi đã có lần chạy
    results_dir: str  # nơi `aml anomaly eval` ghi JSON


class MlConfig(BaseModel):  # Phase 7b; spec anh em thêm trường của mình
    anomaly: AnomalyConfig


class Settings(BaseModel):
    ...
    ml: MlConfig


# src/aml/ml/anomaly/features.py  (thuần: không DB)
ANOMALY_VERSION = "anomaly/v1"  # định nghĩa feature + thuật toán + ngưỡng
ANOMALY_FEATURES = (
    "txns_per_day", "max_txns_day", "amount_log", "cash_ratio", "counterparties", "night_ratio",
    "pass_through", "amount_dev", "txn_dev", "new_counterparty_ratio",
    "in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size",
)  # fmt: skip
GRAPH_FEATURES = ("in_degree", "out_degree", "pagerank_ratio", "shared_cluster_size")
FEATURE_DOCS: dict[str, str]  # một câu tiếng Anh cho mỗi feature (cho model card)
LEG_COLUMNS = (
    "cif",
    "account_id",
    "txn_id",
    "txn_ts",
    "direction",
    "amount_vnd",
    "counterparty_id",
    "channel",
)
SAMPLE_COLUMNS = (
    "cif",
    "month",
    "window_start",
    "window_end",
    "first_ts",
    "last_ts",
    "txn_count",
    "amount_vnd",
    "accounts",
)


def build_samples(
    legs: pd.DataFrame, graph: pd.DataFrame, *, as_of: date, start_date: date, cfg: AnomalyConfig
) -> (
    pd.DataFrame
): ...  # một dòng mỗi (cif, month) có >= 1 leg; SAMPLE_COLUMNS + ANOMALY_FEATURES; sắp (cif, month)


# src/aml/ml/anomaly/model.py  (thuần)
def fit_score(
    X: pd.DataFrame, cfg: AnomalyConfig, *, seed: int
) -> pd.Series: ...  # điểm làm tròn 6, cùng index
def rank_scores(scores: pd.Series) -> pd.Series: ...  # 1..n theo (điểm giảm, cif tăng, month tăng)
def alert_count(n: int, fraction: float) -> int: ...  # ceil(round(fraction * n, 9)); n = 0 -> 0
def top_deviations(X: pd.DataFrame, key: tuple[str, str], k: int) -> list[dict[str, Any]]: ...
def data_hash(
    X: pd.DataFrame,
) -> str: ...  # 16 hex đầu của SHA-256 trên CSV của X (index cif, month)


# src/aml/ml/anomaly/runner.py
class AnomalyError(RuntimeError): ...


SOURCE_ANOMALY = "ANOMALY"
RULE_ID = "ML_ANOMALY"


@dataclass(frozen=True)
class AnomalyRun:
    run_id: int
    model_version: str  # f"{ANOMALY_VERSION}/{run_id}", ví dụ "anomaly/v1/1"
    as_of: date
    samples: int
    customers: int
    months: int
    alerts: int
    threshold: float  # điểm của mẫu có rank = alerts (0.0 khi alerts = 0)
    graph_source: str  # networkx | gds | none
    monitoring_run_id: int  # run_id do record_run cấp
    data_hash: str
    seconds: float


def detect_anomalies(
    db: Database, settings: Settings, *, as_of: date | None = None
) -> pd.DataFrame: ...  # không ghi
def run_anomaly(
    db: Database, settings: Settings, *, as_of: date | None = None, actor: str | None = None
) -> AnomalyRun: ...


# src/aml/ml/anomaly/evaluate.py
COVERAGE_COLUMNS = [
    "typology", "is_suspicious", "scenarios", "flagged_rules", "flagged_anomaly", "flagged_any",
    "new_by_anomaly", "accounts", "accounts_rules", "accounts_anomaly", "accounts_new",
]  # fmt: skip


def anomaly_coverage(
    db: Database,
) -> pd.DataFrame: ...  # một dòng mỗi typology của TYPOLOGY_KEYS có scenario
def evaluate_anomaly(
    db: Database, settings: Settings
) -> dict[str, Any]: ...  # tóm tắt + coverage; không ghi


# src/aml/ml/anomaly/card.py  (đường dẫn mà specs/ml-governance.md CARD_SOURCES trỏ tới)
def card_facts(
    db: Database, settings: Settings, run_id: int | None = None
) -> dict[str, Any]: ...  # Q16


# src/aml/ml/anomaly/case_features.py  (nối vào 7c như 8d)
ANOMALY_CASE_FEATURES = ("anomaly_max_score", "anomaly_flagged_months")
NON_NEGATIVE_ANOMALY = ANOMALY_CASE_FEATURES
ANOMALY_FEATURE_TAG = "+anom/v1"


def write_anomaly_features(db: Database, settings: Settings, run_id: int) -> int: ...
def read_anomaly_features(db: Database, settings: Settings, run_id: int) -> pd.DataFrame | None: ...
def decided_anomaly_features(
    db: Database, settings: Settings, decided: pd.DataFrame
) -> pd.DataFrame | None: ...
```
- `config.yaml`: section cấp cao nhất mới `ml: {anomaly: {baseline_days: 90, min_baseline_days: 28, night_start_hour: 22,
  night_end_hour: 6, n_estimators: 200, max_samples: 256, alert_top_fraction: 0.005, min_samples: 50, top_deviations: 3,
  features: auto, results_dir: results/phase7b}}`. Nguồn feature đồ thị dùng lại `cases.graph_features` (không thêm khoá).
- DDL `sql/duckdb/ddl/200_ml_anomaly.sql` và bản Oracle, sau `ddl/190_memo_analysis.sql`, trước các script `050_*`: bảng
  `anomaly_runs`, `anomaly_scores`, `case_anomaly_features`; view `anomaly_scores_current`; bản Oracle thêm `ALTER TABLE
  case_models MODIFY (feature_version VARCHAR2(60 CHAR))` (idempotent: nới rộng lặp lại không lỗi; bản DuckDB không cần vì
  DuckDB không ép độ dài — Q8).
- Truy vấn: `ml/anomaly_legs.sql` ở `sql/duckdb/` và `sql/oracle/` (đọc `txn_legs` với `txn_ts < {cutoff}`).
- CLI: nhóm lệnh mới `aml anomaly` với `aml anomaly run [--as-of YYYY-MM-DD] [--eval-out PATH]` và `aml anomaly eval
  [--eval-out PATH]`. Không vào `make all` / `tasks.ps1 all` (Q14).
- **File 7b-i sở hữu (tạo mới)**: `src/aml/ml/__init__.py`, `src/aml/ml/anomaly/__init__.py`, `features.py`, `model.py`,
  `runner.py`, `evaluate.py`, `case_features.py`, `card.py`, `cli.py`; `sql/{duckdb,oracle}/ddl/200_ml_anomaly.sql`;
  `sql/{duckdb,oracle}/ml/anomaly_legs.sql`; `tests/ml_anomaly/` (cả thư mục); `specs/ml-anomaly.md`.
- **File dùng chung phải sửa (điểm gộp với spec khác)**: `src/aml/common/config.py`, `config.yaml`, `src/aml/dba/schema.py`
  (thêm `200`), `src/aml/cli.py` (`app.add_typer(anomaly_app, name="anomaly")`), `sql/{duckdb,oracle}/cases/items.sql` và
  `truth_accounts.sql` (thêm `'ANOMALY'`), `src/aml/cases/runner.py` (đếm `ANOMALY`, hậu tố `reason`),
  `src/aml/cases/summary_template.py` (đếm `ANOMALY`, hậu tố dòng Alerts), `src/aml/cases/prioritize.py` (`train` / `score`
  nối 2 cột). **Không sửa** `aml.monitoring.recording`, `aml.cases.features` (`FEATURES`, `FEATURE_VERSION`),
  `aml.cases.model`, `aml.memo.*`, `hibernation.py`, `sql/common/api/*`, `web/` (ràng buộc cho reviewer, không phải AC).

### Thiết kế (đề xuất, chờ xác nhận ở Câu hỏi mở)
- **Đơn vị mẫu** (Q1): một **(cif, tháng lịch)**. Tháng `m` có cửa sổ `[đầu tháng, min(đầu tháng sau, as_of + 1 ngày))` —
  tháng của `as_of` có thể thiếu ngày. Tháng xét: từ tháng của `data.start_date` tới tháng của `as_of`. Một (cif, tháng) là
  mẫu khi cif có ít nhất một dòng `txn_legs` (account nội bộ của cif, cả chiều `IN` lẫn `OUT`) trong cửa sổ. Không loại giao
  dịch trùng DQ (như mọi luật Phase 5). Khoá alert ổn định giữa các lần chạy: `ML_ANOMALY|{cif}|{YYYY-MM}`.
- **Feature** (`ANOMALY_FEATURES`, 14 cột, đúng thứ tự; mọi giá trị là float hữu hạn, làm tròn 10 chữ số trước khi fit; `d_w`
  = số ngày của cửa sổ; tính trên các leg của cif trong cửa sổ; Q5):
  1. `txns_per_day` = số leg / `d_w`; 2. `max_txns_day` = số leg lớn nhất trong một ngày lịch;
  3. `amount_log` = log10(1 + tổng `amount_vnd` của mọi leg); 4. `cash_ratio` = tổng tiền leg `channel = 'CASH'` / tổng tiền
  (0 khi tổng 0); 5. `counterparties` = số `counterparty_id` khác nhau, khác NULL; 6. `night_ratio` = tỉ lệ leg có giờ
  `>= night_start_hour` hoặc `< night_end_hour`; 7. `pass_through` = min(vào, ra) / max(vào, ra) (0 khi max 0);
  8–10. **độ lệch so với baseline của chính cif**: baseline = `[max(đầu tháng − baseline_days ngày, data.start_date), đầu
  tháng)`, `d_b` ngày; nếu `d_b >= min_baseline_days`: `amount_dev` = log10((1 + tiền_w / d_w) / (1 + tiền_b / d_b)),
  `txn_dev` = log10((1 + leg_w / d_w) / (1 + leg_b / d_b)), `new_counterparty_ratio` = |đối tác_w − đối tác_b| / |đối tác_w|
  (0 khi không có đối tác); ngược lại cả ba = 0 (Q6);
  11–14. **đồ thị** (`GRAPH_FEATURES`): MAX trên các account của cif trong nguồn `choose_source(db,
  settings.cases.graph_features, as_of)`; account không có dòng → 0; nguồn `none` → 0 cả bốn. Đây là ảnh chụp tại lần chạy
  network / GDS, dùng chung cho mọi tháng (rò rỉ thời gian, ghi vào hạn chế).
- **Mô hình**: `IsolationForest(n_estimators, max_samples=min(max_samples, n), max_features=1.0, bootstrap=False,
  random_state=settings.seed, n_jobs=1)` fit trên **toàn bộ** mẫu của lần chạy (sắp theo (cif, month)) rồi chấm chính các mẫu
  đó; `anomaly_score = round(-score_samples(X), 6)` ∈ (0, 1], cao hơn = bất thường hơn. Mỗi lần chạy fit mới (Q10); không lưu
  artifact nhị phân — tái lập bằng (`data_hash`, `params`, seed, phiên bản scikit-learn ghi trong `params`).
- **Xếp hạng và ngưỡng** (Q2): `rank` 1..n theo (điểm giảm, `cif` tăng, `month` tăng); `k = alert_count(n,
  alert_top_fraction)`; mẫu `rank <= k` là `alerted`. Ngưỡng luôn sinh đúng `k` alert, kể cả khi không có gì bất thường thật
  (ghi vào hạn chế).
- **Giải thích** (`top_deviations`): với mỗi feature, `z = (x − trung vị) / IQR` trên toàn bộ mẫu của lần chạy (phân vị nội
  suy tuyến tính như mặc định NumPy / pandas; IQR = 0 → chia 1); lấy `top_deviations` feature có |z| lớn nhất (hoà: theo thứ
  tự `ANOMALY_FEATURES`); mỗi phần tử `{feature, value, median, z}` làm tròn 4.
- **Alert** (qua `record_run(db, as_of=as_of, source="ANOMALY", rules=[RuleRun("ML_ANOMALY", model_version, params)],
  alerts=…)` với `params` = dump phẳng của `settings.ml.anomaly`; không sửa `record_run`): `subject_type = "CUSTOMER"`, `subject_id = cif`, `accounts` = các account của cif có leg
  trong cửa sổ (vai `SUBJECT`, sắp tăng), `window_start` = `first_ts` (leg đầu tiên trong tháng), `window_end` = `last_ts`,
  `txn_ids` = mọi `txn_id` khác nhau của các leg đó, `amount_vnd` = tổng `amount_vnd` trên các `txn_id` khác nhau,
  `alert_key = f"ML_ANOMALY|{cif}|{month}"`, `rule_version = model_version`, `details = {anomaly_score, rank, samples,
  alerts, month, model_version, top_deviations}`. `reason` (tiếng Anh, template, không chứa tên hay memo):
  `anomaly score {score:.4f} ranks {rank} of {samples} customer-months as of {as_of} (alerting the top {alerts}); strongest
  deviations from the median: {f1} {z1:+.2f}, {f2} {z2:+.2f}, {f3} {z3:+.2f} (IQR units); model {model_version}; a signal for
  a person to review, not a finding`.
- **Thứ tự ghi**: mọi kiểm tra và tính toán trước lần ghi đầu tiên → `anomaly_scores` → `record_run` → trong **một**
  `db.transaction()`: dòng `anomaly_runs` + audit `ANOMALY_RUN_COMPLETED`. `anomaly_scores_current` theo `MAX(run_id)` của
  `anomaly_runs`, nên điểm của lần chạy chết giữa chừng không bao giờ thành hiện hành; `run_id` mới = 1 + max của
  `anomaly_runs` và `anomaly_scores`.
- **Bảng** (DDL `200`; chỉ INSERT):
  - `anomaly_runs(run_id PK, run_ts UTC, as_of, model_version VARCHAR(20), kind VARCHAR(20) = 'isolation_forest',
    feature_version VARCHAR(20) = 'anomaly/v1', seed, samples, customers, months, alerts, threshold, graph_source VARCHAR(10),
    monitoring_run_id, data_hash VARCHAR(16), features JSON, params JSON, metrics JSON, seconds, actor)` — đủ các cột mà
    `specs/ml-governance.md` đòi ở bảng model (`version` = `model_version`, `trained_ts` = `run_ts`); `params = {config: settings.ml.anomaly (dump), iforest:
    tham số IsolationForest thật dùng, sklearn_version, numpy_version}`; `months` = số tháng khác nhau có mẫu; `metrics = {min, p25, p50, p75, p90, p99, max}` của điểm,
    làm tròn 6 (mô hình không giám sát: không có chỉ số đúng / sai lúc huấn luyện).
  - `anomaly_scores(run_id, cif, month VARCHAR(7), model_version VARCHAR(20), window_start, window_end, score, rank, alerted
    SMALLINT, top_deviations JSON NULL)`, PK `(run_id, cif, month)`; `top_deviations` chỉ khác NULL ở dòng `alerted = 1`.
    **Mọi dòng mang `model_version`.**
  - `case_anomaly_features(run_id, case_id, anomaly_run_id, feature, value)`, PK mọi cột trừ `value`.
  - View `anomaly_scores_current` = dòng của `run_id = (SELECT MAX(run_id) FROM anomaly_runs)`.
- **Audit** (mọi dòng mang phiên bản mô hình, Q9): mỗi alert → dòng `ALERT` của `record_run` (`module='monitoring'`,
  `version='ML_ANOMALY/anomaly/v1/{run_id}'`, `reason` như trên); mỗi lần chạy → `MONITORING_RUN_COMPLETED` của `record_run`
  (`version='monitoring/anomaly'`, hành vi Phase 5 không đổi) và `ANOMALY_RUN_COMPLETED` (`module='ml_anomaly'`,
  `entity_type='anomaly_run'`, `entity_id=str(run_id)`, `version=model_version`, `reason` = `scored {samples} customer-months
  of {customers} customers ({first_month} to {last_month}) with isolation forest {model_version} (seed {seed}, {n_estimators}
  trees, graph features from {graph_source}); {alerts} alert(s) at score >= {threshold:.4f} (top {alert_top_fraction:.1%}); signals for review
  only, nothing is closed or cleared`, `details` = các trường của `AnomalyRun` + `metrics`; `first_month` / `last_month` = tháng nhỏ / lớn nhất có mẫu). Không ghi audit cho từng mẫu
  không bị cờ (điểm của chúng nằm trong `anomaly_scores` cùng `model_version`).
- **Đi vào case** (Q3): `items.sql` lấy `a.source IN ('RULE', 'NETWORK', 'ANOMALY')`; item `ANOMALY` gộp theo golden customer
  và cửa sổ như mọi alert, **có thể mở case mới hoặc dời mốc cửa sổ** (đổi `case_id`) của khách hàng đã có alert. `cases`
  không thêm cột: `alerts` đếm cả ANOMALY, ba cột `*_alerts` cũ giữ nguyên nghĩa. `reason` của case và dòng `- Alerts:` của
  tóm tắt thêm `, {n} ANOMALY` vào sau `{s} SCREENING` **chỉ khi n > 0** (chuỗi cũ không đổi khi chưa có alert ANOMALY).
  `truth_accounts.sql` tính cả item `ANOMALY` (nhãn mô phỏng 7c dùng account của alert như RULE / NETWORK). Item ANOMALY
  **không bao giờ ngủ đông** (giữ `_HIBERNATING_SOURCES`) và không có good-guy (Q15). Item ANOMALY cũng đi vào các feature 7c đã ghim `alerts`, `distinct_rules` (thêm `ML_ANOMALY`) và `alert_amount_log` (alert bất thường mang cả tháng nên tiền đã có trong alert RULE bị đếm lần hai), nên ngay cả với `ml.anomaly.features=off` điểm 7c của case có item ANOMALY vẫn đổi; `aml.cases.features` không sửa.
- **Đánh giá** (`anomaly_coverage`, Q4): giống `network_coverage` của 5c. Với mỗi typology của `TYPOLOGY_KEYS` có scenario:
  `flagged_rules` = scenario có account nằm trong `alert_accounts` của alert hiện hành nguồn RULE hoặc NETWORK (không xét thời
  gian); `flagged_anomaly` = scenario có một dòng `ground_truth` loại `account` mà cif chủ account có mẫu `alerted = 1` của
  lần chạy bất thường hiện hành ở tháng giao với `[start_ts, end_ts]` của dòng đó; `flagged_any` = hợp; `new_by_anomaly` =
  `flagged_anomaly − flagged_rules`; bốn cột `accounts_*` tương tự theo account. Phép so lệch có chủ ý về phía luật (luật
  không cần trùng thời gian), nên `new_by_anomaly` là cận dưới. `evaluate_anomaly` trả `{run_id, model_version, as_of,
  samples, alerts, alert_top_fraction, threshold, suspicious: {scenarios, flagged_rules, flagged_anomaly, new_by_anomaly,
  accounts, accounts_rules, accounts_anomaly, accounts_new}, benign: {scenarios, flagged_anomaly, accounts_anomaly},
  alerts_by_kind: {suspicious, benign, scenario_other_month, none}, alerts_on_rule_alerted_customers, coverage: [dòng]}`;
  `alerts_by_kind` xếp mỗi alert theo thứ tự ưu tiên: trùng tháng với scenario đáng ngờ → `suspicious`; với scenario lành
  tính → `benign`; cif có account trong scenario nhưng khác tháng → `scenario_other_month`; còn lại `none`. Thứ tự lỗi:
  chưa có lần chạy → `AnomalyError("no anomaly run yet: run `aml anomaly run` first")`; `ground_truth` rỗng →
  `AnomalyError("no ground truth: nothing to evaluate against")`.
- **CLI** (`aml.ml.anomaly.cli`, gắn vào `aml` như `aml memo`): `aml anomaly run` gọi `run_anomaly` (actor = system),
  in một dòng `run_id={id} model_version={v} as_of={d} samples={n} customers={c} months={m} alerts={k}
  threshold={t:.4f} graph_source={g} monitoring_run_id={r}`; nếu `ground_truth` khác rỗng in thêm mỗi typology một dòng
  `{typology:<16} scenarios={..} rules={flagged_rules} anomaly={flagged_anomaly} new={new_by_anomaly} accounts={..}
  accounts_rules={..} accounts_anomaly={..} accounts_new={..}` và chỉ ghi JSON khi có `--eval-out`; dòng cuối luôn là
  `anomaly alerts are signals for review: no case is closed or cleared by this model`. `aml anomaly eval` gọi
  `evaluate_anomaly` cho lần chạy hiện hành và **luôn** ghi JSON (mặc định `{results_dir}/anomaly_eval.json`). JSON =
  kết quả `evaluate_anomaly` + `command` (chuỗi lệnh đã gõ, để README dẫn nguồn). `AnomalyError` → stderr, exit 1.
- **Model card** (`card_facts`, định dạng thuộc `specs/ml-governance.md`): `{model: {name: "ml-anomaly", kind:
  "isolation_forest", version, feature_version, trained_ts, as_of, seed, sklearn_version}, data: {synthetic: True, samples,
  customers, months, first_month, last_month, graph_source, data_hash}, features: [{name, doc}], params, metrics, alerts:
  {count, top_fraction, threshold}, evaluation: evaluate_anomaly(…) hoặc None khi không có ground truth, limitations:
  LIMITATIONS, use: {purpose: "alert source and ranking feature", auto_close: False}}`; `LIMITATIONS` là tuple hằng, tiếng
  Anh, gồm ít nhất: dữ liệu tổng hợp; feature đồ thị là ảnh chụp (rò rỉ thời gian cho tháng cũ); không có tín hiệu đêm được
  cài; mẫu lành tính kiểu merchant điểm cao; ngưỡng theo tỉ lệ luôn sinh `k` alert; trên dữ liệu tổng hợp luật đã phủ mọi
  scenario đáng ngờ.
- **Nối vào 7c** (Q7, Q8, Q12): feature case = `anomaly_max_score` (điểm lớn nhất) và `anomaly_flagged_months` (số mẫu
  `alerted = 1`) trên các mẫu của lần chạy bất thường **hiện hành** có `cif` thuộc `linked_cifs.cifs` của ảnh chụp và tháng giao
  với `[txn_summary.window_start, txn_summary.window_end]` (cửa sổ tháng `[ms, me)` giao đoạn ngày `[ws, we]` khi `ms < we + 1
  ngày` và `me > ws`); không có mẫu → 0, 0. `write_anomaly_features(db, settings, run_id)`: chưa có lần chạy bất thường → 0;
  đã có dòng cho (`run_id`, `anomaly_run_id` hiện hành) → 0; ngược lại ghi 2 dòng mỗi case và trả số dòng. `train`: khi
  `ml.anomaly.features == "auto"` và có lần chạy bất thường → nối 2 cột sau 35 cột gốc (và sau 6 cột memo nếu 8d đang bật),
  fit bằng `fit_guarded` của 8d với `non_negative = NON_NEGATIVE + NON_NEGATIVE_ANOMALY`, `feature_version` = phiên bản cũ +
  `+anom/v1` (`features/v1+anom/v1` hoặc `features/v1+memo/v1+anom/v1`), `params.anomaly = {run_id, model_version,
  dropped_features}`, audit `MODEL_TRAINED` thêm `details.anomaly` cùng nội dung; ngược lại **đúng hành vi hiện tại** (không
  khoá `anomaly`). `score`: model có cột bất thường nhận cột của run case hiện hành từ lần chạy bất thường hiện hành; audit
  `SCORING_RUN_COMPLETED` thêm `details.anomaly_features = {trained_version, used_version}` (khác nhau không phải lỗi). Khi cả hai cột bị `fit_guarded` loại (không còn cột bất thường trong `features`), `score` không ghi dòng `case_anomaly_features` nào và `SCORING_RUN_COMPLETED` không có `details.anomaly_features`.

### Tác động lên spec khác — là một phần của spec này
| # | spec | thay đổi | test phải cập nhật |
|---|---|---|---|
| S1 | `specs/case-consolidation.md` | nguồn thứ tư `ANOMALY` trong `items.sql`; hậu tố `, {n} ANOMALY` của `reason` khi n > 0; `alerts` đếm cả ANOMALY | không (chuỗi cũ giữ nguyên khi n = 0) |
| S2 | `specs/case-prioritization.md` | `truth_accounts.sql` tính item ANOMALY; `train` / `score` nối 2 cột khi có lần chạy bất thường; Oracle nới `case_models.feature_version` lên 60 | không (TINY-L không có lần chạy bất thường → hành vi 7c) |
| S3 | `specs/memo-analysis.md` | `fit_guarded` được gọi với danh sách `non_negative` mở rộng; `feature_version` có thể thành `features/v1+memo/v1+anom/v1` | không |
| S4 | `specs/case-summary.md` | dòng `- Alerts:` thêm `, {n} ANOMALY` khi n > 0; AC1 của 7d ghim danh sách script giữa `180` và `050` | `tests/cases/test_summary_unit.py::test_ac1_no_new_schema_script` nhận thêm `ddl/200_ml_anomaly.sql` (đã sửa khi hiện thực, 2026-10-14) |
| S5 | `specs/ml-governance.md` (đang soạn) | card lấy từ `aml.ml.anomaly.card:card_facts` (đúng `CARD_SOURCES` của spec đó) nhưng trả **dict**, không phải `CardFacts | Skipped` — vì 7b-i hiện thực trước governance, governance phải bọc dict thành `CardFacts` (Q16); cặp audit mang phiên bản: (`monitoring`, `ALERT` có `details.rule_id = 'ML_ANOMALY'`) và (`ml_anomaly`, `ANOMALY_RUN_COMPLETED`), registry = `anomaly_runs.model_version` — `version_gaps` phải lọc `ALERT` theo `rule_id` vì `ALERT` của luật mang phiên bản luật | cập nhật `MODEL_DECISIONS` / test AC7 của governance |
| S6 | `specs/screening-ml.md` (210), `specs/ml-governance.md` (220) | dùng chung section `ml:` / `MlConfig` (`ml.screening`, `ml.governance`); mỗi spec chỉ thêm trường của mình | — |
| S7 | Phase 9 (`ui-*`, `metrics`) | nhãn nguồn `ANOMALY` trên UI, bằng chứng của alert ANOMALY trong bảng giao dịch case, dòng ANOMALY trên dashboard phát hiện: **chưa làm** (Ngoài phạm vi); `active_alerts` của dashboard tự đếm cả ANOMALY | không |

## Tiêu chí nghiệm thu
<!-- settings = load_settings(environ={"DB_BACKEND": "duckdb"}); ANOM = settings với thêm
`AML__ML__ANOMALY__MIN_SAMPLES=5`. MINI-C, `tiny_cases`, `tiny_env`, `cli_db`, TINY-L như specs/case-consolidation.md và
specs/case-prioritization.md (MINI-C không có dòng `nx_account_features` → nguồn đồ thị `none`).
LEGS-M = 11 leg của MINI-C (đúng `txn_legs`): C01 T08 2026-01-15 09:00 IN 10M EXT-01 INTERBANK_TRANSFER; C01 T01 2026-03-02
09:00 IN 390M NULL CASH; C03 T02 03-05 10:00 IN 300M A01; C01 T02 03-05 10:00 OUT 300M A03; C04 T03 03-06 10:00 IN 290M A03;
C03 T03 03-06 10:00 OUT 290M A04; C01 T04 03-07 10:00 IN 280M A04; C04 T04 03-07 10:00 OUT 280M A01 (ba dòng sau là
INTERNAL_TRANSFER); C02 T05 04-20 08:00 IN 500M EXT-01 INTERBANK_TRANSFER; C02 T06 04-20 12:00 OUT 480M EXT-02 EBANKING;
C01 T07 05-31 09:00 OUT 50M EXT-03 EBANKING. "(đo)" = giá trị của nguyên mẫu (scikit-learn 1.9.1, NumPy 2.4.6); lệch do
phiên bản thư viện → cập nhật spec, không đổi định nghĩa. Số thực so với sai số 1e-6 trừ khi ghi khác.
Test [oracle] chạy lặp lại được trên Oracle dùng chung, chỉ thêm: không khẳng định số đếm phụ thuộc lịch sử; id lấy từ giá
trị trả về; env ghim `AML__CASES__GRAPH_FEATURES=networkx` trên cả hai backend. -->
- AC1: Given `config.yaml`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS` và gọi `apply_schema(duck)` hai lần, Then `settings.ml.anomaly` có `baseline_days == 90`, `min_baseline_days == 28`, `night_start_hour == 22`, `night_end_hour == 6`, `n_estimators == 200`, `max_samples == 256`, `alert_top_fraction == 0.005`, `min_samples == 50`, `top_deviations == 3`, `features == "auto"`, `results_dir == "results/phase7b"`; `AML__ML__ANOMALY__FEATURES=off` cho `features == "off"`; mỗi override sau raise `pydantic.ValidationError` chứa đúng thông điệp: `BASELINE_DAYS=0` → `ml.anomaly baseline_days must be >= 1`, `MIN_BASELINE_DAYS=91` → `ml.anomaly min_baseline_days must be between 0 and baseline_days`, `NIGHT_END_HOUR=22` → `ml.anomaly night_start_hour and night_end_hour must be 0..23 and differ`, `NIGHT_START_HOUR=24` → cùng thông điệp đó, `N_ESTIMATORS=5` → `ml.anomaly n_estimators must be between 10 and 2000`, `MAX_SAMPLES=1` → `ml.anomaly max_samples must be >= 2`, `ALERT_TOP_FRACTION=0` và `ALERT_TOP_FRACTION=0.2` → `ml.anomaly alert_top_fraction must be in (0, 0.1]`, `MIN_SAMPLES=1` → `ml.anomaly min_samples must be >= 2`, `TOP_DEVIATIONS=15` → `ml.anomaly top_deviations must be between 1 and 14`, `FEATURES=on` → `ValidationError`; `ddl/200_ml_anomaly.sql` có trong `SCHEMA_SCRIPTS` của cả hai backend, ngay sau `ddl/190_memo_analysis.sql` và trước các script `050_*`; `apply_schema` không raise; `SELECT COUNT(*)` trên `anomaly_runs`, `anomaly_scores`, `anomaly_scores_current`, `case_anomaly_features` đều trả 0; `ml/anomaly_legs.sql` resolve qua `sql_file` về `sql/duckdb/` cho `"duckdb"` và `sql/oracle/` cho `"oracle"`, file Oracle qua `split_oracle_script` ra đúng 1 statement và file DDL Oracle ra ít nhất 4 statement trong đó có một chứa `MODIFY` và `feature_version`; `ANOMALY_VERSION == "anomaly/v1"`, `len(ANOMALY_FEATURES) == 14`, `ANOMALY_FEATURES[-4:] == GRAPH_FEATURES`, `set(FEATURE_DOCS) == set(ANOMALY_FEATURES)` và mọi mô tả khác rỗng; `ANOMALY_CASE_FEATURES == ("anomaly_max_score", "anomaly_flagged_months")`.
- AC2: Given LEGS-M, đồ thị rỗng và `cfg = settings.ml.anomaly`, When gọi `s = build_samples(legs, graph, as_of=date(2026, 6, 30), start_date=date(2026, 1, 1), cfg=cfg)`, Then `s` có đúng 6 dòng theo thứ tự (C01, 2026-01), (C01, 2026-03), (C01, 2026-05), (C02, 2026-04), (C03, 2026-03), (C04, 2026-03), cột là `SAMPLE_COLUMNS` rồi `ANOMALY_FEATURES`; dòng (C01, 2026-03) có `window_start = 2026-03-01 00:00:00`, `window_end = 2026-04-01 00:00:00`, `first_ts = 2026-03-02 09:00:00`, `last_ts = 2026-03-07 10:00:00`, `txn_count = 3`, `amount_vnd = 970000000`, `accounts = ["A01"]`, `txns_per_day = 3/31`, `max_txns_day = 1`, `amount_log = log10(1 + 970000000)`, `cash_ratio = 390/970`, `counterparties = 2` (NULL không tính), `night_ratio = 0`, `pass_through = 300/670`, `amount_dev = log10((1 + 970000000/31) / (1 + 10000000/59))` ≈ 2.266260, `txn_dev = log10((1 + 3/31) / (1 + 1/59))` ≈ 0.032818, `new_counterparty_ratio = 1.0` (baseline 2026-01-01 → 2026-03-01, 59 ngày, chỉ có EXT-01); dòng (C01, 2026-01) có ba feature độ lệch đều 0 (baseline 0 ngày < 28); dòng (C01, 2026-05) có `amount_dev = log10((1 + 50000000/31) / (1 + 970000000/90))` ≈ −0.824921, `txn_dev` ≈ −0.000452 (baseline 2026-01-31 → 2026-05-01, 90 ngày, không chứa T08); dòng (C02, 2026-04) có `window_end = 2026-05-01 00:00:00`, `max_txns_day = 2`, `txns_per_day = 2/30`, `pass_through = 0.96`, `amount_dev = log10(1 + 980000000/30)` ≈ 7.514105; mọi giá trị của bốn cột `GRAPH_FEATURES` bằng 0.0; với `as_of=date(2026, 5, 15)` trả 5 dòng (không có (C01, 2026-05)); với `AML__ML__ANOMALY__MIN_BASELINE_DAYS=60` dòng (C01, 2026-03) có ba feature độ lệch bằng 0 (59 < 60); với `night_start_hour=9` (giờ `>= 9` hoặc `< 6`) dòng (C01, 2026-03) có `night_ratio = 1.0`; với `graph` có dòng (`account_id` A01, `in_degree` 3, `out_degree` 1, `pagerank_ratio` 2.5, `shared_cluster_size` 0) và (A02, 7, 0, 0.5, 4) thì mọi dòng của C01 có (3, 1, 2.5, 0) và dòng C02 có (7, 0, 0.5, 4); LEGS-M rỗng trả frame rỗng đủ cột; và hàm không đọc DB, không ghi gì.
- AC3: Given X = 14 cột feature của 6 dòng AC2 (as_of 2026-06-30) và `cfg = ANOM.ml.anomaly`, When gọi `fit_score(X, cfg, seed=42)` hai lần, `fit_score(X, cfg, seed=7)`, `rank_scores`, `alert_count`, `top_deviations` và `data_hash`, Then hai lần seed 42 cho hai Series bằng nhau từng phần tử; điểm (đo) = (C01, 2026-01) 0.549925, (C01, 2026-03) 0.567938, (C01, 2026-05) 0.511577, (C02, 2026-04) 0.502817, (C03, 2026-03) 0.379239, (C04, 2026-03) 0.380698, mọi điểm trong (0, 1] và có đúng 6 chữ số thập phân; `rank_scores` cho rank 1..6 lần lượt (C01, 2026-03), (C01, 2026-01), (C01, 2026-05), (C02, 2026-04), (C04, 2026-03), (C03, 2026-03); với hai mẫu cùng điểm, mẫu `cif` nhỏ hơn có rank nhỏ hơn, cùng `cif` thì `month` nhỏ hơn đứng trước; seed 7 cho Series khác seed 42; `alert_count(6, 0.005) == 1`, `alert_count(6, 0.5) == 3`, `alert_count(1334, 0.005) == 7`, `alert_count(27589, 0.005) == 138`, `alert_count(200, 0.005) == 1`, `alert_count(0, 0.005) == 0`; `top_deviations(X, ("C01", "2026-03"), 3)` trả đúng 3 phần tử với `feature` lần lượt `txns_per_day` (`z` 1.25), `cash_ratio` (`z` 0.4021, IQR 0 → chia 1), `amount_dev` (`z` −0.3725), mỗi phần tử có đúng khoá `feature`, `value`, `median`, `z`; `data_hash(X)` là chuỗi 16 ký tự hex, bằng nhau cho hai lần gọi và khác khi đổi một ô của X đi 1e-6; và đầu vào ít hơn 2 dòng làm `fit_score` raise `ValueError`.
- AC4: Given MINI-C và ANOM, When gọi `r1 = run_anomaly(duck, ANOM)` rồi `r2 = run_anomaly(duck, ANOM)`, Then `r1` có `run_id = 1`, `model_version == "anomaly/v1/1"`, `as_of = date(2026, 6, 30)`, `samples = 6`, `customers = 4`, `months = 4`, `alerts = 1`, `threshold = 0.567938` (đo), `graph_source == "none"`, `data_hash` bằng `data_hash` của AC3, `seconds >= 0`; `anomaly_scores` có 6 dòng `run_id = 1`, mọi dòng `model_version = 'anomaly/v1/1'`, đúng một dòng `alerted = 1` là (C01, 2026-03) với `rank = 1`, `top_deviations` là mảng 3 phần tử bắt đầu bằng `txns_per_day`, 5 dòng còn lại có `top_deviations` NULL; `anomaly_runs` có 1 dòng với `feature_version = 'anomaly/v1'`, `seed = 42`, `features` = mảng 14 tên bằng `ANOMALY_FEATURES`, `params.iforest.n_estimators = 200`, `params.iforest.max_samples = 6` (= min(256, 6)), `params.iforest.random_state = 42`, `params.config.max_samples = 256`, có khoá `params.sklearn_version`, `kind = 'isolation_forest'`, `metrics.max = 0.567938`, `monitoring_run_id = r1.monitoring_run_id`; `alerts` có 1 dòng `source = 'ANOMALY'`, `rule_id = 'ML_ANOMALY'`, `rule_version = 'anomaly/v1/1'`, `subject_type = 'CUSTOMER'`, `subject_id = 'C01'`, `alert_key = 'ML_ANOMALY|C01|2026-03'`, `window_start = 2026-03-02 09:00:00`, `window_end = 2026-03-07 10:00:00`, `txn_count = 3`, `amount_vnd = 970000000`, `details.model_version == "anomaly/v1/1"`, `details.rank == 1`, và `reason` bằng đúng `anomaly score 0.5679 ranks 1 of 6 customer-months as of 2026-06-30 (alerting the top 1); strongest deviations from the median: txns_per_day +1.25, cash_ratio +0.40, amount_dev -0.37 (IQR units); model anomaly/v1/1; a signal for a person to review, not a finding`; `alert_accounts` của alert đó = {(A01, C01, SUBJECT)}, `alert_evidence` = {T01, T02, T04}; `monitoring_runs` có dòng (`rule_id` ML_ANOMALY, `source` ANOMALY, `rule_version` anomaly/v1/1, `alerts` 1, `evidence` 3); `audit_log` có đúng 1 dòng `decision='ALERT'` với `version='ML_ANOMALY/anomaly/v1/1'`, 1 dòng `MONITORING_RUN_COMPLETED` với `version='monitoring/anomaly'` và 1 dòng `module='ml_anomaly'`, `entity_type='anomaly_run'`, `entity_id='1'`, `decision='ANOMALY_RUN_COMPLETED'`, `version='anomaly/v1/1'`, `actor='system'`, `reason` bắt đầu bằng `scored 6 customer-months of 4 customers (2026-01 to 2026-05)`; `r2` có `run_id = 2`, `model_version == "anomaly/v1/2"`, cùng `data_hash`, và 6 dòng `run_id = 2` của `anomaly_scores` có cùng (`cif`, `month`, `score`, `rank`, `alerted`) như run 1; `anomaly_scores_current` chỉ có 6 dòng `run_id = 2`; `alerts_current` có đúng 1 dòng `source = 'ANOMALY'` (của run 2) và vẫn đủ các alert RULE / NETWORK của MINI-C; các dòng `run_id = 1` của `anomaly_scores` và `anomaly_runs` không đổi; và `run_anomaly(duck, ANOM, actor="analyst01")` ghi `ANOMALY_RUN_COMPLETED` với `actor='analyst01'`.
- AC5: Given MINI-C, When gọi `run_anomaly(duck, settings)` (mặc định `min_samples = 50`) và `run_anomaly` trên DuckDB đã `apply_schema` nhưng `transactions` rỗng, Then lần thứ nhất raise `AnomalyError` có thông điệp bằng đúng `only 6 customer-months to learn from, need at least ml.anomaly.min_samples=50`, lần thứ hai raise `AnomalyError` bằng đúng `transactions is empty; run `aml load` first`; trong cả hai trường hợp số dòng của `anomaly_runs`, `anomaly_scores`, `alerts`, `alert_accounts`, `alert_evidence`, `monitoring_runs`, `audit_log` trước và sau bằng nhau; và `detect_anomalies(duck, ANOM)` trên MINI-C trả frame 6 dòng có cột `score`, `rank`, `alerted` mà không ghi dòng nào vào bất kỳ bảng nào.
- AC6: Given MINI-C, When gọi `run_anomaly(duck, ANOM)` rồi `run = run_cases(duck, ANOM)` và `summarize` / `load_case` cho `C-C01-20260302`, Then `run.items = 10`, `run.alerts = 8`, `run.cases = 5` và tập `case_id` bằng đúng 5 case của MINI-C (mốc cửa sổ không đổi vì alert ANOMALY có `event_ts` 2026-03-02 09:00:00 bằng R1); dòng `C-C01-20260302` có `alerts = 4`, `rule_alerts = 2`, `network_alerts = 1`, `screening_alerts = 0`, `sources = 'ANOMALY+NETWORK+RULE'` và `reason` bằng đúng `4 alert(s) (2 RULE, 1 NETWORK, 0 SCREENING, 1 ANOMALY) on G-C01 between 2026-03-02 09:00:00 and 2026-04-20 12:00:00; window of 90 days from the first alert`; bốn case còn lại có `reason` bằng đúng chuỗi của MINI-C AC3 (không có chữ `ANOMALY`); `case_alerts_current` có dòng `item_key = 'ML_ANOMALY|C01|2026-03'`, `source = 'ANOMALY'`, `rule_id = 'ML_ANOMALY'`, `cif = 'C01'`, `case_id = 'C-C01-20260302'`, `status = 'ACTIVE'`, `details` = `{subject_type: "CUSTOMER", roles: ["SUBJECT"]}`; tóm tắt markdown của case có dòng bắt đầu bằng `- Alerts: 4 (2 RULE, 1 NETWORK, 0 SCREENING, 1 ANOMALY)` còn của `C-C04-20260305` bắt đầu bằng `- Alerts: 1 (0 RULE, 1 NETWORK, 0 SCREENING)`; `txn_summary` của `C-C01-20260302` vẫn có `window_start = "2026-01-21"`, `window_end = "2026-04-20"`; sau đó gọi `record_run(duck, as_of=date(2026, 6, 30), source="ANOMALY", rules=[RuleRun("ML_ANOMALY", "anomaly/v1/9", {})], alerts=[AlertRecord(rule_id="ML_ANOMALY", rule_version="anomaly/v1/9", subject_type="CUSTOMER", subject_id="C01", accounts=(("A01", "SUBJECT"),), window_start=2026-01-15 09:00:00, window_end=2026-01-15 09:00:00, txn_ids=("T08",), amount_vnd=10000000, reason="x", details={}, alert_key="ML_ANOMALY|C01|2026-01")])` (lần chạy ML_ANOMALY mới nhất thay alert của run_anomaly) rồi `run_cases(duck, ANOM)` thì các case của `G-C01` là đúng `C-C01-20260115` (item ANOMALY, R1, N1; cửa sổ tới 2026-04-15) và `C-C01-20260420` (R2, R3, S1), còn `C-C01-20260302` và `C-C01-20260531` không có trong run đó (Q3: alert ANOMALY dời được mốc cửa sổ); và `tests/cases/test_run_mini.py`, `tests/api/test_ac4_cases.py`, các test tóm tắt case hiện có vẫn xanh nguyên văn.
- AC7: Given `tiny_cases` (TINY, 52 case run 1, `graph_source` networkx) và settings mặc định, When gọi `r = run_anomaly(db, settings)`, `e = evaluate_anomaly(db, settings)`, `run_cases(db, settings)` rồi `truth_labels(db)`, Then `r.samples = 1334` (đo), `r.customers <= 300`, `r.alerts = 7` (= `alert_count(1334, 0.005)`), `r.graph_source == "networkx"`, `r.months = 6`; 7 dòng `alerted = 1` của `anomaly_scores` có `rank` 1..7 và điểm không tăng theo rank, mọi dòng khác có `rank > 7` và điểm `<= r.threshold`; `alerts_current` có đúng 7 dòng `source = 'ANOMALY'`, mỗi dòng có `alert_key` khớp `^ML_ANOMALY\|[^|]+\|2026-0[1-6]$`, `reason` chứa `model anomaly/v1/{r.run_id}`, `txn_count >= 1` và mọi `txn_id` của `alert_evidence` thuộc một account của `subject_id` trong tháng của khoá; `e["coverage"]` có đúng 6 dòng theo thứ tự `TYPOLOGY_KEYS` với cột `COVERAGE_COLUMNS`; với 4 typology đáng ngờ `flagged_rules == scenarios` và `new_by_anomaly == 0` (đo: luật đã chạm mọi scenario đáng ngờ của TINY), `e["suspicious"]["new_by_anomaly"] == 0`; ở mọi dòng `flagged_any == |rules ∪ anomaly|`, `new_by_anomaly == flagged_any − flagged_rules`, `accounts_new == accounts_anomaly − |anomaly ∩ rules|` (kiểm bằng phép tính độc lập trong test); tổng bốn giá trị của `e["alerts_by_kind"]` bằng 7; `e["model_version"] == r.model_version`; `run_cases` sau đó có các item `ANOMALY` trong `case_alerts_current` và với mỗi case chứa một item ANOMALY mà `alert_accounts` của nó có account thuộc scenario đáng ngờ (cùng golden customer), `truth_labels(db)[case_id].disposition == "SUSPICIOUS"`; và gọi `run_anomaly` lần hai cho cùng `data_hash` và cùng (cif, month, score, rank, alerted) ở cả 1334 dòng.
- AC8: Given MINI-C đã `run_anomaly(duck, ANOM)` rồi `run_cases(duck, ANOM)` (run case 1), When gọi `write_anomaly_features(duck, ANOM, 1)` hai lần và `read_anomaly_features(duck, ANOM, 1)`, Then lần một trả 10 và lần hai trả 0 với `case_anomaly_features` vẫn 10 dòng, mọi dòng có `anomaly_run_id = 1`; frame có index tăng dần (5 case) và cột đúng thứ tự `ANOMALY_CASE_FEATURES`; `C-C01-20260302` = (`anomaly_max_score` 0.567938, `anomaly_flagged_months` 1) (đo: tháng 01, 03 của C01 và 04 của C02 giao cửa sổ 2026-01-21 … 2026-04-20); `C-C01-20260531` = (0.511577, 0) (đo: 04 của C02, 05 của C01); `C-C03-20260305` = (0.379239, 0); `C-C04-20260305` = (0.380698, 0); `C-C05-20260630` = (0.0, 0.0); trước bất kỳ `run_anomaly` nào (MINI-C mới) `write_anomaly_features` trả 0 và `read_anomaly_features` trả `None`; sau `run_anomaly` lần hai (`anomaly_run_id` 2) `write_anomaly_features(duck, ANOM, 1)` ghi thêm 10 dòng `anomaly_run_id = 2` và `read_anomaly_features` trả giá trị của run 2; `write_features(duck, 1)` của 7c trả số dòng = 35 × 5 và `case_features` không có dòng nào có `feature` bắt đầu bằng `anomaly_`.
- AC9: Given TINY-L (38 case có disposition trên ảnh chụp run 1, run hiện hành 2, 52 case mỗi run, chưa phân loại memo), When gọi `train` / `score` trước và sau `run_anomaly(db, settings)`, Then **trước** lần chạy bất thường `train(db, settings)` cho dòng `case_models` có `feature_version = 'features/v1'`, `features` 35 tên bằng `FEATURES`, `params` không có khoá `anomaly` và audit `MODEL_TRAINED` không có `details.anomaly` (hành vi 7c không đổi); **sau** lần chạy bất thường `t = train(db, settings)` cho dòng `case_models` có `feature_version = 'features/v1+anom/v1'`, 35 phần tử đầu của `features` bằng `FEATURES`, phần còn lại là dãy con đúng thứ tự của `ANOMALY_CASE_FEATURES`, `params.anomaly.run_id` bằng `run_id` của lần chạy bất thường, `params.anomaly.model_version` bằng `model_version` của nó, `set(features) | set(params.anomaly.dropped_features) >= set(ANOMALY_CASE_FEATURES)`, mọi cột bất thường còn trong `features` có hệ số `>= 0` trong `artifact`, `details.anomaly` của audit `MODEL_TRAINED` bằng `params.anomaly`, và `case_anomaly_features` có đúng 104 dòng `run_id = 1`; `s = score(db, settings)` ghi 52 dòng `case_scores`, thêm 104 dòng `case_anomaly_features` `run_id = 2`, audit `SCORING_RUN_COMPLETED` có `details.anomaly_features == {"trained_version": <model_version>, "used_version": <model_version>}`; sau một `run_anomaly` nữa rồi `score` lại, `used_version` là phiên bản mới còn `trained_version` giữ phiên bản cũ và `score` không raise; với `AML__ML__ANOMALY__FEATURES=off` `train` cho `feature_version = 'features/v1'` và không có khoá `anomaly`; và số dòng `case_dispositions` cùng trạng thái của `cases_current` trước và sau mọi lời gọi trong AC này bằng nhau.
- AC10: Given `cli_db("full")` (TINY) và một DuckDB đã `aml init-db` nhưng chưa `aml load`, When chạy `aml anomaly eval`, `aml anomaly run`, `aml anomaly run --eval-out <tmp>/a.json`, `aml anomaly eval --eval-out <tmp>/b.json` trên TINY và `aml anomaly run` trên DB chưa nạp, Then `aml anomaly eval` trước lần chạy đầu exit code 1 với stderr chứa `no anomaly run yet: run `aml anomaly run` first`; `aml anomaly run` exit code 0, stdout có một dòng chứa `run_id=`, `model_version=anomaly/v1/`, `samples=1334`, `alerts=7`, `graph_source=networkx`, đúng 6 dòng bắt đầu bằng tên typology theo thứ tự `TYPOLOGY_KEYS` mỗi dòng chứa `scenarios=`, `rules=`, `anomaly=`, `new=`, `accounts_new=`, và dòng cuối bằng đúng `anomaly alerts are signals for review: no case is closed or cleared by this model`; `a.json` và `b.json` là JSON có đúng các khoá cấp cao nhất `command`, `run_id`, `model_version`, `as_of`, `samples`, `alerts`, `alert_top_fraction`, `threshold`, `suspicious`, `benign`, `alerts_by_kind`, `alerts_on_rule_alerted_customers`, `coverage` với `command` lần lượt là `aml anomaly run --eval-out …` và `aml anomaly eval --eval-out …` (chuỗi lệnh đã gõ), `b.json["run_id"]` bằng run mới nhất; `aml anomaly eval` không `--eval-out` ghi `results_dir/anomaly_eval.json` (thư mục `results_dir` trỏ vào `<tmp>` qua `AML__ML__ANOMALY__RESULTS_DIR`); `aml anomaly run` trên DB chưa nạp exit code 1 với stderr chứa `transactions is empty; run `aml load` first`; và `card_facts(db, settings)` trên TINY trả dict có đúng khoá `model`, `data`, `features`, `params`, `metrics`, `alerts`, `evaluation`, `limitations`, `use` với `model.version` bằng phiên bản của lần chạy mới nhất, `data.synthetic is True`, `len(features) == 14`, `use.auto_close is False`, `len(limitations) >= 6`, còn `card_facts(…, run_id=1)` trả phiên bản `anomaly/v1/1`.
- AC11: [oracle] Given TINY nạp vào cả Oracle và một DuckDB tạm qua `load` → `er` → `screen` → `monitor` → `network` → `dq` (cùng `as_of` 2026-06-30, env `AML__CASES__GRAPH_FEATURES=networkx`), When gọi `run_anomaly` rồi `evaluate_anomaly` trên hai backend, Then hai `AnomalyRun` có cùng `samples`, `customers`, `months`, `alerts`, `graph_source`, `data_hash` và `threshold` lệch không quá 1e-6; các dòng `anomaly_scores` của `run_id` trả về có cùng tập (`cif`, `month`, `rank`, `alerted`) và `score` lệch không quá 1e-6; các alert `source = 'ANOMALY'` của `monitoring_run_id` trả về có cùng tập (`alert_key`, `txn_count`, `amount_vnd`, `reason`); `coverage`, `suspicious`, `benign`, `alerts_by_kind` của hai lần đánh giá bằng nhau; trên Oracle `user_tables` có `ANOMALY_RUNS`, `ANOMALY_SCORES`, `CASE_ANOMALY_FEATURES`, `user_views` có `ANOMALY_SCORES_CURRENT`, `user_tab_columns` cho `CASE_MODELS.FEATURE_VERSION` có `CHAR_LENGTH = 60`, và gọi `apply_schema` trên Oracle lần hai không raise.
- AC12: Given mã nguồn của repo và TINY-L đã `run_anomaly`, When đọc file dạng văn bản và so số dòng trước và sau `run_anomaly` lần hai, Then số dòng `case_dispositions`, `cases`, `case_alerts`, `case_scores`, `case_models`, `good_guy_list` và trạng thái của `cases_current` không đổi; không file nào dưới `src/aml/ml/` chứa `record_disposition`, `case_dispositions`, `good_guy`, `UPDATE ` hay `DELETE `; `src/aml/ml/anomaly/` không import `aml.api`, `fastapi`, `neo4j` và chỉ `model.py` import `sklearn`; `_HIBERNATING_SOURCES == ("RULE", "NETWORK")`; mọi dòng `audit_log` có `module='ml_anomaly'` có `version` khớp `^anomaly/v1/\d+$` và mọi dòng `decision='ALERT'` có `details.rule_id = 'ML_ANOMALY'` có `version` khớp `^ML_ANOMALY/anomaly/v1/\d+$`; mọi dòng `anomaly_scores` có `model_version` khớp `^anomaly/v1/\d+$` bằng `model_version` của dòng `anomaly_runs` cùng `run_id`.

## Ngoài phạm vi
- Định dạng model card, file dưới `docs/models/`, lệnh sinh card (`specs/ml-governance.md`); spec này chỉ cung cấp
  `card_facts` và các cột / audit mà card cần.
- Screening ML (`screening/ml/`, DDL 210), selection bias / mẫu dưới ngưỡng (DDL 220), LLM memo (đã có ở 8d).
- UI: nhãn nguồn `ANOMALY`, hiển thị bằng chứng của alert ANOMALY trong `GET /cases/{id}/transactions`
  (`case_transactions.sql` giữ `RULE`, `NETWORK`), dòng ANOMALY trên dashboard phát hiện của 9c, trang điểm bất thường.
- Explainer typology của 8c cho alert ANOMALY (`ALERT_SOURCES` giữ nguyên); đồng bộ alert ANOMALY sang Neo4j.
- Ngủ đông / good-guy cho item ANOMALY (Q15); suppression nào khác dựa trên điểm bất thường.
- Lệnh so sánh có / không có feature bất thường kiểu `aml memo compare` (Q14); đưa `aml anomaly run` vào `make all` /
  `tasks.ps1 all`.
- Lưu artifact mô hình (pickle / joblib) để chấm lại sau; chấm mẫu mới bằng mô hình cũ; huấn luyện theo lô / online.
- Mô hình khác (LOF, autoencoder, one-class SVM); tinh chỉnh siêu tham số; feature theo golden customer thay cho cif (Q1).
- Feature đồ thị theo từng tháng (tính lại network / GDS mỗi tháng); khử trùng giao dịch DQ.
- Quyền Oracle cho các bảng mới (role của 2b); đo trên `large`; ghi số vào README (bước demo: `aml anomaly run --eval-out
  results/phase7b/anomaly_eval.json` trên `small`).
- Mọi hành động tự động lên case từ điểm bất thường (đóng, clear, hạ ưu tiên ngoài mô hình 7c, đề xuất disposition).

## Giả định
- Kết quả tất định với cùng dữ liệu, cấu hình, `settings.seed`, cùng phiên bản scikit-learn / NumPy trên cùng nền tảng;
  giữa Oracle và DuckDB cho phép lệch số thực cỡ 1e-9 ở feature, 1e-6 ở điểm (đường đọc số / thời gian). Phiên bản thư viện
  ghi trong `anomaly_runs.params`.
- `txn_ts` là giờ địa phương Asia/Ho_Chi_Minh, naive (spec `datagen-transactions`); `night_ratio` dùng giờ đó, không đổi
  múi giờ.
- `txn_legs` (view của Phase 5a) là nguồn leg duy nhất; account `EXT-*` không có leg nhưng là `counterparty_id`.
- Feature đồ thị đọc từ bảng đã ghi về hệ thống gốc (`nx_` / `gds_`), không bao giờ gọi Neo4j.
- `reason`, thông điệp lỗi, output CLI bằng tiếng Anh như mọi module trước; tiếng Việt chỉ trên UI.
- `run_cases` vẫn là bước người dùng tự chạy sau `aml anomaly run`; spec này không tự dựng lại case.
- Thời gian dựng feature của code thật trên `small` dưới 60 giây là mục tiêu, **không phải AC** (nguyên mẫu vòng lặp đơn giản
  mất khoảng 70 giây).
- Test [oracle] AC11 xoá các dòng nó đã ghi (theo id trả về; dòng audit vẫn còn), vì một lần chạy bất thường còn sót trên Oracle dùng chung sẽ thêm item ANOMALY vào case và cột bất thường vào mô hình của các test Oracle khác.

## Câu hỏi mở
- [x] Q1. Đơn vị mẫu là gì? **(cần người dùng quyết)** — đề xuất mặc định: **(cif, tháng lịch)**, mẫu chỉ khi cif có giao dịch trong tháng; tháng của `as_of` có thể thiếu ngày. Lý do: brief nói "per-customer" kèm baseline 90 ngày, nên cần cửa sổ hiện tại để so; tháng lịch cho khoá alert ổn định giữa các lần chạy (`ML_ANOMALY|cif|YYYY-MM`), dễ đọc cho investigator, và phủ cả 6 tháng nên bắt được scenario ở đầu kỳ (một điểm duy nhất tại `as_of` sẽ bỏ sót mọi scenario trước tháng 6); cif khớp nguồn feature đồ thị theo account và không phụ thuộc kết quả ER. Phương án thay thế: (a) một mẫu mỗi cif tại `as_of` (cửa sổ 30 ngày gần nhất) — đơn giản, ít alert, nhưng chỉ thấy tháng cuối; (b) cửa sổ trượt 30 ngày neo vào `as_of` — khoá đổi khi `as_of` đổi; (c) theo golden customer — gộp người trùng trước khi chấm, nhưng mẫu đổi khi ER chạy lại. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q2. Ngưỡng alert? **(cần người dùng quyết)** — đề xuất mặc định: **top `alert_top_fraction` = 0,005 số mẫu** (`small`: 138 alert, ngưỡng điểm 0,6526 theo nguyên mẫu; RULE + NETWORK hiện có 267 alert). Lý do: điểm Isolation Forest không có nghĩa tuyệt đối ổn định giữa các tập dữ liệu, còn tỉ lệ cố định cho khối lượng công việc biết trước; theo nguyên mẫu 99 / 138 alert trùng tháng với scenario đáng ngờ và 38 với `benign_merchant`. Phương án thay thế: (a) ngưỡng điểm tuyệt đối (ví dụ `>= 0,65`) — có thể 0 alert hoặc rất nhiều; (b) top-N cố định; (c) 0,01 (276 alert, bắt thêm account `rapid_movement` nhưng cờ cả `benign_payroll`). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q3. Alert ANOMALY đi vào gộp case như nguồn thứ tư, kể cả **mở case mới và dời mốc cửa sổ** (đổi `case_id`) của khách hàng đã có alert? **(cần người dùng quyết)** — đề xuất mặc định: **có, như mọi nguồn** (`event_ts` = giao dịch đầu tiên của cif trong tháng). Lý do: brief yêu cầu "an extra alert source"; gộp case đã là hàm tất định của mọi item, và 7a đã xử lý case biến mất (`_selected_groups` đếm `gone`). Nguyên mẫu `small`: 95 / 138 cif được cờ đã có alert khác, nên một phần case sẽ đổi mốc khi bật nguồn này. Phương án thay thế: (a) alert ANOMALY chỉ gắn vào case đã có, không bao giờ mở case hay dời mốc (cần sửa `assign_cases`); (b) không tạo alert, chỉ là feature xếp hạng. — Trả lời: theo đề xuất mặc định (người dùng chọn trực tiếp, 2026-10-14).
- [x] Q4. Đo "bắt được mà luật bỏ sót" thế nào? — đề xuất mặc định: **cả hai mức scenario và account, như `network_coverage`**: luật = RULE + NETWORK hiện hành, không xét thời gian; mô hình = mẫu bị cờ ở tháng giao với khoảng thời gian của scenario; báo cáo thêm số scenario lành tính bị cờ và phân loại từng alert. Lý do: khớp thước đo đã có của 5c; không cho mô hình "ăn may" nhờ cờ cùng khách ở tháng khác; nói thẳng con số trên `small` là 0 ở mức scenario (luật đã phủ 60 / 60). Phương án thay thế: (a) chỉ mức scenario; (b) luật cũng phải trùng thời gian (con số mới sẽ lớn hơn nhưng so sánh hai bên công bằng hơn); (c) tính cả SCREENING là "luật". — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q5. Bộ feature có đúng ý brief không? — đề xuất mặc định: **14 feature ở mục Thiết kế**: brief (velocity = `txns_per_day` + `max_txns_day`, `cash_ratio`, `counterparties`, `night_ratio`, độ lệch = `amount_dev` + `txn_dev`, 4 cột đồ thị) cộng ba cột ngoài danh sách brief: `amount_log`, `pass_through`, `new_counterparty_ratio`; đêm = 22h–6h. Lý do: tiền chảy qua và đối tác mới là dấu hiệu của rapid movement / mule mà brief nhắm tới; cùng 4 cột đồ thị mà 7c đã dùng. Phương án thay thế: chỉ đúng danh sách brief (bỏ 3 cột thêm); thêm `cycle_alerts` / `is_hub` (chỉ có ở NetworkX, nên GDS sẽ thiếu cột). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q6. Khi lịch sử trước tháng ngắn hơn `min_baseline_days` (tháng đầu tiên của dữ liệu)? — đề xuất mặc định: **vẫn chấm mẫu, ba feature độ lệch = 0**, `min_baseline_days` 28. Lý do: không bỏ tháng 1 (scenario được cài đều cả 6 tháng); 0 nghĩa là "không lệch so với chính mình", trung tính. Phương án thay thế: (a) bỏ mẫu của tháng thiếu baseline (mất 1/6 dữ liệu và scenario tháng 1); (b) thêm cột cờ `has_baseline`. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q7. Feature bất thường cho 7c: hai cột và có chặn hệ số âm không? **(cần người dùng quyết)** — đề xuất mặc định: **`anomaly_max_score` và `anomaly_flagged_months`, chặn không âm qua `fit_guarded` của 8d** (cột có hệ số âm bị loại và ghi vào `dropped_features`). Lý do: một mô hình phát hiện "bất thường hơn" mà lại làm case xuống thấp thì không giải thích được cho investigator; cùng cơ chế đã duyệt ở 8d. Rủi ro nói thẳng: `benign_merchant` điểm cao nên trên dữ liệu tổng hợp hệ số có thể âm thật và cột bị loại. Phương án thay thế: không chặn (để mô hình học cả chiều âm); chỉ một cột `anomaly_max_score`. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q8. `feature_version` có bất thường dài quá 20 ký tự trên Oracle (`features/v1+memo/v1+anom/v1` = 27)? — đề xuất mặc định: **DDL `200` bản Oracle nới `case_models.feature_version` lên `VARCHAR2(60 CHAR)`** (DuckDB không ép độ dài, không cần đổi). Lý do: giữ tên đọc được và tên cũ của 7c / 8d không đổi. Phương án thay thế: tên ngắn hơn (ví dụ `f1+m1+a1`) — phải đổi tên đã ghim ở test 8d. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q9. Audit ở mức nào? — đề xuất mặc định: **một dòng `ALERT` cho mỗi mẫu bị cờ (qua `record_run`), một dòng `ANOMALY_RUN_COMPLETED` mỗi lần chạy, không ghi audit cho mẫu không bị cờ**; mọi dòng `anomaly_scores` mang `model_version`. Lý do: brief "model version on every score written to audit_log" được thoả cho mọi điểm đi vào audit; 27 589 dòng audit mỗi lần chạy trên `small` (khoảng 300 000 trên `large`) làm `audit_log` chỉ-thêm phình mà không thêm quyết định nào. Phương án thay thế: một dòng audit `ANOMALY_SCORED` cho mỗi mẫu. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q10. Phiên bản và vòng đời mô hình? — đề xuất mặc định: **mỗi `aml anomaly run` fit mới trên toàn bộ mẫu rồi chấm chính chúng; `model_version = anomaly/v1/{run_id}`**; tái lập bằng `data_hash` + `params` + seed, không lưu file mô hình. Lý do: Isolation Forest không giám sát, rẻ (0,5 giây trên `small`); không có artifact nhị phân nào trong DB (theo cách 7c lưu model dạng văn bản). Phương án thay thế: huấn luyện một lần, lưu artifact (pickle trong cột BLOB), các lần sau chỉ chấm — cần quy tắc khi nào huấn luyện lại. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q11. Bằng chứng của alert ANOMALY? — đề xuất mặc định: **mọi giao dịch của cif trong tháng** (`alert_evidence`), `amount_vnd` = tổng trên giao dịch khác nhau. Lý do: điểm là của cả tháng, không của một giao dịch; dùng được ngay bởi enrichment / chuỗi bằng chứng sau này. Phương án thay thế: chỉ N giao dịch lớn nhất; không có bằng chứng (`txn_count = 0`). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q12. Model 7c được huấn luyện với lần chạy bất thường X, lúc chấm đã có lần chạy Y mới hơn? — đề xuất mặc định: **chấm bằng lần chạy hiện hành Y, ghi cả hai phiên bản vào `details.anomaly_features`, không lỗi**. Lý do: hàng đợi không bao giờ bị chặn (cùng nguyên tắc 8d); người kiểm soát thấy lệch phiên bản trong audit. Phương án thay thế: raise và yêu cầu `aml cases train` lại; hoặc chấm bằng đúng lần chạy X. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q13. Cấu hình đặt ở đâu? — đề xuất mặc định: **section mới `ml: {anomaly: …}`** (`MlConfig`, spec anh em thêm `ml.screening`, …) và **dùng lại `cases.graph_features`** cho nguồn đồ thị. Lý do: một chỗ cho mọi mô hình Phase 7b; feature đồ thị của case và của mô hình bất thường đến từ cùng một nguồn. Phương án thay thế: section phẳng `ml_anomaly:`; khoá `graph_features` riêng của mô hình. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q14. Có lệnh so sánh 7c có / không có feature bất thường (kiểu `aml memo compare`) và có đưa vào `make all` không? — đề xuất mặc định: **không trong 7b-i**; con số so sánh lấy bằng hai lần `aml cases train` (`AML__ML__ANOMALY__FEATURES=off` và `auto`) và CV ghi trong `MODEL_TRAINED`. Lý do: giữ spec dưới 12 AC; chỉ số CV đã được ghi. Phương án thay thế: thêm `aml anomaly compare` dùng lại `compare_feature_sets` của 8d (thêm 1 AC). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q15. Item ANOMALY có ngủ đông / good-guy không? — đề xuất mặc định: **không** (`_HIBERNATING_SOURCES` giữ `RULE`, `NETWORK`). Lý do: khoá alert đổi theo tháng nên mẫu "lặp lại" của 7b-supp không khớp; giữ hành vi đã duyệt. Phương án thay thế: thêm `ANOMALY` vào nguồn ngủ đông với khoá mẫu theo cif. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
- [x] Q16. Hợp đồng card với `specs/ml-governance.md`: `card_facts` trả gì? — đề xuất mặc định: **`dict` thuần ở
  `aml.ml.anomaly.card:card_facts`** (khoá như mục Thiết kế), `AnomalyError` khi chưa có lần chạy; governance bọc thành
  `CardFacts` / `Skipped`. Lý do: governance đặt thứ tự hiện thực 7b-i trước nó, nên kiểu `CardFacts` chưa tồn tại khi code
  7b-i; dict không tạo phụ thuộc vòng. Phương án thay thế: 7b-i tự định nghĩa `CardFacts` tối thiểu và governance dùng lại;
  hoặc đổi thứ tự để governance hiện thực trước. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-14).
