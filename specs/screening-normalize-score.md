---
id: screening-normalize-score
status: approved
approved_by: pthieu
---

# Phase 3a — Chuẩn hoá tên, trọng số IDF và điểm khớp tên kết hợp

## Bối cảnh
Phase 3 (PROJECT_BRIEF.md mục 4) quá lớn cho một spec nên chia ba: **3a (spec này)** chuẩn hoá tên + IDF + điểm
khớp tên; **3b `screening-tiers-eval`** Tier 1 blocking, Tier 2 định danh phụ, quyết định/audit, `aml screen`,
đánh giá so baseline; **3c `screening-oracle-incremental`** bản Oracle `UTL_MATCH` và incremental screening.
3a là thư viện thuần Python (không ghi DB, không CLI): biến tên khách hàng có dấu (`Nguyễn Thị Hương`) và tên
watchlist Latin không dấu (`HUONG NGUYEN THI`) về cùng một dạng, rồi chấm điểm sao cho khớp chỉ trên token phổ biến
(`NGUYEN VAN`) cho điểm thấp. Người dùng trực tiếp: 3b/3c; gián tiếp: analyst đọc `reason` của từng quyết định.

### Hiện trạng đã kiểm trên dữ liệu Phase 1 (seed 42; TINY = fixture `tiny_parquet`, `small` = `data/parquet`)
- `customers.full_name`: có dấu, dạng Title Case, 2–4 token; **không có pháp nhân** (0 tên chứa `CONG TY`/`TNHH`/
  `CO`/`LTD`/`JSC`/`CP`/`MTV` ở cả TINY lẫn `small`); không null. `small`: 310/5000 tên đã không dấu (bản CIF trùng
  kiểu `NO_DIACRITICS`), có bản đảo thứ tự (`Xuan Thang Huynh`) và bản lỗi gõ (`Trầ Hữu Long`, `Nuỳnh Nguyễn`).
- `watchlist.primary_name` / `watchlist_alias.alias_name`: đã là Latin hoa không dấu, chỉ chữ + khoảng trắng
  (chuẩn hoá là phép đồng nhất trên cả 445 tên TINY và 4594 tên `small`); 2–5 token; alias `AKA` có dạng viết tắt
  chữ đầu (`N THI HA`, `S PARK`: 61/245 alias TINY, 604/2594 alias `small`).
- Token (sau chuẩn hoá): TINY 300 khách hàng → 85 token khác nhau, 268 tên chuẩn hoá khác nhau, 258 khoá không phụ
  thuộc thứ tự khác nhau; `small` 5000 → 228 token, 2796 tên, 2679 khoá.
- Tần suất theo số khách hàng chứa token (document frequency): TINY `NGUYEN` 115 (38,3%), `THI` 72 (24,0%), `TRAN`
  31, `ANH` 28, `LE` 25, `VAN` 20; `small` `NGUYEN` 1810 (36,2%), `THI` 1283 (25,7%), `TRAN` 534, `ANH` 473, `VAN`
  359, và **`CONG` 251 (5,0%)** là tên đệm phổ biến — `CONG TY` chỉ được coi là token pháp nhân khi đi liền nhau
  và có căn cứ khác (Q2). `small` có 111/228 token chỉ xuất hiện ở 1 khách hàng (phần lớn là token lỗi gõ).
- Soundex (tự cài đặt American Soundex để đo): 228 token `small` gộp còn 115 mã; `H520` = {`HOANG`, `HONG`, `HUNG`,
  `HUONG`}, `H000` = {`HA`, `HAI`, `HAO`, `HIEU`, `HO`, `HOA`, `HUU`, ...}, `T000` = {`TAI`, `THAO`, `THI`, `THU`,
  ...}; bỏ dấu đã gộp 280 token có dấu còn 228.
- `pyproject.toml` **chưa có** `rapidfuzz` lẫn `unidecode` (brief mục 1 liệt kê cả hai). Số liệu điểm trong spec đo
  bằng `rapidfuzz` 3.14.6 (`uv run --with rapidfuzz`, không sửa `pyproject.toml`).
