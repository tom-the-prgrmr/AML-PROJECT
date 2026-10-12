---
id: network-detections
status: approved
approved_by: pthieu
---

# Phase 5c — Network detections bằng NetworkX: cụm dùng chung thiết bị/điện thoại/địa chỉ, vòng tiền, tài khoản hub; alert nguồn `NETWORK`, `aml network`

## Bối cảnh
Phần thứ ba của Phase 5 trong PROJECT_BRIEF.md (mục 6, "Network detections (NetworkX in the default path)"); 5a là năm
rule SQL (`specs/monitoring-rules.md`, sở hữu bảng `alerts` / `alert_accounts` / `alert_evidence` / `monitoring_runs`,
view `alerts_current`, hàm `record_run`), 5b là fund-flow tracing (`specs/fund-flow-trace.md`). Spec này hiện thực ba
phát hiện mạng lưới chạy trong bộ nhớ bằng NetworkX: (1) cụm khách hàng dùng chung thiết bị / điện thoại / địa chỉ
(mule ring), (2) vòng tiền A→B→C(→D)→A đúng thứ tự thời gian trong một cửa sổ (round-tripping), (3) tài khoản hub
(degree + PageRank). Dữ liệu đọc qua `Database.query_df` nên chạy được ở chế độ DuckDB-only và cho cùng kết quả trên
Oracle. Kết quả là alert `source = 'NETWORK'` ghi vào bảng của 5a **qua `aml.monitoring.recording.record_run`**, có
`reason` đọc được, evidence txn ids, `audit_log`; thêm bảng đặc trưng theo tài khoản cho Phase 7/7b. Người dùng: analyst
nhận alert nhóm tài khoản kèm lý do; Phase 7 gộp alert thành case theo golden customer; người phỏng vấn xem số liệu
"5c bắt thêm gì so với 5a". Hệ thống chỉ **sinh alert**: không đóng, không chấm điểm ưu tiên, không chặn giao dịch.

### Hiện trạng đã kiểm trên dữ liệu Phase 1 (seed 42)
Đo bằng prototype ngoài repo (script tạm, `uv run --with networkx --with scipy`; NetworkX 3.6.1, SciPy 1.17.1, DuckDB
1.5.x), đọc dữ liệu qua DuckDB sau `load_parquet` + `run_er`. TINY = fixture `tiny_parquet`; `small` = `data/parquet`
hiện có; `dense` = profile `dense` sinh vào thư mục tạm (cùng 5000 customers / 8958 accounts / kịch bản như `small`,
chỉ khác mật độ đối tác).
- **Dependency**: `networkx` **chưa có** trong `pyproject.toml` / `uv.lock`. `nx.pagerank` của NetworkX 3.x **bắt buộc
  có SciPy** (đã thử không có SciPy: `ModuleNotFoundError: No module named 'scipy'`); SciPy cũng chưa có trong môi
  trường (Splink không kéo theo) → cần thêm cả hai (Q3).
- **Giao dịch**: chuyển khoản mà cả hai đầu là tài khoản trong `accounts` ("nội bộ"): TINY 1037, `small` 45 340,
  `dense` 109 964; trong đó chuyển giữa các tài khoản của **cùng một CIF**: TINY 188, `small` 11 323, `dense`
  1570; sau khi bỏ chuyển khoản cùng chủ (golden customer) còn 847 / 34 016 / 108 388. Tài khoản `EXT-*` không có trong `accounts`; mọi `EXT-*` trong `small` (2000) đều vừa gửi vừa nhận. Không có
  giao dịch tự chuyển (`from = to`). Mọi khách hàng đều có ít nhất 1 tài khoản; `device_id`, `phone`, `street` không
  null ở dòng nào. Giao dịch trùng (defect DQ, cùng `txn_ts`, khác `txn_id`): không bản sao nào là bản sao của giao
  dịch thuộc kịch bản (0 trên cả ba bộ).
- **Cụm thuộc tính dùng chung** (`link_members`: mỗi thành viên chép **một** trong ba nhóm thiết bị / điện thoại /
  địa chỉ của thành viên đầu → hình sao quanh collector). Thành phần liên thông trên đồ thị hai phía khách hàng — giá
  trị thuộc tính (điện thoại và địa chỉ chuẩn hoá như Phase 4):

  | thực thể | TINY: số cụm theo cỡ | `small`: số cụm theo cỡ | `small`: cụm ≥ 5 |
  |---|---|---|---|
  | CIF | 2: 17, 3: 4, 4: 1, 29: 1 | 2: 438, 3: 109, 4: 15, 5: 3, 6: 1, 12: 1, 22: 2, 25: 1, 28: 1 | 9 cụm, 4 cụm không có thành viên ring nào (2–3 người, mỗi người 2–3 CIF) |
  | golden customer | 2: 1, 29: 1 | 2: 242, 3: 13, 12: 1, 20: 1, 22: 1, 23: 1, 27: 1 | 5 cụm = đúng 5 ring |

  - Gom theo CIF thì "cụm" chủ yếu là các CIF của cùng một người (`small`: 133 cụm ≥ 3 CIF, chỉ 5 là ring); gom theo
    `golden_customer_id` thì nhiễu còn lại là **trùng địa chỉ giữa người khác nhau** (242 cặp, 13 bộ ba — toàn bộ là
    địa chỉ đơn thuần; chỉ tính thiết bị + điện thoại thì còn đúng 5 cụm). ER trên cả ba bộ không gộp nhầm, không tách
    sót người nào.
  - Ngưỡng theo số khách hàng (`small`): ≥ 2 → 260 cụm; ≥ 3 → 18 cụm (13 bộ ba địa chỉ lành tính); ≥ 4 và ≥ 5 → 5 cụm.
  - 5 cụm `small` phủ 96/96 khách hàng thành viên (collector + member) nhưng kéo theo **8 khách hàng ngoài cuộc** (104
    khách hàng trong cụm; ring 0003: +2, 0004: +4, 0005: +2) — đều dính qua một địa chỉ trùng với đúng một thành viên.
    Phương án "địa chỉ chỉ nối khi có ≥ 3 khách hàng dùng chung": 5 cụm cỡ 12 / 18 / 21 / 22 / 23, đúng 96/96, 0 người
    ngoài cuộc (Q6). TINY: 1 cụm 29 khách hàng = đúng 29 thành viên.
  - Giá trị dùng chung rộng nhất: TINY 16 khách hàng / 1 thiết bị, `small` 10. `ip` không trùng giữa hai khách hàng
    nào. Kết quả cụm của `dense` trùng khít `small` (cùng bảng `customers`).
- **Vòng tiền** (kịch bản: 3–4 chặng, mỗi chặng giữ 92–100% chặng trước, toàn bộ trong 168 giờ; đo được: dài nhất 131
  giờ, tỉ lệ số tiền nhỏ nhất / lớn nhất trong vòng thấp nhất 0,821; lượt đầu 100 triệu–1 tỉ). Tìm kiếm theo thời
  gian (mỗi chặng muộn hơn chặng trước, cả vòng trong cửa sổ), các tài khoản thuộc các khách hàng khác nhau:

  | cấu hình | `small`: bước / vòng | `dense`: bước / vòng / thời gian |
  |---|---|---|
  | mặc định đề xuất (≥ 50 triệu, tỉ lệ ≥ 0,70, dài ≤ 5, 168 giờ) | 66 / 15 (đúng 15 kịch bản) | 66 / 15 / < 0,01 giây |
  | không sàn số tiền, tỉ lệ ≥ 0,70 | 13 239 / 15 | 103 526 / 16 (1 vòng nền) / 0,2 giây |
  | không sàn, không tỉ lệ | 14 038 / 15 | 158 445 / 37 (22 vòng nền) / 0,3 giây |
  | không sàn, không tỉ lệ, 720 giờ, dài ≤ 6 | 73 623 / 15 | 3 807 647 / 1212 / ~4 giây |

  - Với mặc định, số giao dịch còn lại sau từng bước lọc: TINY 847 (khác chủ) → 68 (≥ 50 triệu) → 8 (cùng thành phần
    liên thông mạnh), 12 bước tìm; `small` 34 016 → 867 → 52; `dense` 108 388 → 2111 → 52.
  - Cả 15 alert `small` có evidence **trùng khít** tập giao dịch `evidence` của kịch bản tương ứng (TINY 2/2). Mọi
    ngưỡng sàn từ 20 triệu tới 100 triệu cho cùng 15 vòng; tỉ lệ ≥ 0,90 chỉ còn 8/15.
  - Đối chứng **không xét thời gian** (`nx.simple_cycles` trên đồ thị tĩnh `dense`, 6519 nút, 106 986 cạnh): 6545
    vòng dài ≤ 3 mất 209 giây, 224 455 vòng dài ≤ 4 mất 348 giây — liệt kê tĩnh là thứ gây bùng nổ; ràng buộc thời
    gian + cửa sổ + sàn số tiền mới là thứ chặn (Q11).
- **Hub** (đồ thị có hướng giữa các tài khoản, chỉ chuyển khoản nội bộ khác chủ; TINY 298 tài khoản có cạnh, `small`
  và `dense` 4980):
  - `in_degree` (số tài khoản gửi khác nhau) của nền: `small` tối đa 2, `dense` trung vị 24, tối đa 37 → ngưỡng
    degree tuyệt đối vô dụng trên `dense` (4368 tài khoản có `in_degree` ≥ 10). Collector 14–25 (`small`), merchant
    31–40.
  - PageRank không trọng số, α = 0,85, chia cho mức trung bình (`pagerank_ratio`): collector `small` 2,13–3,83,
    `dense` 2,06–3,71; merchant 4,63–5,93 / 4,48–5,73; nền `dense` (mọi tài khoản) tối đa 1,64; nền `small` tối đa
    3,47 nhưng các tài khoản đó chỉ có `in_degree` ≤ 2. TINY: collector 6,77, merchant 7,30, nền tối đa 5,87.
  - `in_degree` ≥ 10 **và** `pagerank_ratio` ≥ 1,8: `small` 10 tài khoản = 5 collector + **5 merchant lành tính**;
    `dense` cũng đúng 10 tài khoản đó. Tổng tiền vào: merchant 29,7–56,1 triệu, collector 1,05–2,37 tỉ → thêm sàn 100
    triệu thì còn 5 collector trên cả hai profile (Q13).
  - Chiều ra (PageRank trên đồ thị đảo chiều, `out_degree` ≥ 10, tỉ lệ ≥ 2,0): `small` bắt 5 tài khoản = **5 employer
    lành tính, 0 source** (source có tỉ lệ 0,77–1,22 vì mỗi member nhận từ 3 source). Vì vậy thiết kế **không** sinh
    alert hub chiều ra (Q13).
  - PageRank có trọng số theo số tiền không tách tốt hơn (top 10 `small`: 5 merchant + 5 nền).
- **Kết quả của thiết kế đề xuất** (tham số mặc định):

  | rule | TINY: alert / tài khoản / evidence | `small` = `dense`: alert / tài khoản / evidence | `small`: alert rơi vào |
  |---|---|---|---|
  | `NET_SHARED_ATTRIBUTE` | 1 / 53 / 28 | 5 / 194 / 91 | 5/5 mule ring |
  | `NET_CYCLE` | 2 / 8 / 8 | 15 / 52 / 52 | 15/15 round-tripping |
  | `NET_HUB` | 1 / 1 / 31 | 5 / 5 / 106 | 5/5 collector |
  | tổng | 4 / 62 / 67 (39 giao dịch khác nhau) | 25 / 251 / 249 | 0 alert trên benign payroll / merchant |

  Chạy hết 0,13 giây (TINY), 1,9 giây (`small`), 2,4 giây (`dense`). 194 tài khoản của 5 cụm `small` = 96 tài khoản
  kịch bản + 98 tài khoản khác (tài khoản thứ hai/thứ ba của thành viên và tài khoản của 8 khách hàng ngoài cuộc).
