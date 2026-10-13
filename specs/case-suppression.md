---
id: case-suppression
status: approved
approved_by: pthieu
---

# Phase 7b-supp — Suppression: good-guy list cho screening hit đã clear, hibernation cho pattern false-positive lặp lại

## Bối cảnh
Phần "Suppression" của Phase 7 trong PROJECT_BRIEF.md (mục 8), dựng trên `specs/case-consolidation.md` (7a: `case_alerts`
có cột `status` / `suppression_rule` / `suppression_reason` / `retriggered`, `record_disposition`, `run_cases`). Hai cơ
chế: (1) **good-guy list** — cặp (CIF, watchlist entry) đã được investigator clear thì không sinh việc lại cho tới ngày
hết hạn, và tự bật lại khi dữ liệu khách hàng hoặc watchlist entry đổi; (2) **hibernation** — pattern (golden customer,
rule) đã nhiều lần là false positive thì alert mới của pattern đó được "ngủ" N ngày, trừ khi hành vi đổi đáng kể.
**Suppression tác động ở mức item, bên trong `run_cases`, sau khi gom item và trước khi gộp thành case**: item bị
suppress vẫn được lưu (`status = 'SUPPRESSED'`, có `suppression_reason`), được audit, nhưng không vào case nào và không
neo cửa sổ. Suppression **không đóng case, không sửa alert gốc, không sửa disposition**; nguồn sự thật duy nhất của nó
là disposition do người ghi. Người dùng: investigator (hàng đợi ngắn hơn), kiểm soát nội bộ (xem lại item bị suppress
kèm lý do), Phase 9 (số liệu "alert volume trước / sau suppression", mẫu below-the-line).

### Hiện trạng đã kiểm (2026-10-13, seed 42)
- **Dấu vân tay đã có sẵn**: `screening_state(entity_type, entity_id, fingerprint, run_id)` (3c) lưu SHA-256 của các
  trường tham gia screening — khách hàng: tên chuẩn hoá, `dob`, `nationality`, `gender`, `id_number`; watchlist entry:
  `list_type`, ba cột DOB, `nationality`, mọi tên + alias. Lần `FULL` ghi lại toàn bộ, lần incremental cập nhật phần
  đổi; `aml.screening.state.read_state(db)` đọc về `{entity_type: {entity_id: fingerprint}}`. Đây đúng là định nghĩa
  "dữ liệu khách hàng hoặc watchlist đổi" mà brief cần — không phải đặt thêm khái niệm mới. DuckDB tạm của TINY sau
  `run_screening`: 300 dòng `customer`, 200 dòng `watchlist_entry`.
- **Chưa có disposition thật**: mọi disposition trong demo đến từ `record_disposition` — do test gọi, do `aml cases
  dispose`, hoặc do bộ mô phỏng của 7c (`origin = 'SIMULATED'`). Vì vậy lần `run_cases` đầu tiên luôn có 0 item bị
  suppress; suppression chỉ có tác dụng từ lần chạy thứ hai, sau khi có disposition.
- **Cái gì lặp lại giữa các lần chạy**: screening là *trạng thái* — cặp (CIF, entry) còn khớp thì lần chạy nào cũng
  hiện lại với cùng `item_key`; rule / network là *sự kiện* — chạy lại trên cùng dữ liệu cho lại đúng các `alert_key`
  cũ, dữ liệu mới cho `alert_key` mới. Trên `small` (prototype 7a + nhãn ground truth, đo read-only): 34 case chỉ có
  screening là false positive (cặp `ALERT` / `REVIEW` không phải true hit) — đây là khối lượng good-guy list gỡ được;
  chỉ 2 case rule là false positive, nên hibernation gần như không có gì để làm trên dữ liệu tổng hợp hiện tại (Q5).
- **`audit_log.entity_id` rộng 100 ký tự** trong khi `alert_key` rộng tới 300 (`NET_CYCLE|A…>A…>A…>A…|…`) → sự kiện
  audit theo item không dùng `item_key` làm `entity_id` được.
- `SCHEMA_SCRIPTS`: 7a dùng `160` → spec này dùng **`170`**.
- **Chưa đo**: mọi giá trị trong AC (suy ra bằng tay từ luật trên MINI-S; TINY suy từ số đo của 7a); DDL `170`; Oracle.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class SuppressionConfig(BaseModel):
    good_guy_days: int  # >= 1; hạn của một dòng good-guy tính từ ngày clear
    hibernation_days: int  # >= 1; số ngày "ngủ" tính từ lần clear gần nhất của pattern
    hibernation_min_false_positives: int  # >= 1; số alert false positive của pattern để bắt đầu ngủ
    material_change_ratio: (
        float  # >= 1.0; amount_vnd > ratio * alert đã clear lớn nhất -> không suppress
    )


class CasesConfig(BaseModel):
    ...
    suppression: SuppressionConfig


# src/aml/cases/suppression.py
SUPPRESSION_VERSION = "suppression/v1"
GOOD_GUY, HIBERNATION = "GOOD_GUY", "HIBERNATION"


@dataclass(frozen=True)
class GoodGuyEntry:
    entry_no: int
    cif: str
    entry_id: str
    case_id: str
    disposition_id: int
    cleared_on: date
    expires_on: date
    customer_fingerprint: str
    entry_fingerprint: str
    actor: str


