---
id: monitoring-rules
status: approved
approved_by: pthieu
---

# Phase 5a — Transaction monitoring: năm rule SQL (Oracle + DuckDB), bảng `alerts`, đánh giá theo typology, `aml monitor`

## Bối cảnh
Phần đầu của Phase 5 trong PROJECT_BRIEF.md (mục 6, "Rules"); 5b là fund-flow tracing (`specs/fund-flow-trace.md`), 5c là
network detections bằng NetworkX. Spec này hiện thực năm rule giám sát giao dịch — structuring, rapid movement, high
velocity, fan-in/fan-out, dormant account reactivation — mỗi rule là một file `.sql` có **bản Oracle và bản DuckDB**,
tham số lấy từ `config.yaml`. Runner Python chạy các file đó, ghi kết quả vào bảng `alerts` (rule id, rule version,
evidence transaction ids), sinh `reason` đọc được cho từng alert, ghi `audit_log`, và so kết quả với `ground_truth` của
Phase 1 (recall theo typology, số alert rơi vào kịch bản lành tính). Lệnh `aml monitor` thay stub trong
`src/aml/cli.py`. Người dùng: analyst nhận alert kèm lý do và giao dịch bằng chứng; Phase 5c ghi alert mạng lưới vào
cùng bảng; Phase 7 gộp alert thành case theo golden customer. Hệ thống chỉ **sinh alert**: không đóng, không chấm
điểm ưu tiên, không chặn giao dịch.

### Hiện trạng đã kiểm trên dữ liệu Phase 1 (seed 42)
Đo bằng prototype ngoài repo (script tạm + 5 file SQL cho mỗi dialect), đọc dữ liệu qua `load_parquet` vào DuckDB;
TINY = fixture `tiny_parquet`, `small` = `data/parquet` hiện có (5000 customers, 306 000 dòng `transactions`).
- **Ground truth** (`ground_truth`, `entity_type='account'`): TINY có 2 structuring, 2 rapid_movement, 1 mule_ring
  (1 collector + 28 member + 4 source + 3 destination), 2 round_tripping, 1 benign_payroll (1 employer + 20
  employee), 1 benign_merchant (1 merchant + 34 payer). `small`: 20 / 20 / 5 / 15 / 5 / 5.
- **Tài khoản thuộc kịch bản không có giao dịch nền**: `build_background` loại mọi tài khoản của khách hàng có tài
  khoản trong kịch bản; đã đếm — 0 giao dịch ngoài evidence trên các tài khoản này (TINY và `small`). Hệ quả: rule
  dễ tách kịch bản khỏi nền hơn thực tế, và trước kịch bản các tài khoản này "im lặng" (xem rule dormant).
- **Không typology nào được cài cho high velocity và dormant reactivation** (`datagen-typologies` ghi rõ ngoài phạm
  vi) → hai rule này không có recall; chỉ đo được alert rơi vào đâu.
- **Nền giao dịch** (`small`, mỗi tài khoản, cửa sổ trượt): tối đa 8 giao dịch / 24 giờ; tối đa 8 người gửi khác nhau
  và 9 người nhận khác nhau / 7 ngày; không có nộp tiền mặt nào trong dải [360 triệu, 400 triệu) (generator chặn).
- **Benign payroll là look-alike của cả high velocity lẫn fan-out**: employer trả 20–29 người trong 3 giờ ngày 5
  mỗi tháng — nhiều hơn mọi tài khoản nghi ngờ (source của mule ring gửi tới 11–24 người, collector nhận từ 14–31
  người). Benign merchant thì không: tối đa 8 người trả khác nhau / 7 ngày, mỗi khoản ≤ 5 triệu nên tổng không quá
  40 triệu (con số 40 triệu là suy ra, không đo).
- **Đo ba biến thể cho rule đếm (ngưỡng 8)** — (a) đếm thô; (b) bỏ đối tác đã quen ≥ 14 ngày; (c) như (b) cộng 14
  ngày khởi động:

  | | HIGH_VELOCITY TINY | HIGH_VELOCITY `small` | FAN_OUT TINY | FAN_OUT `small` |
  |---|---|---|---|---|
  | (a) | 12 alert, 6 payroll | 47 alert, 30 payroll, 2 nền | 10 alert, 6 payroll | 50 alert, 30 payroll |
  | (b) | 7 alert, 1 payroll | 20 alert, 5 payroll | 5 alert, 1 payroll | 25 alert, 5 payroll |
  | (c) — đề xuất | 6 alert, 0 payroll | 15 alert, 0 payroll | 4 alert, 0 payroll | 20 alert, 0 payroll |

- **Kết quả của thiết kế đề xuất** (tham số mặc định bên dưới):

  | rule | TINY: alert / evidence | `small`: alert | `small`: alert rơi vào |
  |---|---|---|---|
  | `STRUCTURING` | 2 / 14 | 20 | 20 subject structuring (20/20 kịch bản) |
  | `RAPID_MOVEMENT` | 5 / 27 | 45 | 20 subject rapid (20/20), 5 collector mule, 19 hop round-trip, 1 nền |
  | `HIGH_VELOCITY` | 6 / 109 | 15 | 5 collector + 10 source của mule ring |
  | `FAN_IN` | 1 / 31 | 5 | 5 collector (5/5 mule ring) |
  | `FAN_OUT` | 4 / 87 | 20 | 20 source (5/5 mule ring) |
  | `DORMANT_REACTIVATION` | 13 / 55 | 137 | 136 tài khoản kịch bản nghi ngờ (mọi vai), 1 nền |
  | tổng | 31 / 323 (144 giao dịch khác nhau) | 242 / 1196 | 0 alert trên benign payroll / merchant |

  `small`: 12/15 kịch bản round_tripping bị `RAPID_MOVEMENT` bắt "tình cờ" (hop chuyển tiếp ≥ 90% trong 24 giờ;
  13/15 nếu tính cả `DORMANT_REACTIVATION`);
  91 member của mule ring chỉ dính 9 alert `DORMANT_REACTIVATION` — hai typology này là việc của 5c. Cả sáu rule
  chạy hết 0,6 giây trên `small` (DuckDB).
- **Giao dịch trùng (defect DQ)** không đổi kết quả: chạy trên `transactions` gốc và trên bản đã khử trùng cho cùng
  tập alert (TINY 31, `small` 242).
- **Bản Oracle**: Oracle 23.26 đang chạy và đang nạp TINY. Năm file bản Oracle (chỉ `SELECT`, view `txn_legs` viết
  thành CTE) cho đúng 31 alert, 323 dòng evidence, `reason` trùng khít bản DuckDB; chạy 0,4 giây. **Chưa kiểm**: DDL
  và ghi kết quả xuống Oracle. Khác biệt cú pháp duy nhất giữa hai bản: `INTERVAL n DAY` ↔ `NUMTODSINTERVAL(n, 'DAY')`,
  `DATE_SUB('day', a, b)` ↔ `EXTRACT(DAY FROM (b - a))`, dấu kết thúc `;` ↔ `/` → không file nào đặt được ở `sql/common`.
- `SCHEMA_SCRIPTS` đã dùng `000`–`100`. 5a dùng **`110`**, 5b `120`, 5c `130`.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class MonitoringConfig(BaseModel):
    known_counterparty_days: (
        int  # HIGH_VELOCITY / FAN_*: bỏ đối tác đã quen; cũng là số ngày khởi động
    )
    structuring: StructuringRuleConfig  # window_days, min_deposits
    rapid_movement: RapidMovementRuleConfig  # window_hours, min_inflow_vnd, min_pass_through_pct
    high_velocity: HighVelocityRuleConfig  # window_hours, min_txns, min_total_vnd
    fan_in_out: FanRuleConfig  # window_days, min_counterparties, min_total_vnd
    dormant_reactivation: DormantRuleConfig  # dormant_days, window_hours, min_amount_vnd


# src/aml/monitoring/rules.py
@dataclass(frozen=True)
class MonitoringRule:
    rule_id: str
    rule_version: str  # "v1"
    sql_file: str  # vd "monitoring/structuring.sql"
    target_typology: str | None  # typology của ground_truth mà rule nhắm tới, nếu có
    description: str


RULES: tuple[MonitoringRule, ...]  # 6 rule, đúng thứ tự bảng thiết kế


def rule_params(rule_id: str, settings: Settings) -> dict[str, int | float | str]: ...


# src/aml/monitoring/detect.py
@dataclass(frozen=True)
class Detection:
    rule_id: str
    rule_version: str
    account_id: str
    window_start: datetime  # giao dịch bằng chứng đầu tiên
    window_end: datetime  # giao dịch bằng chứng cuối cùng
    txn_ids: tuple[str, ...]  # tăng dần, không trùng
    amount_vnd: int  # tổng amount_vnd của các giao dịch bằng chứng
    metrics: dict[str, int]  # các cột số liệu của file SQL
    reason: str
    alert_key: str  # "<rule_id>|<account_id>|<window_start dạng YYYY-MM-DDTHH:MM:SS>"