- **5c thêm gì so với 5a** (so với 31 / 242 alert của prototype 5a):

  | | TINY: 5a → 5c → hợp | `small`: 5a → 5c → hợp |
  |---|---|---|
  | round_tripping: kịch bản có alert | 2 → 2 → 2 | 13 → 15 → 15 (+2) |
  | round_tripping: tài khoản hop có alert | 2 → 8 → 8 (+6) | 38 → 52 → 52 (+14) |
  | mule_ring: tài khoản member có alert | 6 → 28 → 28 (+22) | 9 → 91 → 91 (+82) |
  | mule_ring: mọi vai (collector, member, source, destination) | 14 → 29 → 36 / 36 | 46 → 96 → 128 / 136 |

  5c không chạm source / destination của mule ring (không dùng chung thuộc tính; 5a đã bắt 20/20 source, 12/20
  destination) và không thêm gì cho structuring / rapid movement. `NET_HUB` trùng hoàn toàn với `FAN_IN` của 5a về tài
  khoản (5/5 collector) — giá trị của nó là đặc trưng PageRank / degree cho Phase 7 và việc vẫn đúng trên `dense`.
- **Tất định**: chạy với `PYTHONHASHSEED` = 0 / 1 / 12345 và trên bản TINY đã xáo thứ tự vật lý của `transactions`,
  `customers`, `accounts` đều cho alert và bảng đặc trưng giống hệt. Không bước nào dùng số ngẫu nhiên.
  `nx.pagerank` với `tol` mặc định (1e-6) lệch ở chữ số thứ ba (TINY collector 6,7662 so với 6,7651 khi `tol` =
  1e-10) → cố định `tol` (Q14).
- `SCHEMA_SCRIPTS` đã dùng `000`–`100`; 5a dùng `110`, 5b `120` (chỉ Oracle), 5c dùng **`130`**. Chưa có
  `src/aml/graph/` và `src/aml/monitoring/` (5a, 5b đang ở dạng spec). 5b đặt code ở `src/aml/graph/trace.py`, config
  `trace`, lệnh `aml trace`; `aml graph` và `aml bench` là stub Phase 6.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class SharedAttributeConfig(BaseModel):
    min_customers: int  # cụm có từ ngần này golden customer mới thành alert
    max_customers_per_value: int  # giá trị dùng chung bởi nhiều khách hàng hơn mức này bị bỏ qua


class CycleConfig(BaseModel):
    min_length: int  # số chặng tối thiểu (>= 3)
    max_length: int  # số chặng tối đa (<= 6)
    window_hours: int  # chặng cuối phải xảy ra trước (chặng đầu + cửa sổ)
    min_amount_vnd: int  # bỏ chuyển khoản nhỏ hơn mức này
    min_amount_ratio: float  # số tiền nhỏ nhất / lớn nhất trong vòng phải >= mức này
    max_search_steps: int  # vượt -> NetworkError, không cắt bớt âm thầm


class HubConfig(BaseModel):
    lookback_days: int  # chỉ dựng đồ thị từ chuyển khoản trong ngần này ngày trước cutoff
    min_in_degree: int
    min_pagerank_ratio: float  # pagerank * số tài khoản có cạnh
    min_inflow_vnd: int
    pagerank_alpha: float


class NetworkConfig(BaseModel):
    shared_attributes: SharedAttributeConfig
    cycles: CycleConfig
    hubs: HubConfig


class Settings(BaseModel):
    ...
    network: NetworkConfig


# src/aml/graph/network/rules.py
@dataclass(frozen=True)
class NetworkRule:
    rule_id: str
    rule_version: str  # "v1"
    target_typology: str  # typology của ground_truth mà rule nhắm tới
    description: str


NETWORK_RULES: tuple[NetworkRule, ...]  # NET_SHARED_ATTRIBUTE, NET_CYCLE, NET_HUB (đúng thứ tự)


def network_rule_params(rule_id: str, settings: Settings) -> dict[str, int | float | str]: ...