- `aml.datagen.customers._strip_diacritics` (hàm private của datagen) đã bỏ dấu bằng `unicodedata` + ánh xạ `đ/Đ`.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/common/config.py
class ScreeningConfig(BaseModel):  # 3b, 3c bổ sung thêm khoá vào cùng model này
    token_set_weight: float  # trọng số của rapidfuzz token_set_ratio
    jaro_winkler_weight: float  # trọng số của Jaro-Winkler; hai trọng số phải cộng bằng 1.0
    token_match_min: float  # Jaro-Winkler tối thiểu để hai token được coi là cùng một token
    token_length_band: int  # chênh lệch độ dài tối đa giữa hai token được đem so
    rare_token_max_df_rate: float  # token "hiếm" khi doc_freq / n_names <= giá trị này
    legal_strong_terms: list[str]  # token/cụm pháp nhân không thể là tên người, bỏ ở mọi vị trí
    legal_weak_terms: list[str]  # token/cụm mơ hồ, chỉ bỏ khi tên có ít nhất một strong term


# src/aml/screening/normalize.py
def strip_diacritics(text: str) -> str: ...
def normalize_name(raw: str | None, cfg: ScreeningConfig) -> str: ...
def name_key(normalized: str) -> str: ...  # các token sắp tăng dần, nối bằng 1 khoảng trắng


# src/aml/screening/idf.py
@dataclass(frozen=True)
class TokenStats:
    n_names: int  # số tên (khách hàng) có tên chuẩn hoá khác rỗng
    doc_freq: Mapping[str, int]  # token -> số tên chứa token (mỗi tên tính 1 lần)

    def idf(self, token: str) -> float: ...  # ln((n_names + 1) / (doc_freq.get(token, 0) + 1))
    def is_rare(self, token: str, max_df_rate: float) -> bool: ...


def build_token_stats(normalized_names: Iterable[str]) -> TokenStats: ...
def customer_token_stats(
    db: Database, cfg: ScreeningConfig
) -> TokenStats: ...  # đọc customers.full_name


# src/aml/screening/scoring.py
def tokens_match(a: str, b: str, cfg: ScreeningConfig) -> bool: ...


@dataclass(frozen=True)
class NameScore:
    token_set: float  # rapidfuzz.fuzz.token_set_ratio, 0..100, làm tròn 2 chữ số
    jaro_winkler: float  # 100 * JaroWinkler.similarity(name_key(a), name_key(b)), làm tròn 2
    fuzzy: float  # token_set_weight * token_set + jaro_winkler_weight * jaro_winkler, làm tròn 2
    coverage: float  # độ phủ token theo trọng số IDF, 0..1, làm tròn 4
    score: float  # round(fuzzy * coverage, 2) — điểm tên cuối cùng, 0..100
    matched: tuple[str, ...]  # token phía khách hàng có token khớp ở phía danh sách (giữ thứ tự)
    common_only: bool  # True khi matched khác rỗng và không token nào trong matched là "hiếm"


