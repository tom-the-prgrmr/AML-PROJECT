# Ghi chú phỏng vấn — AML Investigation Toolkit

Tài liệu nói, không phải tài liệu đọc: mỗi ý một câu ngắn, số liệu lấy từ các lần chạy thật ghi trong
[README.md](../README.md) và `results/`. Mọi số ở đây đều có lệnh sinh ra nó; nếu người phỏng vấn hỏi "đo ở
đâu", chỉ vào file kết quả tương ứng. Đường đi mã nguồn để demo nằm ở [WALKTHROUGH.md](WALKTHROUGH.md).

Một câu mở đầu: *"Dự án là một bộ công cụ giảm công sức điều tra AML, chạy hoàn toàn trên dữ liệu tổng hợp,
Oracle là system of record, Neo4j chỉ là projection chỉ đọc, LLM chạy local. Mọi quyết định tự động đều có
`reason` và vào `audit_log`; không model nào tự đóng case."*

## 1. Từng công cụ: bài toán, số đo, trade-off

| Công cụ | Bài toán nó giải | Số đo (profile `small`, seed 42) | Trade-off cần nói ra |
|---|---|---|---|
| **Name screening** (Phase 3) | Tên Việt gồm 2–4 âm tiết ngắn, khác nhau ở nguyên âm và dấu; fuzzy thuần hoặc phonetic ngập alert | Two-tier `ALERT`: 41 hit, precision 0.61, recall 1.0, giảm 99.6% false flag so với fuzzy (4,436 hit, precision 0.006). Soundex gộp 228 token thành 115 mã | Recall 1.0 vì watchlist tổng hợp. IDF đóng băng giữa hai lần full run; token mới bị coi là hiếm nhất |
| **Entity resolution** (Phase 4) | Một người 2–3 CIF, mỗi CIF một kiểu viết tên, CMND/CCCD, định dạng SĐT, địa chỉ cũ/mới | Splink: 546/546 cặp, 364/364 cụm, precision = recall = 1.0 | Điểm tuyệt đối vì generator không đổi số điện thoại hay DOB giữa các CIF. Test tay thêm 4 ca để thấy 1 `REVIEW`, 1 merge sai, 1 bỏ sót |
| **Transaction monitoring** (Phase 5a) | Luật là hộp đen của vendor, alert không có bằng chứng | 5 luật SQL (Oracle + DuckDB), mỗi alert có evidence txn ids và `reason`; bắt 60/60 scenario cài sẵn, 0 alert trên scenario lành tính | Luật và generator cùng một tác giả. `DORMANT_REACTIVATION` 137 alert là luật ồn nhất; consolidation là thứ giữ nó không thành 137 case |
| **Network detections** (Phase 5c) | Mule ring, round-tripping, hub không thấy được theo từng tài khoản | NetworkX: shared-attribute 5/5, cycle 15/15, hub 5/5 | Chạy trong process, đủ cho 300k giao dịch; ở quy mô lớn mới cần GDS |
| **Fund-flow trace** (Phase 5b, 6) | "Tiền đi đâu?" trả lời bằng tay | 4 cách cùng một câu hỏi, benchmark ở 2/4/6 hop: CTE nhanh nhất (405 ms cho 22,394 path 6 hop) | Xem mục 2 |
| **Case consolidation + enrichment** (Phase 7a) | 10 alert một khách = 10 case ở 10 màn hình | 339 alert → 475 item → 335 case theo golden customer, cửa sổ 90 ngày, 6 khối enrichment | Group alert vào case của mọi khách trong nhóm; cửa sổ neo ở alert đầu, có thể reopen |
| **Suppression** (Phase 7b-supp) | False positive lặp lại hàng tháng | Good-guy list chặn 36 item screening; hibernation 0 (dữ liệu không có FP lặp) | Chỉ disposition của người mới vào good-guy list; có expiry và re-trigger khi dữ liệu đổi |
| **Prioritization** (Phase 7c) | Hàng đợi làm theo thứ tự đến | `prio/logreg/1`: CV ROC-AUC 0.96, held-out 0.99; 8/10 false positive nằm ở 10% đáy hàng đợi | Prevalence 86% suspicious, ngược với production; model chỉ xếp hạng, có version và top factors trên từng score |
| **Anomaly detection** (Phase 7b-i) | Typology luật chưa biết | Isolation Forest, top 0.5% customer-month = 138 alert; **0 scenario mới** vì luật đã phủ 60/60; 6 account `rapid_movement` luật chưa chạm; cờ nhầm 3/5 `benign_merchant` | Báo đúng số 0, kèm số ở mức account và false positive mới |
| **Learned screening model** (7b-ii) | Ngưỡng cố định không học từ reviewer | Ở recall 1.0: 17 hit (precision 0.88) thay vì 23 (`ALERT`) hay 42 (`ALERT`+`REVIEW`); held-out 13 so với 18 và 30 | Chỉ 25 cặp thật trong dữ liệu, kết quả dao động theo seed; Tier 2 decision không đổi |
| **Below-the-line** (7b-iii) | Metric chỉ đo trên case đã alert (selection bias) | Mẫu 200/4,199 khách không alert: 4 đáng ngờ → ước lượng 84 khách bỏ sót, CI 95% 0.8–5.0% | Là phép đo, không phải hành động: không ai bị alert vì nằm trong mẫu |
| **Memo analysis** (8d) | Memo tự do mang tín hiệu (cờ bạc, crypto) | LLM local + luật: 39/46 gold đúng (84.8%); feature memo **không** cải thiện ranking (0.9599 → 0.9579) | Memo cờ bạc/crypto là do generator cài, kể cả có lift cũng không phải bằng chứng |
| **GraphRAG assistant** (Phase 8) | Viết narrative từ 5 màn hình; chatbot bịa | 30 câu hỏi: GraphRAG đúng 18/26, citation precision 98.3%, hallucination 1/25, từ chối đúng 29/30, 4/4 injection không bị theo; vector RAG thuần 0/26 | Model 3B trên GPU 4 GB; câu trả lời thiếu một phần tính là sai |
| **Investigator UI** (Phase 9) | Quyết định không có dấu vết | FastAPI + React, mask PII phía server theo role, mỗi endpoint ghi quyết định đều vào `audit_log` với user | Không có auth thật, bind 127.0.0.1; actor từ header |