def detect(
    db: Database, settings: Settings, *, as_of: date | None = None
) -> tuple[Detection, ...]: ...


# không ghi gì; thứ tự: theo RULES, rồi account_id, rồi window_start


# src/aml/monitoring/recording.py  (5c dùng lại để ghi alert mạng lưới)
@dataclass(frozen=True)
class RuleRun:
    rule_id: str
    rule_version: str
    params: dict[str, int | float | str]


@dataclass(frozen=True)
class AlertRecord:
    rule_id: str
    rule_version: str
    subject_type: str  # "ACCOUNT" | "ACCOUNT_GROUP"
    subject_id: str
    accounts: tuple[tuple[str, str], ...]  # (account_id, role)
    window_start: datetime
    window_end: datetime
    txn_ids: tuple[str, ...]
    amount_vnd: int
    reason: str
    details: dict[str, object]
    alert_key: str


def record_run(
    db: Database,
    *,
    as_of: date,
    source: str,
    rules: Sequence[RuleRun],
    alerts: Sequence[AlertRecord],
) -> int: ...  # cấp run_id + alert_id, ghi 4 bảng, audit; trả run_id


# src/aml/monitoring/runner.py
class MonitoringError(RuntimeError): ...


@dataclass(frozen=True)
class MonitoringRun:
    run_id: int
    as_of: date
    alerts: int
    evidence: int  # số dòng alert_evidence của lần chạy
    by_rule: dict[str, int]  # rule_id -> số alert (đủ 6 khoá, kể cả 0)


def run_monitoring(
    db: Database, settings: Settings, *, as_of: date | None = None
) -> MonitoringRun: ...


# src/aml/monitoring/evaluate.py
def evaluate_rules(db: Database) -> pd.DataFrame: ...
# cột: rule_id, target_typology, alerts, target_hits, other_suspicious, benign, unlabelled,
#      precision, precision_suspicious, scenarios, detected, recall; 6 dòng theo thứ tự RULES
def typology_coverage(db: Database) -> pd.DataFrame: ...


