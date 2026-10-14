---
id: assistant-direction-check
status: approved
approved_by: pthieu
---

# Phase 8c (sửa) — Hậu kiểm chiều tiền và câu suy đoán trong câu trả lời của assistant

## Bối cảnh
Sửa hậu kiểm tất định của 8c (`specs/assistant-answering.md`, đã duyệt). Hiện `check_claims` chỉ kiểm trích dẫn, số tiền,
ngày và từ ngữ phán quyết, nên một câu **nói ngược chiều tiền** vẫn được `supported = true` miễn là nó chép đúng số tiền
và ngày của giao dịch nó trích. Người dùng đo được hai trường hợp như vậy (2026-10-14, `data/aml.duckdb`, profile `small`,
seed 42, case `C-CIF00000955-20260427`, `qwen2.5:3b-instruct`):

1. Câu "Tài khoản A3154676584 cũng nhận tiền từ tài khoản A9418747931 với số tiền 153,936,000 VND vào ngày 2026-04-30
   04:00:16 thông qua chuyển khoản nội bộ." có `supported = true` và trích T0000196919. Nhưng T0000196919 là
   A3154676584 → A9418747931, tức tiền **đi ra**.
2. Câu hỏi "Ai là chủ sở hữu hưởng lợi cuối cùng của số tiền này?" trả `answered` với một câu suy đoán: "Chủ sở hữu hưởng
   lợi cuối cùng của số tiền này có thể là A5538166070, vì họ nhận được 161,398,000 VND từ A3154676584 …". Câu này có
   `supported = true`, nhưng T0000193641 là A5538166070 → A3154676584 (cũng ngược chiều), và bằng chứng không có thông
   tin nào về chủ sở hữu hưởng lợi.

Spec này thêm hai phép kiểm **tất định, không gọi LLM** vào `check_claims`: chiều tiền và câu suy đoán. Q&A
(`answer_question`) và narrative nháp (`draft_narrative`) đều nhận được hai phép kiểm này vì cả hai cùng gọi
`check_claims`. Hợp đồng JSON `Answer` không đổi. Mọi thay đổi nằm trong module của 8c.

### Hiện trạng đã kiểm (2026-10-14, `main` aff6d91)
Đã đọc code. Đã chạy một prototype **ngoài repo** (scratchpad), mở `data/aml.duckdb` ở chế độ `read_only` và tạo một
DuckDB tạm cho MINI-N. Không ghi gì vào repo, `data/`, Oracle hay Neo4j, và không chạy bộ test.
- **Nơi hậu kiểm**: `src/aml/assistant/validation.py`, `check_claim(claim, evidence) -> Checked(text, supported, issues,
  refs)`. Các mã lỗi nằm trong `ISSUES = ("no_citation", "unknown_citation", "amount_not_in_evidence",
  "date_not_in_evidence", "verdict_language")`. `issues` sắp theo thứ tự của `ISSUES`, và `supported == (issues == ())`.
  Docstring của module ghi rõ *"They do not check meaning: the direction of a transfer … is the model's job and the
  evaluation (8e) measures it"*. Mục Thiết kế của spec 8c cũng ghi "Hậu kiểm **không** kiểm ngữ nghĩa (chiều tiền, …)".
  Spec này **đảo quyết định đó cho chiều tiền** (S1, S2).
- **Từ vựng**: `src/aml/assistant/facts.py` có `fold()` (bỏ dấu, `đ` → `d`, chữ thường) và `is_verdict` (danh sách mẫu
  chạy trên văn bản đã `fold`). Hai hàm mới ở spec này đi theo cùng cách.
- **Bằng chứng giao dịch** do `txn_lookup.transaction_fact` dựng, dùng cho cả `case_graph` (nhãn `Transfer`, nguồn
  `neo4j`) lẫn `txn_lookup` / giao dịch ngoài đồ thị (nhãn `Transaction`, nguồn `records`). Mỗi mục có:
  - `text = "<label> <txn_id>: <amount> VND from <src|-> to <dst|-> on <ts> via <channel>[; counterparty …]"`;
  - `citations = ("txn:<id>", "account:<src>", "account:<dst>", ["customer:<owner>"])`;
  - `data = {"txn_id", "src", "dst", "amount", "ts", "channel"}`. Với tiền mặt, `src` hoặc `dst` là `None`.

  `data` **không** có chủ của tài khoản: `src_owner` / `dst_owner` chỉ đi vào hậu tố của `text` khi `hops >= 3`.
- **Narrative** (`narrative.py`) không có mục giao dịch riêng lẻ. Ngữ cảnh của nó là `case_evidence(case)`, trong đó có
  mục đối tác `Counterparty {account_id} ({owner|external}): {IN|OUT} {txns} transaction(s) totalling {vnd} VND`
  (`retriever = "case_view"`, `citations = ("account:<id>",)`, `data = {"account_id", "owner", "direction", "txns",
  "vnd"}`). `direction` lấy từ view `txn_legs`, nhìn từ tài khoản của khách hàng trong case:
  - `IN`: đối tác là bên **gửi** (`counterparty_id = from_account_id`);
  - `OUT`: đối tác là bên **nhận**.

  Vì vậy narrative chỉ được lợi từ phép kiểm chiều tiền khi phép kiểm hiểu cả mục đối tác (Q3). Đo trên MINI-N:
  `case_evidence(V1)` có 12 mục, trong đó E9 = `Counterparty EXT-01 (external): IN 1 transaction(s) totalling
  500,000,000 VND` và E10 = `Counterparty EXT-02 (external): OUT 1 transaction(s) totalling 480,000,000 VND`.