Câu chốt cho mục này: *"Mỗi số trên đều từ dữ liệu mà chính mình cài typology vào, nên nó chứng minh
pipeline đúng, không chứng minh model tốt trên dữ liệu thật. README có mục Known limitations nói rõ điều đó."*

## 2. SQL vs graph: khung quyết định, có số

Câu hỏi benchmark: từ tài khoản X, lần theo tiền ra N hop trong T giờ, hop sau phải muộn hơn hop trước,
không quay lại tài khoản đã đi qua. Bốn cách, cùng dữ liệu, cùng số path, `uv run aml bench`
(Oracle, `small`, cửa sổ 720 giờ, median của 10 lần, `results/phase6/bench_report.md`):

| hop | path | recursive CTE (Oracle) | SQL property graph `GRAPH_TABLE` (Oracle 23ai) | Neo4j Cypher |
|---|---|---|---|---|
| 2 | 4,289 | 43.6 ms | 48.6 ms | 226.0 ms |
| 4 | 10,955 | 160.7 ms | 262.8 ms | 577.6 ms |
| 6 | 22,394 | 405.3 ms | 7,588.8 ms | 1,184.1 ms |

Khung quyết định rút ra:

- **SQL là đủ** khi câu hỏi là một traversal có biên (N hop, T giờ) từ một điểm xuất phát: recursive CTE
  với `CYCLE ... SET` là cách nhanh nhất ở 10/12 ô, 30 dòng, nằm trong system of record, dưới role và audit
  policy sẵn có, không có sync lag. Thêm `acct_edge_daily` (MV theo ngày) cho bản triage 4–5 ms.