def score_names(
    customer_norm: str, list_norm: str, stats: TokenStats, cfg: ScreeningConfig
) -> NameScore: ...
```
- `Settings` thêm trường `screening: ScreeningConfig`; `config.yaml` thêm:
  ```yaml
  screening:
    token_set_weight: 0.5
    jaro_winkler_weight: 0.5
    token_match_min: 0.90
    token_length_band: 1
    rare_token_max_df_rate: 0.02
    legal_strong_terms: [TNHH, MTV, CP, JSC, LTD, CTY, LLC, INC, CORP]
    legal_weak_terms: [CONG TY, CO PHAN, CO]
  ```
- `pyproject.toml` thêm `rapidfuzz>=3.9` vào `dependencies` (Q1 về `unidecode`).
- Tài liệu mới `docs/screening.md`, mục "Why not Soundex / Metaphone" (3b, 3c bổ sung mục khác vào cùng file).

### Thiết kế (xác nhận ở Câu hỏi mở)
- **`normalize_name`** (thuần hàm, không đọc DB): (1) `None`/NaN/không phải chuỗi → `""`; (2) `đ/Đ` → `d/D`, phân
  rã NFD, bỏ ký tự nhóm `Mn`, viết hoa; (3) mọi ký tự ngoài `A–Z` (chữ số, dấu câu, chữ không phải Latin) → khoảng
  trắng; (4) tách token theo khoảng trắng; (5) bỏ mọi `legal_strong_terms` (so theo ranh giới token, cụm nhiều từ so
  nguyên cụm, cụm dài trước); **chỉ khi** bước này bỏ được ít nhất một term thì bỏ tiếp mọi `legal_weak_terms`; nếu
  kết quả rỗng thì trả kết quả của bước (4); (6) nối bằng một khoảng trắng.
- **`name_key`**: token sắp theo thứ tự chữ cái, **giữ token lặp** (`DANG ANH ANH` → `ANH ANH DANG`).
- **IDF** tính trên tập khách hàng (mỗi dòng `customers` là một "document", tên rỗng bị bỏ qua):
  `idf(t) = ln((n_names + 1) / (doc_freq(t) + 1))`; token chưa từng thấy có `doc_freq = 0` nên nhận IDF lớn nhất.
  `is_rare(t)` = `doc_freq(t) / n_names <= max_df_rate` (token chưa thấy luôn hiếm; `n_names = 0` → mọi token hiếm).
- **`tokens_match(a, b)`** = `a == b`, hoặc (`a[0] == b[0]` và `|len(a) − len(b)| <= token_length_band` và
  `rapidfuzz.distance.JaroWinkler.similarity(a, b) >= token_match_min`). Đây là "first-letter/length band" ở mức
  token; Tier 1 của 3b dùng lại đúng hàm này để ứng viên và điểm không bao giờ lệch nhau.
- **`score_names`** (đối số đã chuẩn hoá; phía khách hàng trước): một trong hai tên rỗng → mọi trường số = 0.0,
  `matched = ()`, `common_only = False`. Ngược lại, với C = token khách hàng, W = token danh sách (đa tập):
  `cov_C = Σ idf(u) của u∈C có ít nhất một t∈W khớp / Σ idf(u) của mọi u∈C`, `cov_W` tương tự;
  `coverage = min(cov_C, cov_W)` (mẫu số 0 → 0.0); `score = round(fuzzy * coverage, 2)`. Điểm đối xứng theo hai
  đối số; `matched`/`common_only` tính theo phía khách hàng.
- **Ghi chú Soundex/Metaphone** (`docs/screening.md`): tên Việt là các âm tiết ngắn, khác nhau chủ yếu ở nguyên âm
  và dấu thanh — đúng những thứ Soundex/Metaphone bỏ đi; phụ âm ghép `NG`/`NH`/`TR`/`PH`/`KH`/`TH` bị mã hoá theo
  quy tắc tiếng Anh; ví dụ đo được ở mục Hiện trạng (`HOANG`/`HONG`/`HUNG`/`HUONG` cùng mã `H520`).

## Tiêu chí nghiệm thu
<!-- cfg = settings.screening của config.yaml mặc định (các giá trị ở mục Interface), trừ khi AC nói khác.
BASE = 8 tên khách hàng: "Nguyễn Văn An", "Nguyễn Văn Bình", "Nguyễn Thị Hoa", "Trần Văn Long", "Trần Hữu Long",
"Lê Thị Hoa", "Phạm Quốc Bảo", "Đỗ Xuân Sơn"; STATS = build_token_stats(normalize_name(n, cfg) for n in BASE)
=> n_names = 8; doc_freq: NGUYEN 3, VAN 3, THI 2, HOA 2, TRAN 2, LONG 2, 10 token còn lại 1.
TINY = fixture `tiny_parquet` (300 customers, 200 watchlist, 245 alias, seed 42). Mọi AC chạy ở chế độ DuckDB-only;
điểm đo bằng rapidfuzz 3.14.6. -->
- AC1: Given `cfg` mặc định, When gọi `normalize_name`, Then `"  Nguyễn   Thị  Hương "` → `"NGUYEN THI HUONG"`, `"Đặng Văn Đức"` → `"DANG VAN DUC"`, `"nguyễn thị hương"` → `"NGUYEN THI HUONG"`, `"NGUYEN THI HUONG"` → `"NGUYEN THI HUONG"` (idempotent), chuỗi `"Nguyễn"` ở dạng NFC và dạng NFD cho cùng kết quả `"NGUYEN"`, và `"O'Brien-Smith 3rd"` → `"O BRIEN SMITH RD"`.
- AC2: Given `cfg` mặc định, When gọi `normalize_name`, Then `"CÔNG TY TNHH MTV Thương Mại Hoà Bình"` → `"THUONG MAI HOA BINH"`, `"Hoa Binh Trading Co., Ltd."` → `"HOA BINH TRADING"`, `"Công ty CP Sữa Việt Nam"` → `"SUA VIET NAM"`, `"ABC JSC"` → `"ABC"`; tên người không bị cắt: `"Nguyễn Công Tý"` → `"NGUYEN CONG TY"`, `"Nguyễn Văn Cơ"` → `"NGUYEN VAN CO"`, `"Nguyen Cong Minh"` → `"NGUYEN CONG MINH"`; không có strong term thì weak term được giữ: `"Công ty Hoà Bình"` → `"CONG TY HOA BINH"`; và tên chỉ gồm token pháp nhân không bị xoá sạch: `"Công ty TNHH"` → `"CONG TY TNHH"`.
- AC3: Given `cfg` mặc định, When gọi `normalize_name` với `None`, `""`, `"   "`, `"123 !!!"`, `float("nan")` và `"Иван Петров"`, Then cả sáu trả `""` và không raise; và `name_key("")` trả `""`.
- AC4: Given `cfg` mặc định, When gọi `name_key(normalize_name(x, cfg))`, Then `"Xuan Thang Huynh"`, `"Huỳnh Xuân Thắng"` và `"THANG HUYNH XUAN"` cùng trả `"HUYNH THANG XUAN"`; `"Đặng Anh Anh"` trả `"ANH ANH DANG"` (giữ token lặp); và Given TINY, Then `normalize_name` là phép đồng nhất trên cả 445 tên của `watchlist.primary_name` + `watchlist_alias.alias_name`, mọi tên chuẩn hoá của 300 khách hàng khớp `^[A-Z]+( [A-Z]+)*$`, có đúng 268 tên chuẩn hoá khác nhau và 258 `name_key` khác nhau, và với mỗi cặp ground truth (`sanctions_hit`/`pep_hit`: CIF `subject` × entry `listed_entry`, 5 cặp) `name_key` của khách hàng bằng `name_key` của `primary_name` hoặc của ít nhất một alias của entry đó.
- AC5: Given `STATS` của BASE, When gọi `idf` và `is_rare`, Then `n_names = 8`; `round(idf("NGUYEN"), 4) = 0.8109`, `round(idf("THI"), 4) = 1.0986`, `round(idf("AN"), 4) = 1.5041`, `round(idf("BASHIROV"), 4) = 2.1972` (token chưa thấy = lớn nhất); `is_rare("NGUYEN", 0.25)` là False, `is_rare("THI", 0.25)` là True, `is_rare("BASHIROV", 0.02)` là True; và `build_token_stats([])` cho `n_names = 0`, `idf("X") = 0.0`.
- AC6: Given TINY nạp vào DuckDB bằng `load_parquet`, When gọi `customer_token_stats(duck, cfg)`, Then `n_names = 300`, `len(doc_freq) = 85`, `doc_freq["NGUYEN"] = 115`, `doc_freq["THI"] = 72`, `doc_freq["VAN"] = 20`, `round(idf("NGUYEN"), 4) = 0.9535`, `round(idf("VAN"), 4) = 2.6626`, `round(idf("BASHIROV"), 4) = 5.7071`, và `is_rare("NGUYEN", cfg.rare_token_max_df_rate)` là False.
- AC7: Given `cfg` mặc định, When gọi `tokens_match`, Then `("TRA", "TRAN")`, `("AN", "ANH")`, `("TRAN", "TRANG")` và `("NGUYEN", "NGUYEN")` trả True; `("HA", "HOA")`, `("LE", "LY")`, `("MUHAMMAD", "MOHAMMED")` trả False (Jaro-Winkler dưới 0.90); `("HANH", "ANH")` và `("ZHANG", "CHANG")` trả False (khác chữ cái đầu); `("NGUYEN", "NGUYENTHI")` trả False (lệch độ dài 3 > band 1).
- AC8: Given `STATS` của BASE và `cfg` mặc định, When gọi `score_names(normalize_name(a, cfg), b, STATS, cfg)`, Then (`"Nguyễn Văn An"`, `"NGUYEN VAN AN"`) và (`"Đỗ Xuân Sơn"`, `"SON DO XUAN"`) đều cho `token_set = 100.0`, `jaro_winkler = 100.0`, `fuzzy = 100.0`, `coverage = 1.0`, `score = 100.0`; (`"Trầ Hữu Long"`, `"TRAN HUU LONG"`) cho `token_set = 96.0`, `jaro_winkler = 98.46`, `fuzzy = 97.23`, `coverage = 1.0`, `score = 97.23`, `matched = ("TRA", "HUU", "LONG")`; và (`"Phạm Quốc Bảo"`, `"MUHAMMAD AL RASHID"`) cho `coverage = 0.0`, `score = 0.0`, `matched = ()`.
- AC9: Given `STATS` của BASE và `cfg` với `rare_token_max_df_rate = 0.25`, When gọi `score_names`, Then (`"Nguyễn Văn"`, `"NGUYEN VAN BASHIROV"`) cho `token_set = 100.0` nhưng `fuzzy = 72.72`, `coverage = 0.4247`, `score = 30.88`, `matched = ("NGUYEN", "VAN")`, `common_only = True`; (`"Nguyễn Văn An"`, `"NGUYEN VAN"`) cho `token_set = 100.0`, `fuzzy = 89.48`, `coverage = 0.5188`, `score = 46.42`, `common_only = True`; (`"Nguyễn Thị Hoa"`, `"NGUYEN THI HA"`) cho `fuzzy = 97.08`, `coverage = 0.465`, `score = 45.14`; (`"Lê Thị Hoa"`, `"LY THI HOA"`) cho `fuzzy = 93.0`, `coverage = 0.5`, `score = 46.5`, `matched = ("THI", "HOA")`, `common_only = False`; `score_names(a, b).score == score_names(b, a).score` cho cả bốn cặp; và `score_names("", "NGUYEN VAN AN", STATS, cfg)` cho mọi trường số = 0.0, `common_only = False`.
- AC10: Given `config.yaml`, `pyproject.toml` và thư mục `docs/` của repo (không cần DB), When `load_settings(environ={})`, Then `settings.screening.token_set_weight == 0.5`, `jaro_winkler_weight == 0.5`, `token_match_min == 0.90`, `token_length_band == 1`, `rare_token_max_df_rate == 0.02`, `"TNHH"` thuộc `legal_strong_terms` và `"CONG TY"` thuộc `legal_weak_terms`; `load_settings(environ={"AML__SCREENING__TOKEN_SET_WEIGHT": "0.7"})` raise `pydantic.ValidationError` có thông điệp chứa `must sum to 1`; danh sách `dependencies` của `pyproject.toml` có một mục bắt đầu bằng `rapidfuzz`; và `docs/screening.md` tồn tại, chứa cả `Soundex` lẫn `Metaphone`, chứa bốn token `HOANG`, `HONG`, `HUNG`, `HUONG` cùng mã `H520`.

## Ngoài phạm vi
- Sinh ứng viên/blocking, định danh phụ (DOB, quốc tịch, giới tính, số giấy tờ), quyết định `ALERT`/`REVIEW`/`AUTO_CLEARED`, bảng kết quả, `audit_log`, lệnh `aml screen`, đánh giá so baseline — spec 3b.
- Bản Oracle SQL `UTL_MATCH`, lưu tên chuẩn hoá xuống DB, incremental screening — spec 3c.
- Chuyển tự chữ viết không phải Latin (Cyrillic, Ả Rập, Hán tự) sang Latin: ký tự ngoài `A–Z` bị bỏ; watchlist Phase 1 chỉ có tên Latin.
- Bảng tương đương chuyển tự cho tên nước ngoài (`MUHAMMAD`/`MOHAMMED`, `ZHANG`/`CHANG`): chỉ khớp qua alias `TRANSLITERATION` có sẵn trong `watchlist_alias`, không có từ điển biến thể trong 3a.
- Xử lý riêng chữ viết tắt một ký tự (`N THI HA` khớp `NGUYEN THI HA`), biệt danh, tách/ghép token (`XIAOMING` ↔ `HSIAO MING`).
- So khớp ngữ âm (Soundex/Metaphone/Double Metaphone) và mô hình ML cho tên (Phase 7b `screening/ml/`); 3a chỉ ghi chú lý do không dùng.
- Tự động phân loại khách hàng cá nhân/pháp nhân; thêm cột `customer_type` vào schema Phase 1.
- Ghi số liệu vào README (làm ở bước demo từ lần chạy thật).

## Giả định
- Dữ liệu Phase 1 giữ các tính chất ở mục "Hiện trạng" (seed 42): tên watchlist đã chuẩn hoá, không có pháp nhân ở cả hai phía, không có `full_name` null. Các AC trên TINY chỉ cam kết cho seed 42.
- `rapidfuzz.fuzz.token_set_ratio` và `rapidfuzz.distance.JaroWinkler.similarity` (prefix weight mặc định 0.1) cho kết quả ổn định giữa các bản 3.x; số liệu trong AC đo bằng 3.14.6. Nếu bản cài khác cho số lệch ở chữ số thứ 2 thì báo lại để sửa spec, không sửa công thức.
- IDF luôn lấy từ tập **khách hàng** (kể cả khi chấm tên watchlist): token chỉ có ở watchlist (`BASHIROV`) được coi là hiếm nhất, nên thiếu nó làm điểm tụt mạnh — đúng ý "trap phải điểm thấp".
- Module `aml.screening` không import hàm private của `aml.datagen`; `strip_diacritics` được viết lại trong `normalize.py` (cùng thuật toán).
- Thông điệp lỗi bằng tiếng Anh như các module hiện có; mọi hàm của 3a là thuần hàm trừ `customer_token_stats` (chỉ đọc `customers` qua `Database.query_df`).

## Câu hỏi mở
- [x] Q1. Bỏ dấu bằng gì: `unidecode` (brief mục 1 có liệt kê) hay `unicodedata` của thư viện chuẩn? — đề xuất mặc định: `unicodedata` (NFD + bỏ `Mn`) cộng ánh xạ `đ/Đ`, không thêm `unidecode`; chỉ thêm `rapidfuzz>=3.9`. Lý do: tên watchlist đã là Latin, tên khách hàng chỉ cần bỏ dấu tiếng Việt; bớt một phụ thuộc; `unidecode` còn tự chuyển tự chữ Cyrillic/Hán theo cách khó giải thích với người phỏng vấn. Nếu muốn bám brief từng chữ thì đổi sang `unidecode` (AC3 `"Иван Петров"` khi đó trả `"IVAN PETROV"`). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q2. Bỏ token pháp nhân theo quy tắc nào khi dữ liệu không có cột phân biệt cá nhân/pháp nhân? — đề xuất mặc định: hai danh sách trong config; strong (`TNHH`, `MTV`, `CP`, `JSC`, `LTD`, `CTY`, `LLC`, `INC`, `CORP`) bỏ ở mọi vị trí, weak (`CONG TY`, `CO PHAN`, `CO`) chỉ bỏ khi tên có ít nhất một strong term; không bao giờ xoá tới rỗng. Lý do: brief ghi "bỏ CONG TY, CO..." nhưng đo trên `small` thì `CONG` là tên đệm của 5% khách hàng, còn `Tý`, `Cơ`, `Cổ` là tên người — bỏ vô điều kiện biến `Nguyễn Công Tý` thành `NGUYEN` và `Nguyễn Văn Cơ` thành `NGUYEN VAN`, tức tạo false positive mới. Hệ quả của đề xuất: `Công ty Hoà Bình` (không có strong term) giữ nguyên `CONG TY`. Phương án thay thế: bỏ vô điều kiện đúng như brief. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q3. Ký tự ngoài chữ cái (gạch nối, nháy đơn, chữ số) xử lý thế nào? — đề xuất mặc định: thay bằng khoảng trắng (`O'Brien-Smith 3rd` → `O BRIEN SMITH RD`), chữ số bị bỏ. Lý do: đúng câu "keep only letters and spaces" và khớp cách watchlist Phase 1 viết `AL HUSSEINI`; phương án thay thế là xoá hẳn (`OBRIEN`). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q4. Biểu diễn không phụ thuộc thứ tự: giữ hay bỏ token lặp? — đề xuất mặc định: giữ (đa tập đã sắp xếp, `ANH ANH DANG`). Lý do: `Đặng Anh Anh` và `Đặng Anh` là hai tên khác nhau; TINY có đúng một true hit dạng này. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q5. Công thức và tập tính IDF? — đề xuất mặc định: `ln((N + 1) / (df + 1))` với N = số dòng `customers` (không khử trùng tên), token chưa thấy có df = 0; không tính trên watchlist. Lý do: đúng câu "computed from the customer base"; làm mượt +1 tránh chia 0 và cho token chỉ có ở watchlist trọng số cao nhất. Trên `small`: `NGUYEN` 1,02; `THI` 1,36; `VAN` 2,63; chưa thấy 8,52. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q6. Cách kết hợp `token_set_ratio`, Jaro-Winkler và IDF thành một điểm? — đề xuất mặc định: `fuzzy = 0.5 * token_set_ratio + 0.5 * JW(name_key)`, `score = fuzzy * coverage` với `coverage = min` độ phủ IDF hai phía. Lý do: `token_set_ratio` trả 100 mỗi khi một tên là tập con của tên kia (`NGUYEN VAN` ⊂ `NGUYEN VAN BASHIROV`), nên phải nhân với độ phủ theo độ hiếm; lấy `min` để thiếu token hiếm ở **bất kỳ** phía nào cũng kéo điểm xuống. Phương án thay thế: trung bình cộng hai độ phủ (khoan dung hơn với tên bị thiếu tên đệm). — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q7. Ngưỡng coi hai token là một (`token_match_min`) và dải so sánh? — đề xuất mặc định: Jaro-Winkler ≥ 0.90, cùng chữ cái đầu, lệch độ dài ≤ 1. Lý do: bắt được lỗi gõ đã cài (`TRA`/`TRAN` = 0.94) mà không gộp `HOANG`/`HUONG` (đúng 0.88) hay `LE`/`LY`; hệ quả đã biết: `AN`/`ANH` (0.91) và `TRAN`/`TRANG` (0.96) bị coi là khớp, và lỗi gõ ở **chữ cái đầu** (`Nuỳnh` thay `Huỳnh`) không được bắt. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q8. Alias viết tắt chữ đầu (`N THI HA`, 604 alias trên `small`) có được khớp với tên đầy đủ không? — đề xuất mặc định: không xử lý riêng; token một ký tự là token chưa thấy nên có IDF cao nhất và làm điểm thấp (`Nguyễn Thị Hoa` × `N THI HOA` = 45.09). Lý do: mọi true hit Phase 1 đều khớp được qua tên chính hoặc alias đầy đủ; khớp theo chữ cái đầu sẽ nhân số false positive. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q9. Ghi chú Soundex/Metaphone đặt ở đâu? — đề xuất mặc định: `docs/screening.md` (file mới, 3b/3c viết tiếp vào đó), không đặt trong `docs/knowledge/`. Lý do: `docs/knowledge/` là kho tri thức cho GraphRAG Phase 8; đây là ghi chú thiết kế cho người đọc code. — Trả lời: theo đề xuất mặc định (2026-10-11).
- [x] Q10. Tên khách hàng chuẩn hoá ra rỗng (toàn ký tự không phải Latin) xử lý thế nào? — đề xuất mặc định: `normalize_name` trả `""`, `score_names` trả 0 và tên đó không được tính vào IDF; 3b sẽ không sinh ứng viên cho khách hàng này. Lý do: không có gì để so; Phase 1 không có trường hợp này (DQ framework 2c-ii không có rule cho tên rỗng — ghi là hạn chế đã biết). — Trả lời: theo đề xuất mặc định (2026-10-11).