# cột: typology, is_suspicious, scenarios, flagged, rate, rules; 6 dòng theo thứ tự: structuring,
#      rapid_movement, mule_ring, round_tripping, benign_payroll, benign_merchant
```
- `config.yaml`, mục mới `monitoring` (`thresholds.large_cash_vnd` và `thresholds.structuring_band_pct` dùng lại):
  ```yaml
  monitoring:
    known_counterparty_days: 14
    structuring: {window_days: 14, min_deposits: 3}
    rapid_movement: {window_hours: 24, min_inflow_vnd: 200000000, min_pass_through_pct: 0.90}
    high_velocity: {window_hours: 24, min_txns: 8, min_total_vnd: 100000000}
    fan_in_out: {window_days: 7, min_counterparties: 8, min_total_vnd: 100000000}
    dormant_reactivation: {dormant_days: 90, window_hours: 24, min_amount_vnd: 100000000}
  ```
- DDL `sql/duckdb/ddl/110_monitoring.sql` và `sql/oracle/ddl/110_monitoring.sql`, thêm vào `SCHEMA_SCRIPTS` của cả
  hai backend ngay sau `ddl/100_entity_resolution.sql` (trước các script `050_*`).
- File rule: `sql/duckdb/monitoring/` và `sql/oracle/monitoring/`, mỗi thư mục 5 file: `structuring.sql`,
  `rapid_movement.sql`, `high_velocity.sql`, `fan_in_out.sql`, `dormant_reactivation.sql`.
- CLI: `aml monitor [--as-of YYYY-MM-DD] [--eval-out PATH]` thay stub "arrives in Phase 5".

### Thiết kế (xác nhận ở Câu hỏi mở)
- **View `txn_legs`** (DDL 110): mỗi giao dịch cho một dòng ứng với mỗi phía là tài khoản có trong `accounts` —
  `(account_id, cif, open_date, txn_id, txn_ts, direction, amount_vnd, counterparty_id, channel, branch_id)`;
  `direction` = `IN` (tài khoản là `to_account_id`) hoặc `OUT`; `counterparty_id` = phía bên kia (null với nộp/rút
  tiền mặt và chi thẻ). Tài khoản `EXT-*` không có trong `accounts` nên không bao giờ là chủ thể.
- **Hợp đồng của file rule**: đúng một câu lệnh bắt đầu bằng `WITH`, trả **một dòng cho mỗi cặp (alert, giao dịch
  bằng chứng)** với 5 cột cố định `account_id, window_start, window_end, txn_id, amount_vnd` và các cột số liệu
  nguyên (giống nhau trên mọi dòng của một alert). Placeholder: `{cutoff}` → literal `TIMESTAMP 'YYYY-MM-DD 00:00:00'`
  của ngày `as_of + 1` (rule chỉ thấy `txn_ts < cutoff`), và các khoá của `rule_params` — tất cả định dạng từ giá
  trị đã ép kiểu (`int`, `float`, hằng `IN`/`OUT`), không nhận chuỗi tự do. Không file nào chứa ngưỡng viết cứng.
- **Cửa sổ trượt và gộp đợt** (bốn rule đầu): mỗi giao dịch đủ điều kiện là một *mốc*; mốc "trúng" khi cửa sổ
  `[ts mốc, ts mốc + W)` thoả ngưỡng của rule. Các mốc trúng liên tiếp của một tài khoản cách nhau không quá W được
  gộp thành **một đợt = một alert**; bằng chứng = mọi giao dịch đủ điều kiện của tài khoản trong
  `[mốc trúng đầu, mốc trúng cuối + W)`; `window_start` / `window_end` = giao dịch bằng chứng đầu / cuối.
- **Sáu rule** (`rule_version` đều là `v1`; "đủ điều kiện" = dòng `txn_legs` được rule xét):

  | rule_id | file | đủ điều kiện | mốc trúng khi (trong cửa sổ W) | số liệu | target |
  |---|---|---|---|---|---|
  | `STRUCTURING` | `structuring.sql` | `IN`, `channel = 'CASH'`, `band_low_vnd <= amount_vnd < large_cash_vnd` | W = `window_days`: số lần nộp ≥ `min_deposits` | `deposits`, `total_vnd`, `branches` | `structuring` |
  | `RAPID_MOVEMENT` | `rapid_movement.sql` | mọi dòng (cả tiền mặt, thẻ) | mốc là dòng `IN`; W = `window_hours`: tổng `IN` ≥ `min_inflow_vnd` và tổng `OUT` sau mốc ≥ `min_pass_through_pct` × tổng `IN` | `in_vnd`, `out_vnd` | `rapid_movement` |
  | `HIGH_VELOCITY` | `high_velocity.sql` | mọi dòng trừ dòng có đối tác đã quen | W = `window_hours`: số giao dịch ≥ `min_txns` và tổng ≥ `min_total_vnd`; mốc không nằm trong giai đoạn khởi động | `txns`, `total_vnd` | — |
  | `FAN_IN` | `fan_in_out.sql` (`{direction}` = `IN`) | `IN`, có đối tác, đối tác chưa quen | W = `window_days`: số đối tác khác nhau ≥ `min_counterparties` và tổng ≥ `min_total_vnd`; ngoài giai đoạn khởi động | `counterparties`, `txns`, `total_vnd` | `mule_ring` |
  | `FAN_OUT` | `fan_in_out.sql` (`{direction}` = `OUT`) | như trên với `OUT` | như trên | như trên | `mule_ring` |
  | `DORMANT_REACTIVATION` | `dormant_reactivation.sql` | mọi dòng | giao dịch "đánh thức": `txn_ts >= quiet_since + dormant_days`; alert khi tổng mọi giao dịch của tài khoản trong `[ts đánh thức, + window_hours)` ≥ `min_amount_vnd` | `quiet_days`, `txns`, `total_vnd` | — |

  - `band_low_vnd` = `ceil(large_cash_vnd × (1 − structuring_band_pct))` (360 000 000 với mặc định), tính trong Python.
  - *Đối tác đã quen*: tài khoản đã có giao dịch (chiều nào cũng được) với cùng `counterparty_id` tại thời điểm
    `<= txn_ts − known_counterparty_days` ngày. *Giai đoạn khởi động*: mốc có `ts < MIN(txn_ts của transactions) +
    known_counterparty_days` ngày không được xét (chưa đủ lịch sử để biết đối tác nào mới).
  - `quiet_since` = lớn nhất của (giao dịch liền trước của tài khoản; nếu chưa có thì `MIN(txn_ts)` của cả bảng
    `transactions`) và `open_date`; `quiet_days` = số ngày trọn từ `quiet_since` tới giao dịch đánh thức.
- **`reason`** (tiếng Anh, chỉ gồm số liệu và mốc thời gian `YYYY-MM-DD HH:MM:SS`; không chép memo, tên hay dữ liệu
  tự do nào):
  - `STRUCTURING`: `{deposits} cash deposits of {band_low_vnd:,} to {large_cash_vnd - 1:,} VND (just under the {large_cash_vnd:,} VND reporting threshold) totalling {total_vnd:,} VND at {branches} branch(es) between {start} and {end}`
  - `RAPID_MOVEMENT`: `received {in_vnd:,} VND and sent out {out_vnd:,} VND ({out_vnd / in_vnd:.0%}) between {start} and {end}`
  - `HIGH_VELOCITY`: `{txns} transactions totalling {total_vnd:,} VND between {start} and {end} (at least {min_txns} within {window_hours} hours; counterparties known for {known_counterparty_days}+ days excluded)`
  - `FAN_IN`: `received {total_vnd:,} VND from {counterparties} new senders in {txns} transactions between {start} and {end} (at least {min_counterparties} within {window_days} days)`
  - `FAN_OUT`: `sent {total_vnd:,} VND to {counterparties} new receivers in {txns} transactions between {start} and {end} (at least {min_counterparties} within {window_days} days)`
  - `DORMANT_REACTIVATION`: `no activity for {quiet_days} days, then {txns} transaction(s) totalling {total_vnd:,} VND between {start} and {end} (window {window_hours} hours)`
- **Bảng** (cùng tên cột trên hai backend; không bao giờ UPDATE/DELETE; không lưu tên, memo):
  - `monitoring_runs(run_id, rule_id, run_ts, as_of, source, rule_version, params, alerts, evidence)`, PK
    `(run_id, rule_id)`; `run_ts` UTC; `params` JSON = đúng dict đã thay vào file SQL; `run_id` =
    `1 + max(MAX(run_id) của monitoring_runs, MAX(run_id) của alerts)`.
  - `alerts(alert_id PK, run_id, alert_key, source, rule_id, rule_version, subject_type, subject_id, window_start,
    window_end, txn_count, amount_vnd, reason, details)`, duy nhất `(run_id, alert_key)`; `source` = `RULE` (5a) hoặc
    `NETWORK` (5c); `subject_type` = `ACCOUNT` (5a: `subject_id` = `account_id`) hoặc `ACCOUNT_GROUP` (5c);
    `details` JSON (5a: `metrics`); `alert_id` = số nguyên tăng liên tục toàn bảng, cấp theo thứ tự của `alerts`
    truyền vào.
  - `alert_accounts(alert_id, account_id, cif, role)`, PK `(alert_id, account_id)`: tài khoản liên quan của alert; 5a
    ghi đúng 1 dòng `role = 'SUBJECT'`; `cif` tra từ `accounts` (cầu nối sang `customer_golden` cho Phase 7).
  - `alert_evidence(alert_id, txn_id)`, PK `(alert_id, txn_id)`: evidence transaction ids.
  - View `alerts_current` = các dòng `alerts` có `run_id` bằng `MAX(run_id)` trong `monitoring_runs` **của cùng
    `rule_id`** (mỗi rule lấy lần chạy mới nhất của chính nó, nên 5a và 5c chạy độc lập).
  - Thứ tự ghi: `alerts` → `alert_accounts` → `alert_evidence` → `monitoring_runs` (ghi cuối để view chỉ chuyển sang
    lần chạy mới khi dữ liệu đã đủ) → audit.
  - **Cam kết của đường ghi cho 5c** (`specs/network-detections.md`, Q16): `record_run` nhận `alerts` rỗng (vẫn ghi
    `monitoring_runs` + audit tổng kết) và alert có `txn_ids` rỗng (`txn_count = 0`, không dòng `alert_evidence`);
    độ rộng cột tối thiểu `subject_id` 200, `alert_key` 300, `reason` 1000, `role` 20 ký tự; `details` là JSON lồng
    nhau không giới hạn 4000 byte trên Oracle (kiểu `JSON`/`CLOB`, không phải `VARCHAR2`); `window_start` /
    `window_end` luôn khác null (alert không có evidence do bên gọi tự đặt mốc).
- **Mỗi lần `run_monitoring` là chạy lại toàn bộ** (như `run_er`): mọi detection được ghi dưới `run_id` mới với
  `alert_id` mới; `alert_key` là danh tính ổn định của alert giữa các lần chạy.
- **Audit** (`module='monitoring'`): mỗi alert một sự kiện `entity_type='alert'`, `entity_id=str(alert_id)`,
  `decision='ALERT'`, `reason` = `reason` của alert, `version='<rule_id>/<rule_version>'`, `details = {run_id,
  alert_key, rule_id, subject_id, txn_count, amount_vnd}`; mỗi lần chạy một sự kiện `entity_type='monitoring_run'`,
  `entity_id=str(run_id)`, `decision='MONITORING_RUN_COMPLETED'`, `details = {as_of, source, alerts, evidence, by_rule}`.
- **Đánh giá** (đọc `alerts_current` với `source = 'RULE'` và `ground_truth`): một alert thuộc về kịch bản có tài khoản
  chủ thể nằm trong `ground_truth` (`entity_type='account'`, vai nào cũng tính; mỗi tài khoản thuộc tối đa một kịch
  bản). `target_hits` = alert trên kịch bản thuộc `target_typology`; `other_suspicious` = alert trên kịch bản
  `is_suspicious` khác; `benign` = alert trên kịch bản lành tính; `unlabelled` = còn lại. `precision` =
  `target_hits / alerts`, `precision_suspicious` = `(target_hits + other_suspicious) / alerts`, `recall` =
  `detected / scenarios` (số kịch bản của target có ít nhất 1 alert của rule); làm tròn 4; `None` khi mẫu số bằng 0,
  và `target_hits`, `precision`, `scenarios`, `detected`, `recall` là `None` khi rule không có target.
  `typology_coverage`: `flagged` = số kịch bản có ít nhất 1 alert của bất kỳ rule nào, `rate = flagged / scenarios`,
  `rules` = các `rule_id` (sắp theo chữ cái, nối bằng dấu phẩy).

## Tiêu chí nghiệm thu
<!-- as_of mặc định = date(2026, 6, 30); cấu hình mặc định như mục Interface; DuckDB 1.5.x.
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` (300 customers, 5100 dòng transactions, seed 42).
MINI = DuckDB rỗng sau apply_schema + accounts A1..A5 (cif C1..C5, account_type CURRENT, open_date 2025-01-01, trừ khi
ghi khác) + transactions của từng bộ dưới đây (cột không nêu để null; tài khoản EXT-* không có trong accounts; M = triệu).
MINI-STR (nộp tiền mặt = from null, to <tài khoản>, channel CASH, kèm branch_id):
  A1: S01 2026-03-01 09:00:00 360M BR001; S02 2026-03-05 10:00:00 399 999 000 BR002; S03 2026-03-15 08:59:59 380M BR001
  A2: S04 2026-03-01 09:00:00, S05 2026-03-02 09:00:00, S06 2026-03-15 09:00:00 — mỗi lần 370M BR003
  A3: S07 2026-03-01 09:00:00 390M, S08 2026-03-02 09:00:00 390M, S09 2026-03-03 09:00:00 400M, S10 2026-03-04 09:00:00 359 999 000 — BR004
  A4: S11 2026-03-01 09:00:00 390M và S12 2026-03-02 09:00:00 390M nộp tiền mặt BR005; S13 2026-03-03 09:00:00 RÚT tiền mặt
      (from A4, to null) 390M; S14 2026-03-04 09:00:00 EXT-01 -> A4 390M INTERNAL_TRANSFER
  A5: S15, S16, S17 lúc 09:00:00 các ngày 2026-01-05, 01-06, 01-07 (365M, BR006); S18 2026-01-21 09:00:01, S19 2026-01-22
      09:00:00, S20 2026-01-23 09:00:00 (365M, BR007)
MINI-RAP:
  A1: R01 2026-03-01 10:00:00 nộp tiền mặt 100M; R02 2026-03-01 11:00:00 EXT-01 -> A1 200M INTERBANK_TRANSFER;
      R03 2026-03-01 15:00:00 A1 -> EXT-02 150M EBANKING; R04 2026-03-02 09:59:59 A1 -> EXT-03 130M EBANKING
  A2: R05 2026-03-01 10:00:00 EXT-01 -> A2 300M; R06 2026-03-01 12:00:00 A2 -> EXT-02 269 999 000
  A3: R07 2026-03-01 10:00:00 EXT-01 -> A3 300M; R08 2026-03-02 10:00:00 A3 -> EXT-02 280M
  A4: R09 2026-03-01 10:00:00 EXT-01 -> A4 199 999 000; R10 2026-03-01 12:00:00 A4 -> EXT-02 199M
  A5: R11 2026-03-01 09:00:00 A5 -> EXT-02 280M; R12 2026-03-01 10:00:00 EXT-01 -> A5 300M
  (chuyển đến: INTERBANK_TRANSFER; chuyển đi: EBANKING)