- **Dữ liệu thật** (đo, chỉ đọc):

  | giao dịch | ngày giờ | từ | đến | số tiền | kênh |
  |---|---|---|---|---|---|
  | T0000196919 | 2026-04-30 04:00:16 | A3154676584 | A9418747931 | 153936000 | INTERNAL_TRANSFER |
  | T0000193641 | 2026-04-28 03:19:45 | A5538166070 | A3154676584 | 161398000 | INTERNAL_TRANSFER |
  | T0000192133 | 2026-04-27 08:00:00 | A9418747931 | A5538166070 | 172924000 | INTERNAL_TRANSFER |

  Ba giao dịch tạo thành một vòng. Dòng audit `ANSWERED` 17418 (câu 2) có `cited_ids = [T0000193641,
  C-CIF00000955-20260427, G-CIF00000955, T0000192133]` và `validation = {sentences: 1, supported: 1, unsupported: 0}`.
  Dòng 17416 (câu 1, câu hỏi "Tài khoản A3154676584 nhận tiền từ những tài khoản nào?") có 2 câu, cả 2 đều supported.
- **Prototype đúng các luật ở mục Thiết kế**: cả hai câu đo được đều bị bắt. Câu 1 có `direction_mismatch` ở cả ba dạng
  (có dấu, không dấu, tiếng Anh). Câu 2 có `direction_mismatch` + `speculative`. 22 câu mẫu cho kết quả đúng như các AC
  dưới đây.
- **Ước lượng ảnh hưởng lên 8e** (prototype chạy trên `results/phase8/eval_answers.jsonl`, 90 dòng `graphrag` = 30 câu
  hỏi × 3; lấy 75 câu trả lời không bị từ chối):
  - 102 câu không mang `[CHƯA KIỂM CHỨNG]`. Prototype nhận ra vai trò tài khoản ở 72 câu.
  - Kết quả: **0** `direction_mismatch`, **0** `speculative`.
  - Đây là cận dưới. File chỉ lưu id được trích ở mức cả câu trả lời, không lưu `cites` của từng câu, nên prototype gộp
    mọi giao dịch được trích của câu trả lời lại.

  Dự đoán: bảng số của README không đổi. Vẫn **phải chạy lại thật** (S4).
- **Test hiện có** (đọc, chưa chạy):
  - Các câu mẫu của 8c (`tests/assistant/an_helpers.py`: S_OK1 "Tài khoản A01 nhận … tiền mặt" trên X1 có `dst = A01`;
    "A01 nhận tiền" trong `test_answering_pure.py` / `test_answering_review.py`) đều nói **đúng** chiều.
  - N_OK của narrative chỉ trích mục alert / tài khoản, là những mục không có bên gửi / nhận.
  - Không test nào so sánh `ISSUES` với một tuple cố định.
  - Hợp đồng JSON (`Answer.as_dict`, `web/src/api/types.ts`) không chứa `issues`.

### Interface đề xuất
```python
# src/aml/assistant/facts.py  (thuần; so khớp trên fold(text))
ROLES = ("src", "dst")


def account_roles(text: str, accounts: Collection[str]) -> dict[str, frozenset[str]]:
    ...
    # tài khoản (đúng chuỗi như trong `accounts`) -> vai trò câu gán cho nó; tài khoản không được gán vai trò thì vắng mặt


def is_speculative(text: str) -> bool: ...


# src/aml/assistant/validation.py
ISSUES = (
    "no_citation",
    "unknown_citation",
    "amount_not_in_evidence",
    "date_not_in_evidence",
    "direction_mismatch",  # mới
    "speculative",  # mới
    "verdict_language",
)


def transfer_sides(
    evidence: Evidence,
) -> frozenset[tuple[str, str]]: ...  # {(account_id, "src"|"dst")}
```
`check_claim`, `check_claims`, `Checked`, `Answer`, `Sentence`, `validation_counts`, các prompt và `ANSWER_PROMPT_VERSION`
/ `NARRATIVE_PROMPT_VERSION` giữ nguyên chữ ký.

### Thiết kế (theo đề xuất mặc định ở Câu hỏi mở)
- **`transfer_sides(e)`** trả tập các cặp (tài khoản, vai trò) mà mục bằng chứng chứng thực:
  - *Mục giao dịch*: trích dẫn đầu tiên có kind `txn`, và `data` có khoá `src` và `dst`. Kết quả gồm `(data.src, "src")`
    khi `src` là chuỗi khác rỗng, và `(data.dst, "dst")` khi `dst` là chuỗi khác rỗng. Bên `None` (tiền mặt) không cho
    cặp nào.
  - *Mục đối tác của narrative*: `retriever == "case_view"`, trích dẫn đầu tiên có kind `account`, `data.direction` thuộc
    `("IN", "OUT")`. Kết quả là `{(data.account_id, "src")}` với `IN` và `{(data.account_id, "dst")}` với `OUT`.
  - Mọi mục khác (tài khoản, khách hàng, case, alert, chunk, dòng Text2Cypher, hoạt động) trả `frozenset()`.
