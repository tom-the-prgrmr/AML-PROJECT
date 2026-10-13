---
id: case-consolidation
status: approved
approved_by: pthieu
---

# Phase 7a — Gộp alert thành case theo golden customer (rolling window), enrichment của case, disposition, `aml cases build`

## Bối cảnh
Phần "Consolidation" và "Enrichment" của Phase 7 trong PROJECT_BRIEF.md (mục 8). Phase 7 được tách thành bốn spec viết
theo thứ tự phụ thuộc: **7a** (spec này) → 7b-supp `specs/case-suppression.md` → 7c `specs/case-prioritization.md` → 7d
`specs/case-summary.md`. (Phase "7b" của brief — Isolation Forest, mô hình screening học được, mẫu below-the-line, model
card — **không** thuộc bốn spec này.) Spec này gộp ba nguồn alert đã có — screening (`screening_current`, 3b/3c), rule
(`alerts` nguồn `RULE`, 5a) và network (`alerts` nguồn `NETWORK`, 5c) — thành **một case cho mỗi golden customer trong
một cửa sổ trượt**, gắn cho mỗi case sáu khối enrichment (KYC + risk rating, linked CIFs, DQ issues, tóm tắt giao dịch
90 ngày, lân cận mạng lưới + graph features, alert / disposition trước đó) để investigator không phải mở hệ thống khác,
và đặt nền cho ba spec sau: bảng `case_alerts` có cột trạng thái cho suppression, bảng `case_dispositions` + hàm
`record_disposition` (quyết định của **người**), và `CaseView` / `load_case` cho chấm điểm, tóm tắt, Phase 8, Phase 9.
Hệ thống chỉ **gộp và làm giàu**: không đóng case, không chấm điểm, không sửa alert gốc.

### Hiện trạng đã kiểm (2026-10-13, seed 42)
Đọc code + đo bằng script tạm ngoài repo (scratchpad): TINY = `run_pipeline` với env của fixture `tiny_parquet` →
`load_parquet` → `run_er` → `run_screening` → `run_monitoring` → `run_network` → `run_dq` trên một DuckDB tạm; `small` =
`data/aml.duckdb` hiện có (mở read-only). Prototype của luật gộp bên dưới viết bằng pandas, không nằm trong repo.
- **Alert nằm ở đâu**:
  - Screening: `screening_results(run_id, cif, entry_id, list_type, matched_name, final_score, decision, reason,
    superseded_by)`, view `screening_current`; khoá là cặp (`cif`, `entry_id`); **không có mốc thời gian sự kiện** —
    chỉ có `screening_runs.as_of` của lần chạy. TINY: 5 `ALERT`, 0 `REVIEW`, 50 `AUTO_CLEARED`; `small`: 41 / 31 / 6208.
  - Rule + network: `alerts(alert_id, run_id, alert_key, source, rule_id, rule_version, subject_type, subject_id,
    window_start, window_end, txn_count, amount_vnd, reason, details)`, view `alerts_current` (lần chạy mới nhất của
    từng `rule_id`); `alert_accounts(alert_id, account_id, cif, role)` là cầu nối sang khách hàng; `alert_evidence`.
    `alert_id` đổi sau mỗi lần chạy lại, `alert_key` ổn định. Vai trong `alert_accounts`: `SUBJECT` (6 rule 5a và
    `NET_HUB`), `MEMBER` (`NET_SHARED_ATTRIBUTE`), `ORIGIN` / `HOP` (`NET_CYCLE`); không dòng nào có `cif` null (TINY và
    `small`). TINY: 31 alert `RULE` + 4 `NETWORK`; `small`: 242 + 25.
- **Golden customer**: view `customer_golden(run_id, cif, golden_customer_id, cluster_size)` (Phase 4), mọi CIF một
  dòng; `er_cluster_weights` cho weight của cụm. `golden_customer_id` = `'G-'` + CIF nhỏ nhất của cụm.
- **Graph features**: `nx_account_features_current` (5c, luôn có sau `aml network`; có thêm `cycle_alerts`, `is_hub`)
  và `gds_account_features_current` (6b-ii, chỉ có sau `aml graph gds` — cần Neo4j; có thêm `wcc_*`, `louvain_*`). Cả
  hai là **theo tài khoản**; "bảng đặc trưng theo golden customer" và "chọn giữa hai bảng" đã được 6b-ii ghi là việc
  của Phase 7. DuckDB tạm của TINY: 532 dòng NetworkX, 0 dòng GDS.
- **DQ issues**: `dq_results` chỉ lưu `sample_ids` (tối đa `dq.sample_size` = 20 id nhỏ nhất) — **không có danh sách
  đầy đủ thực thể lỗi theo từng rule**. `run_dq` tính đủ `failed_ids` trong bộ nhớ (`DqRuleResult.failed_ids`) rồi bỏ.
  Vì vậy "DQ issues của khách hàng này" không đọc được từ bảng nào hiện có (Q5).
- **Disposition**: chưa có khái niệm nào. Các "decision" hiện có đều là của máy: screening `ALERT` / `REVIEW` /
  `AUTO_CLEARED`, ER `MATCH` / `REVIEW`, audit `ALERT`, `WITHDRAWN`. Không bảng nào ghi quyết định của investigator.
- **Giao dịch**: view `txn_legs(account_id, cif, open_date, txn_id, txn_ts, direction, amount_vnd, counterparty_id,
  channel, branch_id)` (5a) cho mỗi phía tài khoản nội bộ một dòng; `channel` ∈ `CASH`, `INTERNAL_TRANSFER`,
  `INTERBANK_TRANSFER`, `EBANKING`, `CARD`. `customers.kyc_risk` ∈ `LOW`, `MEDIUM`, `HIGH` (TINY: 211 / 75 / 14).
- **Prototype luật gộp đề xuất** (mốc sự kiện = `window_start` của alert; screening = ngày `as_of` đầu tiên cặp đó là
  `ALERT` / `REVIEW`; cửa sổ neo vào alert đầu tiên):

  | | TINY | `small` |
  |---|---|---|
  | alert khác nhau (`RULE` / `NETWORK` / `SCREENING`) | 40 (31 / 4 / 5) | 339 (242 / 25 / 72) |
  | dòng (alert × golden customer) | 74 (31 / 38 / 5) | 475 (242 / 161 / 72) |
  | golden customer có alert | 52 | 333 |
  | số case với cửa sổ 30 / 90 ngày / không giới hạn | 53 / 52 / 52 | 336 / 335 / 333 |
  | case theo tổ hợp nguồn (90 ngày) | `NETWORK` 27, `RULE` 11, `NETWORK+RULE` 9, `SCREENING` 4, `NETWORK+SCREENING` 1 | `RULE` 123, `NETWORK` 104, `SCREENING` 54, `NETWORK+RULE` 51, `RULE+SCREENING` 2, cả ba 1 |
  | số alert mỗi case (90 ngày) | 1: 38, 2: 9, 3: 3, 4: 1, 5: 1 | 1: 238, 2: 70, 3: 21, 5: 5, 9: 1 |

  - Một alert nhóm (`ACCOUNT_GROUP`) gắn vào **mọi** golden customer có tài khoản trong `alert_accounts`: 4 alert
    `NETWORK` của TINY thành 38 dòng (cụm 29 khách hàng + 2 vòng × 4 + 1 hub); 5 alert `NET_SHARED_ATTRIBUTE` của
    `small` tạo case cho khoảng 104 khách hàng (Q2).
  - Cửa sổ gần như không đổi số case trên dữ liệu này (mỗi kịch bản tổng hợp chỉ kéo dài vài ngày); khác biệt duy nhất
    của TINY: `G-CIF00000104` có alert cụm ngày 2026-04-16 và screening hit ngày 2026-06-30 — 30 ngày thì thành hai
    case, 90 ngày thì một.
  - Case `C-CIF00000189-20260413` (collector của mule ring TINY): 5 alert (`FAN_IN`, `NET_HUB`, `HIGH_VELOCITY`,
    `NET_SHARED_ATTRIBUTE`, `RAPID_MOVEMENT`), alert cuối kết thúc 2026-04-18 10:04:12; 90 ngày tới hết 2026-04-18: 34
    giao dịch (31 vào 2 930 380 000, 3 ra 2 851 894 000), 34 đối tác, 5 ngày có giao dịch.