MINI-VEL (mỗi "loạt" = n giao dịch cách nhau đúng 1 giờ, bắt đầu 09:00:00, mỗi giao dịch một đối tác EXT khác nhau,
chiều đến / đi tuỳ ý trừ khi ghi rõ):
  V00 2026-01-01 00:00:00 EXT-99 -> A5 1M (giao dịch sớm nhất của bảng)
  A1: VA01–VA08 ngày 2026-03-01, mỗi cái 15M: VA01 nộp tiền mặt, VA02 chi thẻ (from A1, to null, CARD), VA03–VA08 chuyển
      khoản xen kẽ đến / đi
  A2: VB01–VB07 ngày 2026-03-01, 7 giao dịch, mỗi cái 20M
  A3: VC01–VC08 ngày 2026-03-01, mỗi cái 12M
  A4: VD01–VD08 ngày 2026-01-14, mỗi cái 15M
  A5: VE01–VE08 ngày 2026-02-01, A5 -> EXT-P0..EXT-P7, mỗi cái 15M; VF01–VF08 ngày 2026-03-01, lại A5 -> EXT-P0..EXT-P7 15M
MINI-FAN:
  F00 2026-01-01 00:00:00 EXT-99 -> A5 1M
  A1: FA01–FA07 lúc 09:00:00 các ngày 2026-03-01 tới 03-07 và FA08 lúc 2026-03-08 08:59:59, từ EXT-A0..EXT-A7, mỗi cái 15M
  A2: FB01–FB08 loạt ngày 2026-03-01, từ EXT-B0..EXT-B6 (FB08 lại từ EXT-B6), mỗi cái 20M
  A3: FC01–FC08 loạt ngày 2026-03-10, A3 -> EXT-C0..EXT-C7, mỗi cái 20M
  A4: FD01–FD08 loạt ngày 2026-03-10, A4 -> EXT-D0..EXT-D7, mỗi cái 12M
  A5: FE01–FE08 loạt ngày 2026-01-05, FF01–FF08 loạt ngày 2026-02-05, FG01–FG08 loạt ngày 2026-03-05 — cả ba loạt đều
      A5 -> EXT-E0..EXT-E7, mỗi cái 20M
  FAN+ = MINI-FAN thêm FH01–FH08: 8 giao dịch cách nhau 1 giờ từ 2026-03-05 09:30:00, A5 -> EXT-N0..EXT-N7, mỗi cái 20M
MINI-DOR (A4 có open_date 2026-02-15):
  D00 2026-01-01 00:00:00 EXT-99 -> A5 1M
  A1: D01 2026-01-10 10:00:00 đến 5M; D02 2026-04-10 10:00:00 đến 60M; D03 2026-04-11 09:59:59 đi 50M; D04 2026-04-11 10:00:00 đi 500M
  A2: D05 2026-01-10 10:00:00 đến 5M; D06 2026-04-10 09:59:59 đến 200M
  A3: D07 2026-04-01 00:00:00 đến 150M
  A4: D08 2026-05-01 09:00:00 đến 500M
  A5: D09 2026-05-01 09:00:00 đến 99 999 000
