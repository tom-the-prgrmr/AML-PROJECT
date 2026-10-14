# Walkthrough — đi theo một alert từ generator tới investigator

Hướng dẫn dẫn người phỏng vấn qua mã nguồn trong khoảng 30 phút, bám theo **một alert có thật** trên
profile `small` (seed 42): alert `STRUCTURING` số 8 trên tài khoản `A3246322433`, thành case
`C-CIF00000166-20260422`. Tám điểm dừng, mỗi điểm: file và dòng cần chỉ, lệnh demo, output thật (chụp từ
bản sao `data/aml.duckdb` ngày 2026-10-14, `DB_BACKEND=duckdb`). Toàn repo ~33.8k dòng Python, 4.5k dòng
SQL, 5.9k dòng TypeScript; walkthrough này chạm 14 file. Ghi chú nói ở [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md).

Chuẩn bị trước buổi demo (một lần):

```powershell
uv run aml status                      # 3 service UP hay không, không sao: mọi lệnh dưới chạy DuckDB
Copy-Item data/aml.duckdb $env:TEMP/demo.duckdb ; $env:AML__DB__DUCKDB_PATH = "$env:TEMP/demo.duckdb"
```

Chạy trên bản sao để `aml ui` đang mở hay bất kỳ ai ghi gì cũng không đổi số trong lúc nói.

## Điểm dừng 1 — Generator cài scenario và ghi ground truth