- `SCHEMA_SCRIPTS` đã dùng `000`–`150` → 7a dùng **`160`**. `aml score` đang là stub Phase 7 (`Makefile` / `tasks.ps1`
  đã có `score`); chưa có nhóm lệnh `aml cases`, chưa có `src/aml/cases/`.
- **Chưa đo**: DDL `160` trên hai backend; mọi giá trị của MINI-C trong AC (suy ra bằng tay từ luật); enrichment đầy đủ
  trên TINY ngoài các số nêu trên; đường Oracle.

### Interface đề xuất (để test và các spec sau gọi trực tiếp)
```python
# src/aml/common/config.py
class CasesConfig(BaseModel):
    window_days: int  # >= 1; cửa sổ neo vào alert đầu tiên của case
    txn_summary_days: int  # >= 1; số ngày của tóm tắt giao dịch (kết thúc ở ngày của alert cuối)
    top_counterparties: int  # >= 0; số đối tác lớn nhất ghi trong enrichment
    graph_features: Literal["auto", "networkx", "gds"]
    # 7b-supp thêm `suppression`, 7c thêm `prioritization`, 7d thêm `summary`


class Settings(BaseModel):
    ...
    cases: CasesConfig


# src/aml/cases/items.py
ITEM_COLUMNS = [
    "item_key",
    "golden_customer_id",
    "source",
    "rule_id",
    "alert_ref",
    "cif",
    "entry_id",
    "event_ts",
    "end_ts",
    "amount_vnd",
    "txn_count",
    "reason",
    "details",
]


def collect_items(db: Database, settings: Settings, *, as_of: date) -> pd.DataFrame: ...


# không ghi gì; sắp theo (golden_customer_id, event_ts, item_key)


# src/aml/cases/consolidate.py  (thuần pandas)
def case_id_for(golden_customer_id: str, window_start: datetime) -> str: ...
def assign_cases(items: pd.DataFrame, window_days: int) -> pd.DataFrame: ...


# thêm cột case_id, window_start; không đổi số dòng


# src/aml/cases/dispositions.py
SUSPICIOUS, FALSE_POSITIVE = "SUSPICIOUS", "FALSE_POSITIVE"
DISPOSITIONS = (SUSPICIOUS, FALSE_POSITIVE)
HUMAN, SIMULATED = "HUMAN", "SIMULATED"  # origin


def record_disposition(
    db: Database,
    settings: Settings,
    case_id: str,
    disposition: str,
    *,
    reason: str,
    actor: str,
    decided_on: date | None = None,  # mặc định settings.data.reference_date
    origin: str = HUMAN,
) -> int: ...  # trả disposition_id


# src/aml/cases/runner.py
CASES_VERSION = "cases/v1"
OPEN, REOPENED, CLOSED = "OPEN", "REOPENED", "CLOSED"
ACTIVE, SUPPRESSED = "ACTIVE", "SUPPRESSED"
SECTIONS = ("kyc", "linked_cifs", "dq_issues", "txn_summary", "network", "history")


class CaseError(RuntimeError): ...


@dataclass(frozen=True)
class CaseRun:
    run_id: int
    as_of: date
    items: int  # dòng (alert × golden customer) trước suppression
    alerts: int  # item_key khác nhau
    suppressed: int  # 7a: luôn 0
    active: int
    cases: int
    opened: int
    reopened: int
    closed: int
    graph_source: str  # "gds" | "networkx" | "none"


def run_cases(
    db: Database, settings: Settings, *, as_of: date | None = None, actor: str | None = None
) -> CaseRun: ...


# src/aml/cases/view.py
@dataclass(frozen=True)
class CaseAlert:
    item_key: str
    source: str
    rule_id: str
    alert_ref: str
    cif: str
    event_ts: datetime
    end_ts: datetime
    amount_vnd: int
    reason: str


@dataclass(frozen=True)
class Disposition:
    disposition_id: int
    disposition: str
    reason: str
    actor: str
    origin: str
    decided_on: date
    run_id: int


@dataclass(frozen=True)
class CaseView:
    case_id: str
    run_id: int
    golden_customer_id: str
    status: str
    window_start: datetime
    first_alert_ts: datetime
    last_alert_ts: datetime
    reason: str
    alerts: tuple[CaseAlert, ...]  # theo (event_ts, item_key)
    enrichment: dict[str, dict[str, Any]]  # khoá = SECTIONS
    subjects: tuple[dict[str, Any], ...]  # dòng customers_masked (hoặc customers) của từng CIF
    disposition: Disposition | None
    score: dict[str, Any] | None  # 7c điền; 7a luôn None


def load_case(
    db: Database, case_id: str, *, run_id: int | None = None, masked: bool = True
) -> CaseView: ...
```
- `config.yaml`, mục mới: `cases: {window_days: 90, txn_summary_days: 90, top_counterparties: 5, graph_features: auto}`.
- DDL `sql/duckdb/ddl/160_cases.sql` và `sql/oracle/ddl/160_cases.sql`, thêm vào `SCHEMA_SCRIPTS` của cả hai backend
  sau `ddl/150_gds.sql` và trước các script `050_*`.
- SQL trong file theo backend, placeholder chỉ định dạng từ giá trị đã ép kiểu: `cases/items.sql` (gom ba nguồn),
  `cases/txn_summary.sql`, `cases/counterparties.sql` — mỗi cái có bản `sql/duckdb/` và `sql/oracle/`.
- `src/aml/dq/runner.py`: thêm hàm **chỉ đọc** `failing_ids(db, settings, *, as_of, table_name) -> dict[str,
  frozenset[str]]` (rule_id → id lỗi của các rule `ROW` đang bật trên bảng đó), tách từ `_evaluate`; `run_dq` không đổi
  hành vi (Q5).
- CLI: nhóm mới `aml cases` với `build [--as-of YYYY-MM-DD]`, `show CASE_ID`, `dispose CASE_ID --disposition
  SUSPICIOUS|FALSE_POSITIVE --reason TEXT --actor USER [--decided-on YYYY-MM-DD]`. `aml score` vẫn là stub cho tới 7c.
- Gói `src/aml/cases/` (`items.py`, `consolidate.py`, `enrich.py`, `dispositions.py`, `runner.py`, `view.py`); test ở
  `tests/cases/`.

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **Item** = một cặp (alert, golden customer). `collect_items` chỉ lấy item có `event_ts` < 00:00 ngày `as_of + 1`:

  | nguồn | lấy từ | `item_key` | `alert_ref` | `rule_id` | `event_ts` / `end_ts` |
  |---|---|---|---|---|---|
  | `SCREENING` | `screening_current` có `decision` ∈ (`ALERT`, `REVIEW`) | `SCREENING\|<cif>\|<entry_id>` | `<cif>:<entry_id>` | `SCREENING_ALERT` / `SCREENING_REVIEW` | cả hai = 00:00 của `MIN(screening_runs.as_of)` trên mọi dòng `screening_results` của cặp đó có `decision` ∈ (`ALERT`, `REVIEW`) |
  | `RULE`, `NETWORK` | `alerts_current` nối `alert_accounts` | `alert_key` | `str(alert_id)` | `rule_id` | `window_start` / `window_end` |

  - Golden customer của item = `customer_golden` của `cif` (screening: `cif` của cặp; rule / network: `cif` của từng
    dòng `alert_accounts`). CIF không có trong `customer_golden` → `'G-' + cif`. Một alert có nhiều tài khoản của cùng
    một golden customer cho **một** item (cột `cif` = CIF nhỏ nhất trong số đó); alert nhóm cho mỗi golden customer
    liên quan một item. `AUTO_CLEARED` không bao giờ là item.
  - `amount_vnd`, `txn_count`, `reason` chép từ alert; screening: 0, 0 và `reason` của `screening_current`.