"Ghi đè X=v" = `load_settings(environ={"DB_BACKEND": "duckdb", "AML__...": "v"})`.
Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given `config.yaml`, hằng `RULES`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, duyệt `RULES` và gọi `apply_schema(duck)` hai lần, Then `settings.monitoring` có `known_counterparty_days == 14`, `structuring` = (`window_days` 14, `min_deposits` 3), `rapid_movement` = (`window_hours` 24, `min_inflow_vnd` 200000000, `min_pass_through_pct` 0.9), `high_velocity` = (`window_hours` 24, `min_txns` 8, `min_total_vnd` 100000000), `fan_in_out` = (`window_days` 7, `min_counterparties` 8, `min_total_vnd` 100000000), `dormant_reactivation` = (`dormant_days` 90, `window_hours` 24, `min_amount_vnd` 100000000); `load_settings(environ={"AML__MONITORING__RAPID_MOVEMENT__MIN_PASS_THROUGH_PCT": "1.5"})` raise `pydantic.ValidationError` chứa `min_pass_through_pct must be in (0, 1]` và `load_settings(environ={"AML__MONITORING__KNOWN_COUNTERPARTY_DAYS": "0"})` raise `pydantic.ValidationError` chứa `known_counterparty_days must be >= 1`; `RULES` có đúng 6 rule theo thứ tự `STRUCTURING`, `RAPID_MOVEMENT`, `HIGH_VELOCITY`, `FAN_IN`, `FAN_OUT`, `DORMANT_REACTIVATION`, tất cả `rule_version == "v1"`, `target_typology` lần lượt là `structuring`, `rapid_movement`, `None`, `mule_ring`, `mule_ring`, `None`, và tập `sql_file` có đúng 5 phần tử (`FAN_IN` và `FAN_OUT` dùng chung `monitoring/fan_in_out.sql`); mỗi `sql_file` resolve qua `sql_file` về `sql/duckdb/monitoring/` và `sql/oracle/monitoring/`, chứa đúng 1 câu lệnh bắt đầu bằng `WITH` (bản Oracle đi qua `split_oracle_script` ra 1 statement), và tập placeholder `{tên}` trong file là tập con của `set(rule_params(rule_id, settings)) | {"cutoff"}`; `rule_params("STRUCTURING", settings) == {"band_low_vnd": 360000000, "large_cash_vnd": 400000000, "min_deposits": 3, "window_days": 14}` và `rule_params("FAN_OUT", settings) == {"direction": "OUT", "known_counterparty_days": 14, "min_counterparties": 8, "min_total_vnd": 100000000, "window_days": 7}`; `ddl/110_monitoring.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]`, đứng sau `ddl/100_entity_resolution.sql` và trước `ddl/050_customers_masked.sql` / `ddl/050_security_objects.sql`; `apply_schema` không raise; và `SELECT COUNT(*)` trên `monitoring_runs`, `alerts`, `alert_accounts`, `alert_evidence`, `alerts_current`, `txn_legs` đều trả 0.
- AC2: Given MINI-STR, When gọi `detect(duck, settings)` và lọc `rule_id == "STRUCTURING"`, Then có đúng 3 detection: (`A1`, `window_start` 2026-03-01 09:00:00, `window_end` 2026-03-15 08:59:59, `txn_ids` = (S01, S02, S03), `amount_vnd` = 1139999000, `metrics` = {deposits: 3, total_vnd: 1139999000, branches: 2}, `reason` bằng đúng `3 cash deposits of 360,000,000 to 399,999,999 VND (just under the 400,000,000 VND reporting threshold) totalling 1,139,999,000 VND at 2 branch(es) between 2026-03-01 09:00:00 and 2026-03-15 08:59:59`, `alert_key` = `STRUCTURING|A1|2026-03-01T09:00:00`), (`A5`, 2026-01-05 09:00:00 tới 2026-01-07 09:00:00, (S15, S16, S17), 1095000000) và (`A5`, 2026-01-21 09:00:01 tới 2026-01-23 09:00:00, (S18, S19, S20), 1095000000); không có detection cho `A2` (S06 cách S04 đúng 14 ngày nên nằm ngoài cửa sổ), `A3` (400M bằng ngưỡng và 359 999 000 dưới dải đều không tính), `A4` (rút tiền mặt và chuyển khoản không tính); When ghi đè `AML__MONITORING__STRUCTURING__MIN_DEPOSITS=2`, Then có 6 detection, trong đó `A2` có `txn_ids` = (S04, S05, S06), `A3` = (S07, S08), `A4` = (S11, S12); When ghi đè `AML__THRESHOLDS__LARGE_CASH_VND=410000000`, Then có đúng 1 detection trên `A3` với `txn_ids` = (S07, S08, S09) và `reason` chứa `369,000,000 to 409,999,999 VND`; và When gọi `detect(duck, settings, as_of=date(2026, 1, 6))` rồi `as_of=date(2026, 1, 7)`, Then lần lượt có 0 và 1 detection `STRUCTURING`.
- AC3: Given MINI-RAP, When gọi `detect(duck, settings)` và lọc `rule_id == "RAPID_MOVEMENT"`, Then có đúng 1 detection: `A1`, `window_start` 2026-03-01 10:00:00, `window_end` 2026-03-02 09:59:59, `txn_ids` = (R01, R02, R03, R04) (tiền mặt nộp vào cũng là dòng tiền vào), `amount_vnd` = 580000000, `metrics` = {in_vnd: 300000000, out_vnd: 280000000}, `reason` bằng đúng `received 300,000,000 VND and sent out 280,000,000 VND (93%) between 2026-03-01 10:00:00 and 2026-03-02 09:59:59`; không có detection cho `A2` (chuyển đi 269 999 000 < 90% của 300M), `A3` (chuyển đi sau đúng 24 giờ), `A4` (tiền vào 199 999 000 < 200M), `A5` (chuyển đi trước khi tiền vào); When ghi đè `AML__MONITORING__RAPID_MOVEMENT__MIN_PASS_THROUGH_PCT=0.89`, Then tập tài khoản có detection là {A1, A2}; When ghi đè `AML__MONITORING__RAPID_MOVEMENT__WINDOW_HOURS=25`, Then là {A1, A3}; và When ghi đè `AML__MONITORING__RAPID_MOVEMENT__MIN_INFLOW_VND=199999000`, Then là {A1, A4}.
- AC4: Given MINI-VEL, When gọi `detect(duck, settings)` và lọc `rule_id == "HIGH_VELOCITY"`, Then có đúng 2 detection: (`A1`, 2026-03-01 09:00:00 tới 2026-03-01 16:00:00, `txn_ids` = VA01–VA08 gồm cả nộp tiền mặt và chi thẻ, `amount_vnd` = 120000000, `metrics` = {txns: 8, total_vnd: 120000000}, `reason` bằng đúng `8 transactions totalling 120,000,000 VND between 2026-03-01 09:00:00 and 2026-03-01 16:00:00 (at least 8 within 24 hours; counterparties known for 14+ days excluded)`) và (`A5`, 2026-02-01 09:00:00 tới 2026-02-01 16:00:00, `txn_ids` = VE01–VE08); không có detection cho `A2` (7 giao dịch), `A3` (tổng 96M < 100M), `A4` (ngày 2026-01-14 nằm trong 14 ngày khởi động tính từ 2026-01-01 00:00:00), và loạt VF của `A5` ngày 2026-03-01 không sinh detection (8 người nhận đã quen từ 28 ngày trước); When ghi đè `AML__MONITORING__HIGH_VELOCITY__MIN_TXNS=7`, Then có 3 detection (thêm `A2` với `amount_vnd` = 140000000); When ghi đè `AML__MONITORING__KNOWN_COUNTERPARTY_DAYS=29`, Then có 3 detection (thêm `A5` với `txn_ids` = VF01–VF08); và When ghi đè `AML__MONITORING__KNOWN_COUNTERPARTY_DAYS=13`, Then có 3 detection trên `A1`, `A4` (VD01–VD08) và `A5` (VE01–VE08).
- AC5: Given MINI-FAN, When gọi `detect(duck, settings)` và lọc `rule_id` thuộc {`FAN_IN`, `FAN_OUT`}, Then có đúng 2 detection: (`FAN_IN`, `A1`, 2026-03-01 09:00:00 tới 2026-03-08 08:59:59, `txn_ids` = FA01–FA08, `amount_vnd` = 120000000, `metrics` = {counterparties: 8, txns: 8, total_vnd: 120000000}, `reason` bằng đúng `received 120,000,000 VND from 8 new senders in 8 transactions between 2026-03-01 09:00:00 and 2026-03-08 08:59:59 (at least 8 within 7 days)`) và (`FAN_OUT`, `A3`, 2026-03-10 09:00:00 tới 2026-03-10 16:00:00, `txn_ids` = FC01–FC08, `amount_vnd` = 160000000, `reason` bằng đúng `sent 160,000,000 VND to 8 new receivers in 8 transactions between 2026-03-10 09:00:00 and 2026-03-10 16:00:00 (at least 8 within 7 days)`); không có detection cho `A2` (8 giao dịch nhưng chỉ 7 người gửi), `A4` (tổng 96M < 100M), `A5` (loạt tháng 1 nằm trong giai đoạn khởi động, loạt tháng 2 và tháng 3 trả cho người nhận đã quen); When ghi đè `AML__MONITORING__FAN_IN_OUT__MIN_COUNTERPARTIES=7`, Then có 3 detection (thêm `FAN_IN` trên `A2` với `metrics.counterparties` = 7, `metrics.txns` = 8); When ghi đè `AML__MONITORING__KNOWN_COUNTERPARTY_DAYS=4`, Then có 3 detection (thêm `FAN_OUT` trên `A5` với `txn_ids` = FE01–FE08); When ghi đè `AML__MONITORING__KNOWN_COUNTERPARTY_DAYS=32`, Then có 3 detection (thêm `FAN_OUT` trên `A5` với `txn_ids` = FF01–FF08); và Given FAN+ với cấu hình mặc định, When gọi `detect`, Then có 3 detection, detection thứ ba là `FAN_OUT` trên `A5` với `window_start` 2026-03-05 09:30:00, `txn_ids` = FH01–FH08 (không chứa giao dịch FG nào), `metrics.counterparties` = 8, `amount_vnd` = 160000000.
- AC6: Given MINI-DOR, When gọi `detect(duck, settings)` và lọc `rule_id == "DORMANT_REACTIVATION"`, Then có đúng 2 detection: (`A1`, `window_start` 2026-04-10 10:00:00, `window_end` 2026-04-11 09:59:59, `txn_ids` = (D02, D03) — D04 cách D02 đúng 24 giờ nên không tính, `amount_vnd` = 110000000, `metrics` = {quiet_days: 90, txns: 2, total_vnd: 110000000}, `reason` bằng đúng `no activity for 90 days, then 2 transaction(s) totalling 110,000,000 VND between 2026-04-10 10:00:00 and 2026-04-11 09:59:59 (window 24 hours)`) và (`A3`, 2026-04-01 00:00:00, `txn_ids` = (D07,), `amount_vnd` = 150000000, `metrics.quiet_days` = 90 — tài khoản chưa từng giao dịch, tính im lặng từ giao dịch sớm nhất của bảng 2026-01-01 00:00:00); không có detection cho `A2` (im lặng 89 ngày 23 giờ 59 phút 59 giây), `A4` (mở ngày 2026-02-15, mới 75 ngày), `A5` (99 999 000 < 100M); When ghi đè `AML__MONITORING__DORMANT_REACTIVATION__DORMANT_DAYS=89`, Then tập tài khoản là {A1, A2, A3} và detection của `A2` có `metrics.quiet_days` = 89; When ghi đè `AML__MONITORING__DORMANT_REACTIVATION__DORMANT_DAYS=75`, Then là {A1, A2, A3, A4} và detection của `A4` có `metrics.quiet_days` = 75; When ghi đè `AML__MONITORING__DORMANT_REACTIVATION__MIN_AMOUNT_VND=99999000`, Then là {A1, A3, A5} và detection của `A5` có `metrics.quiet_days` = 120; và When gọi `detect(duck, settings, as_of=date(2026, 4, 9))`, Then chỉ còn detection của `A3`.
- AC7: Given TINY trong DuckDB, When gọi `run_monitoring(duck, settings)` lần đầu, Then trả `MonitoringRun(run_id=1, as_of=date(2026, 6, 30), alerts=31, evidence=323, by_rule={"STRUCTURING": 2, "RAPID_MOVEMENT": 5, "HIGH_VELOCITY": 6, "FAN_IN": 1, "FAN_OUT": 4, "DORMANT_REACTIVATION": 13})`; `txn_legs` có 6137 dòng; `alerts` có 31 dòng `run_id = 1`, `source = 'RULE'`, `subject_type = 'ACCOUNT'`, `rule_version = 'v1'`, `alert_id` từ 1 tới 31 theo thứ tự (thứ tự `RULES`, `subject_id`, `window_start`), trên 20 `subject_id` khác nhau; dòng `alert_id = 1` có `rule_id = 'STRUCTURING'`, `subject_id = 'A6457424962'`, `alert_key = 'STRUCTURING|A6457424962|2026-02-10T09:52:00'`, `window_start` 2026-02-10 09:52:00, `window_end` 2026-02-15 16:38:00, `txn_count = 8`, `amount_vnd = 3023290000`, `details` = {"deposits": 8, "total_vnd": 3023290000, "branches": 3}, `reason` bằng đúng `8 cash deposits of 360,000,000 to 399,999,999 VND (just under the 400,000,000 VND reporting threshold) totalling 3,023,290,000 VND at 3 branch(es) between 2026-02-10 09:52:00 and 2026-02-15 16:38:00`; dòng `alert_id = 7` có `rule_id = 'RAPID_MOVEMENT'`, `subject_id = 'A9586661327'`, `txn_count = 3`, `reason` bằng đúng `received 1,172,011,000 VND and sent out 1,146,596,000 VND (98%) between 2026-02-22 16:10:24 and 2026-02-23 10:24:53`; dòng `alert_id = 14` có `rule_id = 'FAN_IN'`, `subject_id = 'A4937939209'`, `txn_count = 31`, `reason` bằng đúng `received 2,930,380,000 VND from 31 new senders in 31 transactions between 2026-04-13 09:28:12 and 2026-04-17 23:16:36 (at least 8 within 7 days)`; `alert_accounts` có 31 dòng, tất cả `role = 'SUBJECT'`, dòng của `alert_id = 1` có `account_id = 'A6457424962'`, `cif = 'CIF00000043'`; `alert_evidence` có 323 dòng trên 144 `txn_id` khác nhau, tập `txn_id` của `alert_id = 1` và `alert_id = 2` bằng đúng tập giao dịch `evidence` của `GT-STR-0001` và `GT-STR-0002` trong `ground_truth`, của `alert_id = 4` và `7` bằng đúng `GT-RAP-0001` và `GT-RAP-0002`, và mọi `txn_id` trong `alert_evidence` đều là giao dịch `evidence` của một kịch bản `is_suspicious` (cả 118 giao dịch của `GT-MULE-0001` đều có mặt); `monitoring_runs` có 6 dòng `run_id = 1`, `as_of = 2026-06-30`, `source = 'RULE'`, với (`alerts`, `evidence`) lần lượt (2, 14), (5, 27), (6, 109), (1, 31), (4, 87), (13, 55) và `params` của dòng `STRUCTURING` bằng `rule_params("STRUCTURING", settings)`; `alerts_current` trả đúng 31 dòng đó; và `audit_log` có đúng 32 dòng `module='monitoring'`: 31 dòng `entity_type='alert'`, `decision='ALERT'` (dòng `entity_id='1'` có `version='STRUCTURING/v1'`, `reason` bằng `reason` của alert 1, `details.run_id = 1`, `details.alert_key = 'STRUCTURING|A6457424962|2026-02-10T09:52:00'`) và 1 dòng `entity_type='monitoring_run'`, `entity_id='1'`, `decision='MONITORING_RUN_COMPLETED'` với `details.alerts = 31`, `details.evidence = 323`, `details.by_rule.DORMANT_REACTIVATION = 13`.
- AC8: Given TINY đã chạy `run_monitoring` một lần (AC7), When gọi `run_monitoring(duck, settings)` lần hai, Then trả `run_id = 2` với `alerts`, `evidence`, `by_rule` như lần đầu; `alerts` có 62 dòng (`alert_id` 32 tới 62 thuộc `run_id = 2`), 31 dòng `run_id = 1` không đổi; tập (`alert_key`, `reason`, `txn_count`, `amount_vnd`) và tập (`alert_key`, `txn_id`) của hai lần bằng nhau; `alerts_current` chỉ gồm 31 dòng `run_id = 2`; `audit_log` thêm đúng 32 dòng `module='monitoring'`; When gọi tiếp `run_monitoring(duck, settings, as_of=date(2026, 3, 31))`, Then trả `run_id = 3`, `alerts = 6`, `evidence = 26`, `by_rule` = {STRUCTURING: 2, RAPID_MOVEMENT: 4, HIGH_VELOCITY: 0, FAN_IN: 0, FAN_OUT: 0, DORMANT_REACTIVATION: 0}; `monitoring_runs` có 6 dòng `run_id = 3` (bốn dòng có `alerts = 0`); `alerts_current` còn đúng 6 dòng, `subject_id` của 4 dòng `RAPID_MOVEMENT` là {A1070944972, A1425071026, A4750305205, A9586661327}, và cả 6 `alert_key` đều có trong lần chạy 1; When gọi `record_run(duck, as_of=date(2026, 6, 30), source="NETWORK", rules=[RuleRun("NET_TEST", "v0", {"k": 1})], alerts=[AlertRecord(rule_id="NET_TEST", rule_version="v0", subject_type="ACCOUNT_GROUP", subject_id="GRP-A1070944972", accounts=(("A1070944972", "MEMBER"), ("A1425071026", "MEMBER")), window_start=datetime(2026, 3, 1), window_end=datetime(2026, 3, 2), txn_ids=("T0000000528",), amount_vnd=1, reason="test group", details={"size": 2}, alert_key="NET_TEST|GRP-A1070944972|2026-03-01T00:00:00")])`, Then trả `4`; alert mới có `alert_id = 69`, `source = 'NETWORK'`, 2 dòng `alert_accounts` với `cif` lần lượt `CIF00000070` và `CIF00000169`, 1 dòng `alert_evidence`; `alerts_current` có 7 dòng (6 dòng `RULE` của lần chạy 3 và dòng `NETWORK`); `audit_log` thêm đúng 2 dòng `module='monitoring'` cho lần ghi này; và Given DuckDB chỉ mới `apply_schema` (chưa nạp dữ liệu), When gọi `run_monitoring`, Then raise `MonitoringError` chứa ``run `aml load` first``, `monitoring_runs` và `alerts` vẫn rỗng, `audit_log` không có dòng `monitoring` nào.
- AC9: Given TINY đã chạy `run_monitoring` một lần, When gọi `evaluate_rules(duck)` và `typology_coverage(duck)`, Then `evaluate_rules` trả 6 dòng theo thứ tự `RULES` với (`alerts`, `target_hits`, `other_suspicious`, `benign`, `unlabelled`, `precision`, `precision_suspicious`, `scenarios`, `detected`, `recall`) lần lượt là `STRUCTURING` (2, 2, 0, 0, 0, 1.0, 1.0, 2, 2, 1.0), `RAPID_MOVEMENT` (5, 2, 3, 0, 0, 0.4, 1.0, 2, 2, 1.0), `HIGH_VELOCITY` (6, None, 6, 0, 0, None, 1.0, None, None, None), `FAN_IN` (1, 1, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0), `FAN_OUT` (4, 4, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0), `DORMANT_REACTIVATION` (13, None, 13, 0, 0, None, 1.0, None, None, None); `typology_coverage` trả 6 dòng với (`scenarios`, `flagged`, `rate`) lần lượt `structuring` (2, 2, 1.0), `rapid_movement` (2, 2, 1.0), `mule_ring` (1, 1, 1.0), `round_tripping` (2, 2, 1.0), `benign_payroll` (1, 0, 0.0), `benign_merchant` (1, 0, 0.0), cột `rules` của `round_tripping` là `RAPID_MOVEMENT`, của `mule_ring` là `DORMANT_REACTIVATION,FAN_IN,FAN_OUT,HIGH_VELOCITY,RAPID_MOVEMENT`, của hai dòng benign là chuỗi rỗng; Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), When chạy `aml monitor --eval-out <tmp>/monitoring_eval.csv`, Then exit code 0; stdout có 6 dòng rule, dòng của `STRUCTURING` chứa `alerts=2` và `evidence=14`, dòng của `DORMANT_REACTIVATION` chứa `alerts=13` và `evidence=55`; có dòng tổng kết chứa `run_id=1`, `as_of=2026-06-30`, `alerts=31`, `evidence=323`; có 6 dòng đánh giá, dòng `RAPID_MOVEMENT` chứa `target_hits=2`, `other_suspicious=3`, `benign=0`, `precision=0.40 recall=1.00`, dòng `HIGH_VELOCITY` chứa `precision=n/a recall=n/a`; có 6 dòng phủ typology, dòng `benign_payroll` chứa `scenarios=1 flagged=0`; file `monitoring_eval.csv` có dòng tiêu đề `rule_id,target_typology,alerts,target_hits,other_suspicious,benign,unlabelled,precision,precision_suspicious,scenarios,detected,recall` và 6 dòng dữ liệu; When chạy `aml monitor --as-of 2026-13-01`, Then exit code 2 và `monitoring_runs` không thêm dòng; và Given DuckDB chưa `aml load`, When chạy `aml monitor`, Then exit code 1 và stderr chứa ``run `aml load` first``.
- AC10: [oracle] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, When gọi `run_monitoring` với cùng `as_of = 2026-06-30` trên hai backend rồi `evaluate_rules` trên Oracle, Then `alerts`, `evidence`, `by_rule` của hai `MonitoringRun` bằng nhau (31, 323, {2, 5, 6, 1, 4, 13} theo thứ tự `RULES`); tập (`alert_key`, `reason`, `txn_count`, `amount_vnd`, `window_start`, `window_end`) đọc từ `alerts` và tập (`alert_key`, `txn_id`) đọc từ `alerts` nối `alert_evidence` của lần chạy đó bằng nhau giữa hai backend; trên Oracle `user_tables` có `MONITORING_RUNS`, `ALERTS`, `ALERT_ACCOUNTS`, `ALERT_EVIDENCE`, `user_views` có `TXN_LEGS`, `ALERTS_CURRENT`; `SELECT COUNT(*) FROM txn_legs` trên Oracle trả 6137; `alerts_current` trên Oracle có 31 dòng `source = 'RULE'` thuộc lần chạy đó; số dòng `audit_log` `module='monitoring'` của lần chạy trên Oracle (lọc theo `details.run_id` hoặc `entity_id` của run) là 32; `evaluate_rules` trên Oracle trả đúng 6 dòng như phần đầu AC9; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- Fund-flow tracing (recursive CTE, property graph, Cypher) — 5b; network detections bằng NetworkX (cụm dùng chung thiết bị/điện thoại/địa chỉ, vòng tiền, hub) — 5c; Neo4j — Phase 6. 5a không có rule riêng cho round-tripping và không nhắm tới member của mule ring.
- Gộp alert thành case theo golden customer, enrichment, chấm điểm ưu tiên, good-guy list, hibernation alert lặp lại, disposition của analyst — Phase 7. 5a không đọc `customer_golden`; chỉ lưu `cif` trong `alert_accounts`.
- Hợp nhất screening vào `alerts`: `screening_results` / `screening_current` giữ nguyên (Q11).
- Rule trên cấp khách hàng hoặc golden customer (cộng dồn nhiều tài khoản của một người), loại trừ chuyển khoản giữa các tài khoản của cùng một khách hàng, ngưỡng theo phân khúc / `kyc_risk` / nghề nghiệp, baseline hành vi riêng từng tài khoản (Phase 7b).
- Whitelist tài khoản trả lương / hộ kinh doanh; đọc memo để nhận biết lương (memo là dữ liệu không tin cậy).
- Thêm typology high velocity / dormant vào generator Phase 1 (đổi contract 1b-ii đã duyệt).
- Chạy tăng dần theo ngày, cập nhật alert đang mở khi có giao dịch mới, lịch chạy (`DBMS_SCHEDULER`), chạy song song.
- Bảng danh mục rule trong DB để bật/tắt rule, rule do người dùng tự viết qua UI/CLI, tự tinh chỉnh ngưỡng.
- Quyền Oracle (`ROLE_GRANTS`, `020_grants.sql`) trên các bảng/view mới; purge/retention cho `alerts`; index và đo hiệu năng trên profile `dense` / `large`.
- Ghi số liệu vào README (làm ở bước demo của phase, từ lần chạy thật trên `small`).