- **Property graph trong DB giúp** với pattern ngắn, độ dài cố định: ở 2 hop `pgq` cách CTE dưới 1 ms
  (`dense`) và là query ngắn nhất (19 dòng), không cần hệ thống thứ hai. Với path sâu hoặc biến thiên nó
  chậm nhất (query là một khối `GRAPH_TABLE` cho mỗi số hop nối `UNION ALL`, 99 dòng ở 6 hop, chưa tune).
- **Graph DB riêng được biện minh** không phải vì tốc độ trace (chậm hơn CTE 2.3–5.2 lần ở mọi ô) mà vì
  thứ nằm ngoài benchmark: một file Cypher cho mọi số hop, pattern độ dài biến thiên (cycle, cụm chung thuộc
  tính), thuật toán đồ thị (WCC, Louvain, PageRank), và khám phá tương tác cho investigator. Chi phí: full
  sync 42–51 s, incremental 2 s, một service nữa phải vá, giám sát, backup; Community không có RBAC, không
  cluster, không online backup.
- **Kết luận kiến trúc**: Oracle giữ rules, trace, báo cáo; Neo4j là projection chỉ đọc, đồng bộ qua user
  Oracle chỉ đọc, `MERGE` idempotent, có watermark và kiểm tra `in_sync` sau mỗi lần chạy. Mọi thứ cần
  chính xác tuyệt đối trả lời từ Oracle.
- Giới hạn của bằng chứng: một máy, container local, 306k giao dịch, một tài khoản nặng nhất mỗi profile,
  cache ấm, `pgq` chưa tune. Benchmark là một lệnh để chạy lại khi dữ liệu đổi.

## 3. Data governance

- **Data quality framework**: bảng `dq_rules` (10 luật: completeness, validity, uniqueness, consistency,
  timeliness) mỗi luật một file `SELECT`, kết quả vào `dq_results` với `sample_ids`, view trend; `aml dq run`
  in kèm độ khớp với nhãn lỗi mà generator cài (`dq_labels`). DQ issue của khách hàng là một khối enrichment
  của case và một feature của ranking.
- **Lineage**: mọi bảng kết quả có `run_id` trỏ về bảng `*_runs` với `as_of`, config hash, version; alert
  giữ evidence txn ids; score giữ `model_version` và `feature_version`; `ground_truth` đi theo Parquet
  manifest. ERD ở `docs/erd/`.
- **Ownership / least privilege**: bốn role Oracle `aml_app`, `aml_analyst`, `aml_graph_sync`,
  `aml_auditor`; user sync đồ thị chỉ có SELECT; `apply_security` chỉ thêm grant, không bao giờ revoke
  (việc thu quyền là thao tác có chủ đích của DBA).
- **Masking**: view `customers_masked` (tên, giấy tờ, SĐT che một phần) cho role analyst, kiểm tra bằng
  reference Python trên cả hai backend; UI mask phía server theo role, xem bản đầy đủ ghi một dòng
  `PII_VIEWED`.
- **Audit**: `audit_log` append-only (trigger từ chối UPDATE/DELETE/TRUNCATE; unified audit policy trên
  bảng PII và chính `audit_log`), partition theo tháng, mỗi dòng có `module`, `entity`, `decision`, `reason`,
  `version`, `actor`, `details` JSON. Trên `small` sau mọi phase: ~18k dòng. Assistant ghi câu hỏi, retriever,
  Cypher sinh ra, id đã lấy, kết quả kiểm chứng, feedback vào `details`.
- **Retention**: `aml retention` archive partition cũ ra Parquet, kiểm tra số dòng, rồi mới drop với
  `UPDATE GLOBAL INDEXES`; sàn pháp lý 60 tháng là hằng số trong code, config không thể đặt thấp hơn;
  partition neo không bao giờ bị drop; `audit_log` nằm ngoài purge.
- **Đối chiếu pháp lý**: `docs/legal/rule-mapping.md` ánh xạ từng luật với Luật PCRT (Đ27, Đ28), ghi mức
  khớp Mạnh/Trung bình/Yếu và liệt kê dấu hiệu luật có mà app chưa làm được (thu nhập không phù hợp, nhiều
  thiết bị/IP nước ngoài, giao dịch xuyên biên giới).