- **Gộp** (`assign_cases`, tất định, không phụ thuộc thứ tự đầu vào): với mỗi golden customer, sắp item theo
  (`event_ts`, `item_key`); item đầu mở case với `window_start = event_ts`; item kế tiếp vào case đang mở khi `event_ts
  < window_start + window_days` ngày (nửa mở), ngược lại mở case mới. `case_id` = `'C-'` + `golden_customer_id` bỏ
  tiền tố `G-` + `'-'` + `YYYYMMDD` của `window_start` (vd `C-CIF00000189-20260413`). Chỉ item `ACTIVE` tham gia gộp
  (7b-supp là nơi duy nhất đặt `SUPPRESSED`).
- **Bảng** (DDL `160`; cùng tên cột trên hai backend; **không bao giờ UPDATE / DELETE**; không lưu tên, số giấy tờ,
  điện thoại, email, địa chỉ, mã thiết bị, memo):
  - `case_runs(run_id PK, run_ts UTC, as_of, window_days, items, alerts, suppressed, active, cases, opened, reopened,
    closed, graph_source, version, config_hash)`; `run_id` = `MAX + 1` (tính cả trên `cases`); `config_hash` = 16 ký
    tự hex đầu của SHA-256 trên JSON khoá đã sắp của `settings.cases`.
  - `cases(run_id, case_id, golden_customer_id, window_start, first_alert_ts, last_alert_ts, alerts, rule_alerts,
    network_alerts, screening_alerts, sources, status, reason)`, PK `(run_id, case_id)`; `first_alert_ts` =
    `MIN(event_ts)`, `last_alert_ts` = `MAX(end_ts)`; `sources` = các nguồn sắp theo chữ cái nối bằng `+`.
  - `case_alerts(run_id, item_key, golden_customer_id, case_id, source, rule_id, alert_ref, cif, entry_id, event_ts,
    end_ts, amount_vnd, txn_count, status, suppression_rule, suppression_reason, retriggered, reason, details JSON)`,
    PK `(run_id, item_key, golden_customer_id)`; 7a: `status = 'ACTIVE'`, `suppression_rule` và `suppression_reason`
    null, `retriggered = 0`, `case_id` khác null. `details`: screening = `{decision, list_type, final_score}`; rule /
    network = `{subject_type, roles}` (`roles` = các vai của tài khoản thuộc golden customer đó, tăng dần) — để feature
    của 7c là hàm thuần của ảnh chụp.
  - `case_enrichment(run_id, case_id, section, content JSON)`, PK `(run_id, case_id, section)`; đủ 6 `section`.
  - `case_dispositions(disposition_id PK, case_id, run_id, disposition, reason, actor, origin, decided_on, decided_ts
    UTC)`; `run_id` = lần chạy mới nhất có `case_id` đó (ảnh chụp mà người quyết định đã nhìn).
  - View `cases_current`, `case_alerts_current`, `case_enrichment_current` = dòng có `run_id = MAX(run_id)` của
    `case_runs`; `case_dispositions_current` = dòng có `disposition_id` lớn nhất của từng `case_id`.
  - Thứ tự ghi: `case_alerts` → `cases` → `case_enrichment` → 1 dòng `case_runs` (ghi cuối) → audit.
- **Trạng thái case** (tính lúc `run_cases`, lưu trong `cases.status`): chưa có disposition → `OPEN`; có disposition và
  mọi `item_key` `ACTIVE` của case trong lần chạy này đều nằm trong `case_alerts` của (`run_id` của disposition mới
  nhất, `case_id`) và không item nào có `retriggered = 1` → `CLOSED`; còn lại → `REOPENED`. Chỉ `record_disposition`
  (do người gọi) mới làm một case thành `CLOSED`.
- **`cases.reason`**: `{alerts} alert(s) ({rule_alerts} RULE, {network_alerts} NETWORK, {screening_alerts} SCREENING) on {golden_customer_id} between {first_alert_ts} and {last_alert_ts}; window of {window_days} days from the first alert`.
- **Enrichment** (mỗi khối một JSON; mọi danh sách sắp tất định):
  - `kyc`: `{risk_rating, cifs: [{cif, kyc_risk, occupation, nationality, gender, birth_year, id_type}]}`;
    `risk_rating` = mức cao nhất của các CIF theo `LOW` < `MEDIUM` < `HIGH` (null khi mọi CIF đều null).
  - `linked_cifs`: `{cluster_size, cifs, accounts: [{account_id, cif, account_type, open_date}], er: {pairs,
    min_match_weight} | null}` (`er` lấy từ `er_cluster_weights`, null với cụm một CIF).
  - `dq_issues`: `{customer: [{cif, rule_id, dimension}], transactions: {rule_id: số giao dịch lỗi}}` — rule `ROW` đang
    bật của bảng `customers` trên các CIF của case, và của bảng `transactions` trên các giao dịch của khách hàng trong
    cửa sổ tóm tắt; tính bằng `failing_ids` với `as_of` của lần chạy (rule có 0 lỗi không xuất hiện).
  - `txn_summary`: cửa sổ `[D − txn_summary_days + 1, D]` với `D` = ngày của `last_alert_ts`; trên `txn_legs` của mọi
    tài khoản thuộc mọi CIF của golden customer: `{window_start, window_end, txn_count, in_count, out_count, in_vnd,
    out_vnd, cash_in_vnd, cash_out_vnd, counterparties, max_txn_vnd, active_days, by_channel: {channel: {count,
    vnd}}}`; `txn_count` = số `txn_id` khác nhau; `counterparties` = số `counterparty_id` khác null khác nhau.
  - `network`: `{source, features: {in_degree, out_degree, in_vnd, out_vnd, pagerank_ratio, shared_cluster_id,
    shared_cluster_size, cycle_alerts, is_hub, wcc_size, louvain_size}, counterparties: [{account_id,
    golden_customer_id, direction, txns, vnd}], shared_alert_cases: [case_id]}`.
    - `features` gộp từ tài khoản lên golden customer: `MAX` cho `in_degree`, `out_degree`, `pagerank_ratio`,
      `shared_cluster_size`, `is_hub`, `wcc_size`, `louvain_size`; `SUM` cho `in_vnd`, `out_vnd`, `cycle_alerts`;
      `shared_cluster_id` = giá trị khác null nhỏ nhất. Khoá không có ở nguồn đang dùng → null.
    - `source`: `graph_features = networkx` → `nx_account_features_current`; `gds` → `gds_account_features_current`;
      `auto` → `gds` khi view GDS có dòng **và** `as_of` của dòng `gds_runs` mới nhất bằng `as_of` của lần chạy, ngược
      lại `networkx`. Bảng được chọn không có dòng nào → `source = "none"`, mọi `features` null. **`run_cases` không
      bao giờ mở kết nối Neo4j** — chỉ đọc bảng đã được ghi về hệ thống gốc.
    - `counterparties`: `top_counterparties` đối tác lớn nhất trong cửa sổ tóm tắt theo (`vnd` giảm, `account_id`
      tăng, `direction`), bỏ đối tác thuộc chính golden customer đó; `golden_customer_id` null với `EXT-*`.
    - `shared_alert_cases`: `case_id` khác (cùng lần chạy) có chung ít nhất một `item_key`, tăng dần.
  - `history`: `{prior_cases: [{case_id, first_alert_ts, alerts, disposition, decided_on}], prior_alerts,
    screening_auto_cleared, suppressed_items}` — `prior_cases` = case khác của cùng golden customer có `window_start`
    sớm hơn (ảnh chụp mới nhất của từng `case_id` trên mọi lần chạy, kèm disposition mới nhất nếu có); `prior_alerts` =
    tổng `alerts` của chúng; `screening_auto_cleared` = số dòng `AUTO_CLEARED` hiện hành của các CIF; `suppressed_items`
    = số item `SUPPRESSED` của khách hàng trong lần chạy.