# src/aml/graph/network/shared.py
def attribute_keys(customers: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame: ...
# cột: cif, device_key, phone_key, address_key; sắp theo cif; giá trị không dùng được -> None


# src/aml/graph/network/runner.py
FEATURE_COLUMNS = [
    "account_id", "in_degree", "out_degree", "in_vnd", "out_vnd", "pagerank", "pagerank_ratio",
    "cycle_alerts", "shared_cluster_id", "shared_cluster_size", "is_hub",
]


class NetworkError(RuntimeError): ...


@dataclass(frozen=True)
class NetworkDetections:
    alerts: tuple[AlertRecord, ...]  # AlertRecord của aml.monitoring.recording (5a)
    features: pd.DataFrame  # FEATURE_COLUMNS, một dòng cho mỗi dòng accounts, sắp theo account_id
    active_accounts: int  # số tài khoản có ít nhất một cạnh trong đồ thị hub
    cycle_search_steps: int


@dataclass(frozen=True)
class NetworkRun:
    run_id: int
    as_of: date
    alerts: int
    evidence: int  # số dòng alert_evidence của lần chạy
    by_rule: dict[str, int]  # đủ 3 khoá, kể cả 0
    accounts: int  # số dòng nx_account_features của lần chạy
    active_accounts: int
    cycle_search_steps: int


def detect_network(db: Database, settings: Settings, *, as_of: date | None = None) -> NetworkDetections: ...
# không ghi gì; thứ tự alert: NET_SHARED_ATTRIBUTE (theo subject_id), NET_CYCLE (theo window_start, subject_id),
# NET_HUB (theo subject_id)
def run_network(db: Database, settings: Settings, *, as_of: date | None = None) -> NetworkRun: ...


# src/aml/graph/network/evaluate.py
def evaluate_network(db: Database) -> pd.DataFrame: ...
# cột như evaluate_rules của 5a: rule_id, target_typology, alerts, target_hits, other_suspicious, benign,
#      unlabelled, precision, precision_suspicious, scenarios, detected, recall; 3 dòng theo thứ tự NETWORK_RULES
def network_coverage(db: Database) -> pd.DataFrame: ...
# cột: typology, is_suspicious, scenarios, flagged_rule, flagged_network, flagged_any, new_by_network,
#      accounts, accounts_rule, accounts_network, accounts_any, accounts_new, rules; 6 dòng theo thứ tự:
#      structuring, rapid_movement, mule_ring, round_tripping, benign_payroll, benign_merchant
```
- `pyproject.toml`: thêm `networkx>=3.4,<4` và `scipy>=1.13` vào `dependencies` (và cập nhật `uv.lock`).
- `config.yaml`, mục mới `network`:
  ```yaml
  network:
    shared_attributes: {min_customers: 5, max_customers_per_value: 50}
    cycles: {min_length: 3, max_length: 5, window_hours: 168, min_amount_vnd: 50000000,
             min_amount_ratio: 0.70, max_search_steps: 1000000}
    hubs: {lookback_days: 365, min_in_degree: 10, min_pagerank_ratio: 1.8, min_inflow_vnd: 100000000,
           pagerank_alpha: 0.85}
  ```
- DDL `sql/duckdb/ddl/130_network.sql` và `sql/oracle/ddl/130_network.sql`, thêm vào `SCHEMA_SCRIPTS` của cả hai
  backend sau `ddl/110_monitoring.sql` (Oracle: sau cả `ddl/120_property_graph.sql` nếu 5b đã có) và trước các script
  `050_*`. Không tạo lại bảng nào của 5a.
- CLI mới: `aml network [--as-of YYYY-MM-DD] [--eval-out PATH]`. Không đụng `aml monitor`, `aml trace`, `aml graph`,
  `aml bench`.
- Gói `src/aml/graph/network/` (`rules.py`, `inputs.py`, `shared.py`, `cycles.py`, `hubs.py`, `runner.py`,
  `evaluate.py`); phụ thuộc một chiều vào `aml.monitoring.recording` (5a) và `aml.entity_resolution.normalize`.

### Thiết kế (xác nhận ở Câu hỏi mở)
- **Đầu vào** (ba câu `SELECT` đơn giản qua `Database.query_df`, viết inline như `entity_resolution/runner.py`; tên
  cột trả về được hạ về chữ thường; **mọi phép sắp xếp làm trong Python theo thứ tự chuỗi**, không dựa vào `ORDER BY`
  / collation của backend):
  - `customers` (`cif`, `phone`, `device_id`, `street`, `ward`, `district`, `province`) + `admin_unit_mapping`;
  - `accounts` (`account_id`, `cif`) nối `customer_golden` → **chủ** của tài khoản = `golden_customer_id` của CIF; CIF
    không có dòng trong `customer_golden` được coi là một khách hàng riêng (`'G-' + cif`);
  - **chuyển khoản** = dòng `transactions` có cả `from_account_id` và `to_account_id` nằm trong `accounts`, hai tài
    khoản khác nhau và **khác chủ**, `txn_ts` trước `cutoff` = 00:00 ngày `as_of + 1`. Nộp/rút tiền mặt, chi thẻ, giao
    dịch với `EXT-*` và chuyển giữa các tài khoản của cùng một khách hàng không tham gia đồ thị nào.
  - `customers` hoặc `accounts` rỗng / chưa có → `NetworkError` chứa ``run `aml load` first``; `customer_golden` rỗng
    → `NetworkError` chứa ``run `aml er` first``. Cả hai xảy ra trước khi ghi bất cứ thứ gì.
  - `as_of` mặc định `settings.data.reference_date`. Thuộc tính khách hàng không có lịch sử: cụm luôn tính trên
    `customers` hiện tại, `as_of` chỉ cắt giao dịch.
- **Ba rule** (`rule_version` đều là `v1`):

  | rule_id | chủ thể | target | `network_rule_params` |
  |---|---|---|---|
  | `NET_SHARED_ATTRIBUTE` | `ACCOUNT_GROUP` | `mule_ring` | `min_customers`, `max_customers_per_value` |
  | `NET_CYCLE` | `ACCOUNT_GROUP` | `round_tripping` | 6 khoá của `cycles` |
  | `NET_HUB` | `ACCOUNT` | `mule_ring` | 5 khoá của `hubs` |

- **`NET_SHARED_ATTRIBUTE`**:
  - `attribute_keys`: `device_key` = `device_id` bỏ khoảng trắng hai đầu (rỗng → `None`); `phone_key` =
    `normalize_phone(phone)` của Phase 4; `address_key` = đúng `addr_key` mà `prepare_records` của Phase 4 sinh cho
    dòng đó (`street|phường mới|tỉnh mới` đã bỏ dấu, viết hoa; `None` khi `street` rỗng).
  - Đồ thị hai phía: nút khách hàng (chủ) — nút giá trị (`device` / `phone` / `address`, giá trị). Một giá trị chỉ
    tạo cạnh khi số khách hàng khác nhau mang nó nằm trong `[2, max_customers_per_value]`. Cụm = tập khách hàng của
    một thành phần liên thông; thành alert khi có ≥ `min_customers` khách hàng.
  - `subject_id` = `'SHARED-'` + CIF nhỏ nhất của cụm; `alert_key` = `NET_SHARED_ATTRIBUTE|<subject_id>` (không có mốc
    thời gian: danh tính là cụm). `accounts` = **mọi** tài khoản của mọi CIF thuộc các khách hàng trong cụm, vai
    `MEMBER`, tăng theo `account_id`.
  - Evidence = các chuyển khoản mà cả hai đầu là tài khoản của cụm; `amount_vnd` = tổng của chúng; `window_start` /
    `window_end` = evidence đầu / cuối. Cụm không có chuyển khoản nào vẫn là alert: `txn_ids` rỗng, `amount_vnd` = 0,
    `window_start` = `window_end` = 00:00:00 ngày `as_of`.
  - `details` = `{customers, cifs (tăng dần), accounts, links: {device, phone, address} (số khách hàng dính vào ít
    nhất một giá trị dùng chung thuộc loại đó), shared_values: {device, phone, address} (số giá trị dùng chung),
    internal_txns, internal_vnd}`. Không lưu số điện thoại, địa chỉ hay mã thiết bị trong `reason` / `details`.
  - `reason`: `{customers} customers ({accounts} accounts) linked by shared device ({links.device} customers), phone ({links.phone}), address ({links.address}); ` +
    `{n} transfer(s) totalling {vnd:,} VND between members between {start} and {end}` hoặc `no transfers between members`.
- **`NET_CYCLE`**:
  - Ứng viên = chuyển khoản có `amount_vnd >= min_amount_vnd`. Cắt tỉa: dựng đồ thị có hướng tĩnh trên các cặp (gửi,
    nhận), chỉ giữ chuyển khoản mà hai đầu thuộc **cùng một** thành phần liên thông mạnh có ≥ `min_length` tài khoản.
  - **Vòng** = dãy chuyển khoản `t1 … tk` (`min_length <= k <= max_length`) với: người nhận của `ti` là người gửi của
    `ti+1`, người nhận của `tk` là người gửi của `t1`; `k` tài khoản khác nhau thuộc `k` chủ khác nhau; `txn_ts` tăng
    **ngặt** (bằng nhau không tính); `txn_ts(tk) < txn_ts(t1) + window_hours`; số tiền nhỏ nhất ≥ `min_amount_ratio`
    × số tiền lớn nhất trong dãy.
  - Tìm kiếm: lần lượt lấy từng ứng viên làm `t1` (theo `txn_ts`, `txn_id`), duyệt theo chiều sâu các chuyển khoản
    rời tài khoản cuối của đường đi có `txn_ts` lớn hơn chặng trước và nhỏ hơn `txn_ts(t1) + window_hours` (theo
    `txn_ts`, `txn_id`). **Mỗi chuyển khoản được xét như vậy là một bước**, đếm trước mọi phép kiểm khác; tổng số bước
    là `cycle_search_steps`. Vì `t1` luôn là chặng sớm nhất nên mỗi vòng được tìm thấy đúng một lần. Số bước vượt
    `max_search_steps` → `NetworkError` chứa `cycle search exceeded max_search_steps`, không ghi gì.
  - Gộp thành alert: các vòng có cùng **dãy tài khoản chính tắc** (xoay dãy để bắt đầu từ `account_id` nhỏ nhất, giữ
    chiều) được sắp theo (`txn_ts(t1)`, dãy `txn_id`); một vòng nhập vào **đợt** hiện tại khi `txn_ts(t1)` của nó nhỏ
    hơn `txn_ts(t1)` của vòng đầu đợt + `window_hours`, ngược lại mở đợt mới. Mỗi đợt = một alert.
  - `subject_id` = dãy chính tắc nối bằng `>`; `alert_key` = `NET_CYCLE|<subject_id>|<window_start dạng
    YYYY-MM-DDTHH:MM:SS>`; `accounts`: người gửi `t1` của vòng đầu đợt có vai `ORIGIN`, còn lại `HOP`; evidence = hợp
    `txn_id` của mọi vòng trong đợt; `amount_vnd` = tổng evidence; `window_start` / `window_end` = evidence đầu / cuối.
  - `details` = `{length, origin, path (từ origin, theo chiều tiền), first_vnd, last_vnd, hours (số giờ trọn từ t1
    tới tk), instances (số vòng trong đợt)}` — các số liệu lấy từ vòng đầu đợt.
  - `reason`: `{first_vnd:,} VND left {origin} and {last_vnd:,} VND ({last_vnd / first_vnd:.0%}) returned after {length} transfers across {length} customers in {hours} hours ({path nối bằng ' -> '} -> {origin}) between {start} and {end}`.
- **`NET_HUB`**:
  - Đồ thị có hướng không trọng số: cạnh gửi → nhận cho mỗi cặp tài khoản có ít nhất một chuyển khoản với `txn_ts >=
    cutoff − lookback_days` ngày; nút = tài khoản có ít nhất một cạnh (`active_accounts`); nút và cạnh được thêm theo
    thứ tự `account_id` tăng dần.
  - `pagerank` = `nx.pagerank(G, alpha=pagerank_alpha, weight=None, tol=1e-10, max_iter=200)` làm tròn 8;
    `pagerank_ratio` = `pagerank × active_accounts` làm tròn 4; `in_degree` / `out_degree` = số tài khoản gửi / nhận
    khác nhau; `in_vnd` / `out_vnd` = tổng tiền trên các cạnh vào / ra.
  - Hub khi `in_degree >= min_in_degree` **và** `pagerank_ratio >= min_pagerank_ratio` **và** `in_vnd >=
    min_inflow_vnd`. Không có alert hub chiều ra.
  - `subject_id` = `account_id`, vai `SUBJECT`; `alert_key` = `NET_HUB|<account_id>`; evidence = mọi chuyển khoản đi
    vào tài khoản trong đồ thị; `amount_vnd` = `in_vnd`; `details` = `{in_degree, out_degree, in_vnd, out_vnd,
    pagerank_ratio, active_accounts, transfers}`.
  - `reason`: `received {in_vnd:,} VND from {in_degree} accounts of other customers in {transfers} transfers between {start} and {end}; PageRank {pagerank_ratio:.2f}x the average of {active_accounts} active accounts`.
- **Bảng đặc trưng** (DDL 130; cùng tên cột trên hai backend; không bao giờ UPDATE/DELETE):
  - `nx_account_features(run_id, account_id, in_degree, out_degree, in_vnd, out_vnd, pagerank, pagerank_ratio,
    cycle_alerts, shared_cluster_id, shared_cluster_size, is_hub)`, PK `(run_id, account_id)`: một dòng cho **mọi**
    tài khoản trong `accounts`; tài khoản không có cạnh nhận 0 ở mọi cột số; `cycle_alerts` = số alert `NET_CYCLE`
    của lần chạy có tài khoản này; `shared_cluster_id` / `shared_cluster_size` = `subject_id` và số khách hàng của
    alert `NET_SHARED_ATTRIBUTE` chứa tài khoản (null / 0 khi không có); `is_hub` 0/1.
  - View `nx_account_features_current` = các dòng có `run_id = MAX(run_id)` của chính bảng này.
  - Tiền tố `nx_` dành cho kết quả NetworkX; Phase 6 ghi đặc trưng GDS vào bảng khác (đề xuất tiền tố `gds_`).
- **`run_network`** = `detect_network` → `record_run(db, as_of=as_of, source="NETWORK", rules=[3 RuleRun với
  network_rule_params], alerts=detections.alerts)` → ghi `nx_account_features` với `run_id` vừa nhận. 5c **không**
  tự `INSERT` vào bảng nào của 5a và không tự ghi `audit_log`: mỗi alert một sự kiện `ALERT` và mỗi lần chạy một sự
  kiện `MONITORING_RUN_COMPLETED` đều do `record_run` ghi (`module='monitoring'`). Mỗi lần chạy là chạy lại toàn bộ
  dưới `run_id` mới (như 5a); `alerts_current` tự lấy lần chạy mới nhất của từng `rule_id`.
- **Đánh giá** (đọc `alerts_current` nối `alert_accounts`, và `ground_truth` với `entity_type='account'`):
  - Kịch bản của một alert = kịch bản có **nhiều tài khoản của alert nhất** (hoà → `scenario_id` nhỏ nhất); alert
    không có tài khoản nào thuộc kịch bản là `unlabelled`. Các cột của `evaluate_network` định nghĩa như
    `evaluate_rules` của 5a, tính trên alert `source = 'NETWORK'`.
  - `network_coverage`: `flagged_rule` = số kịch bản có ít nhất một alert `source = 'RULE'` (theo định nghĩa của 5a:
    tài khoản chủ thể thuộc kịch bản); `flagged_network` = số kịch bản là kịch bản của ít nhất một alert `NETWORK`;
    `flagged_any` = hợp; `new_by_network` = có `NETWORK` mà không có `RULE`. `accounts` = số tài khoản của typology
    trong `ground_truth`; `accounts_rule` / `accounts_network` = số trong đó xuất hiện ở `alert_accounts` của alert
    hiện hành nguồn tương ứng; `accounts_any` = hợp; `accounts_new` = có ở `NETWORK` mà không có ở `RULE`; `rules` =
    các `rule_id` nguồn `NETWORK` đã gắn với typology (sắp theo chữ cái, nối bằng dấu phẩy).
  - Chưa có lần chạy `NETWORK` nào → `NetworkError` chứa ``run `aml network` first``. Chưa có alert `RULE` nào → các
    cột `*_rule` bằng 0, không lỗi.
- **CLI `aml network`**: in 3 dòng theo rule (`<rule_id> alerts=<n> evidence=<n>`), một dòng tổng kết (`run_id=`,
  `as_of=`, `alerts=`, `evidence=`, `accounts=`, `active_accounts=`, `cycle_search_steps=`), rồi khi `ground_truth` có
  dữ liệu: 3 dòng đánh giá và 6 dòng phủ typology; `--eval-out PATH` ghi bảng `evaluate_network` ra CSV. Exit 0 khi
  chạy xong, 1 khi `NetworkError`, 2 khi tham số sai.

## Tiêu chí nghiệm thu
<!-- as_of mặc định = date(2026, 6, 30); cấu hình mặc định như mục Interface; NetworkX 3.x, SciPy, DuckDB 1.5.x.
"Ghi đè X=v" = `load_settings(environ={"DB_BACKEND": "duckdb", "AML__NETWORK__...": "v"})`. M = triệu.
So sánh số thực: pagerank_ratio làm tròn 2 chữ số.
TINY = fixture `tiny_parquet` nạp bằng `load_parquet` rồi `run_er(duck, settings)` (300 customers, 532 accounts, 5100
dòng transactions, seed 42).
Mọi bộ MINI = DuckDB rỗng sau `apply_schema` + các dòng nêu dưới đây; cột không nêu để null; mỗi tài khoản là
`account_type` CURRENT, `open_date` 2025-01-01 trừ khi ghi khác; giao dịch có `channel` INTERNAL_TRANSFER;
`customer_golden` được dựng bằng 1 dòng `er_runs` (run_id 1) + các dòng `er_golden` (run_id 1): mỗi CIF là golden
riêng `G-<cif>` trừ khi ghi khác.
MINI-SHR: customers C01..C22, accounts A01..A22 (A<n> thuộc C<n>) và A01S (C01, SAVINGS). `admin_unit_mapping` có đúng
1 dòng (Phường Bình Thạnh, Quận Tân Phú, Bà Rịa - Vũng Tàu) -> (Phường An Phú, TP. Hồ Chí Minh).
  Thuộc tính (phone | device_id | street, ward, district, province); "HN" = (Phường An Phú, null, Hà Nội):
  C01: 0901000001 | DEV-R | 1 Lê Lợi, Phường An Phú, null, TP. Hồ Chí Minh
  C02: +84 90 100 0001 | DEV-02 | 2 Hai Bà Trưng, HN
  C03: 0903000003 | DEV-R | 3 Hai Bà Trưng, HN
  C04: 0904000004 | DEV-04 | 1 Lê Lợi, Phường Bình Thạnh, Quận Tân Phú, Bà Rịa - Vũng Tàu
  C05: 0905000005 | DEV-04 | 5 Hai Bà Trưng, HN
  C06, C07, C08: 0906000006 | DEV-06 | 6 Nguyễn Huệ, HN   (cùng một người: er_golden của cả ba là G-C06)
  C09: 0909000009 | DEV-09 | 6 Nguyễn Huệ, HN
  C10: 0910000010 | DEV-06 | 10 Hai Bà Trưng, HN
  C11: 0906 000 006 | DEV-11 | 11 Hai Bà Trưng, HN
  C12: 0912000012 | DEV-12 | 12 Pasteur, HN;  C13: 0913000013 | DEV-13 | 12 Pasteur, HN
  C14..C19: 0999999999 | DEV-<n> | <n> Hai Bà Trưng, HN   (C19 KHÔNG có dòng er_golden)
  C20, C21: 12345 | null | null;  C22: null | '' | ''
  Giao dịch: T01 2026-03-01 10:00:00 A02->A01 10M; T02 2026-03-02 10:00:00 A03->A01 20M; T03 2026-03-03 10:00:00
  A01->EXT-01 25M; T04 2026-03-03 11:00:00 A01->A20 5M; T05 2026-03-04 10:00:00 A01->A01S 3M; T06 2026-07-01 10:00:00
  A04->A01 7M; T07 2026-03-05 10:00:00 A05->A04 1M.
MINI-CYC: mỗi tài khoản sau thuộc một khách hàng riêng `C-<tài khoản>`, riêng G1S (SAVINGS) thuộc `C-G1`:
  B1 B2 B3, D1 D2 D3, E1 E2 E3, F1 F2, G1 G2 G3 G4 G1S, H1 H2 H3, I1 I2 I3, J1..J6, L1 L2 L3, M1 M2.
  Y01 2026-03-01 10:00:00 B1->B2 100M; Y02 2026-03-02 10:00:00 B2->B3 95M; Y02D 2026-03-02 10:00:00 B2->B3 95M (bản
  trùng); Y03 2026-03-03 10:00:00 B3->B1 90M;
  Y11 2026-05-01 10:00:00 B2->B3 80M; Y12 2026-05-02 10:00:00 B3->B1 80M; Y13 2026-05-03 10:00:00 B1->B2 80M;
  Y21 2026-03-05 10:00:00 D1->D2 100M; Y22 2026-03-04 10:00:00 D2->D3 100M; Y23 2026-03-06 10:00:00 D3->D1 100M;
  Y31 2026-04-01 10:00:00 E1->E2 100M; Y32 2026-04-03 10:00:00 E2->E3 100M; Y33 2026-04-08 10:00:00 E3->E1 100M;
  Y41 2026-03-01 10:00:00 F1->F2 100M; Y42 2026-03-02 10:00:00 F2->F1 100M;
  Y51..Y55 lúc 10:00:00 các ngày 2026-03-01 tới 03-05, mỗi cái 100M: G1->G2, G2->G3, G3->G1S, G1S->G4, G4->G1;
  Y61 2026-03-01 10:00:00 H1->H2 100M; Y62 2026-03-02 10:00:00 H2->H3 69M; Y63 2026-03-03 10:00:00 H3->H1 69M;
  Y71 2026-03-01 10:00:00 I1->I2 60M; Y72 2026-03-02 10:00:00 I2->I3 49 999 000; Y73 2026-03-03 10:00:00 I3->I1 55M;
  Y81..Y86 ngày 2026-03-01 lúc 10:00:00, 11:00:00, 12:00:00, 13:00:00, 14:00:00, 15:00:00, mỗi cái 100M: J1->J2, J2->J3,
  J3->J4, J4->J5, J5->J6, J6->J1;
  Y91 2026-03-10 10:00:00 L1->L2 100M; Y92 2026-03-10 10:00:00 L2->L3 100M; Y93 2026-03-11 10:00:00 L3->L1 100M;
  Y101 2026-03-01 10:00:00 M1->EXT-5 100M; Y102 2026-03-02 10:00:00 EXT-5->M2 100M; Y103 2026-03-03 10:00:00 M2->M1 100M.
MINI-HUB: tài khoản P0, Q0, R0, W0, L0, S01..S10, U01..U10, V01..V09, X01..X10, Z01..Z10, mỗi cái một khách hàng riêng
  `C-<tài khoản>`, riêng er_golden của C-X09 và C-X10 là `G-C-W0` (cùng chủ với W0).
  HP01..HP10: 2026-03-01 lúc 01:00:00 tới 10:00:00 (mỗi giờ một cái), S<k>->P0 20M; HP11 2026-03-01 12:00:00 S01->P0 20M;
  HP12 2026-03-01 13:00:00 EXT-1->P0 500M; HP13 2026-03-06 10:00:00 P0->S02 150M;
  HQ01..HQ10: 2026-03-02 lúc 01:00:00 tới 10:00:00, U<k>->Q0 9 999 000;
  HR01..HR09: 2026-03-03 lúc 01:00:00 tới 09:00:00, V<k>->R0 20M;
  HW01..HW10: 2026-03-04 lúc 01:00:00 tới 10:00:00, X<k>->W0 20M;
  HL01..HL09: 2026-03-05 lúc 01:00:00 tới 09:00:00, Z<k>->L0 20M; HL10 2025-06-30 10:00:00 Z10->L0 20M.
Test có nhãn [oracle] dùng @pytest.mark.oracle; các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given `config.yaml`, `pyproject.toml`, hằng `NETWORK_RULES`, thư mục `sql/` của repo và DuckDB rỗng (`duck`), When `load_settings(environ={})`, duyệt `NETWORK_RULES` và gọi `apply_schema(duck)` hai lần, Then `settings.network.shared_attributes` = (`min_customers` 5, `max_customers_per_value` 50), `settings.network.cycles` = (`min_length` 3, `max_length` 5, `window_hours` 168, `min_amount_vnd` 50000000, `min_amount_ratio` 0.7, `max_search_steps` 1000000), `settings.network.hubs` = (`lookback_days` 365, `min_in_degree` 10, `min_pagerank_ratio` 1.8, `min_inflow_vnd` 100000000, `pagerank_alpha` 0.85); `load_settings(environ={"AML__NETWORK__CYCLES__MAX_LENGTH": "2"})` raise `pydantic.ValidationError` chứa `max_length must be >= min_length`, `load_settings(environ={"AML__NETWORK__CYCLES__MAX_LENGTH": "7"})` raise `pydantic.ValidationError` chứa `max_length must be <= 6`, `load_settings(environ={"AML__NETWORK__CYCLES__MIN_AMOUNT_RATIO": "1.5"})` raise `pydantic.ValidationError` chứa `min_amount_ratio must be in [0, 1]` và `load_settings(environ={"AML__NETWORK__SHARED_ATTRIBUTES__MIN_CUSTOMERS": "1"})` raise `pydantic.ValidationError` chứa `min_customers must be >= 2`; `import networkx` và `import scipy` thành công, `networkx.__version__` bắt đầu bằng `3.`; `NETWORK_RULES` có đúng 3 rule theo thứ tự `NET_SHARED_ATTRIBUTE`, `NET_CYCLE`, `NET_HUB`, tất cả `rule_version == "v1"`, `target_typology` lần lượt `mule_ring`, `round_tripping`, `mule_ring`; `network_rule_params("NET_SHARED_ATTRIBUTE", settings) == {"max_customers_per_value": 50, "min_customers": 5}`, `network_rule_params("NET_CYCLE", settings) == {"max_length": 5, "max_search_steps": 1000000, "min_amount_ratio": 0.7, "min_amount_vnd": 50000000, "min_length": 3, "window_hours": 168}` và `network_rule_params("NET_HUB", settings) == {"lookback_days": 365, "min_in_degree": 10, "min_inflow_vnd": 100000000, "min_pagerank_ratio": 1.8, "pagerank_alpha": 0.85}`; `ddl/130_network.sql` có trong `SCHEMA_SCRIPTS["duckdb"]` và `SCHEMA_SCRIPTS["oracle"]`, đứng sau `ddl/110_monitoring.sql` và trước `ddl/050_customers_masked.sql` / `ddl/050_security_objects.sql`, resolve qua `sql_file` về đúng `sql/<backend>/`; `apply_schema` không raise; và `SELECT COUNT(*)` trên `nx_account_features` và `nx_account_features_current` đều trả 0.
- AC2: Given MINI-SHR, When gọi `detect_network(duck, settings)` và lọc `rule_id == "NET_SHARED_ATTRIBUTE"`, Then có đúng 2 alert theo thứ tự: (`subject_type` = `ACCOUNT_GROUP`, `subject_id` = `SHARED-C01`, `alert_key` = `NET_SHARED_ATTRIBUTE|SHARED-C01`, `accounts` = ((A01, MEMBER), (A01S, MEMBER), (A02, MEMBER), (A03, MEMBER), (A04, MEMBER), (A05, MEMBER)), `txn_ids` = (T01, T02, T07), `amount_vnd` = 31000000, `window_start` 2026-03-01 10:00:00, `window_end` 2026-03-05 10:00:00, `details` = {customers: 5, cifs: [C01, C02, C03, C04, C05], accounts: 6, links: {device: 4, phone: 2, address: 2}, shared_values: {device: 2, phone: 1, address: 1}, internal_txns: 3, internal_vnd: 31000000}, `reason` bằng đúng `5 customers (6 accounts) linked by shared device (4 customers), phone (2), address (2); 3 transfer(s) totalling 31,000,000 VND between members between 2026-03-01 10:00:00 and 2026-03-05 10:00:00`) — C02 nối qua điện thoại khác định dạng, C04 qua địa chỉ viết theo đơn vị hành chính cũ, C05 chỉ nối bắc cầu qua thiết bị của C04; T03 (ra `EXT-01`), T04 (tới tài khoản ngoài cụm), T05 (cùng chủ) và T06 (sau `as_of`) không phải evidence — và (`subject_id` = `SHARED-C14`, 6 tài khoản A14 tới A19, `txn_ids` = (), `amount_vnd` = 0, `window_start` = `window_end` = 2026-06-30 00:00:00, `details.customers` = 6, `details.links` = {device: 0, phone: 6, address: 0}, `reason` bằng đúng `6 customers (6 accounts) linked by shared device (0 customers), phone (6), address (0); no transfers between members`) — C19 không có trong `customer_golden` vẫn được tính là một khách hàng; không có alert cho nhóm C06 tới C11 (6 CIF nhưng chỉ 4 khách hàng vì C06, C07, C08 là một người), C12 và C13 (2 khách hàng), C20 và C21 (số điện thoại `12345` không hợp lệ nên không phải giá trị dùng chung), C22; When ghi đè `AML__NETWORK__SHARED_ATTRIBUTES__MIN_CUSTOMERS=4`, Then có 3 alert, alert thứ hai có `subject_id` = `SHARED-C06`, `details.customers` = 4, `details.cifs` = [C06, C07, C08, C09, C10, C11], 6 tài khoản A06 tới A11, `details.links` = {device: 2, phone: 2, address: 2} và `reason` bằng đúng `4 customers (6 accounts) linked by shared device (2 customers), phone (2), address (2); no transfers between members`; When ghi đè `MIN_CUSTOMERS=6`, Then chỉ còn `SHARED-C14`; When ghi đè `AML__NETWORK__SHARED_ATTRIBUTES__MAX_CUSTOMERS_PER_VALUE=5`, Then chỉ còn `SHARED-C01` (số điện thoại do 6 khách hàng dùng chung bị bỏ qua); When gọi `detect_network(duck, settings, as_of=date(2026, 7, 1))`, Then `SHARED-C01` có `txn_ids` = (T01, T02, T06, T07), `amount_vnd` = 38000000, `window_end` 2026-07-01 10:00:00 và `SHARED-C14` có `window_start` 2026-07-01 00:00:00; và Given tiếp tục `DELETE FROM er_runs`, When gọi `detect_network`, Then raise `NetworkError` chứa ``run `aml er` first``.
- AC3: Given MINI-CYC, When gọi `detect_network(duck, settings)` và lọc `rule_id == "NET_CYCLE"`, Then mọi alert đều có `subject_id` = `B1>B2>B3` (2 alert, chi tiết ở AC4) và không có alert nào cho: D1, D2, D3 (Y22 xảy ra trước Y21 nên không có cách xoay nào cho thời gian tăng dần), E1, E2, E3 (Y33 cách Y31 đúng 168 giờ nên nằm ngoài cửa sổ), F1, F2 (vòng 2 chặng), G1, G2, G3, G1S, G4 (vòng 5 chặng đi qua hai tài khoản G1 và G1S của cùng một khách hàng), H1, H2, H3 (69M / 100M = 0,69 < 0,70), I1, I2, I3 (Y72 = 49 999 000 dưới sàn 50M), J1 tới J6 (vòng 6 chặng), L1, L2, L3 (Y91 và Y92 cùng `txn_ts`), M1, M2 (vòng đi qua `EXT-5`); When ghi đè `AML__NETWORK__CYCLES__WINDOW_HOURS=169`, Then có 3 alert, thêm `E1>E2>E3` với `txn_ids` = (Y31, Y32, Y33), `details.hours` = 168; When ghi đè `AML__NETWORK__CYCLES__MIN_AMOUNT_RATIO=0.69`, Then có 3 alert, thêm `H1>H2>H3` với `amount_vnd` = 238000000 và `reason` chứa `100,000,000 VND left H1 and 69,000,000 VND (69%) returned after 3 transfers`; When ghi đè `AML__NETWORK__CYCLES__MIN_AMOUNT_VND=49999000`, Then có 3 alert, thêm `I1>I2>I3` với `amount_vnd` = 164999000; When ghi đè `AML__NETWORK__CYCLES__MAX_LENGTH=6`, Then có 3 alert, thêm `J1>J2>J3>J4>J5>J6` với 6 tài khoản (J1 vai `ORIGIN`, 5 tài khoản còn lại vai `HOP`), `txn_ids` = (Y81, Y82, Y83, Y84, Y85, Y86), `details.length` = 6, `details.hours` = 5, `window_start` 2026-03-01 10:00:00, `window_end` 2026-03-01 15:00:00; When ghi đè `MAX_LENGTH=4`, Then vẫn đúng 2 alert `B1>B2>B3`; và trong mọi trường hợp trên không có alert `NET_SHARED_ATTRIBUTE` hay `NET_HUB` nào.
- AC4: Given MINI-CYC, When gọi `detect_network(duck, settings)`, Then `cycle_search_steps = 37` và có đúng 2 alert `NET_CYCLE` theo thứ tự: alert thứ nhất có `subject_type` = `ACCOUNT_GROUP`, `subject_id` = `B1>B2>B3`, `alert_key` = `NET_CYCLE|B1>B2>B3|2026-03-01T10:00:00`, `accounts` = ((B1, ORIGIN), (B2, HOP), (B3, HOP)), `txn_ids` = (Y01, Y02, Y02D, Y03) (hai vòng chỉ khác bản giao dịch trùng được gộp làm một), `amount_vnd` = 380000000, `window_start` 2026-03-01 10:00:00, `window_end` 2026-03-03 10:00:00, `details` = {length: 3, origin: B1, path: [B1, B2, B3], first_vnd: 100000000, last_vnd: 90000000, hours: 48, instances: 2}, `reason` bằng đúng `100,000,000 VND left B1 and 90,000,000 VND (90%) returned after 3 transfers across 3 customers in 48 hours (B1 -> B2 -> B3 -> B1) between 2026-03-01 10:00:00 and 2026-03-03 10:00:00`; alert thứ hai (đợt tháng 5 của cùng ba tài khoản, bắt đầu từ B2) có cùng `subject_id` = `B1>B2>B3`, `alert_key` = `NET_CYCLE|B1>B2>B3|2026-05-01T10:00:00`, `accounts` = ((B1, HOP), (B2, ORIGIN), (B3, HOP)), `txn_ids` = (Y11, Y12, Y13), `amount_vnd` = 240000000, `details.path` = [B2, B3, B1], `details.instances` = 1, `reason` bằng đúng `80,000,000 VND left B2 and 80,000,000 VND (100%) returned after 3 transfers across 3 customers in 48 hours (B2 -> B3 -> B1 -> B2) between 2026-05-01 10:00:00 and 2026-05-03 10:00:00`; When gọi `detect_network(duck, settings, as_of=date(2026, 3, 2))` rồi `as_of=date(2026, 3, 3)`, Then lần lượt có 0 và 1 alert `NET_CYCLE` (alert tháng 3 với đủ 4 `txn_ids`); When ghi đè `AML__NETWORK__CYCLES__MAX_SEARCH_STEPS=37`, Then vẫn 2 alert; When ghi đè `MAX_SEARCH_STEPS=36`, Then `detect_network` raise `NetworkError` chứa `cycle search exceeded max_search_steps`; và Given tiếp tục `UPDATE er_golden SET golden_customer_id = 'G-C-B1' WHERE cif = 'C-B3'` (B3 thành tài khoản của chủ B1), When gọi `detect_network(duck, settings)`, Then có 0 alert `NET_CYCLE`.
- AC5: Given MINI-HUB, When gọi `detect_network(duck, settings)`, Then `active_accounts = 51` và có đúng 1 alert, `rule_id` = `NET_HUB`: `subject_type` = `ACCOUNT`, `subject_id` = `P0`, `alert_key` = `NET_HUB|P0`, `accounts` = ((P0, SUBJECT),), `txn_ids` = HP01 tới HP11 (11 giao dịch; HP12 từ `EXT-1` không tính), `amount_vnd` = 220000000, `window_start` 2026-03-01 01:00:00, `window_end` 2026-03-01 12:00:00, `details.in_degree` = 10 (S01 gửi hai lần vẫn là một người gửi), `details.out_degree` = 1, `details.in_vnd` = 220000000, `details.out_vnd` = 150000000, `details.transfers` = 11, `details.active_accounts` = 51, `details.pagerank_ratio` làm tròn 2 bằng 12.13, `reason` bằng đúng `received 220,000,000 VND from 10 accounts of other customers in 11 transfers between 2026-03-01 01:00:00 and 2026-03-01 12:00:00; PageRank 12.13x the average of 51 active accounts`; trong `features` (54 dòng): Q0 có `in_degree` = 10, `in_vnd` = 99990000, `pagerank_ratio` = 3.37, `is_hub` = 0 (dưới sàn 100M); R0 có `in_degree` = 9; W0 có `in_degree` = 8 (X09, X10 cùng chủ với W0 nên không tính, và X09 có mọi cột số bằng 0); L0 có `in_degree` = 9 (HL10 ngày 2025-06-30 nằm ngoài 365 ngày); S02 có `in_degree` = 1, `pagerank_ratio` trong khoảng [10.6, 10.7] (cao nhưng chỉ có một người gửi), `is_hub` = 0; tổng cột `pagerank` lệch 1.0 không quá 0.000001; When ghi đè `AML__NETWORK__HUBS__MIN_INFLOW_VND=99990000`, Then tập hub là {P0, Q0}; When ghi đè `AML__NETWORK__HUBS__MIN_IN_DEGREE=9`, Then là {L0, P0, R0}; When ghi đè `MIN_IN_DEGREE=8`, Then là {L0, P0, R0, W0}; When ghi đè `MIN_IN_DEGREE=1`, Then là {L0, P0, R0, S02, W0}; When ghi đè `AML__NETWORK__HUBS__LOOKBACK_DAYS=366`, Then là {L0, P0}, `active_accounts = 52`, alert của L0 có `txn_ids` = HL01 tới HL10 và `window_start` 2025-06-30 10:00:00; When ghi đè `AML__NETWORK__HUBS__MIN_PAGERANK_RATIO=12.2`, Then không có hub nào, và với `12.1` thì là {P0}; When gọi `detect_network(duck, settings, as_of=date(2026, 3, 1))`, Then hub duy nhất là P0 với `details.out_degree` = 0, `details.active_accounts` = 13, `details.pagerank_ratio` làm tròn 2 bằng 5.53; và When gọi với `as_of=date(2026, 2, 28)`, Then có 0 alert, `active_accounts = 0` và không raise.
- AC6: Given TINY trong DuckDB (đã `run_er`, chưa chạy 5a), When gọi `detect_network(duck, settings)`, Then `active_accounts = 298`, `cycle_search_steps = 12` và có đúng 4 alert theo thứ tự, tất cả `rule_version = "v1"`: (1) `NET_SHARED_ATTRIBUTE`, `subject_id` = `SHARED-CIF00000002`, 53 tài khoản vai `MEMBER` (đầu `A1043446740`, cuối `A9840068430`) của 29 CIF, 28 `txn_ids` (đầu `T0000002986`, cuối `T0000003071`), `amount_vnd` = 2849484000, `window_start` 2026-04-16 01:11:48, `window_end` 2026-04-17 23:16:36, `details.customers` = 29, `details.links` = {device: 16, phone: 7, address: 8}, `details.shared_values` = {device: 1, phone: 1, address: 1}, `reason` bằng đúng `29 customers (53 accounts) linked by shared device (16 customers), phone (7), address (8); 28 transfer(s) totalling 2,849,484,000 VND between members between 2026-04-16 01:11:48 and 2026-04-17 23:16:36`, và tập CIF của 53 tài khoản bằng đúng tập CIF của 29 tài khoản vai `collector` / `member` của `GT-MULE-0001`; (2) `NET_CYCLE`, `subject_id` = `A1070944972>A8201784530>A3312263346>A9950029109`, `alert_key` = `NET_CYCLE|A1070944972>A8201784530>A3312263346>A9950029109|2026-03-22T15:00:00`, `A8201784530` vai `ORIGIN` và 3 tài khoản còn lại vai `HOP`, `txn_ids` = (T0000002197, T0000002246, T0000002299, T0000002327) bằng đúng tập giao dịch `evidence` của `GT-RND-0001`, `amount_vnd` = 1722240000, `reason` bằng đúng `456,916,000 VND left A8201784530 and 399,475,000 VND (87%) returned after 4 transfers across 4 customers in 105 hours (A8201784530 -> A3312263346 -> A9950029109 -> A1070944972 -> A8201784530) between 2026-03-22 15:00:00 and 2026-03-27 00:11:51`; (3) `NET_CYCLE`, `subject_id` = `A4750305205>A7799247681>A7641423153>A9059982551`, `A9059982551` vai `ORIGIN`, `txn_ids` = (T0000002277, T0000002283, T0000002332, T0000002400) bằng đúng `evidence` của `GT-RND-0002`, `amount_vnd` = 1532271000, `details.hours` = 94; (4) `NET_HUB`, `subject_id` = `A4937939209`, 31 `txn_ids`, `amount_vnd` = 2930380000, `details.in_degree` = 31, `details.out_degree` = 3, `reason` bằng đúng `received 2,930,380,000 VND from 31 accounts of other customers in 31 transfers between 2026-04-13 09:28:12 and 2026-04-17 23:16:36; PageRank 6.77x the average of 298 active accounts`; `features` có 532 dòng với cột bằng `FEATURE_COLUMNS`, 298 dòng `pagerank > 0`, 53 dòng `shared_cluster_id = 'SHARED-CIF00000002'` (đều `shared_cluster_size = 29`), 8 dòng `cycle_alerts = 1`, 1 dòng `is_hub = 1`; dòng `A1463821795` (merchant lành tính) có `in_degree` = 34, `in_vnd` = 38925000, `pagerank_ratio` = 7.30, `is_hub` = 0; dòng `A6457424962` (không có chuyển khoản nào) có mọi cột số bằng 0; `attribute_keys(customers, mapping)` trả 300 dòng có `phone_key` và `address_key` bằng đúng `phone_norm` và `addr_key` của `prepare_records` cho từng CIF; When ghi đè `AML__NETWORK__SHARED_ATTRIBUTES__MIN_CUSTOMERS=2`, Then có 2 alert `NET_SHARED_ATTRIBUTE`, alert thêm là `SHARED-CIF00000148` với `details.customers` = 2 và `details.links` = {device: 0, phone: 0, address: 2}; When ghi đè `MAX_CUSTOMERS_PER_VALUE=15`, Then alert cụm duy nhất là `SHARED-CIF00000014` với `details.customers` = 14, `details.links.device` = 0 (thiết bị do 16 khách hàng dùng chung bị bỏ qua); và Given một DuckDB khác chứa cùng dữ liệu TINY nhưng các dòng `transactions`, `customers`, `accounts` được chèn lại theo thứ tự đã xáo, When gọi `detect_network`, Then `alerts` và `features` bằng đúng kết quả của DuckDB gốc.
- AC7: Given TINY trong DuckDB (đã `run_er`, chưa chạy 5a), When gọi `run_network(duck, settings)` lần đầu, Then trả `NetworkRun(run_id=1, as_of=date(2026, 6, 30), alerts=4, evidence=67, by_rule={"NET_SHARED_ATTRIBUTE": 1, "NET_CYCLE": 2, "NET_HUB": 1}, accounts=532, active_accounts=298, cycle_search_steps=12)`; `alerts` có 4 dòng `run_id = 1`, `source = 'NETWORK'`, `alert_id` 1 tới 4 theo thứ tự của AC6, `subject_type` lần lượt `ACCOUNT_GROUP`, `ACCOUNT_GROUP`, `ACCOUNT_GROUP`, `ACCOUNT`, `txn_count` lần lượt 28, 4, 4, 31; `alert_accounts` có 62 dòng (53 `MEMBER`, 2 `ORIGIN`, 6 `HOP`, 1 `SUBJECT`) trên 61 tài khoản khác nhau, dòng (`alert_id = 4`, `A4937939209`) có `cif = 'CIF00000189'` và dòng `ORIGIN` của `alert_id = 2` có `account_id = 'A8201784530'`, `cif = 'CIF00000206'`; `alert_evidence` có 67 dòng trên 39 `txn_id` khác nhau; `monitoring_runs` có 3 dòng `run_id = 1`, `source = 'NETWORK'`, `as_of = 2026-06-30`, với (`alerts`, `evidence`) lần lượt (1, 28), (2, 8), (1, 31) và `params` của dòng `NET_CYCLE` bằng `network_rule_params("NET_CYCLE", settings)`; `nx_account_features` có 532 dòng `run_id = 1`, dòng `A4937939209` có `in_degree = 31`, `out_degree = 3`, `in_vnd = 2930380000`, `out_vnd = 2851894000`, `pagerank_ratio` làm tròn 2 bằng 6.77, `shared_cluster_id = 'SHARED-CIF00000002'`, `is_hub = 1`; `audit_log` có đúng 5 dòng `module='monitoring'`: 4 dòng `decision='ALERT'` (dòng `entity_id='2'` có `version='NET_CYCLE/v1'` và `reason` bằng `reason` của alert 2) và 1 dòng `decision='MONITORING_RUN_COMPLETED'`, `entity_id='1'`, `details.source = 'NETWORK'`, `details.alerts = 4`; When gọi tiếp `run_monitoring(duck, settings)` của 5a rồi `run_network(duck, settings)` lần hai, Then lần lượt trả `run_id = 2` (31 alert `RULE`) và `run_id = 3` với `alerts`, `evidence`, `by_rule` như lần đầu; 4 alert mới có `alert_id` 36 tới 39; tập (`alert_key`, `reason`, `txn_count`, `amount_vnd`) và tập (`alert_key`, `txn_id`) của lần 1 và lần 3 bằng nhau; 4 dòng `run_id = 1` của `alerts` không đổi; `alerts_current` có 35 dòng (31 dòng `RULE` của `run_id = 2` và 4 dòng `NETWORK` của `run_id = 3`); `nx_account_features` có 1064 dòng và `nx_account_features_current` chỉ gồm 532 dòng `run_id = 3`; When gọi tiếp `run_network(duck, settings, as_of=date(2026, 3, 26))`, Then trả `run_id = 4`, `alerts = 1`, `evidence = 0`, `by_rule = {"NET_SHARED_ATTRIBUTE": 1, "NET_CYCLE": 0, "NET_HUB": 0}`; alert đó có `alert_key = 'NET_SHARED_ATTRIBUTE|SHARED-CIF00000002'`, `txn_count = 0`, `amount_vnd = 0`, `window_start` = `window_end` = 2026-03-26 00:00:00, `reason` kết thúc bằng `no transfers between members`, 53 dòng `alert_accounts` và 0 dòng `alert_evidence`; `monitoring_runs` có 3 dòng `run_id = 4` (hai dòng `alerts = 0`); `alerts_current` còn 32 dòng (31 `RULE` và 1 `NETWORK`); Given DuckDB chỉ mới `apply_schema`, When gọi `run_network`, Then raise `NetworkError` chứa ``run `aml load` first``; và Given TINY đã `load_parquet` nhưng chưa `run_er`, When gọi `run_network`, Then raise `NetworkError` chứa ``run `aml er` first``; trong cả hai trường hợp lỗi `alerts`, `monitoring_runs`, `nx_account_features` vẫn rỗng và `audit_log` không có dòng `monitoring` nào.
- AC8: Given TINY đã `run_er`, `run_monitoring` (5a: 31 alert `RULE`) rồi `run_network`, When gọi `evaluate_network(duck)` và `network_coverage(duck)`, Then `evaluate_network` trả 3 dòng theo thứ tự `NETWORK_RULES` với (`alerts`, `target_hits`, `other_suspicious`, `benign`, `unlabelled`, `precision`, `precision_suspicious`, `scenarios`, `detected`, `recall`) lần lượt là `NET_SHARED_ATTRIBUTE` (1, 1, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0), `NET_CYCLE` (2, 2, 0, 0, 0, 1.0, 1.0, 2, 2, 1.0), `NET_HUB` (1, 1, 0, 0, 0, 1.0, 1.0, 1, 1, 1.0) — alert cụm được gán cho `GT-MULE-0001` vì 29 trên 53 tài khoản của nó thuộc kịch bản này và 24 tài khoản còn lại không thuộc kịch bản nào; `network_coverage` trả 6 dòng với (`scenarios`, `flagged_rule`, `flagged_network`, `flagged_any`, `new_by_network`, `accounts`, `accounts_rule`, `accounts_network`, `accounts_any`, `accounts_new`) lần lượt `structuring` (2, 2, 0, 2, 0, 2, 2, 0, 2, 0), `rapid_movement` (2, 2, 0, 2, 0, 10, 2, 0, 2, 0), `mule_ring` (1, 1, 1, 1, 0, 36, 14, 29, 36, 22), `round_tripping` (2, 2, 2, 2, 0, 8, 2, 8, 8, 6), `benign_payroll` (1, 0, 0, 0, 0, 21, 0, 0, 0, 0), `benign_merchant` (1, 0, 0, 0, 0, 35, 0, 0, 0, 0), cột `rules` của `mule_ring` là `NET_HUB,NET_SHARED_ATTRIBUTE`, của `round_tripping` là `NET_CYCLE`, của bốn dòng còn lại là chuỗi rỗng; When gọi tiếp `run_network` với ghi đè `AML__NETWORK__HUBS__MIN_INFLOW_VND=0` rồi `evaluate_network` và `network_coverage`, Then dòng `NET_HUB` là (2, 1, 0, 1, 0, 0.5, 0.5, 1, 1, 1.0) (alert thêm nằm trên merchant lành tính `A1463821795`, `reason` bắt đầu bằng `received 38,925,000 VND from 34 accounts of other customers in 67 transfers`) và dòng `benign_merchant` có `flagged_network = 1`, `accounts_network = 1`, `rules = 'NET_HUB'`; Given TINY đã `run_er` và `run_network` nhưng chưa `run_monitoring`, When gọi `network_coverage`, Then cả 6 dòng có `flagged_rule = 0` và `accounts_rule = 0`, dòng `mule_ring` có `new_by_network = 1`, `accounts_new = 29`; và Given TINY chưa chạy `run_network`, When gọi `evaluate_network`, Then raise `NetworkError` chứa ``run `aml network` first``.
- AC9: Given `DB_BACKEND=duckdb` với TINY đã nạp (`tiny_env`), đã chạy `aml er` và `aml monitor`, When chạy `aml network --eval-out <tmp>/network_eval.csv`, Then exit code 0; stdout có 3 dòng rule, dòng `NET_SHARED_ATTRIBUTE` chứa `alerts=1` và `evidence=28`, dòng `NET_CYCLE` chứa `alerts=2` và `evidence=8`, dòng `NET_HUB` chứa `alerts=1` và `evidence=31`; có dòng tổng kết chứa `run_id=2`, `as_of=2026-06-30`, `alerts=4`, `evidence=67`, `accounts=532`, `active_accounts=298`, `cycle_search_steps=12`; có 3 dòng đánh giá, dòng `NET_CYCLE` chứa `target_hits=2`, `benign=0`, `precision=1.00 recall=1.00`; có 6 dòng phủ typology, dòng `mule_ring` chứa `scenarios=1`, `rule=1`, `network=1`, `new=0`, `accounts=36`, `accounts_rule=14`, `accounts_network=29`, `accounts_new=22`, dòng `benign_merchant` chứa `network=0`; file `network_eval.csv` có dòng tiêu đề `rule_id,target_typology,alerts,target_hits,other_suspicious,benign,unlabelled,precision,precision_suspicious,scenarios,detected,recall` và 3 dòng dữ liệu; When chạy `aml network --as-of 2026-13-01`, Then exit code 2 và `monitoring_runs` không thêm dòng; When chạy `aml network` với biến môi trường `AML__NETWORK__CYCLES__MAX_SEARCH_STEPS=11`, Then exit code 1, stderr chứa `cycle search exceeded max_search_steps` và `alerts` không thêm dòng; Given TINY đã `aml load` nhưng chưa `aml er`, When chạy `aml network`, Then exit code 1 và stderr chứa ``run `aml er` first``; và Given DuckDB chưa `aml load`, When chạy `aml network`, Then exit code 1 và stderr chứa ``run `aml load` first``.
- AC10: [oracle] Given TINY nạp bằng `load_parquet` vào cả Oracle và một DuckDB tạm, rồi `run_er` trên cả hai, When gọi `run_network` với cùng `as_of = 2026-06-30` trên hai backend rồi `evaluate_network` trên Oracle, Then `alerts`, `evidence`, `by_rule`, `accounts`, `active_accounts`, `cycle_search_steps` của hai `NetworkRun` bằng nhau (4, 67, {1, 2, 1} theo thứ tự `NETWORK_RULES`, 532, 298, 12); tập (`alert_key`, `subject_id`, `reason`, `txn_count`, `amount_vnd`, `window_start`, `window_end`) đọc từ `alerts`, tập (`alert_key`, `account_id`, `role`, `cif`) đọc từ `alerts` nối `alert_accounts` và tập (`alert_key`, `txn_id`) đọc từ `alerts` nối `alert_evidence` của lần chạy đó bằng nhau giữa hai backend; tập (`account_id`, `in_degree`, `out_degree`, `in_vnd`, `out_vnd`, `pagerank_ratio` làm tròn 2, `cycle_alerts`, `shared_cluster_id`, `shared_cluster_size`, `is_hub`) của `nx_account_features` của lần chạy đó bằng nhau giữa hai backend; trên Oracle `user_tables` có `NX_ACCOUNT_FEATURES`, `user_views` có `NX_ACCOUNT_FEATURES_CURRENT`, và view này có 532 dòng thuộc lần chạy đó; số dòng `audit_log` `module='monitoring'` của lần chạy trên Oracle (lọc theo `details.run_id` hoặc `entity_id` của run) là 5; `evaluate_network` trên Oracle trả đúng 3 dòng như phần đầu AC8; và gọi `apply_schema` trên Oracle lần hai không raise.

## Ngoài phạm vi
- Rule SQL và mọi bảng / view / hàm của 5a (`alerts`, `alert_accounts`, `alert_evidence`, `monitoring_runs`, `alerts_current`, `record_run`, `aml monitor`): 5c chỉ gọi `record_run`, không sửa schema, không sửa `evaluate_rules` / `typology_coverage`.
- Fund-flow tracing (recursive CTE, SQL property graph) — 5b. 5c không dùng `acct_edge_daily`, không gọi `trace`.
- Neo4j, Cypher, GDS (WCC, Louvain, PageRank trong Neo4j), ghi đặc trưng GDS về Oracle, benchmark — Phase 6. 5c chỉ giữ chỗ tiền tố `nx_` cho đặc trưng NetworkX.
- Gộp alert thành case theo golden customer, enrichment, chấm điểm ưu tiên, dùng `nx_account_features` làm feature cho mô hình, good-guy list, disposition — Phase 7 / 7b.
- Alert hub chiều ra (tài khoản phân phối), hub theo degree thuần, PageRank có trọng số theo số tiền, PageRank ở cấp khách hàng, betweenness / community detection (Louvain) / k-core.
- Thuộc tính dùng chung khác: `ip`, `email`, số giấy tờ, `device_id` / `ip` ghi trên từng giao dịch; cụm theo thời gian (thuộc tính đổi theo ngày); trọng số theo độ hiếm của giá trị; quy tắc riêng cho địa chỉ (xem Q6).
- Vòng tiền đi qua tài khoản `EXT-*` hoặc qua tiền mặt; vòng 2 chặng (A→B→A); vòng giữa các tài khoản của cùng một khách hàng; vòng dài hơn 6 chặng; chia nhỏ / gộp số tiền giữa các chặng (một chặng tách thành nhiều giao dịch).
- Xác định vai trong cụm (collector, mule, nạn nhân), loại "người ngoài cuộc" khỏi cụm, whitelist hộ kinh doanh / employer.
- Chạy tăng dần, đồ thị trượt theo ngày, lịch chạy, chạy song song; bảng danh mục rule trong DB để bật/tắt.
- Quyền Oracle (`ROLE_GRANTS`, `020_grants.sql`) trên `nx_account_features`; purge/retention; đo hiệu năng trên profile `large`.
- Ghi số liệu vào README (làm ở bước demo của phase, từ lần chạy thật trên `small` và `dense`).

## Giả định
- Dữ liệu Phase 1 giữ các tính chất ở mục "Hiện trạng" (seed 42); AC6–AC10 chỉ cam kết cho TINY seed 42. Số liệu `small` / `dense` trong mục Hiện trạng chỉ để định hướng, không phải cam kết.
- Mọi con số phát hiện trong AC2–AC6 và AC8 (số alert, tài khoản, evidence, cửa sổ, `details`, `reason`, `pagerank_ratio`, `cycle_search_steps`, kết quả đánh giá) lấy từ prototype chạy thật trên DuckDB với NetworkX 3.6.1 / SciPy 1.17.1; các cột `*_rule` của AC8 dùng 31 alert của prototype 5a. **Suy ra từ thiết kế, chưa đo** (prototype không ghi bảng và 5a chưa có code): toàn bộ phần ghi của AC7 (`run_id`, `alert_id` 1–4 và 36–39, số dòng `monitoring_runs` / `alert_accounts` / `nx_account_features` / `audit_log`, `alerts_current` 35 / 32 dòng), thông điệp `ValidationError` ở AC1, định dạng stdout / CSV và `run_id=2` ở AC9, trường hợp "chưa `run_monitoring`" ở cuối AC8.
- AC10 chưa chạy trên Oracle (schema đang có đối tượng tạm của công việc khác nên không đụng tới): DDL 130, việc đọc `customers` / `transactions` từ Oracle cho 5c và việc ghi `nx_account_features` đều chưa kiểm. Căn cứ để tin là khớp: toàn bộ thuật toán chạy trong Python trên ba DataFrame, không phép sắp xếp nào dựa vào backend, và Phase 4 đã đọc `customers` từ Oracle cho kết quả trùng DuckDB.
- 5a được hiện thực trước 5c và giữ đúng chữ ký `record_run` / `AlertRecord` / `RuleRun` trong `specs/monitoring-rules.md`, kèm các điểm ở Q16. Phase 4 đã chạy (`customer_golden` có dữ liệu) trước `aml network`.
- `uv add "networkx>=3.4,<4" "scipy>=1.13"` giải được với các phiên bản đang khoá (đã chạy thử bằng `uv run --with networkx --with scipy`, không sửa `pyproject.toml`); nếu bước hiện thực khoá ra phiên bản cho `pagerank_ratio` lệch ở chữ số thứ hai thì cập nhật spec chứ không sửa công thức.
- `customers` không có lịch sử thuộc tính: chạy với `as_of` trong quá khứ vẫn dùng thiết bị / điện thoại / địa chỉ hiện tại. `txn_ts` là giờ địa phương naive (quy ước 1b-i); không dùng đồng hồ máy ngoài `run_ts` / `event_ts` do `record_run` ghi.
- Toàn bộ chuyển khoản nội bộ trước `cutoff` vừa bộ nhớ một tiến trình (`small` 45 nghìn dòng, `dense` 110 nghìn; `large` ước 1–2 triệu, chưa đo). PII của `customers` (điện thoại, địa chỉ) được kéo về bộ nhớ tiến trình trong lúc chạy như Phase 4, không ghi ra đĩa và không ghi vào bảng kết quả.
- `run_network` không chạy đồng thời với `run_monitoring` hay một `run_network` khác (`run_id`, `alert_id` cấp bằng `MAX + 1` trong `record_run`). Nếu ghi `nx_account_features` lỗi sau khi `record_run` đã xong thì alert của lần chạy vẫn tồn tại, bảng đặc trưng giữ lần chạy trước; chạy lại `aml network` để đồng bộ.
- Tên cột mới (`in_degree`, `out_degree`, `pagerank`, `is_hub`, `cycle_alerts`, …) không phải từ khoá dành riêng của Oracle 23ai; nếu DDL báo lỗi thì đổi tên ở cả hai backend và cập nhật spec.
- Lệnh chạy dưới schema owner (`aml_owner`), đọc `customers` gốc (không qua view che PII). `evaluate_network` / `network_coverage` chỉ có ý nghĩa trên dữ liệu tổng hợp. `reason`, thông điệp lỗi và output CLI bằng tiếng Anh như các lệnh hiện có.
- Test [oracle] nạp lại TINY vào schema `aml_owner` và để lại dòng trong các bảng / `audit_log`; AC10 so theo `run_id` của lần chạy trong test, không giả định `run_id = 1`.

## Câu hỏi mở
- [x] Q1. Đặt code ở đâu? — đề xuất mặc định: gói con `src/aml/graph/network/`, cạnh `src/aml/graph/trace.py` của 5b, phụ thuộc một chiều vào `aml.monitoring.recording`. Lý do: brief xếp network analysis vào `graph/`, Phase 6 sẽ đặt bản Cypher / GDS tương ứng ở `graph/neo4j/`; gói con riêng nên 5b và 5c hiện thực song song chỉ đụng nhau ở file rỗng `graph/__init__.py`. Phương án thay thế: `src/aml/monitoring/network/` (gần nơi ghi alert hơn, nhưng `monitoring/` sẽ phải import NetworkX / SciPy). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q2. Lệnh CLI? — đề xuất mặc định: lệnh riêng `aml network [--as-of] [--eval-out]`; `aml monitor` giữ nguyên là 5a. Lý do: 5a và 5c chạy độc lập (`alerts_current` lấy lần chạy mới nhất theo từng `rule_id`), 5c cần `aml er` chạy trước còn 5a thì không, và hai spec được hiện thực song song; `aml graph` / `aml bench` để dành cho Phase 6. Phương án thay thế: cờ `aml monitor --network` (một lệnh cho cả Phase 5, nhưng phải sửa lệnh của 5a và `MonitoringRun.by_rule`). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q3. Dependency? — đề xuất mặc định: thêm `networkx>=3.4,<4` và `scipy>=1.13`. Lý do: đã đo — `nx.pagerank` của NetworkX 3.x không chạy nếu thiếu SciPy; Phase 7 (scikit-learn) cũng sẽ kéo SciPy. Phương án thay thế: tự viết PageRank bằng power iteration trên NumPy (~30 dòng, không cần SciPy) — bớt một dependency nhưng lệch chữ "NetworkX" của brief. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q4. Gom cụm theo CIF hay theo golden customer của Phase 4? — đề xuất mặc định: theo `golden_customer_id`; "chủ" của tài khoản trong cả ba phát hiện cũng là golden customer; `customer_golden` rỗng thì `aml network` dừng với ``run `aml er` first``; CIF mới chưa có trong `customer_golden` được coi là một khách hàng riêng. Lý do: đã đo — theo CIF, `small` có 9 cụm ≥ 5 CIF mà 4 cụm chỉ là 2–3 người với nhiều CIF, và 133 cụm ≥ 3 CIF mà chỉ 5 là ring; theo golden còn đúng 5 ring. Hệ quả: 5c phụ thuộc Phase 4, và một lần ER gộp nhầm / tách sót sẽ lan sang đây. Phương án thay thế: thiếu `customer_golden` thì tự lùi về CIF kèm cảnh báo (chạy được không cần ER, nhưng kết quả đổi âm thầm). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q5. Thuộc tính nào được coi là "dùng chung" và chuẩn hoá ra sao? — đề xuất mặc định: `customers.device_id` (bỏ khoảng trắng), điện thoại qua `normalize_phone` và địa chỉ qua `addr_key` của Phase 4 (đã quy đơn vị hành chính cũ → mới); không dùng `ip`, `email`, hay `device_id` / `ip` trên từng giao dịch. Lý do: đúng ba loại brief nêu và đúng ba nhóm `link_members` chép; tái dùng chuẩn hoá đã kiểm thử nên `+84 90 …` và `090…` là một số; `ip` không trùng giữa hai khách hàng nào trong dữ liệu, giao dịch kịch bản có `device_id` null. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q6. Ngưỡng cụm và "người ngoài cuộc"? — đề xuất mặc định: thành phần liên thông đơn thuần trên cả ba loại thuộc tính, alert khi cụm có ≥ `min_customers` = 5 khách hàng. Lý do: đã đo `small` — ngưỡng 3 sinh 18 cụm (13 bộ ba trùng địa chỉ lành tính), ngưỡng 4 và 5 đều cho đúng 5 ring; 5 là cỡ ring nhỏ nhất generator sinh và lớn hơn một hộ gia đình thông thường. Hạn chế đã đo: 5 cụm kéo theo 8 khách hàng ngoài cuộc (trên 104) vì trùng địa chỉ với đúng một thành viên. Phương án thay thế đã đo: địa chỉ chỉ nối khi có ≥ 3 khách hàng dùng chung → 5 cụm đúng 96/96 thành viên, 0 người ngoài cuộc, nhưng (suy ra, chưa đo) ring nhỏ có đúng một thành viên chép địa chỉ sẽ mất thành viên đó và có thể tụt dưới ngưỡng — với ring 5 người xác suất khoảng 40%. Cần người dùng chốt ưu tiên recall hay tránh kéo người ngoài cuộc vào alert. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q7. Chặn giá trị "siêu phổ biến" (số tổng đài, địa chỉ chung cư, thiết bị quầy giao dịch)? — đề xuất mặc định: bỏ qua giá trị do hơn `max_customers_per_value` = 50 khách hàng dùng chung. Lý do: một giá trị như vậy sẽ dán cả đồ thị thành một cụm; 50 lớn hơn ring lớn nhất generator sinh (30) và giá trị rộng nhất đo được (16). Hạn chế: ring thật lớn hơn 50 người dùng chung một thiết bị sẽ bị bỏ sót phần đó; AC6 cho thấy hạ ngưỡng xuống 15 làm cụm TINY co từ 29 còn 14 khách hàng. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q8. Nội dung alert cụm? — đề xuất mặc định: một alert `ACCOUNT_GROUP` cho mỗi cụm, `alert_accounts` gồm **mọi** tài khoản của các khách hàng trong cụm (vai `MEMBER`), evidence là chuyển khoản giữa các thành viên; cụm chưa có chuyển khoản nội bộ vẫn là alert với 0 evidence; `reason` / `details` chỉ có số đếm và danh sách CIF, không có số điện thoại / địa chỉ / mã thiết bị. Lý do: Phase 7 gộp case theo khách hàng nên cần đủ tài khoản; dùng chung thuộc tính là tín hiệu KYC có trước cả giao dịch; giữ PII ngoài bảng alert như 5a. Hệ quả đo được: TINY 53 tài khoản cho 29 khách hàng (24 tài khoản phụ không nằm trong `ground_truth`). Phương án thay thế: chỉ alert khi cụm có chuyển khoản nội bộ; hoặc chỉ liệt kê tài khoản có giao dịch. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q9. Đồ thị giao dịch dựng từ `transactions` thô hay `acct_edge_daily`? — đề xuất mặc định: từ `transactions` thô, chỉ lấy chuyển khoản mà hai đầu đều là tài khoản trong `accounts` và khác chủ. Lý do: vòng tiền cần thứ tự thời gian trong ngày và `txn_id` làm evidence — `acct_edge_daily` chỉ có tổng theo ngày; bỏ `EXT-*` vì không có KYC để biết chủ (và mọi `EXT-*` đều vừa gửi vừa nhận nên sẽ sinh vòng giả); bỏ chuyển giữa tài khoản của cùng một người (`small`: 11 323 dòng) vì đó không phải đối tác. Đã đo: đọc và dựng đồ thị `dense` (110 nghìn dòng) trong ~2 giây. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q10. Định nghĩa vòng tiền? — đề xuất mặc định: 3 tới 5 chặng; thời gian tăng ngặt; chặng cuối trước (chặng đầu + 168 giờ); mỗi tài khoản một khách hàng khác nhau; mỗi chặng ≥ 50 triệu; số tiền nhỏ nhất ≥ 70% số tiền lớn nhất. Lý do: generator sinh 3–4 chặng, mỗi chặng giữ ≥ 92% (thấp nhất đo được 0,821), trong 7 ngày, lượt đầu ≥ 100 triệu; 70% ≈ 0,9^3 cho phép hao 10% mỗi chặng qua 4 chặng; 5 chặng để khớp "cycles of length 3–5" của Phase 6. Đã đo: 15/15 kịch bản `small` và `dense`, evidence trùng khít, 0 vòng ngoài; bỏ sàn tiền thì `dense` thêm 1 vòng nền, bỏ cả tỉ lệ thì thêm 22. Lưu ý: kết quả hoàn hảo một phần do tài khoản kịch bản không có giao dịch nền. Cần người dùng chốt sàn 50 triệu / 70% / 168 giờ. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q11. Chặn bùng nổ khi liệt kê vòng trên `dense`? — đề xuất mặc định: bốn lớp — sàn số tiền, cắt tỉa theo thành phần liên thông mạnh, tìm kiếm theo thời gian neo ở chặng sớm nhất trong cửa sổ, và ngân sách `max_search_steps` = 1 000 000 (vượt thì `NetworkError`, không ghi gì, không cắt bớt âm thầm). Lý do: đã đo `dense` — mặc định 66 bước; không sàn 103 526 bước (0,2 giây); cấu hình rộng nhất thử nghiệm 3,8 triệu bước; trong khi `nx.simple_cycles` không xét thời gian mất 348 giây cho vòng dài ≤ 4. Dừng hẳn thay vì trả kết quả thiếu là cùng hướng với `max_paths` của 5b. Phương án thay thế: cắt tại ngân sách và ghi cờ `truncated` (cần chỗ lưu cờ — `record_run` hiện không có). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q12. Một alert vòng tiền là gì? — đề xuất mặc định: các vòng trên cùng dãy tài khoản (xoay về `account_id` nhỏ nhất) bắt đầu cách nhau dưới `window_hours` gộp thành một đợt = một alert; `subject_id` là dãy tài khoản nối bằng `>`; tài khoản gửi chặng đầu có vai `ORIGIN`. Lý do: bản giao dịch trùng (defect DQ) tạo ra nhiều vòng chỉ khác một `txn_id` — AC4 gộp 2 vòng thành 1 alert; cùng nhóm lặp lại vào tháng khác là alert khác. `subject_id` đọc được ngay và khớp `PATH_SEPARATOR` của 5b. Hệ quả: `subject_id` dài tới 59 ký tự với mã tài khoản hiện tại (xem Q16). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q13. Định nghĩa hub — **câu hỏi ảnh hưởng nhiều nhất tới số alert và FP**? — đề xuất mặc định: chỉ hub **chiều vào**: `in_degree` ≥ 10 **và** `pagerank_ratio` ≥ 1,8 **và** tổng tiền vào ≥ 100 triệu, trên đồ thị chuyển khoản khác chủ trong 365 ngày. Lý do, đều đã đo: (i) degree đơn thuần vô dụng trên `dense` (4368 tài khoản có `in_degree` ≥ 10) còn PageRank vẫn tách được collector (≥ 2,06) khỏi nền (≤ 1,64); (ii) degree + PageRank bắt 5 collector **và 5 merchant lành tính** trên cả `small` lẫn `dense` (precision 0,5) — sàn 100 triệu (cùng giá trị với `fan_in_out.min_total_vnd` của 5a) loại 5 merchant (29,7–56,1 triệu) và giữ 5 collector (≥ 1,05 tỉ); (iii) hub chiều ra bằng PageRank đảo chiều chỉ bắt 5 employer lành tính và 0 source nên không sinh alert. Cần người dùng chốt vì: ngưỡng 1,8 nằm trong khe hẹp giữa 1,64 và 2,06 (chỉnh theo dữ liệu tổng hợp); sàn 100 triệu chỉ hiệu quả vì merchant tổng hợp có doanh thu nhỏ (merchant thật sẽ vượt); và `NET_HUB` không thêm tài khoản nào so với `FAN_IN` của 5a (trùng 5/5 collector). Phương án thay thế: (a) bỏ sàn tiền, chấp nhận và báo rõ 5 FP merchant (AC8 đã đo trường hợp này trên TINY: precision 0,5); (b) không sinh alert hub, chỉ ghi PageRank / degree vào `nx_account_features` cho Phase 7. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q14. Chi tiết PageRank và tính tất định? — đề xuất mặc định: không trọng số, α = 0,85 (config), `tol = 1e-10`, `max_iter = 200` (hằng số trong code), nút và cạnh thêm theo thứ tự `account_id`, `pagerank_ratio` = PageRank × số tài khoản có cạnh, làm tròn 4; `settings.seed` không tham gia vì không bước nào dùng số ngẫu nhiên. Lý do: đã đo — có trọng số theo số tiền không tách tốt hơn; `tol` mặc định 1e-6 làm lệch chữ số thứ ba; kết quả giống hệt qua ba giá trị `PYTHONHASHSEED` và khi xáo thứ tự dòng. AC chỉ so `pagerank_ratio` tới 2 chữ số. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q15. Có cần DDL `130` không? — đề xuất mặc định: có, một bảng `nx_account_features` (một dòng cho mỗi tài khoản mỗi lần chạy: degree, tiền vào/ra, PageRank, số alert vòng, cụm, cờ hub) và view `nx_account_features_current`. Lý do: Phase 7 cần "graph features" cho mọi tài khoản bị alert chứ không riêng hub, Phase 7b cần làm feature; số liệu đã tính sẵn trong lần chạy; tiền tố `nx_` tránh trùng với bảng GDS của Phase 6 và cho Phase 6 một mốc đối chiếu PageRank. Hệ quả: mỗi lần chạy thêm 8958 dòng trên `small`. Phương án thay thế: không có DDL, Phase 7 tự tính lại khi cần. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q16. Đường ghi của 5a (`record_run`, Q21 / AC8 của `specs/monitoring-rules.md`) cần gì để 5c ghi được? — đề xuất mặc định: 5c dùng nguyên chữ ký hiện có và **không đổi schema**, nhưng 5a cần cam kết năm điểm mà spec 5a chưa nêu: (1) `record_run` chấp nhận alert có `txn_ids` rỗng (`txn_count = 0`, không dòng `alert_evidence`) và danh sách `alerts` rỗng; (2) độ rộng cột: `subject_id` ≥ 128 ký tự (vòng 6 tài khoản × `account_id` VARCHAR(20) + 5 dấu `>` = 125), `alert_key` ≥ 200, `reason` ≥ 500, `role` ≥ 10; (3) `details` nhận JSON lồng nhau (danh sách CIF, dict `links`) không giới hạn 4000 byte trên Oracle; (4) `window_start` / `window_end` của alert không có evidence: 5c ghi 00:00:00 ngày `as_of` vì `AlertRecord` khai báo `datetime` không null — nếu 5a cho phép null thì 5c chuyển sang null; (5) `evaluate_rules` / `typology_coverage` của 5a luôn lọc `source = 'RULE'` để AC9 của 5a không đổi khi có alert `NETWORK`. Lý do: một đường ghi duy nhất cho `alerts_current` và audit; AC8 của 5a mới thử một alert nhóm có 1 evidence và `details` phẳng. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q17. Chạy lại `aml network` và danh tính alert? — đề xuất mặc định: mỗi lần chạy là ảnh chụp đầy đủ dưới `run_id` mới (như 5a); `alert_key` ổn định giữa các lần chạy: cụm theo `subject_id`, vòng theo dãy tài khoản + thời điểm chặng đầu, hub theo tài khoản. Lý do: cụm và hub là trạng thái "tính tới `as_of`" nên không gắn mốc thời gian vào khoá; AC7 kiểm tập `alert_key` của hai lần chạy bằng nhau. Hạn chế: `subject_id` của cụm đổi khi CIF nhỏ nhất rời cụm hoặc hai cụm nhập làm một. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q18. Đánh giá alert nhóm theo ground truth và so với 5a? — đề xuất mặc định: alert thuộc kịch bản có nhiều tài khoản của nó nhất; `evaluate_network` dùng đúng các cột của `evaluate_rules`; thêm `network_coverage` so 5a / 5c / hợp ở cả mức kịch bản lẫn mức tài khoản. Lý do: alert cụm chứa cả tài khoản phụ và người ngoài cuộc nên không dùng được "tài khoản chủ thể" như 5a; mức tài khoản mới cho thấy giá trị của 5c (`small`: member có alert 9 → 91, mức kịch bản thì mule ring đã 5/5 từ 5a). Hạn chế: alert cụm có 8 người ngoài cuộc vẫn được tính là trúng. — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q19. Ngữ nghĩa `as_of`? — đề xuất mặc định: chỉ cắt giao dịch (`txn_ts` trước 00:00 ngày `as_of + 1`), thuộc tính khách hàng luôn là hiện tại; mặc định `settings.data.reference_date`. Lý do: `customers` không có lịch sử; giống 5a. Hệ quả: chạy với `as_of` trước khi ring hoạt động vẫn ra alert cụm với 0 evidence (AC7). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q20. Phạm vi Oracle? — đề xuất mặc định: DDL 130 cho cả hai backend, ba câu `SELECT` viết inline (không có file `.sql` theo dialect vì không dùng cú pháp riêng), ghi qua `record_run` và `insert_df`, một AC [oracle] so khớp với DuckDB (AC10); chưa cấp quyền cho các role của 2b. Lý do: cùng hướng với Phase 4 (thuật toán chạy trong Python, backend chỉ là nơi đọc / ghi). Chưa kiểm trên Oracle (xem Giả định). — Trả lời: theo đề xuất mặc định (2026-10-12).
- [x] Q21. Một spec hay tách đôi? — đề xuất mặc định: một spec (10 AC). Lý do: ba phát hiện dùng chung đầu vào, đường ghi, bảng đặc trưng và fixture. Nếu muốn giảm rủi ro: tách `NET_HUB` + `nx_account_features` (AC5 và phần đặc trưng của AC6 / AC7 / AC10) thành 5c-ii, vì đây là phần ít giá trị phát hiện nhất và có ngưỡng phụ thuộc dữ liệu nhiều nhất (Q13). — Trả lời: theo đề xuất mặc định (2026-10-12).