## 4. Quy mô production

- **Partitioning**: `transactions` interval partition theo tháng, local index; `explain-pruning` cho thấy
  `PARTITION RANGE SINGLE / ITERATOR / ALL`. Tuning demo: `TRUNC(txn_ts)` trên partition key quét mọi
  partition (4,449 buffer gets), half-open range prune còn một (752), 60 ms → 5 ms, không hint, không index
  mới. Số để so giữa các máy là buffer gets.
- **Incremental screening**: chi phí full ≈ khách hàng × tên trong danh sách; thay đổi hằng ngày chỉ vài
  khách và vài entry. Fingerprint SHA-256 các trường ảnh hưởng quyết định (đổi SĐT không đếm), IDF đóng băng
  trong `screening_token_stats` nên delta run = full run cùng IDF; từ chối chạy khi config hash đổi. Production
  thay fingerprint bằng `updated_at` hoặc CDC; entry mới lên danh sách phải alert ngay, không đợi full run.
- **CDC-based graph sync**: hiện sync theo watermark `txn_ts` với overlap 60 phút và `MERGE`; sản xuất thay
  bằng GoldenGate/LogMiner hoặc Debezium đẩy sự kiện, cùng cơ chế idempotent; lag đo bằng data time, sau mỗi
  lần chạy so đếm với nguồn. Full rebuild chỉ khi đổi backend nguồn, reload, hoặc OUT OF SYNC.
- **HA/DR**: Oracle Free trong demo là NOARCHIVELOG, một container, không standby; runbook có script tham
  chiếu RMAN level 0/1, PITR, Data Pump, bật ARCHIVELOG. Production: Data Guard cho Oracle; Neo4j Community
  không cluster, không online backup, nên projection phải rebuild được từ Oracle trong vài phút (42 s trên
  `small`), đó là chiến lược DR của nó.
- **Access control**: role tối thiểu ở Oracle; Neo4j Community không có RBAC nên chỉ đọc đến từ session
  READ access mode + guard ứng dụng từ chối mọi write clause và mọi `CALL` ngoài allow-list; Enterprise sẽ
  thêm reader role. Text2Cypher thêm schema allow-list, `LIMIT` ép buộc, timeout server-side, độ dài path tối
  đa, và log mọi query sinh ra.
- **Model governance và validation**: model lưu trong DB với version, seed, data hash, feature version,
  metrics; version nằm trên mọi score và mọi dòng audit (`aml models audit-check` quét 11 loại quyết định,
  báo lỗ hổng, không sửa dòng cũ); model card sinh từ metadata đã lưu, không gõ tay; test tĩnh chặn mọi
  module ML ghi disposition. Thiếu và nói rõ: chưa có bước phê duyệt model, model mới nhất tự thành active.
- **Below-the-line testing**: mẫu ngẫu nhiên có seed của khách không alert, nhãn từ ground truth, báo
  Wilson interval (4/200 → 0.8–5.0%); biến thể `+btl` huấn luyện thêm mẫu đó và báo metric tách theo quần
  thể vì gộp chung bị thổi phồng (mọi khách mẫu có 0 alert). Dashboard có thêm mẫu auto-cleared và suppressed
  kèm ground truth để chứng minh không chặn nhầm thứ quan trọng.

## 5. GenAI governance

- **On-prem LLM, data residency**: `qwen2.5:3b-instruct` + `bge-m3` qua Ollama trong container local, không
  API ngoài; provider `fake` deterministic cho test; cache phản hồi trên đĩa (temperature 0, seed) nên eval
  lặp lại được và không tốn GPU. Đổi model = đổi một dòng config, nhưng `details.model` phải đi vào audit.