- **`record_disposition`**: `case_id` chưa từng có trong `cases` → `CaseError` chứa `unknown case_id`; `disposition`
  ngoài `DISPOSITIONS` → `ValueError`; `reason` rỗng → `ValueError`; `origin = HUMAN` mà `actor` bằng
  `settings.audit.system_actor` → `CaseError` chứa `a disposition needs a human actor`. Ghi 1 dòng `case_dispositions`
  và 1 dòng audit. Không sửa `cases`.
- **Audit** (`module='cases'`, `version=CASES_VERSION`): mỗi case **mới hoặc đổi** trong lần chạy một sự kiện
  `entity_type='case'`, `entity_id=case_id`: `CASE_OPENED` (`case_id` lần đầu xuất hiện), `CASE_REOPENED` (trạng thái
  thành `REOPENED` mà ở lần chạy trước không phải), `CASE_UPDATED` (tập `item_key` khác lần chạy trước, không thuộc hai
  loại trên); `reason` = `cases.reason`; `details = {run_id, golden_customer_id, alerts, sources, item_keys}`. Case
  không đổi → không có sự kiện. Mỗi lần chạy một sự kiện `entity_type='case_run'`, `decision='CASE_RUN_COMPLETED'`,
  `details` = các trường của `CaseRun`. Disposition: `entity_type='case'`, `decision` = giá trị disposition, `reason`
  và `actor` của người gọi, `details = {disposition_id, run_id, origin, decided_on}`.
- **Lỗi của `run_cases`** (trước khi ghi bất cứ thứ gì): `customer_golden` rỗng → `CaseError` chứa ``run `aml er`
  first``; chưa có dòng nào trong cả `screening_runs` lẫn `monitoring_runs` → `CaseError` chứa ``run `aml screen` or
  `aml monitor` first``. Có lần chạy nguồn nhưng 0 item → lần chạy hợp lệ với 0 case.
- **CLI**: `aml cases build` in `run_id= as_of= items= alerts= suppressed= active= cases= opened= reopened= closed=
  graph_features=<source>`; `aml cases show` in dòng đầu `case_id status golden_customer_id alerts=<n>`, mỗi alert một
  dòng, rồi mỗi khối enrichment một dòng JSON; `aml cases dispose` in `disposition_id=`. `CaseError` → stderr, exit 1;
  ngày sai định dạng → exit 2.

## Tiêu chí nghiệm thu
<!-- settings = load_settings(environ={"DB_BACKEND": "duckdb"}) trừ khi nói khác; as_of mặc định 2026-06-30; M = triệu.
TINY = `tiny_parquet` nạp bằng `load_parquet`, rồi `run_er`, `run_screening`, `run_monitoring`, `run_network`, `run_dq`
(fixture mới `tiny_cases`, dựng một lần rồi chép). Test [oracle] dùng @pytest.mark.oracle; còn lại chạy DuckDB-only.
MINI-C = DuckDB rỗng sau `apply_schema`, rồi chèn trực tiếp:
  customers C01..C06: nationality 'VN', gender 'F', dob 1990-01-01, id_type 'PASSPORT', id_number 'B1234561'..'B1234566',
    kyc_risk C01 'LOW', C02 'HIGH', C03 'MEDIUM', còn lại 'LOW'; occupation 'Kế toán' trừ C02 là NULL;
  er_runs 1 dòng run_id 1 và er_golden (run 1): C01, C02 -> 'G-C01' (cluster_size 2); C03..C06 -> 'G-C0n' (cluster_size 1);
  accounts A01..A06 (cif C01..C06, account_type 'CURRENT', open_date 2025-01-01);
  transactions: T01 2026-03-02 09:00:00 nộp tiền mặt -> A01 390M CASH; T02 2026-03-05 10:00:00 A01 -> A03 300M
    INTERNAL_TRANSFER; T03 2026-03-06 10:00:00 A03 -> A04 290M INTERNAL_TRANSFER; T04 2026-03-07 10:00:00 A04 -> A01 280M
    INTERNAL_TRANSFER; T05 2026-04-20 08:00:00 EXT-01 -> A02 500M INTERBANK_TRANSFER; T06 2026-04-20 12:00:00 A02 -> EXT-02
    480M EBANKING; T07 2026-05-31 09:00:00 A01 -> EXT-03 50M EBANKING; T08 2026-01-15 09:00:00 EXT-01 -> A01 10M
    INTERBANK_TRANSFER;
  alert bằng `record_run(as_of=2026-06-30, source="RULE", ...)` (mọi rule v1, subject_type ACCOUNT, vai SUBJECT):
    R1 STRUCTURING A01 2026-03-02 09:00:00 -> 2026-03-02 09:00:00 (T01) 390M;
    R2 RAPID_MOVEMENT A02 2026-04-20 08:00:00 -> 2026-04-20 12:00:00 (T05, T06) 980M;
    R3 FAN_OUT A01 2026-05-31 09:00:00 -> 2026-05-31 09:00:00 (T07) 50M;
    R4 DORMANT_REACTIVATION A03 2026-03-05 10:00:00 -> 2026-03-06 10:00:00 (T02, T03) 590M;
  rồi `record_run(source="NETWORK", ...)`: N1 NET_CYCLE ACCOUNT_GROUP subject 'A01>A03>A04', accounts (A01, ORIGIN),
    (A03, HOP), (A04, HOP), 2026-03-05 10:00:00 -> 2026-03-07 10:00:00 (T02, T03, T04) 870M; alert_key = '<rule_id>|<subject>|<window_start ISO>';
  screening_runs 1 dòng (run_id 1, as_of 2026-06-30) và screening_results (run 1, superseded_by NULL): S1 (C02, WL1,
    SANCTIONS, ALERT, final_score 100), S2 (C05, WL2, PEP, REVIEW, final_score 80), S3 (C06, WL3, PEP, AUTO_CLEARED, 60).