@dataclass(frozen=True)
class Verdict:
    suppress: bool
    lifted: bool  # có entry / pattern nhưng không áp dụng vì hết hạn, đổi dữ liệu hoặc đổi hành vi
    retriggered: bool  # item quay lại case đã đóng -> case thành REOPENED
    reason: str | None  # None khi không có entry / pattern nào liên quan


def good_guy_verdict(
    entry: GoodGuyEntry | None,
    *,
    as_of: date,
    customer_fingerprint: str | None,
    entry_fingerprint: str | None,
    latest_disposition_id: int | None,  # disposition mới nhất của entry.case_id
) -> Verdict: ...


@dataclass(frozen=True)
class HibernationPattern:
    golden_customer_id: str
    rule_id: str
    false_positives: int  # số item_key khác nhau đã được clear
    cleared_on: date  # ngày clear gần nhất
    max_amount_vnd: int  # alert đã clear lớn nhất
    handled: frozenset[str]  # item_key đã nằm trong case được clear


def hibernation_verdict(
    pattern: HibernationPattern | None,
    *,
    item_key: str,
    event_ts: datetime,
    amount_vnd: int,
    cfg: SuppressionConfig,
) -> Verdict: ...


def evaluate_suppression(
    db: Database, settings: Settings, items: pd.DataFrame, *, as_of: date
) -> pd.DataFrame: ...


# không ghi gì; trả items + cột status, suppression_rule, suppression_reason, retriggered, lifted