- **Hallucination controls** (ba lớp, đều bằng code, không nhờ model tự chấm):
  1. Model chỉ được trả lời theo JSON schema mà citation giới hạn trong các evidence item của lượt đó.
  2. Mỗi câu được kiểm: có cite ít nhất một item; mọi số tiền và ngày tháng phải xuất hiện trong evidence tin
     cậy; chiều chuyển tiền phải đúng; không chứa kết luận ("khách sạch", "đóng case"); câu nước đôi bị cờ.
  3. Câu không đạt hiện `[CHƯA KIỂM CHỨNG]`; không câu nào đạt thì trả lời "Không đủ bằng chứng."
  Kết quả đo: hallucination 1/25 và đó là câu đúng nhưng cite sai chiều, chính lớp kiểm chiều bắt được nó.
- **Prompt injection**: memo, tên, reason, chunk là dữ liệu không tin cậy, được bọc trong thẻ
  `<untrusted>` có escape, kèm thông báo cho model rằng đó là dữ liệu chép từ khách hàng; memo không bao giờ
  vào `audit_log`. Eval: 4/4 memo injection tới được context và không câu trả lời nào làm theo.
- **Text2Cypher risk**: query sinh ra đi qua guard (chỉ `MATCH`/`OPTIONAL MATCH`, cấm `CALL/UNION/UNWIND/
  SHOW/…`, label/property/function theo schema allow-list, path ≤ 3, `LIMIT` ép, timeout, tối đa 2 lần
  sinh), chạy trong session READ, và được log nguyên văn. Rủi ro còn lại: query đúng cú pháp nhưng sai nghĩa;
  vì vậy câu trả lời vẫn phải qua kiểm chứng câu, và router chỉ gọi Text2Cypher khi retriever cố định không
  đủ.
- **Vì sao con người sở hữu mọi disposition**: trách nhiệm pháp lý và báo cáo STR là của ngân hàng và cán
  bộ, không của model; model có selection bias và nhãn mô phỏng; assistant chỉ đọc và nháp (narrative có
  watermark `DRAFT — requires investigator review`); UI không có endpoint nào để model đóng case; test tĩnh
  đảm bảo module ML không gọi `record_disposition`.

## 6. 15 câu hỏi có thể gặp và câu trả lời ngắn

1. **Vì sao không dùng Soundex/Metaphone cho tên Việt?** Tên Việt khác nhau ở nguyên âm và dấu, đúng phần
   phonetic code vứt đi; phụ âm ghép NG/NH/TR mã hoá theo tiếng Anh. Đo trên `small`: 228 token thành 115
   mã, `HOANG/HONG/HUNG/HUONG` chung một mã. Thay bằng normalise + `token_set_ratio` + Jaro-Winkler + IDF.
2. **IDF weighting làm gì?** Token hiếm trong tập khách hàng mới mang thông tin; khớp chỉ "NGUYEN VAN" có
   coverage thấp nên điểm thấp. Entry bẫy (trap) trong watchlist chỉ chứa token phổ biến để kiểm tra điều đó.
3. **Precision 0.61 có chấp nhận được không?** Ở ngưỡng `ALERT` 41 hit cho 25 cặp thật; fuzzy cùng ngưỡng
   là 4,436 hit. Tier 2 (DOB, quốc tịch, giới tính) auto-clear với lý do ghi lại. Model 7b-ii giảm tiếp còn 17
   hit ở cùng recall nhưng chỉ 25 cặp thật nên nói kèm seed.
4. **Vì sao Splink mà không viết luật tay?** Luật tay là blocking; Splink cho xác suất khớp có giải thích
   (match weight theo từng so sánh) và ngưỡng `MATCH/REVIEW` cấu hình được. m cố định từ config, u ước lượng
   từ cặp ngẫu nhiên; kết quả 1.0 là do generator, test tay chỉ ra 1 merge sai và 1 bỏ sót.
5. **Rules viết SQL có khó bảo trì không?** Mỗi luật một file mỗi backend, tham số từ config, test trên
   fixture nhỏ; alert có evidence và reason nên investigator và auditor đọc được. Đổi ngưỡng = đổi
   `config.yaml`, có `rule_version` trên alert.
6. **Khi nào cần graph database?** Xem mục 2: không phải vì tốc độ trace (CTE nhanh hơn ở mọi ô), mà vì
   pattern biến thiên, thuật toán đồ thị và khám phá tương tác. Ở quy mô này NetworkX cho cùng feature; Neo4j
   là lựa chọn cho investigator, không phải cho capacity.