- **`account_roles(text, accounts)`**: mọi so khớp chạy trên `fold(text)`, nên có dấu hay không dấu đều như nhau và id
  được so không phân biệt hoa thường. Một lần nhắc tài khoản là một lần id xuất hiện mà không dính liền chữ hay số ở hai
  bên. Vai trò của mỗi lần nhắc xét theo thứ tự sau:
  1. **Giới từ đứng ngay trước id**. Giữa giới từ và id chỉ được có, tuỳ chọn, `tai khoan` | `tk` | `cac tai khoan` |
     `account` | `accounts` | `the account`.
     - Giới từ nguồn: `tu`, `from`, `khoi` → vai trò `src`.
     - Giới từ đích: `den`, `toi`, `sang`, `cho`, `vao`, `ve`, `to`, `into` → vai trò `dst`. Riêng giới từ đích **không**
       tạo vai trò khi đứng ngay sau `lien quan`, `related`, `linked`, `belong(s)` hay `thuoc` ("liên quan tới tài
       khoản X" không nói chiều tiền).
  2. **Không có giới từ thì xét động từ đứng sau id.** Lấy đoạn văn bản sau id. Đoạn dừng ở dấu câu `, ; : . ! ?` đứng
     trước khoảng trắng hoặc ở cuối câu (dấu phẩy trong `153,936,000` không cắt đoạn), hoặc ở lần nhắc kế tiếp của một
     tài khoản. Xét 4 từ đầu tiên của đoạn; cụm động từ xuất hiện sớm nhất quyết định vai trò:
     - Cụm vào: `nhan`, `duoc chuyen`, `duoc nop`, `receive(s|d)`, `receiving`, `is credited`, `was credited` → `dst`.
     - Cụm ra: `chuyen`, `gui`, `thanh toan`, `rut`, `send(s)`, `sent`, `transfer(s|red)`, `pay(s)`, `paid`,
       `wire(s|d)`, `withdraw(s)`, `withdrew`, `debited` → `src`.
     - Khi một cụm vào và một cụm ra bắt đầu cùng một từ, cụm vào thắng (`duoc chuyen` thắng `chuyen`).
  3. Không khớp luật nào thì lần nhắc đó không có vai trò.

  Đại từ (`họ`, `they`) **không** được quy về tài khoản nào. Dấu phẩy chặn luật 2, nên trong "…có thể là A5538166070,
  vì họ nhận được…" tài khoản A5538166070 không được gán vai trò.
- **`direction_mismatch`** chỉ xét khi câu có ít nhất một mục phân giải được (cùng nhánh với kiểm số tiền / ngày):
  1. Gọi `S` là hợp các `transfer_sides` của các mục được trích. `S` rỗng thì không xét.
  2. Tính `R = account_roles(câu, {a for a, _ in S})`. Chỉ những tài khoản có mặt trong `S` mới được gán vai trò.
  3. Câu bị gắn `direction_mismatch` khi tồn tại một tài khoản `a` và một vai trò `r ∈ R[a]` mà `(a, r) ∉ S`. Nói cách
     khác, mỗi vai trò câu gán cho một tài khoản phải được **ít nhất một** mục được trích chứng thực.

  Hệ quả:
  - Câu chỉ nêu một tài khoản thì kiểm riêng tài khoản đó.
  - Câu chuỗi "từ A sang B rồi sang C" trích A→B và B→C thì đạt, vì không có luật ghép cặp (Q4).
  - Tài khoản câu nêu mà không nằm trong `S` thì phép kiểm này bỏ qua (Q5).
- **`speculative`**: `is_speculative(câu)` đúng khi `fold(câu)` chứa một trong các cụm sau như một từ trọn vẹn: `co the
  la`, `co le`, `co kha nang`, `duong nhu`, `hinh nhu`, `chac la`, `du doan`, `may be`, `might be`, `could be`,
  `possibly`, `probably`, `perhaps`, `likely`, `presumably`. Không tính `co the` đi trước một động từ (chỉ khả năng làm
  gì, như "investigator có thể yêu cầu"), và không tính `may` đứng một mình (tháng May). Mã này được gắn bất kể câu trích
  gì, giống `verdict_language` (Q6).
- **Trạng thái và số đếm** (không có luật mới, chỉ là hệ quả của `supported == (issues == ())`):
  - Câu mang một trong hai mã mới thì `supported = false`. Câu vẫn được hiển thị với tiền tố `UNVERIFIED[language]` và vẫn
    được đánh số trích dẫn.
  - `Answer.validation` tính câu đó vào `unsupported`.
  - `details.validation.issues` của audit đếm thêm `direction_mismatch` / `speculative`. Shape của `details` không đổi.
  - Khi không câu nào còn được đỡ, câu trả lời thành `insufficient_evidence` với `refusal_reason = "nothing_supported"`,
    và các câu nằm ở `discarded` (luật cũ của 8c, Q7).
  - `answer_id` của một câu trả lời không mang câu bị gắn cờ mới thì không đổi. Câu trả lời có câu bị gắn cờ thì đổi
    `text` (thêm tiền tố), do đó đổi `answer_id`.
- **Không gọi thêm LLM, không đổi prompt.** `llm_calls` của Q&A và narrative giữ nguyên. Cache của 8a vẫn khớp, nên một
  lần chạy lại 8e chỉ phát lại câu trả lời đã lưu.

### Sửa kéo theo (duyệt spec này là duyệt các thay đổi đó)
| # | Chỗ sửa | Thay đổi |
|---|---|---|
| S1 | docstring của `src/aml/assistant/validation.py` | liệt kê `direction_mismatch` và `speculative` vào danh sách phép kiểm (bước 3b và 4a). Câu "They do not check meaning" sửa thành: số đếm và quan hệ vẫn không kiểm; chiều tiền chỉ được kiểm theo từ vựng ở trên. |
| S2 | `specs/assistant-answering.md` (đã duyệt), mục Thiết kế "Hậu kiểm `check_claims`" và hàng L4 của bảng phòng thủ | thêm hai bước mới và dẫn sang spec này; bỏ "chiều tiền" khỏi danh sách "không kiểm ngữ nghĩa". Không đổi AC nào của 8c. |
| S3 | `facts.py`: docstring của module | thêm `account_roles` / `is_speculative` vào mô tả (chỉ docstring). |
| S4 | đánh giá 8e | Sau khi hiện thực, chạy `uv run aml rag eval --force` (cần Neo4j + Ollama; phát lại cache vì prompt không đổi). Nếu `results/phase8/eval_result.json` không đổi, README giữ nguyên số và ghi thêm commit của lần chạy lại vào câu "The committed result …". Nếu đổi, cập nhật bảng README, `docs/assistant-eval.md` và `results/phase8/` bằng số của lần chạy đó, kèm lệnh và commit. Không có AC tự động cho bước này (cần dịch vụ ngoài). |

## Tiêu chí nghiệm thu
<!-- Mọi AC là pytest DuckDB-only (không Ollama / Neo4j / Oracle), dùng helpers của tests/assistant/an_helpers.py:
EV, X1, X2, S_OK1, LLM, J, FakeRetriever, K0, audit8c, mini_n, CASE = C-C01-20260302. settings = load_settings(environ={"DB_BACKEND": "duckdb"}).
D1 = Evidence("E1", "fact", "case_graph", "neo4j", "Transfer T0000196919: 153,936,000 VND from A3154676584 to A9418747931 on 2026-04-30 04:00:16 via INTERNAL_TRANSFER", ("txn:T0000196919", "account:A3154676584", "account:A9418747931"), {"txn_id": "T0000196919", "src": "A3154676584", "dst": "A9418747931", "amount": 153936000, "ts": datetime(2026, 4, 30, 4, 0, 16), "channel": "INTERNAL_TRANSFER"})
D2 = như D1 với ref "E2", T0000193641, src A5538166070, dst A3154676584, 161,398,000 / 161398000, 2026-04-28 03:19:45.
D3 = như D1 với ref "E3", T0000192133, src A9418747931, dst A5538166070, 172,924,000 / 172924000, 2026-04-27 08:00:00.
D4 = Evidence("E4", "fact", "case_view", "cases", "Counterparty A9418747931 (G-CIF00002986): OUT 1 transaction(s) totalling 153,936,000 VND", ("account:A9418747931",), {"account_id": "A9418747931", "owner": "G-CIF00002986", "direction": "OUT", "txns": 1, "vnd": 153936000})
DEV = (D1, D2, D3, D4); RD = FakeRetriever(DEV); CHK(text, cites, ev=DEV) = check_claim(Claim(text, cites), ev).
A315 = "A3154676584", A941 = "A9418747931", A553 = "A5538166070"; ACC3 = {A315, A941, A553}.
S_DIR1 = "Tài khoản A3154676584 cũng nhận tiền từ tài khoản A9418747931 với số tiền 153,936,000 VND vào ngày 2026-04-30 04:00:16 thông qua chuyển khoản nội bộ."  (câu đo được 1)
S_SPEC2 = "Chủ sở hữu hưởng lợi cuối cùng của số tiền này có thể là A5538166070, vì họ nhận được 161,398,000 VND từ A3154676584 vào ngày 2026-04-28 03:19:45 thông qua chuyển khoản INTERNAL_TRANSFER."  (câu đo được 2)
S_IN = "Tài khoản A3154676584 nhận 161,398,000 VND từ tài khoản A5538166070 vào ngày 2026-04-28 03:19:45."
S_OUT = "Tài khoản A3154676584 chuyển 153,936,000 VND cho tài khoản A9418747931 vào ngày 2026-04-30."
S_EN = "Account A3154676584 sent 153,936,000 VND to account A9418747931 on 2026-04-30."
S_CHAIN = "Tiền đi từ tài khoản A9418747931 sang tài khoản A5538166070 rồi sang tài khoản A3154676584."
"(đo)" = kết quả đã thấy trên prototype ngoài repo; còn lại suy ra từ thiết kế. -->
- AC1: Given `facts.account_roles`, When gọi với `accounts = ACC3` trên từng câu sau, Then kết quả đúng như sau (đo): S_DIR1 → `{A315: {"dst"}, A941: {"src"}}`; bản không dấu `"Tai khoan A3154676584 cung nhan tien tu tai khoan A9418747931 voi so tien 153,936,000 VND."` → `{A315: {"dst"}, A941: {"src"}}`; `"Account A3154676584 received 153,936,000 VND from account A9418747931 on 2026-04-30."` → `{A315: {"dst"}, A941: {"src"}}`; S_SPEC2 → `{A315: {"src"}}` (A553 không có vai trò vì dấu phẩy chặn, `họ` không được quy về tài khoản nào); S_OUT → `{A315: {"src"}, A941: {"dst"}}`; S_EN → `{A315: {"src"}, A941: {"dst"}}`; `"Giao dịch T0000196919 chuyển 153,936,000 VND từ A3154676584 đến A9418747931."` → `{A315: {"src"}, A941: {"dst"}}`; S_CHAIN → `{A941: {"src"}, A553: {"dst"}, A315: {"dst"}}`; `"Tài khoản A3154676584 nhận tiền từ A5538166070 và chuyển cho A9418747931."` → `{A315: {"dst"}, A553: {"src"}, A941: {"dst"}}`; `"Tài khoản A3154676584 được chuyển 5,000,000 VND."` → `{A315: {"dst"}}`; `"Giao dịch T0000196919 liên quan tới tài khoản A3154676584."` → `{}`; `"Investigator có thể yêu cầu chứng từ của tài khoản A3154676584."` → `{}`; và `account_roles("a3154676584 nhận tiền.", {A315})` → `{A315: {"dst"}}` (không phân biệt hoa thường, khoá trả về là chuỗi của `accounts`).
- AC2: Given `facts.is_speculative`, `validation.transfer_sides` và `validation.ISSUES`, When gọi trên các giá trị sau, Then `ISSUES == ("no_citation", "unknown_citation", "amount_not_in_evidence", "date_not_in_evidence", "direction_mismatch", "speculative", "verdict_language")`; `is_speculative` trả `True` cho S_SPEC2, `"Tài khoản A3154676584 có thể là tài khoản trung gian."`, `"Tai khoan nay co le la tai khoan mule."`, `"Account A9418747931 is possibly a mule account."`, `"This might be layering."` và trả `False` cho S_IN, `"Investigator có thể yêu cầu chứng từ của tài khoản A3154676584."`, `"Account A3154676584 sent 153,936,000 VND to account A9418747931 in May 2026."`, `"Khách hàng có hành vi đáng ngờ."`; `transfer_sides(D1) == {(A315, "src"), (A941, "dst")}`, `transfer_sides(X1) == {("A01", "dst")}` (bên `None` của tiền mặt bị bỏ), `transfer_sides(D4) == {(A941, "dst")}`, `transfer_sides(replace(D4, data={**D4.data, "direction": "IN"})) == {(A941, "src")}`, và `transfer_sides(X2) == frozenset()`.
- AC3: Given DEV, When `CHK(S_DIR1, ("E1",))` (câu đo được 1, có dấu) và hai bản cùng nghĩa của nó ở AC1 (không dấu, tiếng Anh) với `("E1",)`, Then cả ba có `supported == False`, `issues == ("direction_mismatch",)` (số tiền 153,936,000 và ngày 2026-04-30 đều có trong D1 nên không có mã nào khác), `refs == ("E1",)`; và `CHK(S_DIR1, ("E1", "E2"))` cũng có `issues == ("direction_mismatch",)`, vì A941 chỉ là `dst` trong D1 và không có mặt trong D2.
- AC4: Given DEV, When `CHK(S_SPEC2, ("E2", "E3"))` (câu đo được 2; cùng hai giao dịch mà câu thật đã trích), Then `supported == False`, `issues == ("direction_mismatch", "speculative")`, `refs == ("E2", "E3")` (A315 là `dst` trong D2 và không có mặt trong D3; 161,398,000 VND và 2026-04-28 có trong D2 nên không có `amount_not_in_evidence` / `date_not_in_evidence`); và `CHK("Tài khoản A3154676584 có thể là tài khoản trung gian.", ("E1",))` có `issues == ("speculative",)`.
- AC5: Given DEV và EV của 8c, When kiểm các câu nói đúng chiều, Then mỗi câu có `supported == True` và `issues == ()`: `CHK(S_IN, ("E2",))`, `CHK(S_OUT, ("E1",))`, `CHK(S_EN, ("E1",))`, `CHK("Giao dịch T0000196919 chuyển 153,936,000 VND từ A3154676584 đến A9418747931.", ("T0000196919",))`, `CHK(S_CHAIN, ("E3", "E2"))`, `CHK("Tài khoản A9418747931 nhận 153,936,000 VND.", ("E1",))`, `CHK("Giao dịch T0000196919 liên quan tới tài khoản A3154676584.", ("E1",))`, `CHK("Investigator có thể yêu cầu chứng từ của tài khoản A3154676584.", ("E1",))`, `CHK("Tài khoản A1111111111 nhận tiền từ tài khoản A2222222222.", ("E1",))` (cả hai tài khoản không có trong D1 nên phép kiểm chiều bỏ qua), và S_OK1 của 8c trên EV với `("E1",)` vẫn cho `(True, (), ("E1",))`.
- AC6: Given DEV và EV, When kiểm các câu sai chiều chỉ nêu một tài khoản, Then mỗi câu có `issues == ("direction_mismatch",)`: `CHK("Tài khoản A9418747931 chuyển đi 153,936,000 VND.", ("E1",))`; `check_claim(Claim("Tài khoản A01 chuyển 390,000,000 VND tiền mặt vào ngày 2026-03-02.", ("E1",)), EV)` (X1 là tiền mặt nộp vào A01); `CHK("Tiền được gửi từ A9418747931 tới A3154676584.", ("E1",))`; và `CHK("Khách hàng nhận 153,936,000 VND từ tài khoản A9418747931.", ("E4",))` (mục đối tác OUT: A941 là bên nhận). Còn `CHK("Khách hàng chuyển 153,936,000 VND cho tài khoản A9418747931.", ("E4",))` có `issues == ()`.
- AC7: Given MINI-N (`mini_n(duck)`), RD và `fake = LLM(J({"text": S_DIR1, "cites": ["E1"]}, {"text": S_IN, "cites": ["E2"]}))`, When `a = answer_question(duck, settings, "Tài khoản A3154676584 nhận tiền từ những tài khoản nào?", case_id=CASE, retriever=RD, llm=fake)`, Then `a.status == "answered"`; `set(a.as_dict()) == {"answer_id", "case_id", "question", "language", "status", "sentences", "citations", "retrievers", "validation", "model", "prompt_version"}`; `[s["supported"] for s in a.as_dict()["sentences"]] == [False, True]`; `[s["citations"] for s in a.as_dict()["sentences"]] == [[1], [2]]`; `a.as_dict()["validation"] == {"sentences": 2, "supported": 1, "unsupported": 1}`; `a.text.splitlines()[0] == "[CHƯA KIỂM CHỨNG] " + S_DIR1 + " [1]"`; `a.llm_calls == 1`; và dòng cuối của `audit8c(duck)` có `decision == "ANSWERED"`, `reason == "answered: 2 sentence(s), 1 supported, 1 flagged; 4 context item(s), 2 cited"`, `details.validation == {"sentences": 2, "supported": 1, "unsupported": 1, "issues": {"direction_mismatch": 1}}` và `details.flagged[0]["issues"] == ["direction_mismatch"]`.
- AC8: Given MINI-N, RD và `fake = LLM(J({"text": S_SPEC2, "cites": ["E2", "E3"]}))`, When `a = answer_question(duck, settings, "Ai là chủ sở hữu hưởng lợi cuối cùng của số tiền này?", case_id=CASE, retriever=RD, llm=fake)`, Then `a.status == "insufficient_evidence"`, `a.refusal_reason == "nothing_supported"`, `a.text == "Không đủ bằng chứng."`, `a.sentences == ()`, `a.citations == ()`, `len(a.discarded) == 1`, `a.discarded[0].issues == ("direction_mismatch", "speculative")`, `a.as_dict()["validation"] == {"sentences": 0, "supported": 0, "unsupported": 0}`, `a.llm_calls == 1` (không có lời gọi kiểm tra nào thêm); và dòng cuối của `audit8c(duck)` có `decision == "INSUFFICIENT_EVIDENCE"`, `details.refusal_reason == "nothing_supported"`, `details.validation == {"sentences": 0, "supported": 0, "unsupported": 0, "issues": {"direction_mismatch": 1, "speculative": 1}}`.
- AC9: Given MINI-N (case_evidence có E9 = đối tác EXT-01 `IN` 500,000,000 VND và E10 = đối tác EXT-02 `OUT` 480,000,000 VND) và `fake = LLM(json.dumps({"timeline": [{"text": "Khách hàng nhận 500,000,000 VND từ tài khoản EXT-01.", "cites": ["E9"]}, {"text": "Khách hàng nhận 480,000,000 VND từ tài khoản EXT-02.", "cites": ["E10"]}]}, ensure_ascii=False))`, When `d = draft_narrative(duck, settings, CASE, llm=fake, knowledge=K0())`, Then `[s.supported for s in d.sections["timeline"]] == [True, False]`, `d.sections["timeline"][1].issues == ("direction_mismatch",)`, `d.narrative.markdown` chứa `"1 of 2 sentence(s) verified."`, `d.llm_calls == 1`, và dòng `NARRATIVE_DRAFTED` cuối của `audit8c(duck)` có `details.validation == {"sentences": 2, "supported": 1, "unsupported": 1, "issues": {"direction_mismatch": 1}}`.
- AC10: Given repo sau khi hiện thực, When chạy `uv run pytest tests/assistant/test_answering_pure.py tests/assistant/test_answering_qa.py tests/assistant/test_answering_review.py tests/assistant/test_answering_narrative.py tests/assistant/test_answering_audit.py tests/assistant/test_answering_injection.py tests/api/test_insight_ac4_chat.py` mà không sửa test nào, gọi `check_claims` hai lần trên cùng các claim S_DIR1 / S_SPEC2 / S_IN với DEV, và đọc mã nguồn của `facts.py` / `validation.py`, Then các test đó đều xanh (không câu mẫu nào của 8c / 9c đổi `supported`, và `answer_id` mong đợi `ans-9504e4efe5dd` của 9c vẫn đúng); hai lần gọi `check_claims` trả kết quả bằng nhau; và hai file đó không import `aml.assistant.llm`, `requests`, `httpx` hay `ollama`.

## Ngoài phạm vi
- **Không** dùng LLM (hay mô hình NLI) để kiểm câu. Không đổi prompt, `ANSWER_PROMPT_VERSION` hay
  `NARRATIVE_PROMPT_VERSION`; một chỉ dẫn kiểu "đừng suy đoán" trong prompt là việc riêng, vì nó làm mất cache và buộc
  8e gọi lại mô hình thật.
- **Không** đổi hợp đồng JSON `Answer` / `Sentence` / `Citation`, `web/src/api/types.ts`, `aml.api.contracts`. Không đưa
  `issues` ra API. Không đổi shape của `details` trong audit (chỉ thêm mã mới trong `validation.issues`).
- **Luật ghép cặp** (một giao dịch duy nhất phải có đúng cặp nguồn → đích mà câu nêu) không làm. Câu nói về một đường
  tiền ("từ A đến C qua B"), dạng có trong 8 câu multi-hop của golden set, sẽ bị gắn cờ sai.
- Kiểm vai trò của **mã khách hàng / CIF** (`G-CIF…`, `CIF…`) và quy đại từ (`họ`, `they`, `nó`) về một tài khoản.
  `data` của mục giao dịch không có chủ tài khoản (Q2).
- **Phủ định** ("A01 không nhận tiền từ A02") không được xử lý. Câu phủ định có vai trò trái với giao dịch sẽ bị gắn cờ.
  Hướng sai này thiên về an toàn: câu vẫn hiện, chỉ mang nhãn chưa kiểm chứng.
- Câu bị động tiếng Anh với `by` ("received by account X", "sent by X"): `by` không phải giới từ trong danh sách, nên câu
  này không được gán vai trò.
- Kiểm số đếm ("3 giao dịch"), quan hệ sở hữu ("A01 thuộc G-C01"), kênh, giờ phút. Danh sách "sự kiện mà bằng chứng
  không bao giờ có" (chủ sở hữu hưởng lợi, UBO, nghề nghiệp) cũng không làm (Q6).
- Kiểm lại câu trả lời cũ trong `audit_log` hay `results/`. Chỉ lần chạy mới mới dùng phép kiểm mới.
- Mọi sửa đổi ngoài `src/aml/assistant/facts.py`, `src/aml/assistant/validation.py`, docstring liên quan và các test mới;
  `answering.py` và `narrative.py` không cần sửa code.

## Giả định
- Danh sách giới từ / động từ / cụm suy đoán là **danh sách từ vựng**, giống `is_verdict`. Nó bắt được các dạng đã thấy
  (câu đo được, các mẫu câu của `transaction_fact`, 102 câu của 8e) và biến thể gần, không bắt được mọi cách diễn đạt.
  8e vẫn là nơi đo chất lượng ngữ nghĩa.
- `fold` gộp vài từ khác nghĩa thành cùng một chuỗi: `từ` / `tư` / `tự` → `tu`, `nhận` / `nhân` → `nhan`, `về` / `vé` →
  `ve`. Luật chỉ áp khi giới từ đứng **ngay trước id** hoặc động từ nằm trong 4 từ **ngay sau id**, nên va chạm chỉ xảy ra
  khi từ đó dính sát id. Chấp nhận rủi ro này.
- Mục giao dịch của mọi retriever đều do `transaction_fact` dựng, có `data.src` / `data.dst` và trích dẫn đầu kind `txn`.
  Mục đối tác của narrative có `direction ∈ {IN, OUT}` theo `txn_legs`.
- Câu do mô hình viết chỉ nhắc id tài khoản theo đúng chuỗi trong bằng chứng (không thêm khoảng trắng, không viết tắt).
  Id viết sai thì không khớp, và phép kiểm chiều bỏ qua id đó.
- Ước lượng "0 thay đổi trên 8e" là cận dưới (xem Hiện trạng). Số thật lấy từ lần chạy S4.
- Mọi AC suy ra từ thiết kế và từ prototype ngoài repo; chưa chạy dòng code nào của repo. Lệch nhỏ khi hiện thực (vd ranh
  giới từ) thì cập nhật spec, không đổi quy ước.

## Câu hỏi mở
- [x] Q1. Những cách diễn đạt nào được tính là nói chiều tiền? — đề xuất mặc định: đúng các danh sách ở Thiết kế. Tức là — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  giới từ ngay trước id (`từ/from/khỏi` = nguồn; `đến/tới/sang/cho/vào/về/to/into` = đích, trừ khi đi sau "liên quan /
  related / linked / belongs / thuộc") hoặc cụm động từ trong 4 từ ngay sau id (nhận / được chuyển / được nộp / receive /
  credited = vào; chuyển / gửi / thanh toán / rút / send / transfer / pay / wire / withdraw / debited = ra). Áp cho có
  dấu, không dấu và tiếng Anh nhờ `fold`. Lý do: phủ hết các mẫu câu thật đã thấy (câu đo được, `transaction_fact`, 72/102
  câu của 8e) mà không có dương tính giả trên 102 câu đó.
- [x] Q2. Có kiểm vai trò của mã khách hàng / CIF hay quy đại từ `họ` về tài khoản không? — đề xuất mặc định: **không**. — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  Chỉ id tài khoản có trong bên gửi / nhận của mục được trích mới được kiểm; đại từ không được quy. Lý do: `data` của mục
  giao dịch không có chủ tài khoản, và quy đại từ đòi hỏi phân tích cú pháp, không tất định đủ tin cậy. Câu đo được 2 vẫn
  bị bắt nhờ vế "từ A3154676584".
- [x] Q3. Mục đối tác của narrative (`Counterparty … IN|OUT`) có được dùng làm bằng chứng chiều tiền không? — đề xuất mặc — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  định: **có** (IN → đối tác là nguồn, OUT → đối tác là đích). Lý do: narrative không có mục giao dịch riêng lẻ. Không có
  luật này thì `draft_narrative` không được lợi gì từ phép kiểm mới, trái với yêu cầu.
- [x] Q4. Câu trích nhiều giao dịch: mỗi vai trò chỉ cần **một** giao dịch được trích chứng thực, hay phải có một giao — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  dịch mang đúng cặp nguồn → đích? — đề xuất mặc định: **chỉ cần một, xét riêng từng tài khoản; không ghép cặp**. Lý do:
  luật ghép cặp gắn cờ sai các câu về đường tiền nhiều chặng ("từ A sang B rồi sang C", "từ A đến C qua B") mà golden set
  có 8 câu multi-hop. Câu đo được 1 và 2 vẫn bị bắt vì mỗi câu có một vai trò không giao dịch nào chứng thực.
- [x] Q5. Một tài khoản câu gán vai trò nhưng **không** có trong giao dịch nào được trích thì sao? — đề xuất mặc định: — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  **bỏ qua** (không gắn `direction_mismatch`). Lý do: đó là lỗi trích thiếu / trích sai, khác lỗi chiều tiền. Câu có thể
  trích mục tài khoản cho id đó, và kiểm số tiền / ngày vẫn chạy. Phương án khác: gắn mã mới `party_not_in_evidence`.
- [x] Q6. Câu suy đoán bị gắn cờ chỉ vì từ ngữ, hay chỉ khi điều suy đoán không có trong bằng chứng? — đề xuất mặc định: — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  **chỉ vì từ ngữ** (mã `speculative`, áp cho mọi câu, kể cả câu chỉ trích chunk tri thức). Lý do: kiểm tất định không
  biết được một suy đoán ("có thể là chủ sở hữu hưởng lợi") có nằm trong bằng chứng hay không. Một câu đã kiểm chứng nên
  nói điều bằng chứng ghi. Suy luận thuộc về investigator, và câu vẫn hiện với nhãn chưa kiểm chứng. 8e có 0/102 câu dính
  danh sách này. Không thêm danh sách chủ đề "bằng chứng không bao giờ có" (beneficial owner, UBO): câu khẳng định thẳng
  "chủ sở hữu hưởng lợi là X" mà không suy đoán vẫn lọt nếu chiều tiền đúng. Đây là giới hạn được ghi lại.
- [x] Q7. Khi mọi câu đều bị gắn cờ (như câu đo được 2) thì trạng thái là gì? — đề xuất mặc định: giữ luật 8c, — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  `insufficient_evidence` với `refusal_reason = "nothing_supported"` và các câu nằm ở `discarded`. Không thêm lý do từ
  chối mới. Lý do: đúng hành vi đã duyệt, và người dùng nhận "Không đủ bằng chứng." thay vì một câu suy đoán.
- [x] Q8. Có thêm mã lỗi mới không, và đặt ở đâu trong `ISSUES`? — đề xuất mặc định: **hai mã mới** `direction_mismatch` — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  và `speculative`, đặt sau `date_not_in_evidence` và trước `verdict_language`. Chúng chỉ hiện ở `Sentence.issues` nội bộ
  và ở `details.validation.issues` / `details.flagged` của audit. Không có marker hiển thị mới: dùng lại tiền tố
  `[CHƯA KIỂM CHỨNG]` / `[UNVERIFIED]`. Lý do: không đổi hợp đồng UI, và audit vẫn cho biết vì sao câu bị gắn cờ.
- [x] Q9. Có phải chạy lại 8e và sửa README không? — đề xuất mặc định: **có chạy lại** (`uv run aml rag eval --force`, — Trả lời: theo đề xuất mặc định (người dùng chọn khi duyệt, 2026-10-14).
  phát lại cache) sau khi hiện thực (S4). Chỉ sửa số trong README / `docs/assistant-eval.md` / `results/phase8/` khi kết
  quả đổi, và ghi lệnh cùng commit. Lý do: số trong README phải từ lần chạy thật. Ước lượng ngoài repo dự đoán không đổi
  (0 cờ mới trên 102 câu), nhưng ước lượng đó gộp id ở mức câu trả lời nên chưa đủ làm bằng chứng.