## Giả định
- Dữ liệu Phase 1 giữ các tính chất ở mục "Hiện trạng" (seed 42); AC7–AC10 chỉ cam kết cho TINY seed 42. Số liệu `small` trong mục Hiện trạng chỉ để định hướng, không phải cam kết.
- Mọi con số detection trong AC2–AC9 (số alert, evidence, cửa sổ, số liệu, `reason`, kết quả đánh giá) lấy từ prototype chạy thật trên DuckDB. **Suy ra từ thiết kế, chưa đo** (prototype không ghi bảng): `alert_id`, số dòng `audit_log` (32 / 2), nội dung `monitoring_runs`, `alert_accounts`, toàn bộ phần `record_run` của AC8 (`alert_id = 69`, `run_id = 4`), thông điệp `ValidationError` ở AC1, định dạng stdout / CSV ở AC9.
- AC10: mới kiểm phần `SELECT` của 5 file bản Oracle trên TINY đang nạp sẵn (31 alert, 323 evidence, `reason` trùng DuckDB); DDL 110 và việc ghi (`insert_df` vào cột JSON) trên Oracle chưa chạy. Các bộ MINI chưa chạy trên Oracle.
- Tên cột mới (`source`, `role`, `details`, `window_start`, `window_end`) không phải từ khoá dành riêng của Oracle 23ai (`role` và `details` đã dùng ở `ground_truth` / `audit_log`); nếu DDL báo lỗi thì đổi tên cột ở cả hai backend và cập nhật spec.
- `txn_ts` là giờ địa phương naive (quy ước 1b-i); `as_of` mặc định `settings.data.reference_date`, không dùng đồng hồ máy ngoài `run_ts` / `event_ts` (UTC).
- "Giao dịch sớm nhất của bảng" (`MIN(txn_ts)`) đại diện cho ngày bắt đầu quan sát; nếu Phase 2c purge partition cũ thì mốc này dịch theo.
- Sau `aml load` lại dữ liệu khác, `alerts` cũ vẫn còn (append-only); phải chạy lại `aml monitor` để `alerts_current` trỏ sang lần chạy mới. `alert_evidence` / `alert_accounts` không có khoá ngoại tới `transactions` / `accounts`.
- `run_monitoring` và `record_run` không chạy đồng thời từ hai tiến trình (`run_id`, `alert_id` cấp bằng `MAX + 1`); 5c gọi `record_run` chứ không tự `INSERT` vào `alerts`.
- 5b đọc tài khoản bị alert từ `alerts_current` / `alert_accounts` (nếu cần) và không ghi vào các bảng của 5a.
- Lệnh chạy dưới schema owner (`aml_owner`); `evaluate_rules` / `typology_coverage` chỉ có ý nghĩa trên dữ liệu tổng hợp. `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có.
- Test [oracle] nạp lại TINY vào schema `aml_owner` và để lại dòng trong các bảng mới / `audit_log`; AC10 so theo `run_id` của lần chạy trong test, không giả định `run_id = 1`.

## Câu hỏi mở
- [x] Q1. Bộ rule gồm những `rule_id` nào? — đề xuất mặc định: 6 `rule_id` từ 5 file SQL — `STRUCTURING`, `RAPID_MOVEMENT`, `HIGH_VELOCITY`, `FAN_IN`, `FAN_OUT`, `DORMANT_REACTIVATION`; fan-in và fan-out dùng chung `fan_in_out.sql` với tham số `{direction}`. Lý do: brief liệt kê "fan-in/fan-out" là một mục nhưng hai chiều bắt hai vai khác nhau (collector vs. source), tách `rule_id` cho `alert_key` và bảng đánh giá rõ ràng. Phương án thay thế: một `rule_id` `FAN_IN_OUT` với cột `pattern`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q2. Một alert là gì và cửa sổ tính thế nào? — đề xuất mặc định: chủ thể là **tài khoản**; cửa sổ trượt neo tại từng giao dịch đủ điều kiện, các mốc trúng chồng lấn gộp thành một đợt = một alert; `window_start` / `window_end` là giao dịch bằng chứng đầu / cuối. Lý do: tránh một kịch bản sinh hàng chục alert chồng nhau (TINY: 2 kịch bản structuring → đúng 2 alert); viết được bằng self-join + `LAG`, chạy giống nhau trên hai backend. Hạn chế: một nguồn tiền của mule ring có 2 alert `HIGH_VELOCITY` vì có khoảng lặng giữa hai đợt. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q3. Định nghĩa structuring? — đề xuất mặc định: ≥ 3 lần nộp tiền mặt trong dải [`large_cash_vnd` × (1 − `structuring_band_pct`), `large_cash_vnd`) trong 14 ngày; đúng ngưỡng không tính (đã thuộc diện báo cáo); không yêu cầu nhiều chi nhánh (chỉ đưa số chi nhánh vào `reason`). Lý do: khớp cách Phase 1 cài (4–8 lần, 14 ngày); đo được 20/20 kịch bản `small`, 0 alert ngoài. Lưu ý: kết quả hoàn hảo là do generator chặn tiền mặt nền dưới dải — dữ liệu thật sẽ có FP. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q4. Định nghĩa rapid movement? — đề xuất mặc định: trong 24 giờ kể từ một dòng tiền vào, tổng vào ≥ 200 triệu và tổng ra (sau mốc) ≥ 90% tổng vào; tính mọi kênh kể cả tiền mặt và thẻ; không chặn trên (đợt gộp có thể cho tỉ lệ > 100%, TINY có 1 alert 223% trên collector). Lý do: Phase 1 cài 200 triệu–2 tỉ, chuyển đi 95,5–98,5%; đo `small`: 20/20 kịch bản, thêm 5 collector và 19 hop round-trip (đều là tài khoản trung chuyển thật), 1 alert nền → precision theo typology 0,44, theo "nghi ngờ bất kỳ" 0,98. Cần người dùng chốt ngưỡng 200 triệu / 90%. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q5. Định nghĩa high velocity? — đề xuất mặc định: ≥ 8 giao dịch (cả hai chiều, mọi kênh) trong 24 giờ với tổng ≥ 100 triệu. Lý do: nền `small` tối đa 8 giao dịch / 24 giờ — ở ngưỡng 8 đếm thô còn 2 alert nền, bỏ đối tác quen (Q7) thì còn 0; ngưỡng 10 bỏ sót 1/5 collector, ngưỡng 6 sinh 28 alert nền nếu đếm thô. Không có typology riêng nên không có recall — chỉ báo alert rơi vào đâu (TINY 6/6, `small` 15/15 trên mule ring). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q6. Định nghĩa fan-in / fan-out? — đề xuất mặc định: ≥ 8 đối tác khác nhau trong 7 ngày với tổng ≥ 100 triệu, tính riêng chiều nhận (`FAN_IN`) và chiều gửi (`FAN_OUT`). Lý do: đo `small` — 5/5 collector và 20/20 source, 0 alert nền, 0 alert merchant (tối đa 8 người trả / 7 ngày nhưng mỗi khoản ≤ 5 triệu, không tới 100 triệu). Hạn chế suy ra (chưa đo): generator cho phép mule ring 5 member → collector chỉ có 4 + 3 = 7 người gửi < 8, sẽ sót; `small` seed 42 không có ring nhỏ như vậy (ít nhất 14 người gửi). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q7. Xử lý benign payroll thế nào (employer trả 20–29 người mỗi tháng — trúng cả high velocity lẫn fan-out)? — đề xuất mặc định: `HIGH_VELOCITY`, `FAN_IN`, `FAN_OUT` bỏ qua giao dịch với **đối tác đã quen** (đã giao dịch với tài khoản từ ≥ `known_counterparty_days` = 14 ngày trước) và không xét mốc trong **14 ngày khởi động** đầu dữ liệu. Lý do: đã đo ba biến thể (bảng ở mục Hiện trạng) — đếm thô cho 30 alert payroll mỗi rule trên `small`; chỉ bỏ đối tác quen còn 5 (kỳ lương đầu tiên 05/01); thêm khởi động còn 0 mà không mất alert nghi ngờ nào. Cần người dùng chốt vì **khởi động là lựa chọn có chủ ý**: nó giả lập hệ thống đã có lịch sử, đổi lại mọi kịch bản fan / velocity rơi vào 14 ngày đầu sẽ không bị bắt (`small` và TINY không có kịch bản nào như vậy), và một employer hoàn toàn mới ngoài đời vẫn sẽ bị alert một lần. Phương án thay thế: (i) không khởi động — chấp nhận 1 FP cho mỗi employer và báo rõ; (ii) đếm thô và để Phase 7 hibernation xử lý. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q8. Định nghĩa dormant reactivation? — đề xuất mặc định: không có giao dịch nào trong ≥ 90 ngày (tính từ giao dịch liền trước; tài khoản chưa từng giao dịch thì tính từ giao dịch sớm nhất của bảng; không sớm hơn `open_date`), sau đó tổng giao dịch trong 24 giờ ≥ 100 triệu. Lý do: tài khoản mở lâu, im lặng suốt 90 ngày quan sát rồi nhận / chuyển số tiền lớn là dormant theo nghĩa thực tế. Lưu ý quan trọng: 136/137 alert `small` rơi vào tài khoản kịch bản nghi ngờ **vì generator không sinh giao dịch nền cho tài khoản kịch bản** (chúng im lặng tới lúc kịch bản bắt đầu) — con số này là sản phẩm của dữ liệu tổng hợp, không chứng minh rule hiệu quả. Phương án thay thế: chỉ tính tài khoản đã từng có giao dịch trước đó ("re-activation" đúng nghĩa) — đã đo: TINY 0 alert, `small` 1 alert (nền). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q9. Tham số đặt ở đâu? — đề xuất mặc định: mục mới `monitoring` trong `config.yaml` (một mục con cho mỗi file rule + `known_counterparty_days`); structuring dùng lại `thresholds.large_cash_vnd` và `thresholds.structuring_band_pct` đã có (cùng nguồn với generator). Lý do: brief yêu cầu ngưỡng nằm trong config, ghi đè bằng `AML__MONITORING__...`; không nhân đôi ngưỡng tiền mặt. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q10. Lược đồ alert? — đề xuất mặc định: `alerts` (một dòng / alert, có `source`, `subject_type`, `subject_id`, `details` JSON) + bảng con `alert_accounts` (tài khoản liên quan kèm `cif`, `role`) + bảng con `alert_evidence` (`txn_id`) + `monitoring_runs` + view `alerts_current`. Lý do: 5c ghi alert nhóm tài khoản bằng `subject_type = 'ACCOUNT_GROUP'` và nhiều dòng `alert_accounts` mà không đổi schema; Phase 7 nối `alert_accounts.cif` → `customer_golden`; evidence dạng bảng con nối được với `transactions` (Phase 6/8 cần trích dẫn giao dịch). Phương án thay thế: cột JSON `evidence_txn_ids` ngay trên `alerts` (đúng chữ brief hơn, nhưng khó join và khác cú pháp JSON giữa hai backend). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q11. Có hợp nhất screening vào `alerts` không? — đề xuất mặc định: không; `screening_results` giữ nguyên, Phase 7 đọc `screening_current` và `alerts_current` song song. Lý do: chủ thể của screening là cặp (CIF, watchlist entry) với điểm số riêng, không có giao dịch bằng chứng; ép chung bảng phải sửa 3b/3c đã duyệt. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q12. Chạy lại `aml monitor` thì sao? — đề xuất mặc định: mỗi lần chạy là một ảnh chụp đầy đủ dưới `run_id` mới (như `run_er`), không xoá / sửa dòng cũ; `alerts_current` lấy lần chạy mới nhất của từng `rule_id`; `alert_key` (`rule|tài khoản|window_start`) là danh tính ổn định giữa các lần chạy (đã đo: chạy với 6 mốc `as_of` khác nhau trên TINY, mọi `alert_key` đều trùng với lần chạy đầy đủ). Lý do: alert luôn phản ánh đúng những gì rule thấy tại `as_of`. Hệ quả: `alert_id` đổi theo lần chạy (Phase 7 nên tham chiếu `alert_key`), mỗi lần chạy thêm 242 alert + 243 dòng audit trên `small`. Phương án thay thế: chỉ thêm alert có `alert_key` chưa tồn tại (chạy lại = 0 alert mới, `alert_id` ổn định) — nhưng alert đã ghi sẽ không được bổ sung giao dịch đến sau. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q13. `rule_version` là gì? — đề xuất mặc định: hằng `v1` cho từng rule trong `RULES` (tăng tay khi sửa logic SQL); tham số của từng lần chạy lưu ở `monitoring_runs.params`. Lý do: brief yêu cầu rule version trên alert; tách "logic đổi" (version) khỏi "ngưỡng đổi" (params) để truy vết được cả hai. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q14. Có bảng danh mục rule trong DB (như `dq_rules`) để bật/tắt không? — đề xuất mặc định: không; danh mục là hằng Python `RULES`, lần chạy nào cũng chạy đủ 6 rule. Lý do: giữ phạm vi nhỏ; tắt rule là quyết định cần kiểm soát thay đổi, chưa có yêu cầu. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q15. Mức chi tiết của audit? — đề xuất mặc định: một sự kiện `ALERT` cho mỗi alert + một sự kiện tổng kết mỗi lần chạy (TINY 32 dòng, `small` 243 dòng / lần chạy). Lý do: mỗi alert là một quyết định tự động cần `reason`; tài khoản không bị alert thì không ghi. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q16. Đánh giá theo ground truth thế nào? — đề xuất mặc định: alert "trúng" kịch bản khi tài khoản chủ thể thuộc kịch bản đó (vai nào cũng tính); mỗi rule báo `target_hits` / `other_suspicious` / `benign` / `unlabelled`, hai precision (theo typology mục tiêu và theo "nghi ngờ bất kỳ") và recall theo kịch bản; `HIGH_VELOCITY` và `DORMANT_REACTIVATION` không có target nên precision / recall theo typology để trống; thêm bảng phủ theo typology (kịch bản benign phải có `flagged = 0`). Lý do: một rule bắt đúng tài khoản trung chuyển của typology khác không nên bị coi là sai hoàn toàn, nhưng cũng không được tính vào precision của typology mục tiêu. Hạn chế: source / destination (có thể là nạn nhân) cũng được tính là "nghi ngờ". — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q17. Giao dịch trùng (defect DQ) có bị loại trước khi chạy rule không? — đề xuất mặc định: không, rule chạy trên `transactions` nguyên trạng. Lý do: đã đo — khử trùng không đổi alert nào (TINY, `small`); giám sát không nên âm thầm bỏ dữ liệu, DQ đã báo riêng (`TXN_DUPLICATE`). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q18. Ngữ nghĩa `as_of`? — đề xuất mặc định: rule chỉ thấy giao dịch có `txn_ts` trước 00:00 ngày `as_of + 1`; mặc định `settings.data.reference_date`, ghi đè bằng `--as-of`. Lý do: giống `aml dq run` / `aml er`; cho phép tái hiện "rule thấy gì vào ngày X". — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q19. Hình dạng CLI? — đề xuất mặc định: `aml monitor` chạy 6 rule, in số alert theo rule, dòng tổng kết, rồi bảng đánh giá và bảng phủ typology khi `ground_truth` có dữ liệu; `--eval-out PATH` ghi bảng đánh giá theo rule ra CSV; exit 0 khi chạy xong (có alert không phải lỗi), 1 khi chưa nạp dữ liệu, 2 khi tham số sai. Lý do: `make monitor` / `tasks.ps1 monitor` giữ nguyên; giống `aml er --eval-out`. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q20. Phạm vi Oracle? — đề xuất mặc định: DDL 110 và 5 file rule cho cả hai backend (`sql/oracle/monitoring/`, `sql/duckdb/monitoring/`, không dùng `sql/common` vì phép cộng interval khác cú pháp), ghi qua `insert_df`, một AC [oracle] so khớp với DuckDB (AC10); chưa cấp quyền cho các role của 2b. Lý do: cùng hướng với 3b/4; phần `SELECT` đã chạy khớp trên Oracle 23.26. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q21. 5c ghi alert bằng cách nào? — đề xuất mặc định: gọi `aml.monitoring.recording.record_run` (cấp `run_id` / `alert_id`, tra `cif`, ghi 4 bảng, audit) với `source = 'NETWORK'`, DDL riêng của 5c (số `130`) không tạo lại bảng nào của 5a. Lý do: một đường ghi duy nhất nên `alerts_current` và audit nhất quán; AC8 kiểm đường này bằng một alert nhóm giả. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q22. Một spec hay tách đôi? — đề xuất mặc định: một spec (10 AC). Lý do: sáu rule dùng chung runner, bảng và fixture. Nếu muốn giảm rủi ro: tách AC10 [oracle] + bản Oracle của DDL / file rule thành 5a-ii. — Trả lời: theo đề xuất mặc định (2026-10-12).