7. **Oracle 23ai property graph có thay được Neo4j không?** Với pattern ngắn cố định, có: ở 2 hop cách CTE
   dưới 1 ms, query ngắn nhất, không service mới. Với path sâu hoặc biến thiên thì chưa (7.6 s ở 6 hop, chưa
   tune). Cần đo lại khi tune.
8. **Làm sao bảo đảm Neo4j chỉ đọc khi Community không có RBAC?** Session READ access mode (server từ
   chối write) cộng guard ứng dụng chặn write clause và `CALL` ngoài allow-list, GDS chạy stream không write
   back vào Neo4j mà ghi về Oracle. Enterprise thêm reader role.
9. **Sync lag xử lý thế nào?** Watermark theo `txn_ts`, overlap 60 phút, `MERGE` idempotent, sau mỗi lần
   so đếm với nguồn (`in_sync`); lag đo bằng data time. Câu hỏi cần chính xác trả lời từ Oracle; production
   dùng CDC.
10. **Model ưu tiên có tự đóng case không?** Không. Nó chỉ xếp hạng, ghi score + version + top factors vào
    audit; đóng case cần disposition của người, và chỉ disposition mới vào good-guy list. Test tĩnh chặn
    module ML gọi `record_disposition`.
11. **Selection bias xử lý ra sao?** Nhãn chỉ có trên case đã alert. Mẫu below-the-line 200/4,199 khách
    không alert, gán nhãn ground truth, đo model trên đó (ROC-AUC 0.96, PR-AUC 0.24 ở prevalence 2%), báo CI;
    biến thể `+btl` báo metric tách theo quần thể. Trên dữ liệu thật mẫu này là việc của reviewer.
12. **Anomaly detection bắt được gì luật bỏ sót?** Trên dữ liệu này: 0 scenario, vì luật đã phủ 60/60. Báo
    đúng số 0 kèm 6 account luật chưa chạm và 3/5 `benign_merchant` bị cờ nhầm. Giá trị thật của nó nằm ở
    typology chưa biết, thứ dữ liệu tổng hợp không có.
13. **LLM bịa thì sao?** Ba lớp kiểm bằng code (mục 5): schema citation, kiểm từng câu về số tiền/ngày/
    chiều tiền/kết luận, cờ `[CHƯA KIỂM CHỨNG]` hoặc từ chối. Đo: 1/25 hallucination và là cite sai chiều,
    không bịa id nào. Vector RAG thuần 0/26 vì không thấy giao dịch.
14. **Dữ liệu khách hàng có ra ngoài không?** Không: Ollama local, không API ngoài, cache trên đĩa trong
    `data/`; PII mask theo role, xem bản đầy đủ ghi `PII_VIEWED`; memo không vào audit.
15. **Điểm yếu lớn nhất của dự án?** Dữ liệu tổng hợp do chính mình cài typology: recall 1.0 chứng minh
    pipeline đúng, không chứng minh model tốt; prevalence ngược production; nhãn không nhiễu; 25 cặp screening
    thật; chưa có bước phê duyệt model; chưa chạy profile `large`. Tất cả nằm trong README mục Known
    limitations, và đó là điều mình muốn người phỏng vấn thấy trước khi họ hỏi.

## 7. Nếu chỉ còn 5 phút

1. Mở `aml status`, nói kiến trúc trong một câu.
2. `aml cases show C-CIF00000166-20260422`: alert có reason, case có 6 khối enrichment, score có top factors.
3. Chỉ dòng `audit_log` của alert đó (`STRUCTURING/v1`, actor `system`, `details` có evidence).
4. Bảng benchmark 3 dòng và câu kết luận "SQL là đủ cho trace, graph là projection".
5. Một câu trả lời của assistant có `[CHƯA KIỂM CHỨNG]` hoặc bảng eval 18/26, 1/25, 4/4.
6. Mục Known limitations: "đây là những gì số liệu không chứng minh được".