Giá trị MINI-C suy ra bằng tay từ luật; giá trị TINY đo bằng prototype (mục Hiện trạng). -->
- AC1: Given `config.yaml`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS` và gọi `apply_schema(duck)` hai lần, Then `settings.cases.window_days == 90`, `settings.cases.txn_summary_days == 90`, `settings.cases.top_counterparties == 5`, `settings.cases.graph_features == "auto"`; `load_settings(environ={"AML__CASES__WINDOW_DAYS": "0"})` raise `pydantic.ValidationError` chứa `window_days must be >= 1` và `AML__CASES__GRAPH_FEATURES=neo4j` raise `ValidationError`; `ddl/160_cases.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]`, đứng sau `ddl/150_gds.sql` và trước `ddl/050_customers_masked.sql` / `ddl/050_security_objects.sql`; `apply_schema` không raise; `SELECT COUNT(*)` trên `case_runs`, `cases`, `case_alerts`, `case_enrichment`, `case_dispositions`, `cases_current`, `case_alerts_current`, `case_enrichment_current`, `case_dispositions_current` đều trả 0; ba file `cases/items.sql`, `cases/txn_summary.sql`, `cases/counterparties.sql` resolve qua `sql_file` về `sql/duckdb/` cho `"duckdb"` và về `sql/oracle/` cho `"oracle"`, và mỗi file Oracle qua `split_oracle_script` ra đúng 1 statement; `ROLE_GRANTS` không chứa cặp nào có tên bảng bắt đầu bằng `case`.
- AC2: Given hàm thuần `assign_cases` và một frame item của hai khách hàng đưa vào theo thứ tự đảo ngược — `G-C01`: (`k1`, 2026-03-02 09:00:00), (`k2`, 2026-03-05 10:00:00), (`k3`, 2026-05-31 08:59:59), (`k4`, 2026-05-31 09:00:00), (`k5`, 2026-06-30 00:00:00); `G-C03`: (`k2`, 2026-03-05 10:00:00), (`k9`, 2026-03-05 10:00:00), When gọi `assign_cases(items, 90)`, Then kết quả có đúng 7 dòng; `k1`, `k2`, `k3` của `G-C01` có `case_id = 'C-C01-20260302'` và `window_start = 2026-03-02 09:00:00`; `k4` (đúng bằng `window_start` + 90 ngày) và `k5` có `case_id = 'C-C01-20260531'`; hai dòng của `G-C03` có `case_id = 'C-C03-20260305'`; `assign_cases(items, 91)` cho `k4` vào `C-C01-20260302` và `k5` vào `C-C01-20260630`; `assign_cases(items, 365)` cho cả 5 dòng của `G-C01` cùng `C-C01-20260302`; `assign_cases(items, 1)` cho `G-C01` 4 `case_id` khác nhau (`k3` và `k4` cách nhau 1 giây nên chung case `C-C01-20260531`); frame rỗng có đủ cột trả frame rỗng có thêm cột `case_id`, `window_start`; và `case_id_for("G-CIF00000189", datetime(2026, 4, 13, 9, 28, 12)) == "C-CIF00000189-20260413"`.
- AC3: Given MINI-C, When gọi `run = run_cases(duck, settings)`, Then `run.run_id = 1`, `run.as_of = date(2026, 6, 30)`, `run.items = 9`, `run.alerts = 7`, `run.suppressed = 0`, `run.active = 9`, `run.cases = 5`, `run.opened = 5`, `run.reopened = 0`, `run.closed = 0`; `cases_current` có đúng 5 dòng `status = 'OPEN'` với (`case_id`, `golden_customer_id`, `alerts`, `rule_alerts`, `network_alerts`, `screening_alerts`, `sources`) = (`C-C01-20260302`, `G-C01`, 3, 2, 1, 0, `NETWORK+RULE`), (`C-C01-20260531`, `G-C01`, 2, 1, 0, 1, `RULE+SCREENING`), (`C-C03-20260305`, `G-C03`, 2, 1, 1, 0, `NETWORK+RULE`), (`C-C04-20260305`, `G-C04`, 1, 0, 1, 0, `NETWORK`), (`C-C05-20260630`, `G-C05`, 1, 0, 0, 1, `SCREENING`); dòng `C-C01-20260302` có `first_alert_ts = 2026-03-02 09:00:00`, `last_alert_ts = 2026-04-20 12:00:00` và `reason` bằng đúng `3 alert(s) (2 RULE, 1 NETWORK, 0 SCREENING) on G-C01 between 2026-03-02 09:00:00 and 2026-04-20 12:00:00; window of 90 days from the first alert`; `case_alerts_current` có 9 dòng, tất cả `status = 'ACTIVE'`, `retriggered = 0`, `suppression_rule` và `suppression_reason` null; alert N1 xuất hiện ở 3 dòng (`G-C01`, `G-C03`, `G-C04`) cùng `item_key = 'NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00'`; dòng screening của `G-C01` có `item_key = 'SCREENING|C02|WL1'`, `alert_ref = 'C02:WL1'`, `rule_id = 'SCREENING_ALERT'`, `cif = 'C02'`, `entry_id = 'WL1'`, `event_ts = 2026-06-30 00:00:00`, `case_id = 'C-C01-20260531'`, `details` = `{decision: "ALERT", list_type: "SANCTIONS", final_score: 100.0}`; dòng N1 của `G-C03` có `details` = `{subject_type: "ACCOUNT_GROUP", roles: ["HOP"]}`; dòng R2 (tài khoản của `C02`) có `golden_customer_id = 'G-C01'` và `case_id = 'C-C01-20260302'`; không dòng nào có `cif = 'C06'` (cặp `AUTO_CLEARED` không là item); `run_cases(duck, settings, as_of=date(2026, 5, 30))` trả `items = 6`, `cases = 3` (R3, S1, S2 nằm sau cutoff) và `run_id = 2`; và với `AML__CASES__WINDOW_DAYS=365`, `run_cases` trả `cases = 4` trong đó `C-C01-20260302` có `alerts = 5`.
- AC4: Given MINI-C đã `run_cases(duck, settings)` (run 1), When đọc `case_enrichment_current` và gọi `load_case(duck, "C-C01-20260302")`, Then mỗi case có đúng 6 dòng với `section` = `kyc`, `linked_cifs`, `dq_issues`, `txn_summary`, `network`, `history`; với `C-C01-20260302`: `kyc.risk_rating = "HIGH"`, `kyc.cifs` có 2 phần tử theo thứ tự `C01`, `C02` và phần tử `C01` = `{cif: "C01", kyc_risk: "LOW", occupation: "Kế toán", nationality: "VN", gender: "F", birth_year: 1990, id_type: "PASSPORT"}`; `linked_cifs.cluster_size = 2`, `linked_cifs.cifs = ["C01", "C02"]`, `linked_cifs.accounts` có 2 phần tử `A01`, `A02`; `dq_issues.customer` chứa `{cif: "C02", rule_id: "KYC_OCCUPATION_MISSING", dimension: "COMPLETENESS"}` và không có phần tử nào của `C01` với rule đó; `txn_summary` = (`window_start` `2026-01-21`, `window_end` `2026-04-20`, `txn_count` 5, `in_count` 3, `out_count` 2, `in_vnd` 1170000000, `out_vnd` 780000000, `cash_in_vnd` 390000000, `cash_out_vnd` 0, `counterparties` 4, `max_txn_vnd` 500000000, `active_days` 4) và `txn_summary.by_channel` = `{CASH: {count: 1, vnd: 390000000}, EBANKING: {count: 1, vnd: 480000000}, INTERBANK_TRANSFER: {count: 1, vnd: 500000000}, INTERNAL_TRANSFER: {count: 2, vnd: 580000000}}` (T07 và T08 nằm ngoài cửa sổ); `network.counterparties` = 4 phần tử theo thứ tự (`EXT-01`, null, `IN`, 1, 500000000), (`EXT-02`, null, `OUT`, 1, 480000000), (`A03`, `G-C03`, `OUT`, 1, 300000000), (`A04`, `G-C04`, `IN`, 1, 280000000); `network.shared_alert_cases = ["C-C03-20260305", "C-C04-20260305"]`; `history.prior_cases = []`; với `C-C01-20260531`: `history.prior_cases` có đúng 1 phần tử có `case_id = "C-C01-20260302"`, `alerts = 3`, `disposition = null` và `history.prior_alerts = 3`, còn `txn_summary.window_end = "2026-06-30"` và `txn_summary.txn_count = 3` (T05, T06, T07); với `C-C05-20260630`: `txn_summary.txn_count = 0`, `in_vnd = 0`, `by_channel = {}`, `network.counterparties = []`; không dòng `content` nào của `case_enrichment` chứa chuỗi `B123456` (số giấy tờ) hay khoá `full_name`, `phone`, `email`, `address`, `memo`; `load_case` trả `CaseView` có `status = "OPEN"`, `len(alerts) = 3` theo thứ tự R1, N1, R2, `enrichment` đủ 6 khoá, `disposition is None`, `score is None`, `subjects` có 2 phần tử lấy từ `customers_masked` (không có khoá `dob`), còn `load_case(duck, "C-C01-20260302", masked=False)` trả `subjects` có khoá `dob`; và `load_case(duck, "C-NOPE-20260101")` raise `CaseError` chứa `unknown case_id`.
- AC5: Given MINI-C có thêm `nx_account_features` (run 1) cho A01 = (`in_degree` 2, `out_degree` 1, `in_vnd` 290000000, `out_vnd` 300000000, `pagerank` 0.3, `pagerank_ratio` 1.8, `cycle_alerts` 1, `shared_cluster_id` null, `shared_cluster_size` 0, `is_hub` 0) và A02 = (1, 3, 500000000, 480000000, 0.1, 0.6, 0, `SHARED-C02`, 5, 1), When gọi `run_cases(duck, settings)`, Then `run.graph_source = "networkx"` và `network` của `C-C01-20260302` có `source = "networkx"`, `features` = `{in_degree: 2, out_degree: 3, in_vnd: 790000000, out_vnd: 780000000, pagerank_ratio: 1.8, shared_cluster_id: "SHARED-C02", shared_cluster_size: 5, cycle_alerts: 1, is_hub: 1, wcc_size: null, louvain_size: null}`; Given chèn thêm 1 dòng `gds_runs` (`run_id` 1, `as_of` 2026-06-30) và `gds_account_features` (run 1) cho A01 có `in_degree` 7, `wcc_size` 4, `louvain_size` 3, When gọi lại `run_cases`, Then `graph_source = "gds"`, `features.in_degree = 7`, `features.wcc_size = 4`, `features.cycle_alerts` null và `features.is_hub` null; với `AML__CASES__GRAPH_FEATURES=networkx` cùng dữ liệu đó thì `graph_source = "networkx"`; khi dòng `gds_runs` có `as_of = 2026-05-31` (khác `as_of` của lần chạy) thì `auto` cho `graph_source = "networkx"`; Given MINI-C gốc (hai bảng đặc trưng đều rỗng), Then `graph_source = "none"`, `network.source = "none"`, mọi giá trị của `features` là null và `counterparties` vẫn có 4 phần tử; và trong mọi trường hợp trên, với `AML__NEO4J__URI=bolt://127.0.0.1:1` (Neo4j không chạy) `run_cases` không raise.
- AC6: Given MINI-C đã `run_cases` (run 1), When gọi `record_disposition(duck, settings, "C-C01-20260302", "FALSE_POSITIVE", reason="cash deposits explained by a property sale", actor="analyst01", decided_on=date(2026, 6, 30))` rồi `run_cases` (run 2), Then lời gọi trả `1`; `case_dispositions` có 1 dòng (`case_id` `C-C01-20260302`, `run_id` 1, `disposition` `FALSE_POSITIVE`, `actor` `analyst01`, `origin` `HUMAN`, `decided_on` 2026-06-30); `audit_log` có 1 dòng `module='cases'`, `entity_type='case'`, `entity_id='C-C01-20260302'`, `decision='FALSE_POSITIVE'`, `actor='analyst01'`, `reason='cash deposits explained by a property sale'`, `details.disposition_id = 1`; trước run 2 dòng `cases` của run 1 vẫn `status = 'OPEN'` (không UPDATE); run 2 trả `cases = 5`, `opened = 0`, `reopened = 0`, `closed = 1`, và `cases_current` có `C-C01-20260302` với `status = 'CLOSED'`, bốn case còn lại `OPEN`; `history.prior_cases[0]` của `C-C01-20260531` có `disposition = "FALSE_POSITIVE"`, `decided_on = "2026-06-30"`; `load_case(duck, "C-C01-20260302").disposition.actor == "analyst01"`; Given thêm alert R5 bằng `record_run(source="RULE", rules=[HIGH_VELOCITY], alerts=[R5])` với R5 = `HIGH_VELOCITY` A01 2026-04-25 09:00:00 → 2026-04-25 10:00:00, When `run_cases` (run 3), Then `C-C01-20260302` có `alerts = 4`, `status = 'REOPENED'`, `run.reopened = 1`, `run.closed = 0`, và `audit_log` có đúng 1 dòng `decision='CASE_REOPENED'` cho case đó; `record_disposition` lần hai (`SUSPICIOUS`, `actor="analyst02"`) trả `2` và `run_cases` (run 4) cho `status = 'CLOSED'` với `case_dispositions_current` của case đó là dòng `disposition_id = 2`; `record_disposition(duck, settings, "C-NOPE-20260101", "SUSPICIOUS", reason="x", actor="a")` raise `CaseError` chứa `unknown case_id`; `disposition="CLOSED"` raise `ValueError`; `reason=""` raise `ValueError`; `actor="system"` raise `CaseError` chứa `a disposition needs a human actor`; và sau mọi bước, số dòng `cases` của run 1 vẫn là 5 (không dòng nào bị sửa hay xoá).
- AC7: Given MINI-C, When gọi `run_cases(duck, settings)` hai lần liên tiếp, Then lần một ghi vào `audit_log` đúng 6 dòng `module='cases'`: 5 dòng `decision='CASE_OPENED'`, `entity_type='case'`, `version='cases/v1'` (dòng `entity_id='C-C01-20260302'` có `reason` bằng `cases.reason` của case đó, `details.alerts = 3`, `details.sources = "NETWORK+RULE"`, `details.item_keys` có 3 phần tử) và 1 dòng `entity_type='case_run'`, `entity_id='1'`, `decision='CASE_RUN_COMPLETED'` với `details.cases = 5`, `details.items = 9`; lần hai trả `run_id = 2`, `opened = 0`, mọi trường còn lại ngoài `run_id` bằng lần một, và chỉ thêm đúng 1 dòng audit (`CASE_RUN_COMPLETED`, `entity_id='2'`); `cases`, `case_alerts`, `case_enrichment` giữ đủ dòng của cả hai lần (5 / 9 / 30 dòng mỗi `run_id`); tập (`case_id`, `status`, `alerts`, `reason`) và mọi `content` của enrichment giống hệt giữa hai lần; các view `*_current` chỉ trả dòng `run_id = 2`; và khi chèn MINI-C với thứ tự vật lý đảo ngược của `transactions`, `accounts`, `screening_results` thì kết quả của `run_cases` (ngoài `run_ts`) không đổi.
- AC8: Given TINY (`tiny_cases`), When gọi `run = run_cases(db, settings)`, Then `run.items = 74`, `run.alerts = 40`, `run.active = 74`, `run.cases = 52`, `run.opened = 52`, `run.graph_source = "networkx"`; `cases_current` có 52 dòng của 52 `golden_customer_id` khác nhau, số dòng theo `sources` là `NETWORK` 27, `RULE` 11, `NETWORK+RULE` 9, `SCREENING` 4, `NETWORK+SCREENING` 1, và theo `alerts` là 1: 38, 2: 9, 3: 3, 4: 1, 5: 1; `case_alerts_current` có 31 dòng `RULE`, 38 dòng `NETWORK`, 5 dòng `SCREENING`; case `C-CIF00000189-20260413` có `alerts = 5`, `first_alert_ts = 2026-04-13 09:28:12`, `last_alert_ts = 2026-04-18 10:04:12`, các `rule_id` là đúng `FAN_IN`, `NET_HUB`, `HIGH_VELOCITY`, `NET_SHARED_ATTRIBUTE`, `RAPID_MOVEMENT`, `txn_summary` = (`window_start` `2026-01-19`, `window_end` `2026-04-18`, `txn_count` 34, `in_count` 31, `out_count` 3, `in_vnd` 2930380000, `out_vnd` 2851894000, `cash_in_vnd` 0, `counterparties` 34, `max_txn_vnd` 1019225000, `active_days` 5), `network.features` có `in_degree = 31`, `out_degree = 3`, `pagerank_ratio = 6.7651`, `shared_cluster_id = "SHARED-CIF00000002"`, `shared_cluster_size = 29`, `is_hub = 1`, và `network.shared_alert_cases` có đúng 28 phần tử; case `C-CIF00000104-20260416` có `sources = 'NETWORK+SCREENING'` và `alerts = 2`; với `AML__CASES__WINDOW_DAYS=30` thì `run.cases = 53` và `G-CIF00000104` có hai case `C-CIF00000104-20260416`, `C-CIF00000104-20260630`; tổng `alerts` của mọi case bằng 74; và mọi `case_id` trong `case_alerts_current` đều có dòng trong `cases_current`.
- AC9: Given `tiny_env` đã `aml load`, `aml er`, `aml screen`, `aml monitor`, `aml network`, When chạy `aml cases build`, Then exit code 0 và stdout có một dòng chứa `run_id=1`, `as_of=2026-06-30`, `items=74`, `alerts=40`, `suppressed=0`, `active=74`, `cases=52`, `opened=52`, `reopened=0`, `closed=0`, `graph_features=networkx`; `aml cases show C-CIF00000189-20260413` exit code 0 với dòng đầu chứa `C-CIF00000189-20260413`, `OPEN`, `G-CIF00000189`, `alerts=5` và stdout chứa `txn_summary`; `aml cases dispose C-CIF00000189-20260413 --disposition SUSPICIOUS --reason "collector of a mule ring" --actor analyst01` exit code 0 với stdout chứa `disposition_id=1`; `aml cases show C-NOPE-20260101` exit code 1 với stderr chứa `unknown case_id`; `aml cases dispose C-CIF00000189-20260413 --disposition MAYBE --reason x --actor a` exit code 2; `aml cases build --as-of 2026-13-01` exit code 2 và `case_runs` không thêm dòng; `aml --help` liệt kê `cases` và `aml score` vẫn exit code 1 với stderr chứa `arrives in Phase 7` [ghi chú: mệnh đề "`aml score` vẫn là stub" đã được thay bởi `specs/case-prioritization.md`]; Given DuckDB chỉ mới `aml load` (chưa `aml er`), When chạy `aml cases build`, Then exit code 1, stderr chứa ``run `aml er` first`` và `case_runs`, `audit_log` không có dòng `cases` nào; và Given đã `aml er` nhưng chưa `aml screen`, `aml monitor`, `aml network`, Then exit code 1 với stderr chứa ``run `aml screen` or `aml monitor` first``.
- AC10: [oracle] (Schema Oracle dùng chung và giữ lịch sử: test ghim `graph_features = networkx`; `opened` và số dòng audit của Oracle tính theo các `case_id` đã có trước đó — 52 và 53 trên schema sạch, 0 và 1 khi chạy lại.) Given TINY nạp vào cả Oracle và một DuckDB tạm, cả hai đã `run_er`, `run_screening`, `run_monitoring`, `run_network`, `run_dq` với `as_of = 2026-06-30`, When gọi `run_cases` trên hai backend, Then `items`, `alerts`, `active`, `cases`, `opened`, `graph_source` của hai `CaseRun` bằng nhau (74, 40, 74, 52, 52, `networkx`); tập (`case_id`, `golden_customer_id`, `alerts`, `sources`, `status`, `reason`) của `cases_current` và tập (`item_key`, `golden_customer_id`, `case_id`, `source`, `rule_id`, `cif`) của `case_alerts_current` bằng nhau giữa hai backend; `content` của sáu khối enrichment của `C-CIF00000189-20260413` bằng nhau sau khi phân tích JSON (số thực so với sai số 1e-9); trên Oracle `user_tables` có `CASE_RUNS`, `CASES`, `CASE_ALERTS`, `CASE_ENRICHMENT`, `CASE_DISPOSITIONS` và `user_views` có `CASES_CURRENT`, `CASE_ALERTS_CURRENT`, `CASE_ENRICHMENT_CURRENT`, `CASE_DISPOSITIONS_CURRENT`; số dòng `audit_log` `module='cases'` của lần chạy trên Oracle (lọc theo `details.run_id` hoặc `entity_id` của run) là 53; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- **Suppression** (good-guy list, hibernation, `status = 'SUPPRESSED'`, `retriggered`) — `specs/case-suppression.md`; 7a chỉ tạo cột và luôn ghi `ACTIVE` / 0.
- **Chấm điểm ưu tiên**, bảng feature, model, disposition mô phỏng từ ground truth, lệnh `aml score` — `specs/case-prioritization.md`. **Case summary** markdown và `NarrativeGenerator` — `specs/case-summary.md`.
- Phase 7b của brief: Isolation Forest và alert nguồn `ANOMALY`, mô hình screening học được, mẫu below-the-line, model card, phân loại memo bằng LLM. Điểm mở rộng để lại: cột `source` của `case_alerts` nhận nguồn mới mà không đổi schema; `case_enrichment` nhận `section` mới.
- Một case cho cả nhóm (case theo ring / theo vòng tiền); gộp case giữa các golden customer; tách / nhập case thủ công; giao case cho người xử lý, SLA, hàng đợi, ghi chú, đính kèm, escalation nhiều cấp, lập STR.
- Sửa `alerts`, `screening_results`, `er_golden`, `dq_results`; thêm cột thời gian vào `screening_results`; bảng `dq_failures` lưu toàn bộ thực thể lỗi (Q5); đổi `run_dq`.
- Đọc Neo4j trực tiếp, k-hop neighbourhood quá 1 hop, node `Case` / quan hệ `MATCHES_TYPOLOGY` trên Neo4j (Phase 8); đồ thị Cytoscape (Phase 9).
- Giữ ổn định `case_id` khi `golden_customer_id` đổi giữa hai lần `aml er` (hạn chế đã biết của Phase 4); chuyển disposition sang case mới khi cụm ER đổi.
- API FastAPI, UI, che PII theo role (Phase 9); quyền Oracle trên các bảng `case*` cho role của 2b (cùng hướng với 3b Q15: bổ sung ở Phase 9 khi có người dùng không phải owner).
- Đo hiệu năng trên `large`; chạy đồng thời hai `run_cases`; ghi số liệu vào README (bước demo, từ lần chạy thật trên `small`).