def add_good_guys(
    db: Database, settings: Settings, case_id: str, disposition_id: int
) -> (
    int
): ...  # số dòng good_guy_list đã thêm; record_disposition gọi khi disposition = FALSE_POSITIVE
```
- `config.yaml`: `cases.suppression: {good_guy_days: 365, hibernation_days: 90, hibernation_min_false_positives: 2,
  material_change_ratio: 1.5}`.
- DDL `sql/duckdb/ddl/170_case_suppression.sql` và bản Oracle, thêm vào `SCHEMA_SCRIPTS` sau `ddl/160_cases.sql` và
  trước các script `050_*`: bảng `good_guy_list`, view `good_guy_current`.
- `CaseRun` (7a) thêm trường `suppressed_by_rule: dict[str, int]` (đủ hai khoá `GOOD_GUY`, `HIBERNATION`, kể cả 0) và
  `lifted: int`.
- CLI: `aml cases build` in thêm hai dòng `GOOD_GUY suppressed=<n>` và `HIBERNATION suppressed=<n>`; lệnh mới `aml
  cases suppressed [--limit N]` liệt kê item `SUPPRESSED` của lần chạy hiện hành kèm lý do.
- **Sửa kéo theo ở 7a — là một phần của spec này**: `run_cases` gọi `evaluate_suppression` giữa `collect_items` và
  `assign_cases`; `record_disposition` gọi `add_good_guys` khi `disposition = FALSE_POSITIVE`.

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **Vị trí trong pipeline**: `collect_items` → **`evaluate_suppression`** → `assign_cases` (chỉ item `ACTIVE`) →
  enrichment → ghi. Item `SUPPRESSED` được ghi vào `case_alerts` với `case_id` null, `suppression_rule`,
  `suppression_reason`; không tính vào `cases.alerts`, không neo cửa sổ, không vào feature của 7c. Một case mà mọi item
  đều bị suppress thì không có dòng trong lần chạy đó (ảnh chụp cũ và disposition của nó vẫn còn, và vẫn hiện ở
  `history.prior_cases`).
- **Good-guy list** (chỉ cho item `SCREENING`):
  - Bảng `good_guy_list(entry_no PK, cif, entry_id, case_id, disposition_id, cleared_on, expires_on,
    customer_fingerprint, entry_fingerprint, actor, created_ts UTC)`, append-only; view `good_guy_current` = dòng có
    `entry_no` lớn nhất của từng (`cif`, `entry_id`).
  - **Thêm dòng**: khi `record_disposition(..., FALSE_POSITIVE)` thành công, với mỗi item `SCREENING` `ACTIVE` của case
    trong ảnh chụp của disposition: `cleared_on = decided_on`, `expires_on = decided_on + good_guy_days` ngày, hai dấu
    vân tay đọc từ `screening_state` lúc đó. Thiếu dấu vân tay của CIF hoặc của entry → không thêm dòng, ghi audit
    `GOOD_GUY_SKIPPED`. Disposition `SUSPICIOUS` không thêm gì.
  - **Áp dụng** (`good_guy_verdict`, xét dòng `good_guy_current` của cặp; theo thứ tự, dừng ở điều kiện đầu tiên khớp):
    1. không có dòng → `Verdict(False, False, False, None)`;
    2. `disposition_id` của dòng không còn là disposition mới nhất của `case_id` đó (đã có quyết định sau thay thế) →
       không suppress, không lifted, không retriggered — quyết định sau là thứ có hiệu lực;
    3. `as_of > expires_on` → lifted + retriggered, lý do `good-guy entry for {cif} x {entry_id} expired on {expires_on}; alert re-raised`;
    4. dấu vân tay khách hàng hiện tại khác (hoặc không còn) → lifted + retriggered, `customer data of {cif} changed since the clearance on {cleared_on}; alert re-raised`;
    5. dấu vân tay entry hiện tại khác (hoặc không còn) → lifted + retriggered, `watchlist entry {entry_id} changed since the clearance on {cleared_on}; alert re-raised`;
    6. còn lại → suppress, `good-guy list: {cif} x {entry_id} cleared on {cleared_on} by {actor} (case {case_id}); valid until {expires_on}; customer and watchlist entry unchanged`.
  - Item retriggered là `ACTIVE` với `retriggered = 1`; theo luật trạng thái của 7a, case chứa nó thành `REOPENED`.
    Investigator clear lại → dòng good-guy mới (dấu vân tay mới, hạn mới) → lần chạy sau lại suppress.
- **Hibernation** (chỉ cho item `RULE` / `NETWORK`; pattern = (`golden_customer_id`, `rule_id`)):
  - **Alert đã clear của pattern** = item `ACTIVE` nguồn `RULE` / `NETWORK` trong ảnh chụp (`run_id` của disposition,
    `case_id`) của những case mà **disposition mới nhất** là `FALSE_POSITIVE`. `false_positives` = số `item_key` khác
    nhau; `cleared_on` = `decided_on` lớn nhất; `max_amount_vnd` = `amount_vnd` lớn nhất; `handled` = tập `item_key` đó.
  - **Áp dụng** (`hibernation_verdict`, theo thứ tự):
    1. không có pattern, hoặc `false_positives < hibernation_min_false_positives` → `Verdict(False, False, False, None)`;
    2. `item_key` ∈ `handled` → không suppress (alert cũ ở lại trong case đã đóng của nó);
    3. ngày của `event_ts` > `cleared_on + hibernation_days` → không suppress (hết thời gian ngủ);
    4. `amount_vnd > material_change_ratio × max_amount_vnd` → lifted, lý do `hibernation of {rule_id} on {golden_customer_id} lifted: amount {amount_vnd:,} VND is above {ratio}x the largest cleared alert ({max_amount_vnd:,} VND)`;
    5. còn lại → suppress, `hibernated: {rule_id} on {golden_customer_id} was a false positive {false_positives} time(s), last cleared on {cleared_on}; suppressed until {until}; amount {amount_vnd:,} VND is not above {ratio}x the largest cleared alert ({max_amount_vnd:,} VND)` với `until = cleared_on + hibernation_days`.
  - Hibernation không có bảng riêng: pattern là hàm thuần của `case_dispositions` + `case_alerts`, tính lại mỗi lần
    chạy. Case được clear rồi bị đổi thành `SUSPICIOUS` thì các alert của nó tự rời khỏi mọi pattern.
- **Audit** (`module='cases'`, `version=SUPPRESSION_VERSION`), mỗi lần `run_cases`:
  - mỗi item bị suppress: `entity_type='alert_item'`, `entity_id='<alert_ref>@<golden_customer_id>'` (ngắn hơn 100 ký
    tự; `item_key` nằm trong `details`), `decision='SUPPRESSED'`, `reason` = `suppression_reason`, `details = {run_id,
    item_key, rule, source, rule_id, cleared_on, until}`;
  - mỗi item lifted: cùng `entity_type` / `entity_id`, `decision='SUPPRESSION_LIFTED'`, `reason` như trên;
  - sự kiện `CASE_RUN_COMPLETED` của 7a có thêm `details.suppressed_by_rule` và `details.lifted`.
  - Lúc ghi disposition: mỗi dòng good-guy mới một sự kiện `entity_type='good_guy'`, `entity_id='<cif>:<entry_id>'`,
    `decision='GOOD_GUY_ADDED'`, `actor` = người ghi disposition, `reason` = `{cif} x {entry_id} cleared as a false positive in case {case_id}; suppressed until {expires_on} unless the customer or the watchlist entry changes`,
    `details = {entry_no, case_id, disposition_id, cleared_on, expires_on}`; thiếu dấu vân tay → `GOOD_GUY_SKIPPED` với
    `reason` chứa `no screening fingerprint`.

## Tiêu chí nghiệm thu
<!-- settings, as_of, M như specs/case-consolidation.md. MINI-S = MINI-C của 7a, cộng thêm:
  screening_state (run_id 1): ('customer', 'C02', 'fp-c02'), ('customer', 'C05', 'fp-c05'),
    ('watchlist_entry', 'WL1', 'fp-wl1'), ('watchlist_entry', 'WL2', 'fp-wl2');
  hai alert RULE trong cùng lần `record_run` với R1..R4: H1 HIGH_VELOCITY A04 2026-02-01 09:00:00 -> 2026-02-01 10:00:00
    100M; H2 HIGH_VELOCITY A04 2026-02-20 09:00:00 -> 2026-02-20 10:00:00 120M (không có txn_ids).
  Run 1 trên MINI-S vì vậy có 11 item, 5 case: C-C01-20260302 (3), C-C01-20260531 (2), C-C03-20260305 (2),
    C-C04-20260201 (H1, H2, N1), C-C05-20260630 (S2).
HIB = lần `record_run(source="RULE", rules=[HIGH_VELOCITY], alerts=[H1, H2, H3, H4, H5, H6, H7])` với (đều trên A04, kéo dài
  1 giờ): H3 2026-04-10 09:00:00 150M; H4 2026-04-15 09:00:00 180M; H5 2026-04-20 09:00:00 180 000 001;
  H6 2026-06-09 09:00:00 100M; H7 2026-06-08 23:00:00 100M.
E = GoodGuyEntry(entry_no=1, cif="C05", entry_id="WL2", case_id="C-C05-20260630", disposition_id=1,
  cleared_on=date(2026, 6, 30), expires_on=date(2027, 6, 30), customer_fingerprint="fp-c05", entry_fingerprint="fp-wl2",
  actor="analyst01"). Mọi giá trị suy ra bằng tay từ luật. -->
- AC1: Given `config.yaml`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, đọc `SCHEMA_SCRIPTS` và gọi `apply_schema(duck)` hai lần, Then `settings.cases.suppression` = (`good_guy_days` 365, `hibernation_days` 90, `hibernation_min_false_positives` 2, `material_change_ratio` 1.5); `load_settings(environ={"AML__CASES__SUPPRESSION__GOOD_GUY_DAYS": "0"})` raise `pydantic.ValidationError` chứa `good_guy_days must be >= 1`, `AML__CASES__SUPPRESSION__MATERIAL_CHANGE_RATIO=0.9` raise `ValidationError` chứa `material_change_ratio must be >= 1.0` và `AML__CASES__SUPPRESSION__HIBERNATION_MIN_FALSE_POSITIVES=0` raise `ValidationError` chứa `hibernation_min_false_positives must be >= 1`; `ddl/170_case_suppression.sql` có trong `SCHEMA_SCRIPTS` của cả hai backend, đứng sau `ddl/160_cases.sql` và trước các script `050_*`; `apply_schema` không raise; `SELECT COUNT(*)` trên `good_guy_list` và `good_guy_current` đều trả 0; `SUPPRESSION_VERSION == "suppression/v1"`.
- AC2: Given hàm thuần `good_guy_verdict` và `E`, When gọi với `latest_disposition_id=1` trừ khi nói khác, Then `good_guy_verdict(None, as_of=date(2026, 7, 1), customer_fingerprint="fp-c05", entry_fingerprint="fp-wl2", latest_disposition_id=None)` trả `Verdict(False, False, False, None)`; với `E`, `as_of=date(2026, 7, 1)` và hai dấu vân tay khớp trả `suppress=True`, `lifted=False`, `retriggered=False`, `reason` bằng đúng `good-guy list: C05 x WL2 cleared on 2026-06-30 by analyst01 (case C-C05-20260630); valid until 2027-06-30; customer and watchlist entry unchanged`; `as_of=date(2027, 6, 30)` (đúng ngày hết hạn) vẫn `suppress=True`; `as_of=date(2027, 7, 1)` trả `suppress=False`, `lifted=True`, `retriggered=True`, `reason` bằng đúng `good-guy entry for C05 x WL2 expired on 2027-06-30; alert re-raised`; `customer_fingerprint="fp-c05-v2"` trả `suppress=False`, `lifted=True`, `retriggered=True`, `reason` bằng đúng `customer data of C05 changed since the clearance on 2026-06-30; alert re-raised`; `entry_fingerprint="fp-wl2-v2"` trả `reason` bằng đúng `watchlist entry WL2 changed since the clearance on 2026-06-30; alert re-raised`; `customer_fingerprint=None` cũng trả `lifted=True` với `reason` bắt đầu bằng `customer data of C05 changed`; khi cả ngày hết hạn đã qua lẫn dấu vân tay khách hàng đổi thì `reason` bắt đầu bằng `good-guy entry for C05 x WL2 expired`; và `latest_disposition_id=2` (đã có quyết định sau) trả `Verdict(False, False, False, None)` dù dấu vân tay khớp và chưa hết hạn.
- AC3: Given MINI-S đã `run_cases` (run 1: `items = 11`, `suppressed = 0`, `cases = 5`, `suppressed_by_rule == {"GOOD_GUY": 0, "HIBERNATION": 0}`), When gọi `record_disposition(duck, settings, "C-C05-20260630", "FALSE_POSITIVE", reason="namesake, different person", actor="analyst01", decided_on=date(2026, 6, 30))` rồi `run_cases` (run 2), Then `good_guy_list` có đúng 1 dòng (`entry_no` 1, `cif` `C05`, `entry_id` `WL2`, `case_id` `C-C05-20260630`, `disposition_id` 1, `cleared_on` 2026-06-30, `expires_on` 2027-06-30, `customer_fingerprint` `fp-c05`, `entry_fingerprint` `fp-wl2`, `actor` `analyst01`); `audit_log` có 1 dòng `decision='GOOD_GUY_ADDED'`, `entity_type='good_guy'`, `entity_id='C05:WL2'`, `actor='analyst01'`, `version='suppression/v1'`, `reason` bằng đúng `C05 x WL2 cleared as a false positive in case C-C05-20260630; suppressed until 2027-06-30 unless the customer or the watchlist entry changes`; run 2 trả `items = 11`, `suppressed = 1`, `active = 10`, `cases = 4`, `closed = 0`, `suppressed_by_rule == {"GOOD_GUY": 1, "HIBERNATION": 0}`, `lifted = 0`; trong `case_alerts_current` dòng `item_key = 'SCREENING|C05|WL2'` có `status = 'SUPPRESSED'`, `suppression_rule = 'GOOD_GUY'`, `case_id` null, `retriggered = 0` và `suppression_reason` bằng đúng chuỗi `good-guy list: C05 x WL2 cleared on 2026-06-30 by analyst01 (case C-C05-20260630); valid until 2027-06-30; customer and watchlist entry unchanged`; `cases_current` không có `C-C05-20260630` trong khi `cases` vẫn có dòng (`run_id` 1, `C-C05-20260630`) và `case_dispositions` vẫn có dòng của nó; 10 dòng còn lại của `case_alerts_current` đều `ACTIVE`; `audit_log` của run 2 có đúng 1 dòng `decision='SUPPRESSED'` với `entity_type='alert_item'`, `entity_id='C05:WL2@G-C05'`, `details.item_key = "SCREENING|C05|WL2"`, `details.rule = "GOOD_GUY"`; When tiếp tục `record_disposition(duck, settings, "C-C01-20260531", "FALSE_POSITIVE", reason="same name, older person", actor="analyst01", decided_on=date(2026, 6, 30))` rồi `run_cases` (run 3), Then `good_guy_list` có thêm dòng (`C02`, `WL1`), run 3 có `suppressed = 2`, và `C-C01-20260531` còn `alerts = 1` (chỉ R3), `sources = 'RULE'`, `status = 'CLOSED'`; và `record_disposition(duck, settings, "C-C03-20260305", "SUSPICIOUS", reason="layering", actor="analyst01")` không thêm dòng nào vào `good_guy_list`.
- AC4: Given MINI-S ở trạng thái sau run 2 của AC3 (cặp `C05` × `WL2` đang bị suppress), When dữ liệu hoặc ngày đổi rồi gọi `run_cases`, Then sau `UPDATE screening_state SET fingerprint = 'fp-c05-v2' WHERE entity_id = 'C05'`: `suppressed = 0`, `lifted = 1`, dòng `SCREENING|C05|WL2` có `status = 'ACTIVE'`, `retriggered = 1`, `case_id = 'C-C05-20260630'`, case đó có `status = 'REOPENED'`, `run.reopened = 1`, và `audit_log` có 1 dòng `decision='SUPPRESSION_LIFTED'`, `entity_id='C05:WL2@G-C05'` với `reason` bằng đúng `customer data of C05 changed since the clearance on 2026-06-30; alert re-raised`; khi tiếp đó gọi `record_disposition(duck, settings, "C-C05-20260630", "FALSE_POSITIVE", reason="reviewed again after the KYC update", actor="analyst02", decided_on=date(2026, 7, 5))` và `run_cases`, thì `good_guy_list` có dòng `entry_no = 2` với `customer_fingerprint = 'fp-c05-v2'`, `expires_on = 2027-07-05`, `actor = 'analyst02'`, và cặp lại `SUPPRESSED` với `suppression_reason` chứa `cleared on 2026-07-05 by analyst02`; Given lại trạng thái sau run 2 của AC3 và `UPDATE screening_state SET fingerprint = 'fp-wl2-v2' WHERE entity_id = 'WL2'`, Then dòng lifted có `reason` bằng đúng `watchlist entry WL2 changed since the clearance on 2026-06-30; alert re-raised`; Given lại trạng thái sau run 2 của AC3, Then `run_cases(duck, settings, as_of=date(2027, 6, 30))` vẫn có `suppressed = 1`, còn `run_cases(duck, settings, as_of=date(2027, 7, 1))` có `suppressed = 0`, `lifted = 1` và `reason` của dòng lifted bằng đúng `good-guy entry for C05 x WL2 expired on 2027-06-30; alert re-raised`; Given lại trạng thái sau run 2 của AC3 và `record_disposition(duck, settings, "C-C05-20260630", "SUSPICIOUS", reason="second review: true match", actor="lead01")`, Then lần `run_cases` kế tiếp có `suppressed = 0`, `lifted = 0`, dòng `SCREENING|C05|WL2` là `ACTIVE` với `retriggered = 0`, case `C-C05-20260630` có `status = 'CLOSED'` và không có dòng audit `SUPPRESSED` hay `SUPPRESSION_LIFTED` nào cho lần chạy đó; và Given MINI-S **không có** dòng `screening_state` của `WL1`, When `record_disposition(duck, settings, "C-C01-20260531", "FALSE_POSITIVE", reason="x", actor="analyst01")`, Then `good_guy_list` không có dòng nào của `C02`, `audit_log` có 1 dòng `decision='GOOD_GUY_SKIPPED'`, `entity_id='C02:WL1'` với `reason` chứa `no screening fingerprint`, và lần `run_cases` kế tiếp vẫn có `SCREENING|C02|WL1` là `ACTIVE`.
- AC5: Given MINI-S đã `run_cases` (run 1), `record_disposition(duck, settings, "C-C04-20260201", "FALSE_POSITIVE", reason="payroll batches of a registered business", actor="analyst01", decided_on=date(2026, 3, 10))`, rồi HIB, When gọi `run_cases` (run 2), Then `run.items = 16`, `run.suppressed = 3`, `run.active = 13`, `run.cases = 6`, `suppressed_by_rule == {"GOOD_GUY": 0, "HIBERNATION": 3}`, `lifted = 1`; H3, H4 (đúng bằng 1.5 × 120M) và H7 (ngày 2026-06-08 = ngày cuối của thời gian ngủ) có `status = 'SUPPRESSED'`, `suppression_rule = 'HIBERNATION'`, `case_id` null; `suppression_reason` của H3 bằng đúng `hibernated: HIGH_VELOCITY on G-C04 was a false positive 2 time(s), last cleared on 2026-03-10; suppressed until 2026-06-08; amount 150,000,000 VND is not above 1.5x the largest cleared alert (120,000,000 VND)`; H1, H2 và N1 của `G-C04` vẫn `ACTIVE` trong `C-C04-20260201`; H5 là `ACTIVE`, `retriggered = 0`, `case_id = 'C-C04-20260201'`, case đó có `alerts = 4` và `status = 'REOPENED'`, và có 1 dòng audit `decision='SUPPRESSION_LIFTED'` với `reason` bằng đúng `hibernation of HIGH_VELOCITY on G-C04 lifted: amount 180,000,001 VND is above 1.5x the largest cleared alert (120,000,000 VND)`; H6 (2026-06-09, sau thời gian ngủ) là `ACTIVE` trong case mới `C-C04-20260609` có `alerts = 1` — case này không mang ngày 20260608 của H7 (item bị suppress không neo cửa sổ) — và không có dòng audit `SUPPRESSION_LIFTED` cho H6; N1 của `G-C04` không bị suppress (pattern `NET_CYCLE` mới có 1 alert đã clear) và N1 của `G-C01`, `G-C03` không đổi; không item `SCREENING` nào có `suppression_rule = 'HIBERNATION'`; `history.suppressed_items` của `C-C04-20260609` bằng 3; với `AML__CASES__SUPPRESSION__HIBERNATION_MIN_FALSE_POSITIVES=3` cùng dữ liệu thì `suppressed = 0`; với `AML__CASES__SUPPRESSION__MATERIAL_CHANGE_RATIO=1.0` thì chỉ H7 bị suppress (`suppressed = 1`, `lifted = 3`); với `AML__CASES__SUPPRESSION__HIBERNATION_DAYS=30` (ngủ tới 2026-04-09) thì `suppressed = 0`, `lifted = 0`; và sau `record_disposition(duck, settings, "C-C04-20260201", "SUSPICIOUS", reason="second review", actor="lead01")` thì lần `run_cases` kế tiếp có `suppressed = 0` (case không còn là false positive nên pattern biến mất).
- AC6: Given hàm thuần `hibernation_verdict`, `cfg` mặc định và `P = HibernationPattern("G-C04", "HIGH_VELOCITY", 2, date(2026, 3, 10), 120000000, frozenset({"k1", "k2"}))`, When gọi với từng item, Then `hibernation_verdict(None, item_key="k9", event_ts=datetime(2026, 4, 10, 9), amount_vnd=1, cfg=cfg)` trả `Verdict(False, False, False, None)`; pattern có `false_positives = 1` trả `Verdict(False, False, False, None)`; `item_key="k1"` (đã xử lý) trả `suppress=False`, `lifted=False`; `item_key="k9"`, `event_ts=datetime(2026, 6, 8, 23, 59, 59)`, `amount_vnd=180000000` trả `suppress=True`, `retriggered=False`; cùng item với `event_ts=datetime(2026, 6, 9, 0, 0, 0)` trả `suppress=False`, `lifted=False`, `reason is None`; `amount_vnd=180000001` trong thời gian ngủ trả `suppress=False`, `lifted=True`, `retriggered=False`; `event_ts=datetime(2026, 1, 5, 9)` (trước ngày clear, chưa xử lý) với `amount_vnd=100000000` trả `suppress=True`; và pattern có `max_amount_vnd = 0` với `amount_vnd=1` trả `lifted=True`, còn `amount_vnd=0` trả `suppress=True`.
- AC7: Given TINY (`tiny_cases` của 7a) đã `run_cases` (run 1), When gọi `run_cases` lần hai mà chưa có disposition nào, rồi `record_disposition(db, settings, "C-CIF00000041-20260630", "FALSE_POSITIVE", reason="test clearance", actor="analyst01")` và `run_cases` lần ba, Then lần hai có `suppressed = 0`, `lifted = 0`, `cases = 52` và `audit_log` không có dòng `SUPPRESSED` nào; `good_guy_list` có đúng 1 dòng (`CIF00000041`, `WL000199`) với hai dấu vân tay dài 64 ký tự hex bằng đúng `read_state(db)["customer"]["CIF00000041"]` và `read_state(db)["watchlist_entry"]["WL000199"]`, `expires_on = 2027-06-30`; lần ba có `items = 74`, `suppressed = 1`, `active = 73`, `cases = 51`, `suppressed_by_rule == {"GOOD_GUY": 1, "HIBERNATION": 0}`; `cases_current` không có `C-CIF00000041-20260630`; bốn item `SCREENING` còn lại vẫn `ACTIVE`; và gọi `run_cases` lần bốn cho cùng `suppressed`, `cases` và cùng tập (`item_key`, `golden_customer_id`, `status`, `suppression_reason`) như lần ba.
- AC8: Given `tiny_env` đã `aml load`, `aml er`, `aml screen`, `aml monitor`, `aml network`, `aml cases build`, When chạy `aml cases dispose C-CIF00000041-20260630 --disposition FALSE_POSITIVE --reason "namesake" --actor analyst01`, rồi `aml cases build`, rồi `aml cases suppressed`, Then cả ba exit code 0; lệnh `build` in dòng tổng kết chứa `run_id=2`, `items=74`, `suppressed=1`, `active=73`, `cases=51`, một dòng `GOOD_GUY suppressed=1` và một dòng `HIBERNATION suppressed=0`; lệnh `suppressed` in đúng 1 dòng item chứa `SCREENING|CIF00000041|WL000199`, `GOOD_GUY` và `valid until 2027-06-30`; `aml cases suppressed` ngay sau lần `build` đầu tiên (chưa có disposition) exit code 0 và in `0 suppressed item(s)`; và Given DuckDB chưa từng `aml cases build`, When chạy `aml cases suppressed`, Then exit code 1 với stderr chứa ``run `aml cases build` first``.
- AC9: [oracle] Given TINY nạp vào cả Oracle và một DuckDB tạm, cả hai đã chạy các bước nguồn và `run_cases` (run đầu của mỗi backend), When trên cả hai backend gọi `record_disposition(db, settings, "C-CIF00000041-20260630", "FALSE_POSITIVE", reason="test clearance", actor="analyst01")` rồi `run_cases`, Then `suppressed = 1`, `active = 73`, `cases = 51` trên cả hai; dòng `good_guy_current` của (`CIF00000041`, `WL000199`) có cùng `cleared_on`, `expires_on`, `customer_fingerprint`, `entry_fingerprint` trên hai backend; tập (`item_key`, `golden_customer_id`, `status`, `suppression_rule`, `suppression_reason`) của `case_alerts_current` bằng nhau giữa hai backend; trên Oracle `user_tables` có `GOOD_GUY_LIST` và `user_views` có `GOOD_GUY_CURRENT`; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- Mọi thứ của 7a (gom item, gộp case, enrichment, luật trạng thái, `record_disposition`) — spec này chỉ thêm bước suppress và việc ghi good-guy; chấm điểm (7c) và summary (7d).
- **Tự clear / tự đóng**: suppression không ghi disposition, không đổi `status` của case sang `CLOSED`, không đặt `AUTO_CLEARED` cho screening, không sửa `screening_results` / `alerts`.
- Thêm / gỡ dòng good-guy bằng tay không qua disposition (whitelist do quản trị nhập), phê duyệt hai lớp (maker-checker) cho good-guy, hạn riêng theo `list_type`, loại trừ `SANCTIONS` khỏi good-guy (Q2).
- Hibernation theo tài khoản, theo cụm / vòng, theo typology; học ngưỡng "đổi đáng kể" từ dữ liệu; tiêu chí đổi hành vi khác ngoài `amount_vnd` (số giao dịch, đối tác mới, kênh mới) (Q4).
- Suppression ngay trong engine nguồn (không sinh alert trong `aml screen` / `aml monitor`): alert gốc luôn được sinh và lưu đầy đủ.
- Đánh giá suppression so với ground truth, mẫu below-the-line ngẫu nhiên của item bị suppress, biểu đồ volume trước / sau — Phase 7b của brief và Phase 9 (dữ liệu cần thiết đã có: `case_alerts.status`, `suppression_rule`, `case_runs.suppressed`).
- Lift khi cấu hình screening đổi (`config_hash`) mà dấu vân tay không đổi; lift khi ER gộp / tách golden customer.
- Quyền Oracle trên `good_guy_list` cho role của 2b; UI quản lý good-guy (Phase 9).

## Giả định
- **Đã xác nhận (2026-10-13, xem Câu hỏi mở)**: suppression ở mức item, trong `run_cases`, trước khi gộp (Q1); good-guy 365 ngày, áp cho cả `SANCTIONS` và `PEP` (Q2 — người dùng xác nhận trực tiếp); "dữ liệu đổi" = dấu vân tay của 3c trong `screening_state` (Q3); pattern = (golden customer, `rule_id`), ≥ 2 alert đã clear, ngủ 90 ngày, thoát khi `amount_vnd` > 1,5 lần (Q4); không sửa generator để có số liệu hibernation (Q5); lần clear bị đổi thành `SUSPICIOUS` thì good-guy / pattern tự mất hiệu lực (Q6).
- **Suy ra bằng tay, chưa chạy**: mọi giá trị MINI-S (AC2–AC6). AC7–AC9 suy từ số đo của 7a (74 item, 52 case trên TINY; case `C-CIF00000041-20260630` là case chỉ có screening của cặp `CIF00000041` × `WL000199`, đã thấy trong prototype) cộng luật của spec này. Lệch khi hiện thực → cập nhật spec, không sửa luật.
- `screening_state` phản ánh dữ liệu *lúc lần screening gần nhất chạy*: khách hàng đổi dữ liệu nhưng chưa screening lại thì good-guy chưa lift — đúng thứ tự vận hành (đổi dữ liệu → screening → cases).
- `decided_on` của disposition là ngày nghiệp vụ do người gọi đưa (mặc định `reference_date`); hạn good-guy và thời gian ngủ tính bằng ngày lịch, so với `as_of` của `run_cases` / ngày của `event_ts`; không dùng đồng hồ máy.
- Mỗi lần `run_cases` audit lại mọi item bị suppress / lifted của lần đó (như screening audit lại mọi cặp mỗi lần chạy); khối lượng nhỏ (`small`: ước tối đa vài chục dòng mỗi lần).
- Good-guy áp dụng như nhau cho `SANCTIONS` và `PEP`, cho `ALERT` và `REVIEW`; một disposition `FALSE_POSITIVE` ở mức case được coi là clear mọi screening hit trong case đó.
- Trên dữ liệu tổng hợp hiện tại hibernation gần như không có đối tượng (2 case rule false positive trên `small`); AC kiểm bằng fixture dựng tay. Số liệu thật của suppression do bước demo lấy từ lần chạy thật, không bịa.
- `reason`, thông điệp lỗi, output CLI bằng tiếng Anh; test [oracle] để lại dữ liệu như các phase trước.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Suppression đứng ở đâu so với consolidation, và item bị suppress đi đâu? — đề xuất mặc định: ở **mức item, trong `run_cases`, trước khi gộp**; item bị suppress vẫn được lưu trong `case_alerts` (`SUPPRESSED` + lý do) và audit, nhưng không thuộc case nào; case mà mọi item đều bị suppress thì biến khỏi hàng đợi hiện hành (lịch sử còn nguyên). Lý do: brief nói "cleared screening hits" và "alert patterns" — đều là mức alert; đặt trước consolidation thì số "alert trước / sau suppression" và "alert → case" của Phase 9 tách bạch. Phương án thay thế: suppress ở mức case (ẩn cả case) — đơn giản hơn nhưng một alert mới thật sự sẽ bị kéo theo alert cũ đã clear. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q2. **(cần người dùng quyết)** Good-guy list hết hạn sau bao lâu và có áp dụng cho `SANCTIONS` không? — đề xuất mặc định: 365 ngày kể từ ngày clear, áp dụng cho cả `SANCTIONS` lẫn `PEP`. Lý do: chu kỳ rà soát KYC hằng năm là mốc dễ giải thích; hit sanctions là nơi false positive do trùng tên nhiều nhất (`small`: 26 `ALERT` sanctions, phần lớn là người trùng tên). Phương án thận trọng hơn: `SANCTIONS` hạn ngắn hơn (vd 90 ngày) hoặc không bao giờ vào good-guy. — Trả lời: theo đề xuất mặc định (người dùng xác nhận trực tiếp, 2026-10-13).
- [x] Q3. "Dữ liệu khách hàng hoặc watchlist đổi" được hiểu là gì? — đề xuất mặc định: dấu vân tay của 3c trong `screening_state` (khách hàng: tên chuẩn hoá, ngày sinh, quốc tịch, giới tính, số giấy tờ; entry: loại danh sách, ngày sinh, quốc tịch, mọi tên và alias) khác với lúc clear. Lý do: đúng các trường quyết định kết quả screening; đổi số điện thoại hay `program` không làm bật lại. Phương án thay thế: mọi thay đổi trên dòng `customers` đều bật lại (nhiễu hơn). — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q4. **(cần người dùng quyết)** Pattern của hibernation, "lặp lại" và "đổi đáng kể" định nghĩa thế nào? — đề xuất mặc định: pattern = (golden customer, `rule_id`); ngủ khi đã có **≥ 2** alert của pattern được clear là false positive; ngủ **90 ngày** từ lần clear gần nhất; alert mới thoát ngủ khi `amount_vnd` **> 1,5 lần** alert đã clear lớn nhất. Lý do: một lần false positive chưa phải "lặp lại"; số tiền là số đo chung duy nhất của mọi rule 5a / 5c nên so được mà không cần luật riêng từng rule. Phương án thay thế: ngủ ngay sau 1 lần clear; thêm tiêu chí số giao dịch / số đối tác theo từng rule. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q5. **(cần người dùng quyết)** Dữ liệu tổng hợp gần như không có false positive lặp lại của rule (2 case trên `small`) — có cần sinh thêm dữ liệu để hibernation có số liệu demo không? — đề xuất mặc định: **không** sửa generator; hibernation được kiểm bằng fixture dựng tay và README ghi trung thực số item bị ngủ đo được (có thể là 0), kèm giải thích. Lý do: sửa Phase 1 để "có cái mà suppress" là điều chỉnh dữ liệu theo kết quả mong muốn. Phương án thay thế: một spec nhỏ thêm typology lành tính lặp lại hằng tháng **có** bị rule bắt (vd doanh nghiệp trả thưởng quý) vào generator. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q6. Khi một case đã clear bị người khác đổi thành `SUSPICIOUS`, good-guy và hibernation sinh ra từ lần clear đó xử lý thế nào? — đề xuất mặc định: tự mất hiệu lực (dòng good-guy chỉ có hiệu lực khi disposition sinh ra nó còn là quyết định mới nhất của case; pattern chỉ đếm case mà quyết định mới nhất là `FALSE_POSITIVE`), không cần thao tác gỡ. Lý do: không để một lần clear sai tiếp tục che alert. — Trả lời: theo đề xuất mặc định (đã trình bày cho người dùng, không phản đối, 2026-10-13).