**File**: [src/aml/datagen/typologies/structuring.py:26](../src/aml/datagen/typologies/structuring.py#L26)
(`build_structuring`): 4–8 lần nộp tiền mặt trong khoảng `[cap × 0.9, cap)`, trải ≥ 3 ngày trong 14 ngày,
2–3 chi nhánh, giờ hành chính. Dòng 47–56: scenario trả về `accounts=[(subject, "subject")]` và một
`reason` đọc được; `_common.py` ghi nó vào `ground_truth`. Mọi RNG là sub-stream theo bảng từ `seed`.

**Demo**:

```powershell
uv run python -c "import duckdb,os; c=duckdb.connect(os.environ['AML__DB__DUCKDB_PATH'],read_only=True); print(c.sql(\"select * from ground_truth where entity_id='A3246322433'\").fetchall())"
```

```text
('GT-STR-0015', 'structuring', True, 'account', 'A3246322433', 'subject', 2026-04-22 08:37, 2026-05-04 12:40,
 'subject in: 6 cash deposits just under the 400,000,000 VND reporting threshold within 14 days across several branches')
```

**Điểm nhấn**: ngưỡng 400 triệu và band 10% nằm trong `config.yaml` (`thresholds`), generator và rule cùng
đọc một chỗ. Nói luôn hệ quả: rule và generator cùng tác giả, nên recall 1.0 ở điểm dừng 3 là bằng chứng
pipeline đúng, không hơn.

## Điểm dừng 2 — Hai thứ mọi module dùng chung: `Database` và `audit_log`

**File**: [src/aml/common/db.py:37](../src/aml/common/db.py#L37) (`Database`: `execute`, `query_df`,
`run_script`, `insert_df`, `transaction()`), dòng 96 `sql_file` tìm `sql/<backend>/` trước rồi `sql/common/`,
dòng 258 `get_db` fallback DuckDB khi Oracle không lên. [src/aml/common/audit.py:23](../src/aml/common/audit.py#L23)
(`AuditEvent`: `module`, `entity`, `decision`, `reason` bắt buộc, `version`, `actor`, `details` JSON) và
dòng 41 `audit_many`. Oracle: [sql/oracle/ddl/020_transactions_partitioning.sql](../sql/oracle/ddl/020_transactions_partitioning.sql)
(interval partition theo tháng) và `sql/oracle/security/` (4 role, view mask, audit policy, trigger
append-only).

**Demo**: mở [results/phase2/partition_pruning.txt](../results/phase2/partition_pruning.txt) (ba plan
`PARTITION RANGE SINGLE / ITERATOR / ALL`) và bảng tuning trong [dba/RUNBOOK.md](../dba/RUNBOOK.md) mục 7
(4,449 → 752 buffer gets, 60 ms → 5 ms, không hint).

**Điểm nhấn**: feature module không import driver; SQL nằm trong file `.sql`; Oracle script kết thúc mỗi
statement bằng `/`; ghi nào không được tách rời (một dòng dữ liệu và dòng audit của nó) bọc trong
`with db.transaction():`.

## Điểm dừng 3 — Luật bắn: SQL → `alerts` + evidence + audit

**File**: [sql/oracle/monitoring/structuring.sql](../sql/oracle/monitoring/structuring.sql): CTE `q` lọc
tiền mặt vào trong band, `hits` đếm ≥ `{min_deposits}` trong `{window_days}`, `marked/grouped/episodes`
gộp thành một episode mỗi chuỗi (window function `LAG`, `SUM OVER`), dòng 33–40 trả một dòng cho mỗi
(alert, txn bằng chứng). Bản DuckDB cùng tên trong `sql/duckdb/monitoring/`. Python chỉ điền tham số và ghi:
[src/aml/monitoring/recording.py:189](../src/aml/monitoring/recording.py#L189) (`record_run`) cấp
`run_id`/`alert_id`, ghi `alerts`, `alert_accounts`, `alert_evidence`, `monitoring_runs` và dòng 216
`audit_many` một sự kiện `ALERT` mỗi alert với `version = STRUCTURING/v1`.

**Demo**:

```powershell
uv run python -c "import duckdb,os; c=duckdb.connect(os.environ['AML__DB__DUCKDB_PATH'],read_only=True); print(c.sql(\"select alert_id, rule_id, rule_version, subject_id, amount_vnd, reason from alerts where rule_id='STRUCTURING' and subject_id='A3246322433'\").fetchall()); print(c.sql(\"select module, entity_type, entity_id, decision, version, actor, details from audit_log where module='monitoring' and entity_type='alert' and entity_id='8'\").fetchall())"
```

```text
(8, 'STRUCTURING', 'v1', 'A3246322433', 2276794000, '6 cash deposits of 360,000,000 to 399,999,999 VND (just under the
 400,000,000 VND reporting threshold) totalling 2,276,794,000 VND at 2 branch(es) between 2026-04-22 08:37:00 and 2026-05-04 12:40:00')
('monitoring', 'alert', '8', 'ALERT', 'STRUCTURING/v1', 'system',
 '{"run_id": 1, "alert_key": "STRUCTURING|A3246322433|2026-04-22T08:37:00", "rule_id": "STRUCTURING", "subject_id": "A3246322433", "txn_count": 6, "amount_vnd": 2276794000}')
```

Bảng kết quả để chỉ: [results/phase5/monitor_eval.csv](../results/phase5/monitor_eval.csv) (60/60 scenario,
0 alert trên scenario lành tính) và `network_eval.csv` (5c, NetworkX, cùng đường ghi `record_run`). Phase
7b-i (`src/aml/ml/anomaly/runner.py:296`) cũng tái dùng `record_run` với `source = ANOMALY`: nguồn alert thứ
tư đi vào hệ thống bằng đúng một cửa.

## Điểm dừng 4 (rẽ ngang) — Screening: vì sao một hit bị auto-clear

**File**: [src/aml/screening/normalize.py](../src/aml/screening/normalize.py) (bỏ dấu, bỏ TNHH/CTY…, khoá
token không phụ thuộc thứ tự), [src/aml/screening/scoring.py](../src/aml/screening/scoring.py) (`token_set_ratio`
+ Jaro-Winkler, nhân coverage IDF), [src/aml/screening/decision.py:51](../src/aml/screening/decision.py#L51)
(`decide`: Tier 2 với DOB tolerance 1 năm, auto-clear khi gap > 5 năm, discount quốc tịch/giới tính, trả
`Decision` có `reason`).

**Demo**:

```powershell
uv run python -c "import duckdb,os; c=duckdb.connect(os.environ['AML__DB__DUCKDB_PATH'],read_only=True); [print(r) for r in c.sql(\"select cif, matched_name, final_score, decision, reason from screening_current where matched_name='PHAM THI THAO' order by decision\").fetchall()]"
```

```text
('CIF00000675', 'PHAM THI THAO', 100.0, 'ALERT',        'strong name match (name score 100.00, final score 100.00, DOB gap 0y)')
('CIF00000030', 'PHAM THI THAO', 100.0, 'AUTO_CLEARED', 'DOB mismatch > 5y (name score 100.00, DOB gap 8y)')
```

Cùng một tên, hai quyết định, mỗi quyết định một lý do. Bảng:
[results/phase3/screening_eval.csv](../results/phase3/screening_eval.csv) (41 hit / 25 thật so với fuzzy
4,436). Nếu hỏi Soundex: [docs/screening.md](screening.md) có số 228 → 115.

## Điểm dừng 5 — "Tiền đi đâu": recursive CTE và benchmark

**File**: [sql/oracle/trace/cte_raw.sql:5-30](../sql/oracle/trace/cte_raw.sql#L5-L30): `walk` đệ quy, hop sau
phải muộn hơn hop trước và trong `:hours` kể từ hop đầu (dòng 26–28), `CYCLE account_id SET is_cycle`
(dòng 30) chặn quay lại; `FETCH FIRST :row_limit` để không bao giờ cắt lặng lẽ (`max_paths` → `TraceError`).
Ba cách còn lại: `cte_edge.sql` (trên MV `acct_edge_daily`, top-K), `pgq.sql` (`GRAPH_TABLE ... MATCH`,
một khối mỗi số hop), `src/aml/graph/neo4j/trace.py` (một file Cypher cho mọi hop). Benchmark:
[src/aml/graph/bench/runner.py](../src/aml/graph/bench/runner.py).

**Demo**:

```powershell
uv run aml trace --account A5461833942 --hops 2 --hours 72 --method cte_raw --limit 3
```

```text
method=cte_raw backend=duckdb account=A5461833942 hops=2 hours=72 paths=632 accounts=34 cycles=362 seconds=0.055 query_lines=38
  hop=1 A5461833942>A2101536354 step_path=T0000024690 last_ts=2026-01-15 19:44:18 amount_vnd=1198000
  ...
```

Rồi bảng 3 dòng trong README (Oracle, 720 giờ: CTE 405 ms, `pgq` 7.6 s, Neo4j 1.2 s ở 6 hop, cùng 22,394
path) và câu kết luận trong [docs/trace-benchmark.md](trace-benchmark.md): SQL đủ cho trace, property graph
tốt ở pattern ngắn, graph DB riêng là projection cho investigator. Nếu hỏi Neo4j chỉ đọc bằng cách nào:
[src/aml/graph/neo4j/guard.py:83](../src/aml/graph/neo4j/guard.py#L83) (`assert_read_only`).

## Điểm dừng 6 — Case: gộp, enrichment, suppression, summary

**File**: [src/aml/cases/runner.py:220](../src/aml/cases/runner.py#L220) (`run_cases`): item từ ba (nay
bốn) nguồn → một case mỗi golden customer, cửa sổ 90 ngày neo ở alert đầu, trạng thái OPEN/REOPENED/CLOSED;
dòng 31 `SECTIONS` là sáu khối enrichment do `enrich.py` dựng. Suppression áp từng item trước khi gộp:
[src/aml/cases/suppression_rules.py:82](../src/aml/cases/suppression_rules.py#L82) (`good_guy_verdict`: chỉ
disposition của người tạo entry, có expiry, re-trigger khi dữ liệu khách hoặc entry đổi) và dòng 125
(`hibernation_verdict`: ngủ N ngày, thức khi số tiền vượt `material_change_ratio`). Summary không LLM:
`src/aml/cases/summary_template.py` qua interface `NarrativeGenerator` (`cases/narrative.py`).

**Demo**:

```powershell
uv run aml cases show C-CIF00000166-20260422
uv run aml cases summary C-CIF00000166-20260422
```

```text
C-CIF00000166-20260422 CLOSED G-CIF00000166 alerts=2
disposition=SUSPICIOUS actor=simulated_analyst decided_on=2026-06-30
  2026-04-22 08:37:00 RULE DORMANT_REACTIVATION cif=CIF00000166 amount_vnd=377730000 ...
  2026-04-22 08:37:00 RULE STRUCTURING cif=CIF00000166 amount_vnd=2276794000 ...
kyc {"risk_rating": "LOW", "cifs": [{"cif": "CIF00000166", "occupation": "Nhân viên ngân hàng", "birth_year": 1984, ...}]}
linked_cifs {"cluster_size": 1, ...}   dq_issues {"customer": [], "transactions": {}}
txn_summary {"txn_count": 6, "in_vnd": 2276794000, "cash_in_vnd": 2276794000, "counterparties": 0, "max_txn_vnd": 395540000, ...}
network {"source": "gds", "features": {"in_degree": 0, "pagerank_ratio": 0.0, "shared_cluster_size": 0, ...}}
history {"prior_cases": [], "prior_alerts": 0, "screening_auto_cleared": 0, "suppressed_items": 0}
```

Summary mở đầu bằng `TEMPLATE SUMMARY (summary/v1): generated ... without an LLM. It is not a disposition.`
và che tên/giấy tờ (`Vũ V. Q.`, `CCCD ********6512`). Chỉ ra: hai alert cùng tài khoản là một case, `DORMANT_
REACTIVATION` ở đây là alert "đi kèm" (137 lần trên toàn dữ liệu) và consolidation là thứ hấp thụ nó.

## Điểm dừng 7 — Xếp hạng và quản trị model

**File**: [src/aml/cases/prioritize.py:129](../src/aml/cases/prioritize.py#L129) (`train`: nhãn = disposition
mới nhất của case đã quyết, `StratifiedGroupKFold` theo nhóm khách, lưu model + metrics vào `case_models`) và
dòng 190 (`score`: ghi `case_scores` với `model_version`, `top_features`, `queue_rank`; hàng đợi chỉ gồm case
chưa đóng). [src/aml/cases/model.py:168](../src/aml/cases/model.py#L168) (`fit_model`, `class_weight`, cross-validation
theo nhóm; `memo/features.py:212` `fit_guarded` loại feature rủi ro có hệ số âm rồi fit lại).
[src/aml/cases/scoring.py:60](../src/aml/cases/scoring.py#L60) (`case_event`: dòng audit `PRIORITIZED`).
Quản trị: [src/aml/governance/guard.py](../src/aml/governance/guard.py) (quét tĩnh bằng `ast`: module ML không
gọi hàm ghi disposition, không ghi SQL vào bảng quyết định), `governance/cards.py` sinh
[docs/models/prioritization.md](models/prioritization.md) từ bảng, `governance/audit_check.py` kiểm version trên
11 loại quyết định. Selection bias: `src/aml/cases/btl.py` (`seeded_positions`, `wilson_interval`).

**Demo**:

```powershell
uv run python -c "import duckdb,os; c=duckdb.connect(os.environ['AML__DB__DUCKDB_PATH'],read_only=True); print(c.sql(\"select case_id, score, queue_rank, model_version, top_features from case_scores_current where case_id='C-CIF00000166-20260422'\").fetchall()); print(c.sql(\"select decision, version, actor, reason from audit_log where entity_id='C-CIF00000166-20260422' and decision='PRIORITIZED' order by event_ts desc limit 1\").fetchall())"
```

```text
('C-CIF00000166-20260422', 0.999107, None, 'prio/logreg/3', '[{"feature": "pagerank_ratio", "value": 0.0, "contribution": 1.7204}, {"feature": "pass_through", "value": 0.0, "contribution": -1.0348}, {"feature": "rule_alerts", "value": 2.0, "contribution": 0.5587}, ...]')
('PRIORITIZED', 'prio/logreg/3', 'cli', 'priority score 0.9991 from prio/logreg/3, not in the queue (CLOSED); top factors: pagerank_ratio +1.72, pass_through -1.03, rule_alerts +0.56, memo_tx...')
```

`queue_rank` là `None` vì case đã CLOSED bởi disposition: model chấm nhưng không xếp vào hàng đợi, và
không bao giờ là bên đóng. Số để chỉ: README mục Phase 7 (CV 0.96, held-out 0.99, 8/10 false positive ở
10% đáy) và 7b (below-the-line 4/200, CI 0.8–5.0%; anomaly bắt thêm **0** scenario và nói thẳng điều đó).

## Điểm dừng 8 — Assistant kiểm chứng từng câu, UI ghi mọi quyết định

**File**: [src/aml/assistant/answering.py:391](../src/aml/assistant/answering.py#L391) (`answer_question`:
router → retrievers → `chat_json` theo schema → kiểm → audit một dòng mỗi lượt), [src/aml/assistant/validation.py:199](../src/aml/assistant/validation.py#L199)
(`check_claim`: có citation, số tiền và ngày phải có trong evidence tin cậy, chiều chuyển tiền đúng, không
kết luận; dòng 193 `_direction_mismatch`), [src/aml/assistant/evidence.py:45](../src/aml/assistant/evidence.py#L45)
(`UNTRUSTED_NOTICE`, memo bọc `<untrusted>` có escape), [src/aml/assistant/cypher_guard.py:226](../src/aml/assistant/cypher_guard.py#L226)
(`validate_cypher`: cấm clause, allow-list schema, path ≤ 3, ép `LIMIT`). UI:
[src/aml/api/decisions.py:33](../src/aml/api/decisions.py#L33) (`record_case_decision` gọi thẳng
`record_disposition` với `actor = user`; dòng 16 `pii_viewed`), router mỏng trong `src/aml/api/routers/`.

**Demo** (không cần LLM):

```powershell
uv run aml rag explain C-CIF00000166-20260422
```

```text
case=C-CIF00000166-20260422 typologies=1 knowledge=unavailable
typology=structuring rules=STRUCTURING transactions=6 chunks=0
  definition: STRUCTURING v1: Repeated cash deposits just under the large-cash reporting threshold (band_low_vnd=360000000, large_cash_vnd=400000000, min_deposits=3, window_days=14)
  T0000184006 2026-04-22 08:37:00 - -> A3246322433 377730000 CASH
  ...
```

(`knowledge=unavailable` khi Neo4j chưa sync; sau `aml graph sync --full ; aml rag build --full` sẽ có
chunk SOP/typology kèm theo.) Có Ollama thì `uv run aml rag ask "Case này khớp typology nào và vì sao?"
--case C-CIF00000166-20260422` và chỉ phần `Nguồn:` cùng nhãn `[CHƯA KIỂM CHỨNG]` nếu có. Bảng eval trong
README (18/26, 98.3%, 1/25, 29/30, 4/4; vector RAG 0/26). Nếu còn thời gian: `uv run aml ui` trên bản
sao, mở case, bấm disposition, rồi cho xem dòng `audit_log` mới với `actor=analyst01`.

## Những gì nên bỏ qua khi nói

- `src/aml/cli.py` (1,400 dòng Typer): chỉ là cửa vào, không có logic.
- `src/aml/datagen/customers.py`, `watchlist.py`: nhiều dòng nhưng chỉ là sinh dữ liệu; nói một câu về seed
  và sub-stream rồi đi tiếp.
- `src/aml/assistant/eval/` và `knowledge/build.py`: cho xem bảng kết quả, không cho xem code trừ khi hỏi.
- `web/`: mở UI thì mở; không đọc TSX.
- `tests/`: nêu con số (1,917 hàm test, marker `oracle/neo4j/ollama` skip có lý do) và cách xây spec-first;
  mở một test chỉ khi hỏi về acceptance criteria.
- `specs/`: tiếng Việt, 38 file; dùng khi cần chứng minh "yêu cầu → test → code", không đọc trong buổi.

## Những chỗ dễ bị hỏi vặn, và câu trả lời

| Hỏi vặn | Trả lời |
|---|---|
| "Recall 1.0 ở mọi luật thì có gì để tin?" | Đồng ý: generator và rule cùng tác giả. Nó chứng minh wiring, không chứng minh model. README liệt kê điều đó đầu tiên trong Known limitations. |
| "Prevalence 86% suspicious là phi thực tế" | Đúng, ngược production. Vì vậy metric được đọc là "false positive bị đẩy xuống đáy bao xa", không phải precision ở đỉnh. |
| "Model có tự đóng case không?" | Không có đường code nào: `queue_rank` chỉ là thứ tự, disposition qua `record_disposition` với actor người, test tĩnh trong `governance/guard.py` chặn module ML gọi nó. |
| "Anomaly detection bắt thêm 0 thì làm làm gì?" | Số 0 là số thật trên dữ liệu này; mình chọn báo đúng thay vì chỉnh để có số đẹp. Giá trị của nó là typology chưa biết, thứ dữ liệu tổng hợp không có. |
| "Neo4j chậm hơn SQL thì sao còn dùng?" | Vì thứ nó thêm nằm ngoài benchmark: pattern biến thiên, GDS, khám phá tương tác. Kiến trúc giữ nó là projection chỉ đọc, không phải nguồn sự thật. |
| "LLM 3B thì tin được gì?" | Không tin model, tin kiểm chứng: schema citation, kiểm từng câu về số/ngày/chiều/kết luận, cờ hoặc từ chối. 1/25 hallucination và đó là cite sai chiều, chính lớp kiểm bắt được. |
| "Dữ liệu có ra ngoài không?" | Ollama local, không API ngoài; PII mask theo role; memo không vào audit; `.env` ngoài git. |
| "Sync lag Neo4j xử lý thế nào?" | Watermark + overlap + `MERGE`, `in_sync` sau mỗi lần; câu cần chính xác hỏi Oracle; production dùng CDC. |
| "Sao không Next.js?" | Logic ở Python; tool nội bộ không cần SSR; Vite build là file tĩnh nên `aml ui` một process. |
| "Thiếu gì?" | Bước phê duyệt model (model mới nhất tự active), auth thật cho UI, profile `large` chưa có số, Oracle Free không HA. Nói trước khi bị hỏi. |