## Giả định
- **Đã xác nhận (2026-10-13, xem Câu hỏi mở)**: cửa sổ neo vào alert đầu tiên, 90 ngày (Q1); alert nhóm gắn vào case của mọi golden customer trong nhóm (Q2 — người dùng xác nhận trực tiếp); mốc của screening hit = `as_of` của lần screening đầu tiên ghi nhận cặp đó (Q3); tóm tắt 90 ngày kết thúc ở ngày của alert cuối (Q4); DQ issues qua hàm chỉ đọc `failing_ids`, không đổi `run_dq` (Q5); `graph_features: auto`, không kết nối Neo4j (Q6); hai giá trị disposition, chỉ người ghi (Q7); nhóm lệnh `aml cases` + `aml score` (Q8).
- **Đã đo** bằng prototype ngoài repo: mọi con số TINY / `small` ở mục Hiện trạng và trong AC8, AC9 (trừ `graph_features=networkx` trên CLI và số dòng audit, suy ra từ thiết kế). **Suy ra bằng tay, chưa chạy**: mọi giá trị MINI-C (AC2–AC7), AC10. Nếu khi hiện thực số đo lệch do chi tiết sắp xếp / biên cửa sổ, cập nhật spec chứ không sửa luật.
- Các AC trên TINY chỉ cam kết cho TINY seed 42 với cấu hình mặc định của Phase 3–5; `as_of` mặc định là `settings.data.reference_date`, không dùng đồng hồ máy ngoài `run_ts` / `decided_ts` / `event_ts` của audit (UTC).
- Enrichment không chép PII: tên, số giấy tờ, điện thoại, email, địa chỉ chỉ được nối lúc đọc (`load_case`) từ `customers_masked` (mặc định) hoặc `customers` — nhất quán với 3b Q14 và Phase 4. Memo giao dịch không bao giờ vào enrichment (memo có thể chứa prompt injection; Phase 8 tự xử lý).
- Tóm tắt giao dịch tính trên `transactions` nguyên trạng, kể cả giao dịch trùng do defect DQ (như 5a); số giao dịch trùng lộ ra ở `dq_issues.transactions`.
- `run_cases` là chạy lại toàn bộ (như `run_er`, `run_monitoring`): mỗi lần ghi một ảnh chụp đầy đủ dưới `run_id` mới; danh tính ổn định giữa các lần là `case_id` và `item_key`. `small`: mỗi lần thêm khoảng 335 dòng `cases`, 475 dòng `case_alerts`, 2010 dòng `case_enrichment`.
- Alert của một lần chạy nguồn có `as_of` muộn hơn `as_of` của `run_cases` bị loại nhờ lọc `event_ts`; `run_cases` không tự chạy lại nguồn nào.
- Lệnh chạy dưới schema owner; `reason`, thông điệp lỗi, output CLI bằng tiếng Anh như các lệnh hiện có. Test [oracle] nạp lại TINY và để lại dòng trong `case*` / `audit_log`.
- `aml cases dispose` là đường nhập quyết định của người cho tới khi có UI (Phase 9); không có xác thực người dùng ở CLI — `--actor` là lời khai.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** "Rolling window" nghĩa là gì và dài bao nhiêu? — đề xuất mặc định: cửa sổ **neo vào alert đầu tiên** của case (alert sau vào case khi cách alert đầu dưới `cases.window_days` = **90** ngày; quá thì mở case mới), như cách 5a gộp "đợt". Lý do: tất định, là hàm thuần của tập alert nên `case_id` ổn định giữa các lần chạy; 90 ngày trùng tầm nhìn của tóm tắt giao dịch. Đã đo: 30 / 90 / không giới hạn cho 53 / 52 / 52 case (TINY) và 336 / 335 / 333 (`small`) — trên dữ liệu tổng hợp gần như không khác. Phương án thay thế: gộp theo khoảng lặng (alert cách alert **liền trước** dưới N ngày — case có thể kéo dài vô hạn), hoặc "mọi alert vào case đang mở của khách hàng, bất kể thời gian". — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q2. **(cần người dùng quyết)** Alert nhóm của 5c (cụm dùng chung thuộc tính, vòng tiền) gắn vào case nào? — đề xuất mặc định: gắn vào case của **mọi** golden customer có tài khoản trong alert (một alert → nhiều case), mỗi case ghi `shared_alert_cases` để investigator thấy các case liên quan. Lý do: brief ghi rõ "one case per golden customer". Hệ quả đã đo: một mule ring 29 người của TINY thành 29 case (21 case chỉ có đúng alert cụm); `small`: 5 alert cụm → khoảng 104 case. Phương án thay thế: chỉ gắn vào vai chính (`ORIGIN`, `SUBJECT`, và thành viên cụm có alert khác) — ít case hơn nhưng thành viên "im lặng" của ring không được ai xem. — Trả lời: theo đề xuất mặc định (người dùng xác nhận trực tiếp, 2026-10-13).
- [x] Q3. **(cần người dùng quyết)** Screening hit không có mốc thời gian sự kiện — đặt vào cửa sổ nào? — đề xuất mặc định: mốc = ngày `as_of` của lần screening **đầu tiên** ghi nhận cặp đó là `ALERT` / `REVIEW` (suy từ `screening_results` + `screening_runs`, không thêm cột). Lý do: ổn định khi chạy lại screening; không đổi schema 3b. Hệ quả: trong demo mọi screening hit có mốc 2026-06-30, nên khách hàng có alert giao dịch từ trước 2026-04-01 sẽ có case screening riêng. Phương án thay thế: screening hit luôn nhập vào case mới nhất của khách hàng. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q4. Tóm tắt giao dịch 90 ngày tính tới ngày nào? — đề xuất mặc định: 90 ngày kết thúc ở **ngày của alert cuối** trong case (`last_alert_ts`), không phải `as_of` của lần chạy. Lý do: case tháng 1 xem lúc tháng 6 vẫn phải thấy hoạt động quanh alert; kết quả không đổi khi chạy lại vào ngày khác. Phương án thay thế: 90 ngày gần nhất tính từ `as_of`. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q5. **(cần người dùng quyết)** "DQ issues của khách hàng" lấy từ đâu khi `dq_results` chỉ lưu mẫu 20 id? — đề xuất mặc định: thêm hàm chỉ đọc `failing_ids` vào `aml.dq.runner` (tách từ `_evaluate`, không đổi `run_dq`) và `run_cases` gọi nó lúc enrich. Lý do: không đổi schema 2c đã duyệt, không cần `aml dq run` trước. Cái giá: mỗi lần `run_cases` chạy lại các câu kiểm DQ (10 rule; `small` dưới 1 giây theo số đo của 2c). Phương án thay thế: thêm bảng `dq_failures(run_id, rule_id, entity_id)` vào DQ framework (sửa spec 2c-ii) và đọc từ đó. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q6. **(cần người dùng quyết)** Graph features lấy từ NetworkX hay GDS, và khi Neo4j không chạy? — đề xuất mặc định: `cases.graph_features: auto` — dùng `gds_account_features_current` khi nó có dòng và cùng `as_of` với lần chạy, ngược lại `nx_account_features_current`; `run_cases` không bao giờ kết nối Neo4j; khối `network` ghi `source` đã dùng. Lý do: Phase 7 chạy được DuckDB-only; 6b-ii đã đo hai nguồn cho cùng degree / PageRank (lệch ≤ 2e-4). Hệ quả: `cycle_alerts`, `is_hub` chỉ có ở nguồn NetworkX, `wcc_size`, `louvain_size` chỉ có ở GDS — khoá thiếu là null. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q7. Disposition có những giá trị nào và ai được ghi? — đề xuất mặc định: hai giá trị `SUSPICIOUS` / `FALSE_POSITIVE`, chỉ ghi qua `record_disposition` với `actor` là người (actor hệ thống bị từ chối); bảng append-only, quyết định sau thay quyết định trước; case `CLOSED` tự thành `REOPENED` khi có alert mới. Lý do: đủ cho nhãn huấn luyện (7c) và suppression (7b-supp); "máy không bao giờ đóng case" được bảo đảm ngay ở đường ghi. Phương án thay thế: thêm `ESCALATED` / `STR_FILED` / `NEEDS_INFO` (workflow đầy đủ — ngoài phạm vi demo). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q8. Hình dạng CLI của Phase 7? — đề xuất mặc định: nhóm `aml cases` (`build`, `show`, `dispose` ở 7a; 7b-supp thêm `suppressed`; 7c thêm `label`, `train`; 7d thêm `summary`) và `aml score` (7c) chạy cả chuỗi để `make score` / `make all` giữ nguyên. Lý do: giống `aml graph sync|query|gds`; từng bước demo được riêng. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
