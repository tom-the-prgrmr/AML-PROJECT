---
id: assistant-knowledge
status: approved
approved_by: pthieu
---

# Phase 8a — Lớp tri thức trong Neo4j và LLM client sau interface (`aml rag build`)

## Bối cảnh
Phase 8 của PROJECT_BRIEF.md (mục 9, "GraphRAG investigator assistant") được tách làm năm spec: **8a (spec này)** dựng
hai nền mà bốn spec còn lại dùng chung — (1) **LLM client sau một interface** (`LLMClient`: `chat` + `embed`), hiện thực
bằng Ollama local, một `FakeLLM` tất định cho test và một lớp cache trên đĩa; (2) **lớp tri thức** trong cùng Neo4j
instance với projection của 6a: tám tài liệu tổng hợp ở `docs/knowledge/`, chia chunk, embed bằng `bge-m3`, lưu node
`Chunk` + vector index, các node `Typology` / `RedFlag` / `Procedure` / `Regulation` theo schema ràng buộc, và liên kết
`(Case)-[:MATCHES_TYPOLOGY {evidence_ids}]->(Typology)` suy tất định từ alert của case. 8b
(`specs/assistant-retrievers.md`) đọc `Chunk`, node tri thức và vector index; 8c (`specs/assistant-answering.md`) trích
dẫn `chunk_id`; 8d (`specs/memo-analysis.md`) chỉ cần `LLMClient` + cache và chạy song song được với 8b; 8e
(`specs/assistant-eval.md`) dùng `FakeLLM` và provider `fake`. Người dùng: người vận hành chạy `aml rag build`; người
phỏng vấn xem tài liệu, đồ thị tri thức và lý do của từng liên kết typology. 8a **không trả lời câu hỏi nào**: không
retriever, không prompt, không narrative. Nó không đóng, không xoá, không sửa case; Oracle / DuckDB vẫn là system of
record — mọi thứ 8a ghi vào Neo4j đều dựng lại được từ `docs/knowledge/` và các bảng case.

### Hiện trạng đã kiểm (2026-10-13, seed 42)
Chỉ đọc: không ghi gì vào Neo4j hay database. Các phép thử trên Neo4j chạy trong session `READ_ACCESS`; DuckDB mở
`read_only`; Ollama chỉ nhận lời gọi `embed` / `chat` thăm dò (không tạo, không xoá mô hình).
- **Dịch vụ** (`uv run aml status`): Oracle **UP** (`localhost:1521/FREEPDB1`, 23.26.3.0.0); Neo4j **UP**
  (`bolt://localhost:7687`, 5.26.31 Community); **Ollama UP** — người dùng chọn Docker + GPU (Q2): container
  `aml-toolkit-ollama-1`, Ollama **0.40.3**, CUDA trên GTX 1650 (3,2 GiB trống), đã có `bge-m3` và
  `qwen2.5:3b-instruct`.
- **Ollama đã đo (0.40.3)**:
  1. `POST /api/embed` với `bge-m3`, `input` là danh sách → `embeddings` là danh sách vector **1024 chiều**; phản hồi
     có thêm `model`, `total_duration`, `load_duration`, `prompt_eval_count`. Chuỗi rỗng trong `input` **không bị từ
     chối** (HTTP 200, vẫn trả một vector 1024 chiều) → client phải tự chặn văn bản rỗng.
  2. Thiếu mô hình → **HTTP 404**, body khác nhau theo endpoint: embed `{"error":"model \"<tên>\" not found, try
     pulling it first"}`, chat `{"error":"model '<tên>' not found"}` → client nhận biết bằng mã 404, không bằng chuỗi.
  3. **Cắt prompt im lặng**: một prompt 17 675 ký tự tiếng Việt (5255 token theo chính Ollama) gửi với `num_ctx: 4096`
     trả HTTP 200, `prompt_eval_count = 2050`, `done_reason = "stop"`, không có trường nào báo cắt, và mô hình trả lời
     sai (mất phần đầu prompt); với `num_ctx: 1024` → `prompt_eval_count = 514`; với `num_ctx: 16384` →
     `prompt_eval_count = 5255` và trả lời đúng. Tức `prompt_eval_count` **không** dùng được để phát hiện cắt (nó nhỏ
     hơn giới hạn cả khi đã cắt).
  4. **Cách phát hiện tin cậy**: thêm `"truncate": false` vào body của `/api/chat` → prompt vượt giới hạn bị từ chối
     bằng **HTTP 400**, body chứa `exceed_context_size_error`, `request (5255 tokens) exceeds the available context
     size (4096 tokens)`, `n_prompt_tokens`, `n_ctx`; prompt ngắn với cùng cờ đó chạy như thường. `/api/embed` với
     `"truncate": false` và đầu vào quá dài → HTTP 400 `{"error":"the input length exceeds the context length"}`.
     (Một lần trong hai lần thử, phản hồi 400 của chat mất 120 giây mới về.)
  5. `format` là JSON schema: `{"type": "object", "properties": {"answer": {"type": "string"}}, "required":
     ["answer"]}` cho nội dung `{"answer": "Hà Nội"}` (có xuống dòng và thụt lề bên trong chuỗi).
  6. `keep_alive: "0s"` gỡ mô hình ngay (`/api/ps` rỗng sau lời gọi); `keep_alive: "5m"` giữ mô hình (`expires_at`
     sau 5 phút). Hai mô hình **nằm cùng lúc trên GPU được** (`/api/ps`: `qwen2.5:3b-instruct` 2,16 GB + `bge-m3`
     664 MB VRAM, context 4096 — khớp số đo của phiên điều phối: 2,2 GB + 664 MB, 100% GPU), nhưng **không bảo đảm**:
     trong lần thăm dò, nạp `bge-m3` ngay sau một lời gọi chat đã đẩy `qwen2.5` ra, lời gọi chat kế tiếp nạp lại nó
     (8,8 giây) và từ đó cả hai cùng ở trong bộ nhớ.
  7. Thời gian (mỗi phép đo 1–2 lần): nạp `bge-m3` lần đầu 13–33 giây, embed khi đã nạp 0,04 giây cho 1–2 câu ngắn;
     chat câu ngắn khi đã nạp 2,8–10 giây, khoảng 22 token/giây và nạp `qwen2.5` lần đầu khoảng 44 giây (hai số sau
     là của phiên điều phối); chat với `num_ctx: 16384` và prompt 5255 token mất 44 giây.

  **Chưa đo**: thời gian embed cả corpus thật (chưa có tài liệu), hành vi khi GPU hết bộ nhớ.
- **Neo4j hiện có**: label `Customer` 273, `Account` 1314, `Device` 264, `Phone` 267, `Address` 265 (cỡ TINY), **không
  có node `SyncState`** (trạng thái do một lần chạy test để lại); 7 constraint và 2 index RANGE của 6a; không có label
  `Case`, `Chunk` hay label tri thức nào.
- **Vector index dùng được trên bản Community này** (đã thử, không tạo gì): `SHOW PROCEDURES` có
  `db.index.vector.queryNodes`, `db.index.vector.createNodeIndex`, `db.create.setNodeVectorProperty`; hàm
  `vector.similarity.cosine([1.0,0.0],[1.0,0.0])` trả `1.0`; câu `CREATE VECTOR INDEX … FOR (c:…) ON (c.embedding)
  OPTIONS {indexConfig: {`vector.dimensions`: 1024, `vector.similarity_function`: 'cosine'}}` và dạng `OPTIONS $opts`
  (map truyền bằng tham số) đều **qua được bước phân tích cú pháp** và bị server từ chối ở bước quyền ghi
  (`Neo.ClientError.Statement.AccessMode`) — tức session READ chặn cả lệnh schema. **Chưa đo**: tạo index thật, thời
  gian index lên `ONLINE`, điểm số trả về của `queryNodes`.
- **Case chưa có trong Neo4j**: `src/aml/graph/neo4j/extract.py` chỉ có `NODE_LABELS = (Customer, Account, Device,
  Phone, Address)`; `sync.py` không đọc bảng `cases*`. Spec này phải tự đưa case vào (Q4).
- **Đường ghi Neo4j hiện có**: duy nhất `client.run_write_file` — chỉ chạy file `.cypher` có tên bắt đầu bằng một tiền
  tố trong `client.WRITE_PREFIXES = ("schema.cypher", "sync/")`, mỗi statement một transaction tự commit; không có hàm
  nào ghi một chuỗi Cypher tuỳ ý. 6a (sync) ghi bằng đường này. 6b GDS **không ghi vào Neo4j**: nó gọi `run_read_file`
  với `procedures=settings.gds.procedures` (chỉ `gds.graph.project`, `gds.graph.drop`, `gds.*.stream`) rồi ghi đặc
  trưng về Oracle / DuckDB. Đường đọc (`run_read`) = guard `assert_read_only` (`guard/v2`) + session `READ_ACCESS` +
  timeout phía server.
- **Ba phép khẳng định của test 6a / 6b sẽ va vào lớp tri thức** (xem Q7): `tests/neo4j_gds/test_static.py` khẳng định
  `WRITE_PREFIXES == ("schema.cypher", "sync/")`; `tests/neo4j_sync/test_sync_neo4j.py` khẳng định tập khoá thuộc tính
  của **mọi** node (`MATCH (n)`) và tập tên của **mọi** constraint bằng đúng tập của 6a; ba file test khẳng định
  `settings.neo4j.read_procedures` bằng đúng 7 procedure hiện có. `sync/wipe.cypher` xoá `Customer` bằng `DELETE`
  (không `DETACH`) nên sẽ lỗi nếu còn quan hệ từ `Case` trỏ vào `Customer`; `tests/neo4j_sync/test_config_static.py`
  khẳng định file đó có đúng 12 statement.
- **Nguồn của liên kết typology** (đã có sẵn trong code, không cần bảng mới): `aml.monitoring.rules.RULES` và
  `aml.graph.network.rules.NETWORK_RULES` mang `target_typology` — `STRUCTURING` → `structuring`, `RAPID_MOVEMENT` →
  `rapid_movement`, `FAN_IN` / `FAN_OUT` / `NET_SHARED_ATTRIBUTE` / `NET_HUB` → `mule_ring`, `NET_CYCLE` →
  `round_tripping`, `HIGH_VELOCITY` và `DORMANT_REACTIVATION` → không có. Alert screening mang `details.list_type` =
  `SANCTIONS` hoặc `PEP` (ground truth dùng `sanctions_hit` / `pep_hit`). Giao dịch bằng chứng ở `alert_evidence`
  (`alert_id`, `txn_id`); `case_alerts.alert_ref` của alert RULE / NETWORK là `alert_id` dạng chuỗi, của screening là
  `<cif>:<entry_id>`.
- **Số liệu `small`** (`data/aml.duckdb`, case run 5, as_of 2026-06-30; đếm bằng truy vấn chỉ đọc theo đúng luật ở mục
  Thiết kế): 309 case trên 308 golden customer; 272 cặp (case, typology) — `mule_ring` 124, `round_tripping` 52,
  `rapid_movement` 45, `structuring` 20, `sanctions_hit` 16, `pep_hit` 15; 247 case có ít nhất một typology, 62 case
  không có (chỉ có `DORMANT_REACTIVATION` 137 item / `HIGH_VELOCITY` 15 item); 267 alert hiện hành với 1445 dòng
  `alert_evidence`.
- **Config / hạ tầng có sẵn**: `OllamaConfig` (`host`, `llm_model: qwen2.5:3b-instruct`, `embed_model: bge-m3`); chưa
  có mục `assistant:`; `aml.common.services.ollama_status` gọi `GET /api/version` bằng `urllib`; marker `oracle` /
  `neo4j` / `ollama` trong `tests/conftest.py` tự skip khi dịch vụ tắt. `pyproject.toml` không có `httpx`, `requests`
  hay `neo4j-graphrag`. `aml rag` là stub in `arrives in Phase 8` (exit 1); không test nào khẳng định stub đó.
  `Makefile` có `rag: ; $(AML) rag` và `tasks.ps1` chạy `uv run aml rag`. Chưa có `src/aml/assistant/`, chưa có
  `docs/knowledge/`. (8b sẽ thêm `neo4j-graphrag` vào `pyproject.toml` — Q10; 8a không thêm gói nào.)
- **docker-compose, service `ollama`**: image `ollama/ollama:latest` (không ghim; đang chạy là 0.40.3), `mem_limit:
  5g`, khối `deploy.resources.reservations.devices` (GPU NVIDIA) đã bỏ comment trong working tree (chưa commit) — đây
  là cấu hình người dùng đã chọn ở Q2.
- **Console Windows**: in tiếng Việt ra stdout với code page mặc định gây `UnicodeEncodeError` (đã gặp ở 7a / 7d) →
  CLI của 8a chỉ in ASCII (số đếm, ID), không in nội dung tài liệu.

### Interface đề xuất (hợp đồng chung cho 8b / 8c / 8d / 8e)
```python
# src/aml/common/config.py
class LlmCacheConfig(BaseModel):
    enabled: bool
    dir: str  # mặc định data/llm_cache (data/ đã git-ignore)


class EmbeddingConfig(BaseModel):
    dimensions: int  # 1..4096; bge-m3 = 1024
    batch_size: int  # số văn bản mỗi lần gọi /api/embed; 1..256


class KnowledgeConfig(BaseModel):
    dir: str  # mặc định docs/knowledge
    chunk_max_chars: int  # >= 200


class AssistantConfig(BaseModel):  # 8b..8e thêm mục con của riêng mình, không đổi các khoá dưới đây
    provider: Literal["ollama", "fake"]
    request_timeout_seconds: float  # > 0
    num_ctx: int  # cửa sổ ngữ cảnh gửi cho Ollama ở mọi lời gọi chat; >= 512
    keep_alive_chat: str  # gửi nguyên văn cho Ollama
    keep_alive_embed: str
    cache: LlmCacheConfig
    embedding: EmbeddingConfig
    knowledge: KnowledgeConfig
    vector_procedures: list[
        str
    ]  # allow-list riêng cho truy vấn vector; KHÔNG gộp vào neo4j.read_procedures


class Settings(BaseModel):
    ...
    assistant: AssistantConfig


# src/aml/assistant/llm.py  (không import neo4j, không import driver database)
TEMPERATURE = 0


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(RuntimeError): ...


@runtime_checkable
class LLMClient(Protocol):
    chat_model: str
    embed_model: str
    seed: int
    num_ctx: int

    def chat(
        self, messages: Sequence[ChatMessage], *, json_schema: Mapping[str, Any] | None = None
    ) -> str: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


Transport = Callable[
    [str, Mapping[str, Any]], Mapping[str, Any]
]  # (đường dẫn, body) -> JSON đã parse


class OllamaClient:
    def __init__(
        self,
        host: str,
        chat_model: str,
        embed_model: str,
        *,
        seed: int,
        num_ctx: int = 4096,
        timeout: float = 300.0,
        keep_alive_chat: str = "5m",
        keep_alive_embed: str = "5m",
        batch_size: int = 16,
        transport: Transport | None = None,  # None -> HTTP POST bằng urllib tới host
    ) -> None: ...


class FakeLLM:
    calls: list[
        dict[str, Any]
    ]  # {"kind": "chat", "messages", "json_schema"} | {"kind": "embed", "texts"}

    def __init__(
        self,
        *,
        dim: int = 1024,
        replies: Sequence[str] | None = None,  # trả lần lượt cho các lời gọi chat
        responder: Callable[[Sequence[ChatMessage], Mapping[str, Any] | None], str] | None = None,
        chat_model: str = "fake-chat",
        embed_model: str = "fake-embed",
        seed: int = 0,
        num_ctx: int = 4096,  # chỉ để vào khoá cache; FakeLLM không giới hạn độ dài
    ) -> None: ...


class CachedLLM:  # bọc bất kỳ LLMClient nào; cùng chat_model / embed_model / seed / num_ctx với client bên trong
    hits: int
    misses: int

    def __init__(self, inner: LLMClient, cache_dir: Path) -> None: ...


def fake_embedding(text: str, dim: int) -> list[float]: ...
def cache_key(kind: str, model: str, payload: Mapping[str, Any]) -> str: ...  # 64 ký tự hex
def get_llm(settings: Settings, *, cached: bool | None = None) -> LLMClient: ...


# cached=None -> settings.assistant.cache.enabled; không gọi dịch vụ nào lúc khởi tạo

# Hợp đồng ổn định của thông điệp LLMError (8c / 8d so khớp bằng chuỗi con; không đổi nếu không sửa spec này):
#   "not valid JSON"                     chat có json_schema mà nội dung không parse được
#   "prompt exceeds the context window"  Ollama từ chối đầu vào dài hơn cửa sổ ngữ cảnh (không bao giờ cắt im lặng)
#   "cannot embed an empty text"         embed nhận chuỗi rỗng / toàn khoảng trắng
#   "is not available on Ollama"         thiếu mô hình


# src/aml/assistant/knowledge/model.py  (thuần Python)
KNOWLEDGE_VERSION = "knowledge/v1"
VECTOR_INDEX = "chunk_embedding"
ENTITY_KEYS = {
    "Typology": "typology_id",
    "RedFlag": "red_flag_id",
    "Procedure": "procedure_id",
    "Regulation": "regulation_id",
}
ID_PATTERNS = {
    "Typology": r"[a-z][a-z0-9_]{2,39}",
    "RedFlag": r"RF-\d{3}",
    "Procedure": r"PROC-\d{3}",
    "Regulation": r"REG-\d{3}",
}
RELATIONS = {  # kiểu quan hệ -> (label nguồn, label đích); không có kiểu nào khác
    "HAS_RED_FLAG": ("Typology", "RedFlag"),
    "INVESTIGATED_BY": ("Typology", "Procedure"),
    "GOVERNED_BY": ("Typology", "Regulation"),
    "REQUIRED_BY": ("Procedure", "Regulation"),
}
DOC_TYPES = ("TYPOLOGY", "SOP", "CHECKLIST", "POLICY")
DOC_ID_PATTERN = r"KB-[A-Z]{2,4}-\d{3}"
CHUNK_ID_PATTERN = r"KB-[A-Z]{2,4}-\d{3}#\d{3}"
TYPOLOGY_IDS = (
    "structuring",
    "rapid_movement",
    "mule_ring",
    "round_tripping",
    "sanctions_hit",
    "pep_hit",
)
SCREENING_LIST_TYPOLOGY = {"SANCTIONS": "sanctions_hit", "PEP": "pep_hit"}


class KnowledgeError(RuntimeError): ...


@dataclass(frozen=True)
class Entity:
    label: str
    id: str
    name: str
    doc_id: str  # tài liệu định nghĩa nó


@dataclass(frozen=True)
class Relation:
    type: str
    source: str  # id thực thể
    target: str


@dataclass(frozen=True)
class KnowledgeDoc:
    doc_id: str  # = doc number, vd "KB-TYP-001"
    title: str
    doc_type: str
    version: str
    effective_date: date
    language: str  # "vi" | "en"
    source_file: str  # tên file
    sha256: str  # của toàn bộ file


@dataclass(frozen=True)
class Chunk:
    chunk_id: str  # f"{doc_id}#{seq:03d}", seq từ 1 trong từng tài liệu
    doc_id: str
    seq: int
    heading: str
    text: str
    mentions: tuple[str, ...]  # id thực thể, tăng dần


@dataclass(frozen=True)
class Corpus:
    docs: tuple[KnowledgeDoc, ...]  # theo doc_id
    chunks: tuple[Chunk, ...]  # theo (doc_id, seq)
    entities: tuple[Entity, ...]  # theo (label, id)
    relations: tuple[Relation, ...]  # theo (type, source, target)
    sha256: str  # của danh sách (doc_id, sha256) đã sắp xếp


# src/aml/assistant/knowledge/docs.py  (thuần: chỉ đọc file)
def split_section(paragraphs: Sequence[str], max_chars: int) -> list[str]: ...
def embed_text(
    doc: KnowledgeDoc, chunk: Chunk
) -> str: ...  # f"{doc.title} — {chunk.heading}\n{chunk.text}"
def load_corpus(directory: Path, *, max_chars: int) -> Corpus: ...  # KnowledgeError nếu sai


# src/aml/assistant/knowledge/matches.py  (chỉ cần Database)
@dataclass(frozen=True)
class TypologyMatch:
    case_id: str
    typology_id: str
    rule_ids: tuple[str, ...]  # tăng dần, không trùng
    alert_keys: tuple[str, ...]  # item_key, tăng dần
    evidence_ids: tuple[str, ...]  # txn_id và alert_ref của screening, tăng dần
    reason: str


def rule_typologies() -> dict[str, str]: ...  # từ RULES + NETWORK_RULES, bỏ rule không có target
def derive_matches(
    db: Database,
) -> list[TypologyMatch]: ...  # theo (case_id, typology_id); không ghi gì


# src/aml/assistant/knowledge/build.py
@dataclass(frozen=True)
class BuildResult:
    build_id: int
    documents: int
    chunks: int
    embedded: int  # số văn bản thực sự gửi tới client embed (cache miss)
    cache_hits: int
    entities: dict[str, int]  # 4 khoá = label
    relations: int  # 4 kiểu trong RELATIONS
    mentions: int
    cases: int
    matches: int
    matches_skipped: int  # typology không có trong corpus
    cases_unlinked: int  # case mà golden customer không có node Customer
    seconds: float


@dataclass(frozen=True)
class KnowledgeStatus:
    build_id: int
    built_at: datetime
    embed_model: str
    index_state: str  # "ONLINE" | ...
    index_dimensions: int
    documents: int
    chunks: int
    chunks_without_embedding: int
    entities: dict[str, int]
    cases: int
    matches: int
    cases_unlinked: int
    corpus_in_sync: bool  # corpus_sha256 đã lưu == sha256 của thư mục hiện tại
    cases_in_sync: bool  # case_run_id đã lưu == MAX(run_id) của case_runs


def build_knowledge(
    db: Database,
    settings: Settings,
    llm: LLMClient,
    *,
    full: bool = False,
    actor: str | None = None,
) -> BuildResult: ...
def knowledge_status(db: Database, settings: Settings) -> KnowledgeStatus: ...  # chỉ đọc
```
- **Mô hình đồ thị tri thức** — 8b / 8c / 8e dựa vào đúng các tên dưới đây:

  | Node | Khoá (duy nhất) | Thuộc tính khác |
  |---|---|---|
  | `Document` | `doc_id` | `title`, `doc_type`, `version`, `effective_date` (Date), `language`, `source_file`, `sha256`, `is_synthetic` (bool), `build_id` |
  | `Chunk` | `chunk_id` | `doc_id`, `seq`, `heading`, `text`, `embedding` (danh sách float, `dimensions` phần tử), `doc_version`, `effective_date` (Date), `language`, `build_id` |
  | `Typology` | `typology_id` | `name`, `doc_id`, `rule_ids` (danh sách rule_id trỏ tới nó, tăng dần), `build_id` |
  | `RedFlag` | `red_flag_id` | `name`, `doc_id`, `build_id` |
  | `Procedure` | `procedure_id` | `name`, `doc_id`, `build_id` |
  | `Regulation` | `regulation_id` | `name`, `doc_id`, `is_synthetic` (bool), `build_id` |
  | `Case` | `case_id` | `golden_customer_id`, `status`, `window_start`, `first_alert_ts`, `last_alert_ts` (LocalDateTime), `alerts`, `sources`, `case_run_id`, `build_id` |
  | `KnowledgeState` | `name` (= `'knowledge'`) | `build_id`, `built_at`, `embed_model`, `dimensions`, `corpus_sha256`, `case_run_id`, `source_backend`, `version` |

  | Quan hệ | Hướng | Thuộc tính |
  |---|---|---|
  | `PART_OF` | `(Chunk)->(Document)` | `build_id` |
  | `NEXT` | `(Chunk)->(Chunk)` kế tiếp trong cùng tài liệu | `build_id` |
  | `MENTIONS` | `(Chunk)->(Typology / RedFlag / Procedure / Regulation)` | `build_id` |
  | `DEFINES` | `(Document)->(thực thể)` | `build_id` |
  | `HAS_RED_FLAG`, `INVESTIGATED_BY`, `GOVERNED_BY`, `REQUIRED_BY` | theo `RELATIONS` | `build_id` |
  | `ABOUT` | `(Case)->(Customer)` (node của 6a, nối theo `golden_customer_id`) | `build_id` |
  | `MATCHES_TYPOLOGY` | `(Case)->(Typology)` | `evidence_ids`, `alert_keys`, `rule_ids` (danh sách chuỗi), `reason`, `build_id` |

  Vector index: tên **`chunk_embedding`**, trên `(:Chunk).embedding`, `vector.similarity_function = 'cosine'`,
  `vector.dimensions = assistant.embedding.dimensions`. Truy vấn (8b): `CALL db.index.vector.queryNodes(
  'chunk_embedding', $k, $vector) YIELD node, score` qua `run_read(…, procedures=settings.assistant.vector_procedures)`.
  **`chunk_id` là ID trích dẫn**: dạng `KB-TYP-001#003` (khớp `CHUNK_ID_PATTERN`); ID thực thể trích dẫn được là giá
  trị khoá của nó (`structuring`, `RF-001`, `PROC-001`, `REG-001`). Không node tri thức nào và không node `Case` nào
  chứa tên, số giấy tờ, điện thoại, email, địa chỉ hay memo.
- `config.yaml`, mục mới (mục `ollama:` giữ nguyên ba khoá hiện có):
  ```yaml
  assistant:                   # Phase 8a: LLM client, cache, knowledge layer (aml rag build)
    provider: ollama           # ollama | fake (fake = FakeLLM; tests and dry demos only)
    request_timeout_seconds: 300
    num_ctx: 4096              # context window of every chat call; a longer prompt is an error, never cut
    keep_alive_chat: 5m        # how long Ollama keeps the chat model loaded
    keep_alive_embed: 5m       # both models fit the 4 GB GPU together (measured); 0s unloads after each call
    cache: {enabled: true, dir: data/llm_cache}
    embedding: {dimensions: 1024, batch_size: 16}
    knowledge: {dir: docs/knowledge, chunk_max_chars: 1200}
    vector_procedures: [db.index.vector.queryNodes]
  ```
- File mới: `src/aml/assistant/__init__.py`, `llm.py`, gói `knowledge/` (`model.py`, `docs.py`, `matches.py`,
  `build.py`); Cypher `src/aml/graph/neo4j/cypher/knowledge/` (`schema.cypher`, `vector_index.cypher`,
  `merge_documents.cypher`, `merge_entities_*.cypher`, `merge_chunks.cypher`, `merge_relations_*.cypher`,
  `merge_cases.cypher`, `merge_matches.cypher`, `sweep.cypher`, `save_state.cypher`, `wipe.cypher`) và
  `read/knowledge_state.cypher`, `read/knowledge_counts.cypher`; SQL `sql/common/assistant/case_items.sql`,
  `sql/common/assistant/case_evidence.sql`; tám file ở `docs/knowledge/`; test ở `tests/assistant/`. **Không DDL mới.**
  8a không thêm gói phụ thuộc nào (client HTTP dùng `urllib`); `neo4j-graphrag` do 8b thêm (Q10) — 8a không dùng và
  không cấm.
- CLI: `aml rag` thành nhóm lệnh: `aml rag build [--full] [--dry-run]`, `aml rag status`. `Makefile`: `rag: ; $(AML)
  rag build`; `tasks.ps1`: target `rag` (và bước `rag` trong `all`) chạy `uv run aml rag build`.
- **Sửa kéo theo ở phần đã duyệt của 6a / 6b** (người dùng đồng ý, 2026-10-13 — Q7): (1) `client.WRITE_PREFIXES` thành
  `("schema.cypher", "sync/", "knowledge/")` và `tests/neo4j_gds/test_static.py` sửa bộ giá trị mong đợi; (2)
  `sync/wipe.cypher` thêm một statement đầu file xoá quan hệ `ABOUT` (12 → 13 statement) và
  `tests/neo4j_sync/test_config_static.py` sửa `12` → `13`, `[:6]` → `[:7]`; (3) ba chỗ test đang gọi `sync/wipe.cypher`
  để dọn Neo4j (`tests/neo4j_sync/conftest.py`, `tests/neo4j_gds/test_cli.py`, `tests/neo4j_queries/helpers.py`) gọi
  thêm `knowledge/wipe.cypher` trước đó. `settings.neo4j.read_procedures` **không đổi**.

### Thiết kế (đã xác nhận ở Câu hỏi mở)
- **`OllamaClient`** — chỉ nói chuyện với `settings.ollama.host`; không có nhà cung cấp hosted nào, không có khoá API.
  - `chat`: `POST /api/chat` với body đúng các khoá `model` (= `chat_model`), `messages` (danh sách `{role, content}`
    đúng thứ tự), `stream: false`, `truncate: false`, `options: {temperature: 0, seed: <seed>, num_ctx: <num_ctx>}`,
    `keep_alive` (= `keep_alive_chat`); có `json_schema` thì thêm `format: <json_schema>`. `truncate: false` làm
    Ollama từ chối (HTTP 400) thay vì cắt prompt im lặng — đã đo. Trả `response["message"]["content"]`. Có `json_schema` mà nội dung
    không parse được bằng `json.loads` → `LLMError` chứa `not valid JSON`. Client **không** kiểm nội dung theo schema
    (việc của nơi gọi — 8c / 8d).
  - `embed`: danh sách rỗng → `[]`, không gọi HTTP. Một phần tử rỗng hoặc chỉ có khoảng trắng → `LLMError` chứa
    `cannot embed an empty text` (áp cho cả `FakeLLM` và `CachedLLM`). Còn lại chia theo `batch_size`, mỗi lô một
    `POST /api/embed` với body `model` (= `embed_model`), `input` (danh sách chuỗi), `truncate: false`, `keep_alive`
    (= `keep_alive_embed`); nối `response["embeddings"]` theo thứ tự. Số vector khác số văn bản, hoặc các vector không
    cùng độ dài → `LLMError` chứa `unexpected Ollama response`.
  - Lỗi của transport mặc định: không kết nối được / quá `timeout` → `aml.common.db.ServiceUnavailableError` chứa
    `cannot reach Ollama at <host>`; HTTP 404 → `LLMError` chứa `model '<tên>' is not available on Ollama` và `ollama
    pull <tên>`; HTTP 400 có body chứa `exceed_context_size_error` hoặc `exceeds the context length` → `LLMError` chứa `prompt
    exceeds the context window` kèm nguyên văn thông điệp của Ollama (có số token và giới hạn); mã HTTP khác 200
    còn lại → `LLMError` chứa `Ollama returned HTTP <mã>`; body thiếu khoá mong đợi →
    `LLMError` chứa `unexpected Ollama response`. Client **không bao giờ tự `pull` mô hình**.
- **`FakeLLM`** — tất định, không mạng, không đồng hồ, không ngẫu nhiên.
  - `fake_embedding(text, dim)`: `tokens = re.findall(r"\w+", text.casefold())`; mỗi token cộng 1 vào vị trí
    `int.from_bytes(sha256(token UTF-8).digest()[:8], "big") % dim`; chia cho chuẩn L2. Không có token nào → vector có
    phần tử đầu `1.0`, còn lại `0.0`. (Hai văn bản chung nhiều từ có cosine cao — đủ để 8b test xếp hạng.)
  - `chat`: có `responder` → trả `responder(messages, json_schema)`; không thì có `replies` → trả phần tử kế tiếp, hết
    phần tử → `LLMError` chứa `no scripted reply left`; không có cả hai → `"{}"` khi có `json_schema`, ngược lại
    `"FAKE-" + sha256(JSON chuẩn tắc của messages)[:12]`. Mỗi lời gọi thêm một phần tử vào `calls`.
- **`CachedLLM`** — `cache_key(kind, model, payload) = sha256(json.dumps({"kind": kind, "model": model, "payload":
  payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()`. Chat: `kind =
  "chat"`, `model = inner.chat_model`, `payload = {"messages": [...], "json_schema": <schema hoặc null>, "seed":
  inner.seed, "temperature": 0, "num_ctx": inner.num_ctx}`. Embed: **mỗi văn bản một khoá**, `kind = "embed"`, `model = inner.embed_model`,
  `payload = {"text": <văn bản>}`. File: `<cache_dir>/<kind>/<key>.json` (UTF-8) chứa `key`, `kind`, `model`,
  `payload`, `response`; ghi qua file tạm cùng thư mục rồi `os.replace` (8b và 8d chạy song song không đọc phải file
  dở). `embed` chỉ gửi các văn bản chưa có trong cache cho client bên trong, **một** lời gọi, không trùng lặp, giữ
  thứ tự xuất hiện đầu tiên; kết quả trả đúng thứ tự đầu vào. File cache hỏng (không phải JSON, thiếu `response`) được
  coi là miss và bị ghi đè. `hits` / `misses` đếm theo từng văn bản (embed) và từng lời gọi (chat). Lỗi của client bên
  trong không được ghi vào cache.
- **`get_llm`**: `provider = "ollama"` → `OllamaClient(settings.ollama.host, settings.ollama.llm_model,
  settings.ollama.embed_model, seed=settings.seed, num_ctx=settings.assistant.num_ctx, timeout=…, keep_alive_*=…,
  batch_size=…)`; `"fake"` →
  `FakeLLM(dim=settings.assistant.embedding.dimensions, seed=settings.seed, num_ctx=settings.assistant.num_ctx)`; bọc `CachedLLM(…,
  settings.path(settings.assistant.cache.dir))` khi cache bật.
- **Tài liệu `docs/knowledge/`** — mọi file `*.md` trực tiếp trong thư mục là một tài liệu (không đệ quy, không có
  README ở đó). Mỗi file mở đầu bằng frontmatter YAML:
  ```markdown
  ---
  doc_number: KB-TYP-001
  title: Chia nhỏ giao dịch tiền mặt (structuring)
  doc_type: TYPOLOGY
  version: "1.0"
  effective_date: 2026-01-01
  language: vi
  defines:
    - {label: Typology, id: structuring, name: Chia nhỏ giao dịch tiền mặt}
    - {label: RedFlag, id: RF-001, name: Nhiều lần nộp tiền mặt ngay dưới ngưỡng báo cáo}
  relations:
    - {from: structuring, type: HAS_RED_FLAG, to: RF-001}
  ---
  # Chia nhỏ giao dịch tiền mặt (structuring)

  ## Dấu hiệu nhận biết {RF-001 structuring}
  ```
  - Bắt buộc: `doc_number` (khớp `DOC_ID_PATTERN`, duy nhất trong thư mục; chính là `doc_id`), `title`, `doc_type`
    (một trong `DOC_TYPES`), `version` (chuỗi), `effective_date` (ngày ISO), `language` (`vi` | `en`). Tuỳ chọn:
    `defines`, `relations`.
  - **Thực thể và quan hệ khai báo trong frontmatter, không do LLM trích** (Q3). Mỗi thực thể được định nghĩa ở đúng
    một tài liệu; quan hệ được tham chiếu thực thể của tài liệu khác (kiểm sau khi nạp hết thư mục).
  - **Chunk**: dòng `# ` là tiêu đề (bỏ qua); mỗi dòng `## ` mở một section; `### ` trở xuống nằm trong văn bản. Phần
    trước section đầu tiên, nếu có chữ, là một section có `heading = title` và không có mention. Cuối dòng `## ` có thể
    có `{id id}` (cách nhau bằng khoảng trắng hoặc dấu phẩy) — phần ngoặc bị cắt khỏi `heading`, và **mọi chunk của
    section đó MENTIONS các thực thể này**. Đoạn văn = khối cách nhau bằng dòng trống, đã bỏ khoảng trắng hai đầu.
    `split_section`: gom tuần tự các đoạn, nối bằng `"\n\n"`, sang chunk mới khi thêm đoạn kế sẽ vượt `max_chars`; một
    đoạn dài hơn `max_chars` bị cắt thành các khúc đúng `max_chars` ký tự (khúc cuối ngắn hơn). Section không có đoạn
    nào thì không sinh chunk. `seq` đánh từ 1 theo thứ tự xuất hiện trong tài liệu.
  - **Lỗi (`KnowledgeError`, thông điệp bắt đầu bằng tên file)**: thiếu frontmatter hoặc thiếu khoá → `missing metadata
    '<khoá>'`; `doc_number` sai mẫu → `invalid doc_number`; trùng → `duplicate doc_number <id>`; `doc_type` lạ →
    `unknown doc_type`; ngày sai → `invalid effective_date`; label ngoài bốn label → `unknown label '<x>'`; id sai mẫu
    của label → `invalid id '<x>' for <Label>`; định nghĩa hai lần → `entity <id> is defined twice`; kiểu quan hệ lạ →
    `unknown relation type '<x>'`; sai cặp label → `relation <TYPE> must go from <A> to <B>`; id chưa định nghĩa (trong
    `relations` hoặc trong ngoặc của heading) → `unknown entity '<id>'`; thực thể không được chunk nào mention →
    `entity <id> is never mentioned`; tài liệu không sinh chunk nào → `no content`; thư mục không có file `.md` nào →
    `no knowledge documents in <thư mục>`.
  - **Tám tài liệu của repo** (đều `language: vi`, `version: "1.0"`, `effective_date: 2026-01-01`, do ta viết, đoạn mở
    đầu của mỗi tài liệu chứa nguyên văn `Tài liệu tổng hợp (synthetic)`):

    | `doc_number` | File | `doc_type` | Định nghĩa |
    |---|---|---|---|
    | `KB-TYP-001` | `typology-structuring.md` | TYPOLOGY | `structuring`; `RF-001`–`RF-003` |
    | `KB-TYP-002` | `typology-rapid-movement.md` | TYPOLOGY | `rapid_movement`; `RF-004`–`RF-006` |
    | `KB-TYP-003` | `typology-mule-ring.md` | TYPOLOGY | `mule_ring`; `RF-007`–`RF-010` |
    | `KB-TYP-004` | `typology-round-tripping.md` | TYPOLOGY | `round_tripping`; `RF-011`–`RF-013` |
    | `KB-TYP-005` | `typology-sanctions-pep.md` | TYPOLOGY | `sanctions_hit`, `pep_hit`; `RF-014`–`RF-016` |
    | `KB-SOP-001` | `sop-investigation.md` | SOP | `PROC-001`–`PROC-006` |
    | `KB-RFC-001` | `red-flag-checklist.md` | CHECKLIST | `RF-017`, `RF-018` (tài khoản ngủ đông hoạt động lại; tần suất cao bất thường) và nhắc lại cả 18 red flag |
    | `KB-POL-001` | `policy-aml-internal.md` | POLICY | `REG-001`–`REG-003` (quy định nội bộ tổng hợp — Q6) |

    Tổng: 6 `Typology`, 18 `RedFlag`, 6 `Procedure`, 3 `Regulation`. Mỗi tài liệu typology có các section: mô tả, cách
    hệ thống phát hiện (nêu **nguyên văn `rule_id`** trỏ tới typology đó và **tên khoá config** của ngưỡng, không chép
    con số ngưỡng — để tài liệu không lệch `config.yaml`), dấu hiệu nhận biết, hướng điều tra (dẫn `PROC-…`), trường
    hợp lành tính dễ nhầm. Mỗi typology có ít nhất 2 `HAS_RED_FLAG`, 1 `INVESTIGATED_BY` và 1 `GOVERNED_BY`; mỗi
    `Procedure` có ít nhất 1 `REQUIRED_BY`. Tài liệu không chứa tên người, số tài khoản hay dữ liệu khách hàng.
- **`derive_matches`** — đọc `case_alerts_current` (chỉ dòng `status = 'ACTIVE'`, `case_id` khác null; case ở mọi
  trạng thái `OPEN` / `REOPENED` / `CLOSED`) và `alert_evidence`. Typology của một item: nguồn `RULE` / `NETWORK` →
  `rule_typologies()[rule_id]` (không có → item bị bỏ qua); nguồn `SCREENING` →
  `SCREENING_LIST_TYPOLOGY[details.list_type]` (cả `SCREENING_ALERT` lẫn `SCREENING_REVIEW`; `list_type` khác → bỏ
  qua). Gom theo (`case_id`, typology): `rule_ids`, `alert_keys` (= `item_key`) không trùng, tăng dần; `evidence_ids`
  = mọi `txn_id` của `alert_evidence` có `alert_id = alert_ref` (item RULE / NETWORK) cộng `alert_ref` của item
  screening (`<cif>:<entry_id>`), không trùng, tăng dần; `reason = "{n} alert(s) from rule(s) {rule_ids nối bằng ', '}
  map to typology {typology_id}"` với `n` = số `alert_keys`. Chưa có case run → danh sách rỗng. Hàm không ghi gì.
- **`build_knowledge`** — thứ tự cố định, để lỗi xảy ra trước khi Neo4j bị đụng tới càng nhiều càng tốt:
  1. `load_corpus(settings.path(knowledge.dir), max_chars=knowledge.chunk_max_chars)`.
  2. `llm.embed([embed_text(doc, chunk) …])` — một lời gọi cho cả corpus (client tự chia lô; `CachedLLM` chỉ gửi phần
     thiếu). Vector nào dài khác `embedding.dimensions` → `KnowledgeError` chứa `embedding has <n> dimensions, expected
     <m>`. Tới đây chưa có gì được ghi.
  3. Mở driver (`shared_driver`). Nếu index `chunk_embedding` đã có với số chiều khác config và `full = False` →
     `KnowledgeError` chứa `vector index chunk_embedding has <n> dimensions but assistant.embedding.dimensions is <m>:
     run aml rag build --full`. `full = True` → chạy `knowledge/wipe.cypher` (xoá theo lô: quan hệ rồi node của
     `Case`, `Chunk`, `Document`, bốn label thực thể, `KnowledgeState`; `DROP` index vector và các constraint của lớp
     tri thức; **không đụng** label / quan hệ nào của 6a ngoài `ABOUT`).
  4. `knowledge/schema.cypher` (constraint duy nhất cho 8 khoá ở bảng trên, `IF NOT EXISTS`) và
     `knowledge/vector_index.cypher` (`CREATE VECTOR INDEX chunk_embedding IF NOT EXISTS … OPTIONS $options`).
  5. `build_id` = `KnowledgeState.build_id` hiện có + 1 (chưa có → 1). `MERGE` theo khoá và `SET` thuộc tính +
     `build_id` cho `Document`, thực thể, `Chunk` (kèm `embedding`), rồi các quan hệ; `Typology.rule_ids` lấy từ
     `rule_typologies()` (hai typology screening có `rule_ids = []`).
  6. `derive_matches(db)` → `MERGE` `Case` cho **mọi** dòng `cases_current` (kể cả case không có typology), `ABOUT`
     tới `Customer` cùng `golden_customer_id` nếu node đó tồn tại, `MATCHES_TYPOLOGY` tới `Typology` nếu typology có
     trong corpus (không có → cộng vào `matches_skipped`). Database chưa có case run → `cases = 0`, không lỗi.
  7. `knowledge/sweep.cypher`: xoá mọi node / quan hệ của lớp tri thức và của `Case` có `build_id` khác lần này (tài
     liệu bị gỡ, chunk thừa, case không còn trong `cases_current`).
  8. `CALL db.awaitIndexes` (index lên `ONLINE` trước khi trả), `knowledge/save_state.cypher`, rồi **một** dòng
     `audit_log`: `module = 'assistant'`, `entity_type = 'knowledge_build'`, `entity_id = <build_id>`, `decision =
     'KNOWLEDGE_BUILD_COMPLETED'`, `version = 'knowledge/v1'`, `reason` = `Built the knowledge layer: {documents}
     document(s), {chunks} chunk(s), {cases} case(s), {matches} typology match(es).`, `details` = các trường của
     `BuildResult` (trừ `seconds`) cộng `embed_model`, `dimensions`, `corpus_sha256`, `case_run_id`, `full`.
  - Mọi lệnh ghi đi qua `client.run_write_file` với file dưới `knowledge/`; không có chuỗi Cypher ghi nào nằm trong mã
    Python. Chạy lại không sinh trùng (mọi thứ là `MERGE` theo khoá có constraint). Lỗi giữa chừng: chạy lại là sửa
    được; `KnowledgeState` chỉ đổi ở bước 8.
  - `build_knowledge` không yêu cầu projection của 6a đã sync: thiếu `Customer` thì `Case` vẫn được tạo, chỉ thiếu
    `ABOUT` và được đếm ở `cases_unlinked`. Sau `aml graph sync --full` (wipe xoá `ABOUT`), chạy lại `aml rag build`
    để nối lại — không tốn lời gọi embed nào vì đã có cache.
- **CLI** (chỉ in ASCII):
  - `aml rag build --dry-run`: chỉ bước 1, không cần dịch vụ nào, không ghi gì; in `dry_run documents={n} chunks={n}
    typologies={n} red_flags={n} procedures={n} regulations={n} relations={n} mentions={n}`, exit 0. `--dry-run`
    đi cùng `--full` → exit 2.
  - `aml rag build [--full]`: in một dòng `build_id={..} documents={..} chunks={..} embedded={..} cache_hits={..}
    typologies={..} red_flags={..} procedures={..} regulations={..} relations={..} mentions={..} cases={..}
    matches={..} matches_skipped={..} cases_unlinked={..} seconds={..}`, exit 0; `provider = fake` thì thêm một dòng
    stderr `FAKE embeddings in use: retrieval results are not meaningful`.
  - `aml rag status`: in `build_id`, `built_at`, `embed_model`, `index`, `dimensions`, `documents`, `chunks`,
    `chunks_without_embedding`, bốn số thực thể, `cases`, `matches`, `cases_unlinked`, `corpus_in_sync`,
    `cases_in_sync` dạng `khoá=giá trị`; chưa build → stderr `knowledge layer not built: run aml rag build`, exit 1.
  - `KnowledgeError` / `LLMError` → stderr, exit 1; Neo4j không kết nối được → stderr `neo4j not available: …`, exit 1;
    Ollama không kết nối được → stderr `ollama not available: …`, exit 1 (nếu mọi embedding đã có trong cache thì
    lệnh chạy được khi Ollama tắt).
- **GPU 4 GB** (GTX 1650): đã đo hai mô hình nằm cùng lúc trên GPU (2,16 GB + 664 MB) nên mặc định
  `keep_alive_embed: 5m` — câu hỏi của 8b không phải nạp lại `bge-m3` (13–33 giây) mỗi lần. Vì việc cùng nằm không
  được bảo đảm (đã thấy một lần Ollama đẩy mô hình chat ra khi nạp mô hình embedding), 8a vẫn (a) embed cả corpus trong
  một đợt ở bước 2, trước mọi lời gọi chat, và (b) giữ mọi embedding trong cache để các lần build sau không nạp
  `bge-m3`. Máy ít VRAM hơn đặt `AML__ASSISTANT__KEEP_ALIVE_EMBED=0s`. `num_ctx` lớn hơn 4096 tốn thêm VRAM và thời
  gian (16384: 44 giây cho một prompt 5255 token) — đổi bằng config, không sửa code.
- **Test**: mặc định dùng `FakeLLM` và không cần dịch vụ nào. Test cần Neo4j đánh `@pytest.mark.neo4j`, dùng
  `FakeLLM(dim=64)` + `AML__ASSISTANT__EMBEDDING__DIMENSIONS=64`, cache ở `tmp_path`, và dọn bằng
  `knowledge/wipe.cypher` + `sync/wipe.cypher` trên Neo4j dev (cùng quy ước với 6a: test xoá dữ liệu Neo4j dev; sau
  khi chạy pytest phải `aml graph sync` và `aml rag build` lại). Chỉ test của AC11 đánh `@pytest.mark.ollama`.

## Tiêu chí nghiệm thu
<!-- settings = load_settings(environ={"DB_BACKEND": "duckdb"}) trừ khi nêu khác. `duck` = fixture DuckDB tạm.
MINI-C, `run_cases`, `add_r5` = tests/cases/helpers.py (specs/case-consolidation.md): alert R1 STRUCTURING A01 (T01),
  R2 RAPID_MOVEMENT A02 (T05, T06), R3 FAN_OUT A01 (T07), R4 DORMANT_REACTIVATION A03 (T02, T03), N1 NET_CYCLE
  A01>A03>A04 (T02, T03, T04), S1 C02/WL1 SANCTIONS ALERT, S2 C05/WL2 PEP REVIEW; 5 case.
  N1_KEY = 'NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00'.
MINI-K = thư mục tạm có đúng hai file:
  kb-a.md: frontmatter doc_number KB-TYP-901, title 'Structuring thử nghiệm', doc_type TYPOLOGY, version "1.0",
    effective_date 2026-01-01, language vi, defines [Typology structuring 'Chia nhỏ giao dịch', RedFlag RF-901 'Nộp
    tiền mặt sát ngưỡng'], relations [structuring HAS_RED_FLAG RF-901, structuring INVESTIGATED_BY PROC-901]; thân:
    '# Structuring thử nghiệm', đoạn 'Đoạn mở đầu.', '## Mô tả {structuring}', đoạn 'Khách hàng chia nhỏ tiền mặt.',
    '## Dấu hiệu {RF-901 structuring}', đoạn 'Nộp tiền nhiều lần dưới ngưỡng.'
  kb-b.md: doc_number KB-SOP-901, title 'SOP thử nghiệm', doc_type SOP, version "2.1", effective_date 2026-02-01,
    language vi, defines [Procedure PROC-901 'Xác minh nguồn tiền', Regulation REG-901 'Quy định thử nghiệm'],
    relations [PROC-901 REQUIRED_BY REG-901]; thân: '# SOP thử nghiệm', '## Bước 1 {PROC-901}', đoạn 'Yêu cầu chứng
    từ nguồn tiền.', '## Căn cứ {REG-901}', đoạn 'Theo quy định nội bộ.'
  KB-C = file thứ ba kb-c.md: doc_number KB-RFC-901, title 'Checklist thử nghiệm', doc_type CHECKLIST, version "1.0",
    effective_date 2026-01-01, language vi, không defines / relations; thân: '## Kiểm tra {RF-901}', đoạn 'Đối chiếu
    sao kê.'
k_settings = settings với AML__ASSISTANT__KNOWLEDGE__DIR = MINI-K, AML__ASSISTANT__EMBEDDING__DIMENSIONS = 64,
  AML__ASSISTANT__CACHE__DIR = <tmp>/cache, AML__ASSISTANT__PROVIDER = fake.
Mọi giá trị MINI-K / MINI-C suy ra bằng tay từ luật ở mục Thiết kế, chưa chạy; hai giá trị sha256 ở AC4 tính bằng
  Python theo đúng công thức cache_key. AC9 chưa chạy; các hành vi Ollama của AC11 đã đo bằng lời gọi HTTP trực tiếp (mục Hiện trạng), chưa chạy qua
  OllamaClient (xem Giả định). -->
- AC1: Given `config.yaml` của repo và các module của 8a, When gọi `s = load_settings(environ={})` và import, Then `s.assistant.provider == "ollama"`, `s.assistant.request_timeout_seconds == 300`, `s.assistant.num_ctx == 4096`, `s.assistant.keep_alive_chat == "5m"`, `s.assistant.keep_alive_embed == "5m"`, `s.assistant.cache.enabled is True`, `s.assistant.cache.dir == "data/llm_cache"`, `s.assistant.embedding.dimensions == 1024`, `s.assistant.embedding.batch_size == 16`, `s.assistant.knowledge.dir == "docs/knowledge"`, `s.assistant.knowledge.chunk_max_chars == 1200`, `s.assistant.vector_procedures == ["db.index.vector.queryNodes"]`; `s.ollama.llm_model == "qwen2.5:3b-instruct"`, `s.ollama.embed_model == "bge-m3"`; `s.neo4j.read_procedures` vẫn là đúng 7 phần tử của 6a và không chứa `db.index.vector.queryNodes`; `load_settings(environ={"AML__ASSISTANT__PROVIDER": "openai"})`, `AML__ASSISTANT__EMBEDDING__DIMENSIONS=0`, `AML__ASSISTANT__EMBEDDING__DIMENSIONS=4097`, `AML__ASSISTANT__EMBEDDING__BATCH_SIZE=0`, `AML__ASSISTANT__KNOWLEDGE__CHUNK_MAX_CHARS=199`, `AML__ASSISTANT__NUM_CTX=511` và `AML__ASSISTANT__REQUEST_TIMEOUT_SECONDS=0` mỗi cái raise `pydantic.ValidationError`; `isinstance(FakeLLM(), LLMClient)`, `isinstance(OllamaClient("http://x", "a", "b", seed=1), LLMClient)` và `isinstance(CachedLLM(FakeLLM(), tmp_path), LLMClient)` đều đúng, `isinstance(object(), LLMClient)` sai; `TEMPERATURE == 0`; `VECTOR_INDEX == "chunk_embedding"`; `KNOWLEDGE_VERSION == "knowledge/v1"`; `re.fullmatch(CHUNK_ID_PATTERN, "KB-TYP-001#003")` khớp còn `"KB-TYP-001"` và `"kb-typ-001#3"` không khớp; `type(get_llm(s, cached=False)).__name__ == "OllamaClient"` với `chat_model == "qwen2.5:3b-instruct"`, `embed_model == "bge-m3"`, `seed == 42`, `num_ctx == 4096`; `type(get_llm(s)).__name__ == "CachedLLM"`; với `AML__ASSISTANT__PROVIDER=fake` và `AML__ASSISTANT__EMBEDDING__DIMENSIONS=64`, `get_llm(s2, cached=False)` là `FakeLLM` và `len(get_llm(s2, cached=False).embed(["a"])[0]) == 64`; các lời gọi `get_llm` trên không mở kết nối mạng nào (chạy được với `AML__OLLAMA__HOST=http://127.0.0.1:1`); mã nguồn `src/aml/assistant/llm.py` không chứa (không phân biệt hoa thường) `openai`, `anthropic`, `googleapis`, `api_key` và không import `neo4j`; `client.WRITE_PREFIXES == ("schema.cypher", "sync/", "knowledge/")`; `Makefile` chứa `$(AML) rag build`; và `tasks.ps1` chứa `"rag", "build"`.
- AC2: Given `FakeLLM` và `fake_embedding`, When gọi các hàm dưới đây, Then `fake_embedding("a a", 8)` có đúng một phần tử khác 0 và phần tử đó bằng `1.0`; `fake_embedding("!!!", 4) == [1.0, 0.0, 0.0, 0.0]`; `fake_embedding("Rửa Tiền", 16) == fake_embedding("rửa tiền", 16)`; tổng bình phương các phần tử của `fake_embedding("nộp tiền mặt sát ngưỡng", 1024)` lệch 1.0 không quá 1e-9; tích vô hướng của `fake_embedding("nộp tiền mặt sát ngưỡng", 1024)` với `fake_embedding("nộp tiền mặt", 1024)` lớn hơn 0.7 và với `fake_embedding("chuyển khoản vòng tròn", 1024)` nhỏ hơn 0.2; `f = FakeLLM(dim=8)` cho `f.embed([]) == []`, `f.embed(["x", "y"]) == [fake_embedding("x", 8), fake_embedding("y", 8)]`, và `f.embed(["x", "  "])` raise `LLMError` chứa `cannot embed an empty text`; `f.chat_model == "fake-chat"`, `f.embed_model == "fake-embed"`, `f.seed == 0`, `f.num_ctx == 4096`; hai `FakeLLM()` khác nhau trả cùng một chuỗi cho `chat([{"role": "user", "content": "xin chào"}])`, chuỗi đó khớp `^FAKE-[0-9a-f]{12}$` và khác chuỗi trả cho `content = "tạm biệt"`; cùng messages đó với `json_schema={"type": "object"}` trả `"{}"`; `FakeLLM(replies=["a", "b"])` trả `"a"` rồi `"b"` và lần gọi `chat` thứ ba raise `LLMError` chứa `no scripted reply left`; `FakeLLM(responder=lambda m, js: m[-1]["content"].upper())` trả `"XIN CHÀO"`; và sau một lời gọi `chat` rồi một lời gọi `embed(["x"])`, `f.calls` có đúng 2 phần tử với `calls[0]["kind"] == "chat"`, `calls[0]["messages"][0]["content"] == "xin chào"`, `calls[1] == {"kind": "embed", "texts": ["x"]}`.
- AC3: Given `OllamaClient("http://ollama.test", "qwen2.5:3b-instruct", "bge-m3", seed=42, batch_size=2, transport=t)` với `t` là hàm ghi lại (đường dẫn, body) và trả `{"message": {"content": "xin chào"}}` cho `/api/chat`, `{"embeddings": [[0.1, 0.2]] * len(body["input"])}` cho `/api/embed`, When gọi `chat` và `embed`, Then `chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}])` trả `"xin chào"` và `t` nhận đúng một lời gọi với đường dẫn `/api/chat` và body bằng đúng `{"model": "qwen2.5:3b-instruct", "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], "stream": False, "truncate": False, "options": {"temperature": 0, "seed": 42, "num_ctx": 4096}, "keep_alive": "5m"}`; một client tạo với `num_ctx=8192` gửi `options.num_ctx == 8192`; cùng lời gọi với `json_schema={"type": "object", "properties": {"category": {"type": "string"}}}` gửi body có thêm đúng một khoá `format` bằng schema đó, và vì nội dung trả về `xin chào` không phải JSON nên raise `LLMError` chứa `not valid JSON`; khi `t` trả `{"message": {"content": "{\"category\": \"salary\"}"}}` thì lời gọi có `json_schema` trả đúng chuỗi `{"category": "salary"}`; `embed(["a", "b", "c"])` trả 3 vector `[0.1, 0.2]` và `t` nhận đúng 2 lời gọi `/api/embed` với body `{"model": "bge-m3", "input": ["a", "b"], "truncate": False, "keep_alive": "5m"}` rồi `{"model": "bge-m3", "input": ["c"], "truncate": False, "keep_alive": "5m"}`; `embed([])` trả `[]` và không gọi `t`; `embed(["a", ""])` raise `LLMError` chứa `cannot embed an empty text` và không gọi `t`; khi `t` trả `{"embeddings": [[0.1, 0.2]]}` cho 2 văn bản thì raise `LLMError` chứa `unexpected Ollama response`; khi `t` trả `{}` cho `/api/chat` thì raise `LLMError` chứa `unexpected Ollama response`; Given `OllamaClient("http://127.0.0.1:1", "m", "e", seed=1, timeout=2)` (transport mặc định, không có gì lắng nghe), Then `chat([{"role": "user", "content": "u"}])` và `embed(["a"])` đều raise `ServiceUnavailableError` chứa `cannot reach Ollama at http://127.0.0.1:1`; và Given một HTTP server cục bộ trong test trả mã 404 với body `{"error": "model not found"}` cho mọi POST, Then `embed(["a"])` của client trỏ tới server đó (`embed_model="bge-m3"`) raise `LLMError` chứa `model 'bge-m3' is not available on Ollama` và chứa `ollama pull bge-m3`, khi server trả mã 400 với body JSON có khoá `error` là chuỗi `request (5255 tokens) exceeds the available context size (4096 tokens), try increasing it; type exceed_context_size_error` thì `chat([{"role": "user", "content": "u"}])` raise `LLMError` chứa `prompt exceeds the context window` và chứa `5255`, khi server trả mã 400 với body `{"error": "the input length exceeds the context length"}` thì `embed(["a"])` raise `LLMError` chứa `prompt exceeds the context window`, khi server trả mã 400 với body `{"error": "bad request"}` thì `embed(["a"])` raise `LLMError` chứa `Ollama returned HTTP 400` và không chứa `context window`, còn khi server trả mã 500 thì raise `LLMError` chứa `Ollama returned HTTP 500`.
- AC4: Given `inner = FakeLLM(dim=8)` và `c = CachedLLM(inner, tmp_path)`, When gọi `cache_key` và các method của `c`, Then `cache_key("embed", "fake-embed", {"text": "xin chào"}) == "7ee83fc4aec3838bb495d8fef8bb94fa139c28a676351ff74b90afb4170d02d0"` và `cache_key("embed", "bge-m3", {"text": "xin chào"}) == "b2850245cf64148915830adeda440e06792283b039ce044af12738d9553b9d48"`; `c.chat_model == "fake-chat"`, `c.embed_model == "fake-embed"`, `c.seed == 0`, `c.num_ctx == 4096`; `c.embed(["xin chào", "b"])` trả `[fake_embedding("xin chào", 8), fake_embedding("b", 8)]`, sau đó `c.misses == 2`, `c.hits == 0`, thư mục `tmp_path / "embed"` có đúng 2 file và file `7ee83fc4aec3838bb495d8fef8bb94fa139c28a676351ff74b90afb4170d02d0.json` (đọc UTF-8) là JSON có `kind == "embed"`, `model == "fake-embed"`, `payload == {"text": "xin chào"}`, `response == fake_embedding("xin chào", 8)`; `c.embed(["b", "c", "xin chào", "c"])` trả 4 vector đúng thứ tự đầu vào, và lời gọi `embed` mới nhất trong `inner.calls` có `texts == ["c"]`, sau đó `c.hits == 2`, `c.misses == 3`; một `CachedLLM(FakeLLM(dim=8), tmp_path)` mới gọi `embed(["xin chào", "b", "c"])` không sinh lời gọi nào ở client bên trong của nó (`calls == []`); `CachedLLM(FakeLLM(dim=8, embed_model="other"), tmp_path).embed(["xin chào"])` là miss (client bên trong nhận 1 lời gọi); `m = [{"role": "user", "content": "u"}]`, `c2 = CachedLLM(FakeLLM(replies=["r1", "r2"]), tmp_path)` cho `c2.chat(m) == "r1"`, lần hai `c2.chat(m) == "r1"` (client bên trong chỉ nhận 1 lời gọi chat), `c2.chat(m, json_schema={"type": "object"}) == "r2"` (schema khác là khoá khác), và ngay sau ba lời gọi đó thư mục `tmp_path / "chat"` có đúng 2 file, cả hai có `payload.num_ctx == 4096` và `payload.temperature == 0`; `CachedLLM(FakeLLM(seed=7, replies=["r3"]), tmp_path).chat(m) == "r3"` (seed khác là khoá khác); `CachedLLM(FakeLLM(num_ctx=8192, replies=["r4"]), tmp_path).chat(m) == "r4"` (`num_ctx` khác là khoá khác) và có đúng một file trong `tmp_path / "chat"` có `payload.num_ctx == 8192`; sau khi ghi đè file cache của `"xin chào"` bằng chuỗi `not json`, `c.embed(["xin chào"])` vẫn trả `fake_embedding("xin chào", 8)`, tính là 1 miss và file đó lại là JSON có khoá `response`; khi client bên trong raise `LLMError` (`c.embed([" "])`) thì số file trong `tmp_path / "embed"` không đổi; và không còn file tạm nào (tên không kết thúc bằng `.json`) trong hai thư mục con.
- AC5: Given MINI-K, When gọi `corpus = load_corpus(mini_k, max_chars=1200)` và `split_section`, Then `[d.doc_id for d in corpus.docs] == ["KB-SOP-901", "KB-TYP-901"]`; tài liệu `KB-TYP-901` có `title == "Structuring thử nghiệm"`, `doc_type == "TYPOLOGY"`, `version == "1.0"`, `effective_date == date(2026, 1, 1)`, `language == "vi"`, `source_file == "kb-a.md"` và `sha256` bằng sha256 của nội dung file; `[c.chunk_id for c in corpus.chunks] == ["KB-SOP-901#001", "KB-SOP-901#002", "KB-TYP-901#001", "KB-TYP-901#002", "KB-TYP-901#003"]`; chunk `KB-TYP-901#001` = (`heading` `Structuring thử nghiệm`, `text` `Đoạn mở đầu.`, `mentions` `()`); `KB-TYP-901#002` = (`Mô tả`, `Khách hàng chia nhỏ tiền mặt.`, `("structuring",)`); `KB-TYP-901#003` = (`Dấu hiệu`, `Nộp tiền nhiều lần dưới ngưỡng.`, `("RF-901", "structuring")`); `KB-SOP-901#001` = (`Bước 1`, `Yêu cầu chứng từ nguồn tiền.`, `("PROC-901",)`); `KB-SOP-901#002` = (`Căn cứ`, `Theo quy định nội bộ.`, `("REG-901",)`); không `heading` nào chứa `{`; `[(e.label, e.id) for e in corpus.entities] == [("Procedure", "PROC-901"), ("RedFlag", "RF-901"), ("Regulation", "REG-901"), ("Typology", "structuring")]` và thực thể `RF-901` có `name == "Nộp tiền mặt sát ngưỡng"`, `doc_id == "KB-TYP-901"`; `[(r.type, r.source, r.target) for r in corpus.relations] == [("HAS_RED_FLAG", "structuring", "RF-901"), ("INVESTIGATED_BY", "structuring", "PROC-901"), ("REQUIRED_BY", "PROC-901", "REG-901")]`; `embed_text` của chunk `KB-TYP-901#003` bằng đúng `"Structuring thử nghiệm — Dấu hiệu\nNộp tiền nhiều lần dưới ngưỡng."`; hai lần `load_corpus` cho hai `Corpus` bằng nhau (`==`) và `corpus.sha256` đổi khi sửa một ký tự trong `kb-b.md`; `split_section(["a" * 40, "b" * 40, "c" * 40], 100) == ["a" * 40 + "\n\n" + "b" * 40, "c" * 40]`; `split_section(["x" * 250], 100) == ["x" * 100, "x" * 100, "x" * 50]`; `split_section([], 100) == []`; và khi thêm vào `kb-a.md` một section `## Dài {structuring}` gồm ba đoạn 500 ký tự rồi `load_corpus(mini_k, max_chars=1200)`, tài liệu `KB-TYP-901` có 5 chunk, chunk `#004` và `#005` cùng `heading == "Dài"`, cùng `mentions == ("structuring",)`, `len(text)` lần lượt 1002 và 500.
- AC6: Given MINI-K với từng thay đổi dưới đây (mỗi lần một thay đổi, trên một bản sao), When gọi `load_corpus(dir, max_chars=1200)`, Then raise `KnowledgeError` có thông điệp chứa tên file bị sửa và chứa chuỗi tương ứng: bỏ dòng `effective_date` của `kb-a.md` → `missing metadata 'effective_date'`; `kb-a.md` không có frontmatter → `missing metadata 'doc_number'`; `doc_number: TYP-1` → `invalid doc_number`; `kb-b.md` đổi `doc_number` thành `KB-TYP-901` → `duplicate doc_number KB-TYP-901`; `doc_type: MEMO` → `unknown doc_type`; `effective_date: 2026-13-01` → `invalid effective_date`; thêm `{label: Person, id: P-001, name: x}` vào `defines` → `unknown label 'Person'`; đổi id red flag thành `RF-1` → `invalid id 'RF-1' for RedFlag`; thêm `{label: RedFlag, id: RF-901, name: y}` vào `defines` của `kb-b.md` → `entity RF-901 is defined twice`; thêm quan hệ `{from: structuring, type: CAUSES, to: RF-901}` → `unknown relation type 'CAUSES'`; thêm quan hệ `{from: RF-901, type: HAS_RED_FLAG, to: structuring}` → `relation HAS_RED_FLAG must go from Typology to RedFlag`; thêm quan hệ `{from: structuring, type: HAS_RED_FLAG, to: RF-999}` → `unknown entity 'RF-999'`; đổi heading thành `## Mô tả {structuring RF-777}` → `unknown entity 'RF-777'`; xoá file `kb-b.md` → `unknown entity 'PROC-901'` (thông điệp chứa `kb-a.md`, nơi khai báo quan hệ); đổi heading `## Căn cứ {REG-901}` thành `## Căn cứ` → `entity REG-901 is never mentioned`; `kb-b.md` chỉ còn frontmatter không có `defines` / `relations` và dòng tiêu đề → `no content`; và với một thư mục rỗng → `KnowledgeError` chứa `no knowledge documents in`.
- AC7: Given thư mục `docs/knowledge` của repo và `settings` mặc định, When gọi `corpus = load_corpus(settings.path("docs/knowledge"), max_chars=1200)` và chạy `aml rag build --dry-run` với `AML__NEO4J__URI=bolt://127.0.0.1:1` và `AML__OLLAMA__HOST=http://127.0.0.1:1`, Then thư mục có đúng 8 file `.md` tên `typology-structuring.md`, `typology-rapid-movement.md`, `typology-mule-ring.md`, `typology-round-tripping.md`, `typology-sanctions-pep.md`, `sop-investigation.md`, `red-flag-checklist.md`, `policy-aml-internal.md`; `[d.doc_id for d in corpus.docs] == ["KB-POL-001", "KB-RFC-001", "KB-SOP-001", "KB-TYP-001", "KB-TYP-002", "KB-TYP-003", "KB-TYP-004", "KB-TYP-005"]`; mọi tài liệu có `language == "vi"`, `version == "1.0"`, `effective_date == date(2026, 1, 1)`; số thực thể theo label là `Typology` 6, `RedFlag` 18, `Procedure` 6, `Regulation` 3; tập id `Typology` bằng đúng `set(TYPOLOGY_IDS)`, tập id `RedFlag` là `RF-001` tới `RF-018`, `Procedure` là `PROC-001` tới `PROC-006`, `Regulation` là `REG-001` tới `REG-003`; `set(rule_typologies().values()) | set(SCREENING_LIST_TYPOLOGY.values()) == set(TYPOLOGY_IDS)`; mỗi typology là nguồn của ít nhất 2 quan hệ `HAS_RED_FLAG`, 1 `INVESTIGATED_BY` và 1 `GOVERNED_BY`; mỗi `Procedure` là nguồn của ít nhất 1 `REQUIRED_BY`; mỗi tài liệu có ít nhất 3 chunk, tổng số chunk không dưới 30, mọi `len(chunk.text)` nằm trong 1 đến 1200; chunk `#001` của mỗi tài liệu chứa nguyên văn `Tài liệu tổng hợp (synthetic)`; văn bản các chunk của `KB-TYP-001` chứa `STRUCTURING` và `thresholds.large_cash_vnd`, của `KB-TYP-002` chứa `RAPID_MOVEMENT`, của `KB-TYP-003` chứa cả `FAN_IN`, `FAN_OUT`, `NET_SHARED_ATTRIBUTE`, `NET_HUB`, của `KB-TYP-004` chứa `NET_CYCLE`, của `KB-TYP-005` chứa cả `SCREENING_ALERT` và `SCREENING_REVIEW`; không chunk nào chứa chuỗi `400000000`; 18 red flag đều được ít nhất một chunk của `KB-RFC-001` mention; lệnh `--dry-run` exit code 0, stdout chỉ gồm ký tự ASCII và có đúng một dòng bắt đầu bằng `dry_run documents=8 chunks=` chứa `typologies=6 red_flags=18 procedures=6 regulations=3`, trong đó số sau `chunks=` bằng `len(corpus.chunks)`; lệnh không ghi dòng nào vào `audit_log` và không tạo file nào trong thư mục cache; và khi `AML__ASSISTANT__KNOWLEDGE__DIR` trỏ tới một thư mục rỗng, `aml rag build --dry-run` exit code 1 với stderr chứa `no knowledge documents in`.
- AC8: Given MINI-C đã `run_cases(duck, settings)` (run 1), When gọi `rule_typologies()` và `ms = derive_matches(duck)`, Then `rule_typologies() == {"STRUCTURING": "structuring", "RAPID_MOVEMENT": "rapid_movement", "FAN_IN": "mule_ring", "FAN_OUT": "mule_ring", "NET_SHARED_ATTRIBUTE": "mule_ring", "NET_CYCLE": "round_tripping", "NET_HUB": "mule_ring"}`; `SCREENING_LIST_TYPOLOGY == {"SANCTIONS": "sanctions_hit", "PEP": "pep_hit"}`; `[(m.case_id, m.typology_id) for m in ms]` bằng đúng `[("C-C01-20260302", "rapid_movement"), ("C-C01-20260302", "round_tripping"), ("C-C01-20260302", "structuring"), ("C-C01-20260531", "mule_ring"), ("C-C01-20260531", "sanctions_hit"), ("C-C03-20260305", "round_tripping"), ("C-C04-20260305", "round_tripping"), ("C-C05-20260630", "pep_hit")]`; phần tử `("C-C01-20260302", "structuring")` có `rule_ids == ("STRUCTURING",)`, `alert_keys == ("STRUCTURING|A01|2026-03-02T09:00:00",)`, `evidence_ids == ("T01",)` và `reason == "1 alert(s) from rule(s) STRUCTURING map to typology structuring"`; phần tử `("C-C01-20260302", "rapid_movement")` có `evidence_ids == ("T05", "T06")`; ba phần tử `round_tripping` đều có `rule_ids == ("NET_CYCLE",)`, `alert_keys == ("NET_CYCLE|A01>A03>A04|2026-03-05T10:00:00",)`, `evidence_ids == ("T02", "T03", "T04")`; phần tử `("C-C01-20260531", "mule_ring")` có `rule_ids == ("FAN_OUT",)`, `evidence_ids == ("T07",)`; phần tử `sanctions_hit` có `rule_ids == ("SCREENING_ALERT",)`, `alert_keys == ("SCREENING|C02|WL1",)`, `evidence_ids == ("C02:WL1",)`; phần tử `pep_hit` có `rule_ids == ("SCREENING_REVIEW",)`, `evidence_ids == ("C05:WL2",)`; không phần tử nào có `rule_ids` chứa `DORMANT_REACTIVATION`; số dòng của `audit_log`, `cases`, `case_alerts` trước và sau lời gọi bằng nhau; sau `add_r5(duck)` (alert `HIGH_VELOCITY` trên A01) và `run_cases` (run 2), `derive_matches(duck)` vẫn trả đúng 8 phần tử như trên; sau `record_disposition(duck, settings, "C-C01-20260302", "FALSE_POSITIVE", reason="x", actor="analyst01", decided_on=date(2026, 6, 30))` và `run_cases` (case đó `CLOSED`), `derive_matches(duck)` vẫn có 3 phần tử của `C-C01-20260302`; và trên một DuckDB chỉ mới `apply_schema` (chưa có case run), `derive_matches(duck) == []`.
- AC9: [neo4j] Given Neo4j đã dọn bằng `knowledge/wipe.cypher` rồi `sync/wipe.cypher`, MINI-C đã `run_cases(duck, k_settings)` và `llm = CachedLLM(FakeLLM(dim=64), <tmp>/cache)`, When gọi `r1 = build_knowledge(duck, k_settings, llm)`, rồi `r2 = build_knowledge(duck, k_settings, llm)` và các bước dưới đây, Then `r1.build_id == 1`, `r1.documents == 2`, `r1.chunks == 5`, `r1.embedded == 5`, `r1.cache_hits == 0`, `r1.entities == {"Typology": 1, "RedFlag": 1, "Procedure": 1, "Regulation": 1}`, `r1.relations == 3`, `r1.mentions == 5`, `r1.cases == 5`, `r1.matches == 1`, `r1.matches_skipped == 7`, `r1.cases_unlinked == 5`; đếm trong Neo4j (qua `run_read`) cho `Document` 2, `Chunk` 5, `Typology` 1, `RedFlag` 1, `Procedure` 1, `Regulation` 1, `Case` 5, `KnowledgeState` 1, và quan hệ `PART_OF` 5, `NEXT` 3, `MENTIONS` 5, `DEFINES` 4, `HAS_RED_FLAG` 1, `INVESTIGATED_BY` 1, `REQUIRED_BY` 1, `GOVERNED_BY` 0, `ABOUT` 0, `MATCHES_TYPOLOGY` 1; node `Chunk` `KB-TYP-901#003` có `doc_id == "KB-TYP-901"`, `seq == 3`, `heading == "Dấu hiệu"`, `text == "Nộp tiền nhiều lần dưới ngưỡng."`, `doc_version == "1.0"`, `effective_date == date(2026, 1, 1)`, `language == "vi"`, `size(embedding) == 64`; node `Document` `KB-SOP-901` có `version == "2.1"`, `doc_type == "SOP"`, `is_synthetic == true`; node `Typology` `structuring` có `name == "Chia nhỏ giao dịch"`, `rule_ids == ["STRUCTURING"]`; quan hệ `MATCHES_TYPOLOGY` duy nhất đi từ `Case` `C-C01-20260302` tới `Typology` `structuring` với `evidence_ids == ["T01"]`, `alert_keys == ["STRUCTURING|A01|2026-03-02T09:00:00"]`, `rule_ids == ["STRUCTURING"]`, `reason == "1 alert(s) from rule(s) STRUCTURING map to typology structuring"`; node `Case` `C-C05-20260630` có `golden_customer_id == "G-C05"`, `status == "OPEN"`, `alerts == 1`, `sources == "SCREENING"`, `case_run_id == 1`, và tập khoá thuộc tính của mọi node `Case` là đúng `{case_id, golden_customer_id, status, window_start, first_alert_ts, last_alert_ts, alerts, sources, case_run_id, build_id}`; `SHOW INDEXES` có index `chunk_embedding` với `type == "VECTOR"`, `state == "ONLINE"`; `run_read(driver, k_settings, "CALL db.index.vector.queryNodes('chunk_embedding', 1, $v) YIELD node, score RETURN node.chunk_id AS chunk_id, score", {"v": fake_embedding("Structuring thử nghiệm — Dấu hiệu\nNộp tiền nhiều lần dưới ngưỡng.", 64)}, procedures=k_settings.assistant.vector_procedures)` trả đúng 1 dòng có `chunk_id == "KB-TYP-901#003"` và `score >= 0.99`, còn cùng lời gọi không truyền `procedures` raise `WriteBlockedError` chứa `procedure db.index.vector.queryNodes is not allowed in a read-only query`; `audit_log` có đúng 1 dòng `module = 'assistant'` với `entity_type == "knowledge_build"`, `entity_id == "1"`, `decision == "KNOWLEDGE_BUILD_COMPLETED"`, `version == "knowledge/v1"`, `reason == "Built the knowledge layer: 2 document(s), 5 chunk(s), 5 case(s), 1 typology match(es)."`, `details.embed_model == "fake-embed"`, `details.dimensions == 64`, `details.case_run_id == 1`; `r2.build_id == 2`, `r2.embedded == 0`, `r2.cache_hits == 5`, mọi số đếm node / quan hệ trong Neo4j giống hệt sau `r1`, và `audit_log` có 2 dòng `module = 'assistant'`; `knowledge_status(duck, k_settings)` có `build_id == 2`, `embed_model == "fake-embed"`, `index_state == "ONLINE"`, `index_dimensions == 64`, `documents == 2`, `chunks == 5`, `chunks_without_embedding == 0`, `cases == 5`, `matches == 1`, `cases_unlinked == 5`, `corpus_in_sync is True`, `cases_in_sync is True`; sau khi sửa đoạn `Đoạn mở đầu.` của `kb-a.md` thành `Đoạn mở đầu mới.` (chưa build), `knowledge_status` cho `corpus_in_sync is False`, và lần build kế tiếp có `embedded == 1`, `cache_hits == 4`, node `KB-TYP-901#001` có `text == "Đoạn mở đầu mới."`; sau khi thêm KB-C và build, `Document` 3, `Chunk` 6, `MENTIONS` 6; sau khi xoá `kb-c.md` và build, `Document` 2, `Chunk` 5, `MENTIONS` 5 và không còn node `Chunk` nào có `doc_id == "KB-RFC-901"`; sau `run_cases` lần nữa (run mới, chưa build), `knowledge_status` cho `cases_in_sync is False`; với `AML__ASSISTANT__EMBEDDING__DIMENSIONS=32` và `FakeLLM(dim=32)`, `build_knowledge` raise `KnowledgeError` chứa `vector index chunk_embedding has 64 dimensions but assistant.embedding.dimensions is 32: run aml rag build --full`, còn với `full=True` thì thành công, `build_id == 1` và mọi `Chunk` có `size(embedding) == 32`; với `FakeLLM(dim=16)` trong khi config vẫn 32, `build_knowledge` raise `KnowledgeError` chứa `embedding has 16 dimensions, expected 32` và số node trong Neo4j không đổi; Given thêm projection của MINI-C trong Neo4j (`refresh_acct_edge_daily(duck)` rồi `run_sync(duck, k_settings, full=True)`, 5 node `Customer`), Then lần build kế tiếp có `cases_unlinked == 0` và có đúng 5 quan hệ `ABOUT`, trong đó `C-C01-20260302` và `C-C01-20260531` cùng trỏ tới `Customer` `G-C01`; số node `Customer`, `Account` và số quan hệ `TRANSFERRED_TO` trước và sau lần build đó bằng nhau; chạy `sync/wipe.cypher` sau đó không lỗi và để lại `Chunk` 5, `Case` 5, `ABOUT` 0, `Customer` 0; và chạy `knowledge/wipe.cypher` để lại 0 node thuộc các label `Document`, `Chunk`, `Typology`, `RedFlag`, `Procedure`, `Regulation`, `Case`, `KnowledgeState`, không còn index `chunk_embedding`, và tập tên constraint (`SHOW CONSTRAINTS`) bằng đúng 7 constraint của 6a.
- AC10: Given môi trường CLI gồm một DuckDB tạm (`AML__DB__DUCKDB_PATH`) chứa MINI-C đã `run_cases`, `AML__ASSISTANT__KNOWLEDGE__DIR` = MINI-K, `AML__ASSISTANT__PROVIDER=fake`, `AML__ASSISTANT__EMBEDDING__DIMENSIONS=64`, `AML__ASSISTANT__CACHE__DIR=<tmp>/cache`, `AML__NEO4J__URI=bolt://127.0.0.1:1` (Neo4j không chạy), When chạy các lệnh `aml rag`, Then `aml rag --help` exit code 0 và stdout chứa `build` và `status`; `aml rag build --dry-run` exit code 0 với stdout có đúng dòng `dry_run documents=2 chunks=5 typologies=1 red_flags=1 procedures=1 regulations=1 relations=3 mentions=5`; `aml rag build` exit code 1 với stderr chứa `neo4j not available` và không chứa `Traceback`, `audit_log` không có dòng `module = 'assistant'` nào; `aml rag status` exit code 1 với stderr chứa `neo4j not available`; với `AML__ASSISTANT__PROVIDER=ollama`, `AML__OLLAMA__HOST=http://127.0.0.1:1` và thư mục cache rỗng, `aml rag build` exit code 1 với stderr chứa `ollama not available` và chứa `cannot reach Ollama at http://127.0.0.1:1`; với `kb-a.md` bị bỏ dòng `effective_date`, `aml rag build` exit code 1 với stderr chứa `kb-a.md` và `missing metadata 'effective_date'`; và `aml rag build --dry-run --full` exit code 2.
- AC11: [ollama] Given Ollama đang chạy và đã có sẵn `bge-m3` và `qwen2.5:3b-instruct`, `s = load_settings(environ={"AML__ASSISTANT__CACHE__DIR": "<tmp>/cache"})`, When gọi `llm = get_llm(s)`, Then `v = llm.embed(["xin chào", "nộp tiền mặt nhiều lần dưới ngưỡng báo cáo"])` trả 2 vector, mỗi vector có đúng 1024 phần tử kiểu `float`, không phần tử nào là NaN hay vô cực, tổng bình phương mỗi vector lớn hơn 0; `llm.misses == 2`; lời gọi `embed` lần hai với cùng đầu vào trả kết quả bằng đúng `v`, `llm.hits == 2` và `llm.misses` vẫn là 2; `out = llm.chat([{"role": "user", "content": "Trả lời đúng một từ: thủ đô của Việt Nam là gì?"}], json_schema={"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]})` là chuỗi mà `json.loads(out)` cho một dict có khoá `answer` kiểu `str`; lời gọi `chat` lần hai giống hệt trả đúng `out` và là cache hit (`llm.hits == 3`); thư mục `<tmp>/cache/embed` có đúng 2 file và `<tmp>/cache/chat` có đúng 1 file; `llm.chat([{"role": "user", "content": "SECRET=ALPHA. " + "Đây là một câu đệm dài không có ý nghĩa gì. " * 400 + " Câu hỏi: giá trị SECRET ở đầu văn bản là gì?"}])` (khoảng 5250 token theo Ollama, vượt `num_ctx` 4096) raise `LLMError` chứa `prompt exceeds the context window`, sau đó `<tmp>/cache/chat` vẫn có đúng 1 file; `llm.embed(["x " * 20000])` raise `LLMError` chứa `prompt exceeds the context window` và `<tmp>/cache/embed` vẫn có đúng 2 file; và một `get_llm` với `AML__OLLAMA__EMBED_MODEL=khong-co-mo-hinh-nay` raise `LLMError` chứa `model 'khong-co-mo-hinh-nay' is not available on Ollama` khi gọi `embed(["a"])`.

## Ngoài phạm vi
- **Retriever, router, Text2Cypher** (k-hop quanh case / khách hàng, vector + mở rộng đồ thị, allowlist schema, LIMIT ép buộc) — 8b `specs/assistant-retrievers.md`. 8a chỉ để lại node, quan hệ, vector index và `assistant.vector_procedures`.
- **Trả lời, trích dẫn, hậu kiểm, phòng thủ prompt injection, narrative LLM (`register_generator("llm", …)`), Q&A, typology explainer, tiếng Việt / tiếng Anh của câu trả lời** — 8c `specs/assistant-answering.md`. 8a không có prompt nào và không gọi `chat` ngoài test.
- **Phân loại memo, đưa category vào mô hình ưu tiên** — 8d `specs/memo-analysis.md` (chỉ dùng `LLMClient`, `CachedLLM`, `get_llm`).
- **Golden set, metric, so sánh plain vector RAG với GraphRAG** — 8e `specs/assistant-eval.md`.
- **LLM trích thực thể / quan hệ từ văn bản** (Q3); kiểm tra đầu ra của `chat` theo JSON schema (client chỉ kiểm "parse được"); streaming / SSE; gọi bất đồng bộ; đếm token phía client (giới hạn do Ollama kiểm qua `truncate: false`); tự rút gọn prompt quá dài (việc của nơi gọi — 8b / 8c); retry tự động.
- **Nhà cung cấp hosted** (OpenAI, Anthropic, …), khoá API, tự `ollama pull` mô hình, quản lý container Ollama từ CLI.
- **Văn bản pháp quy thật** (người dùng bổ sung sau — brief); 8a chỉ có "quy định nội bộ tổng hợp" đánh dấu `is_synthetic` (Q6). Nạp PDF / DOCX, OCR, tài liệu tiếng Anh song song, nhiều phiên bản của cùng một tài liệu cùng lúc.
- **Node `Alert`, node giao dịch, quan hệ từ `Case` tới `Account`** — bằng chứng nằm trong `evidence_ids` / `alert_keys` của `MATCHES_TYPOLOGY`; chi tiết alert đọc qua `load_case` (8b quyết định có cần thêm node không).
- **Bảng mới trong Oracle / DuckDB** (lịch sử build, bảng typology match): chỉ có một dòng `audit_log` mỗi lần build (Q9). Xoá cache tự động, giới hạn dung lượng cache, mã hoá cache.
- **Sync tăng dần của `Case`** theo watermark: mỗi lần `aml rag build` nạp lại toàn bộ `cases_current` (309 case trên `small`). Tự chạy `aml rag build` sau `aml cases build` hay `aml graph sync`.
- API FastAPI và UI (Phase 9); profile `large`.

## Giả định
- **Đã đo trên Ollama 0.40.3 bằng lời gọi HTTP trực tiếp** (mục Hiện trạng): 1024 chiều, dạng `input` / `embeddings`, `format` là JSON schema, `options.num_ctx`, `truncate: false` → HTTP 400, HTTP 404 khi thiếu mô hình, `keep_alive`. **Chưa chạy qua `OllamaClient`** (chưa có code) — AC11 là nơi kiểm lại; nếu một bản Ollama khác đổi thông điệp 400, sửa phép nhận biết trong client và giữ nguyên chuỗi hợp đồng `prompt exceeds the context window`. `options.seed` + `temperature: 0` được coi là đủ để hai lời gọi giống nhau cho cùng kết quả (hai lần thử cho cùng câu trả lời); hệ thống không dựa vào điều đó vì lần hai luôn là cache hit.
- Phát hiện cắt prompt dựa hoàn toàn vào `truncate: false` của Ollama (bản 0.40.3). Một server cũ bỏ qua cờ này sẽ lại cắt im lặng, nên image Ollama cần được ghim khi hiện thực (Q2).
- **Chưa đo trên Neo4j (chỉ thử cú pháp trong session READ)**: tạo vector index bằng `OPTIONS $options`; `db.awaitIndexes` đủ để index `ONLINE` trước khi truy vấn; `queryNodes` trả `score = 1.0` cho vector trùng hướng (cosine của Neo4j được chuẩn hoá về 0..1); driver ghi `list[float]` Python thành thuộc tính hợp lệ cho vector index; `DROP CONSTRAINT … IF EXISTS` / `DROP INDEX … IF EXISTS` chạy được qua `run_write_file`. Nếu `OPTIONS $options` không tạo được index, dùng `CALL db.index.vector.createNodeIndex` (có sẵn trên server) trong cùng file `.cypher`.
- **Suy ra bằng tay, chưa chạy**: mọi giá trị MINI-K và MINI-C trong AC5, AC6, AC8, AC9, AC10. Riêng đoạn cuối AC9 giả định MINI-C sync được sang Neo4j bằng `run_sync` sau `refresh_acct_edge_daily` (MINI-C chưa từng được sync); nếu fixture thiếu dữ liệu cho sync thì bổ sung fixture, không đổi luật `ABOUT`.
- **Đã đo (chỉ đọc)**: hai giá trị sha256 của AC4 (không đổi khi thêm `num_ctx`, vì `num_ctx` chỉ nằm trong payload chat); số liệu `small` ở mục Hiện trạng; danh sách procedure / hàm vector của server; nội dung Neo4j hiện tại.
- `derive_matches` đọc bằng kết nối chính của `get_db` (owner trên Oracle, như `aml cases`), vì `aml_graph_sync_usr` không có quyền trên các bảng case và lần build còn phải ghi `audit_log`. SQL chỉ là `SELECT` trên `case_alerts_current`, `cases_current`, `alert_evidence` (đặt ở `sql/common/`); `details.list_type` đọc bằng Python nên không phụ thuộc cú pháp JSON của backend. 8a không có AC đánh dấu `[oracle]`.
- `alert_ref` của item RULE / NETWORK trong `case_alerts` là `alert_id` còn hiệu lực (bảng `alerts` chỉ thêm, không xoá), nên nối được với `alert_evidence`.
- `chunk_id` chỉ ổn định khi tài liệu không đổi cấu trúc: thêm một section ở giữa làm lệch `seq` của các chunk sau. Mỗi `Chunk` mang `doc_version` để 8c ghi kèm khi trích dẫn; lần build nào cũng thay toàn bộ chunk của tài liệu đã đổi.
- Tài liệu tri thức do ta viết nhưng 8b / 8c vẫn phải coi `Chunk.text` là **dữ liệu không tin cậy** (người dùng sẽ thêm tài liệu thật sau).
- Test Neo4j của 8a xoá dữ liệu của Neo4j dev (cùng quy ước Q21 của 6a). Cache trên đĩa nằm dưới `data/` (git-ignored) và chứa nguyên văn prompt — 8d sẽ đưa memo giao dịch vào đó; chấp nhận được vì toàn bộ dữ liệu là tổng hợp.
- `provider: fake` là đường để 8e và test CLI chạy không cần Ollama; `KnowledgeState.embed_model = "fake-embed"` và dòng cảnh báo stderr là dấu hiệu nhận biết một index dựng bằng embedding giả.
- Kéo mô hình (`ollama pull bge-m3`, `ollama pull qwen2.5:3b-instruct`) là bước cài đặt thủ công một lần, tải từ registry của Ollama — ngoại lệ lúc cài đặt giống file jar GDS của 6b; lúc chạy không có lời gọi mạng nào ra ngoài máy.

## Câu hỏi mở
- [x] Q1. **(cần người dùng quyết)** Tài liệu `docs/knowledge/` viết bằng ngôn ngữ nào? — đề xuất mặc định: **tiếng Việt** (`language: vi`), giữ nguyên văn `rule_id`, tên khoá config và thuật ngữ tiếng Anh quen dùng trong ngoặc (structuring, mule, PEP). Lý do: brief yêu cầu assistant trả lời tiếng Việt mặc định, `bge-m3` đa ngữ, và trích dẫn cùng ngôn ngữ với câu trả lời dễ hậu kiểm hơn. Phương án thay thế: tiếng Anh (khớp mọi `reason` hiện có trong hệ thống), hoặc song ngữ hai file mỗi tài liệu (gấp đôi chunk và công viết). — Trả lời: theo đề xuất mặc định: tiếng Việt (đã trình bày cho người dùng, không phản đối, 2026-10-13).
- [x] Q2. **(cần người dùng quyết)** Ollama chạy Docker + GPU hay cài native trên Windows? — đề xuất mặc định: **Docker + GPU** — giữ khối `deploy.resources.reservations.devices` đang bỏ comment trong working tree của `docker-compose.yml` (thay đổi chưa commit, không do spec này tạo), ghim tag image thay cho `ollama/ollama:latest`, kéo hai mô hình bằng `docker compose exec ollama ollama pull …`. Lý do: một lệnh `tasks.ps1 up -ComposeProfile llm` như các dịch vụ khác; volume `ollamadata` giữ mô hình. Cần NVIDIA Container Toolkit trong WSL2 — **chưa kiểm trên máy này**. Phương án thay thế: cài Ollama native (dùng GPU trực tiếp, không cần toolkit; `ollama.host` giữ nguyên `http://localhost:11434`, compose service `ollama` chỉ còn là đường dự phòng CPU). Spec này không đổi theo lựa chọn. — Trả lời: **Docker + GPU** (người dùng quyết, 2026-10-13); đã bật và đo — xem mục Hiện trạng. Ghim tag image (đang chạy 0.40.3) khi hiện thực.
- [x] Q3. **(cần người dùng quyết)** Thực thể `Typology` / `RedFlag` / `Procedure` / `Regulation` lấy từ đâu? — đề xuất mặc định: **khai báo trong frontmatter của tài liệu** (`defines`, `relations`) và gắn chunk bằng `{id}` ở heading — tất định, kiểm được bằng test, không tốn lời gọi LLM, đồ thị không đổi giữa hai lần build. Phương án thay thế (đúng chữ brief "extract entities"): LLM trích theo JSON schema ràng buộc rồi kiểm với danh sách label / kiểu quan hệ — với mô hình 3B trên GPU 4 GB kết quả dao động, cần cache + bước duyệt tay, và mọi AC về số thực thể phải nới thành khoảng. Có thể làm sau như một lệnh đề xuất (`aml rag suggest`) mà người viết tài liệu duyệt vào frontmatter. — Trả lời: khai báo trong frontmatter (người dùng quyết, 2026-10-13).
- [x] Q4. **(cần người dùng quyết)** Đưa `Case` vào Neo4j bằng cách nào? — đề xuất mặc định: **`aml rag build` nạp** mọi dòng `cases_current` thành node `Case` (không PII) và nối `(Case)-[:ABOUT]->(Customer)`; kéo theo một statement xoá `ABOUT` ở đầu `sync/wipe.cypher`. Lý do: `Case` là dữ liệu của Phase 7, không phải của projection giao dịch; 6a không phải đọc thêm bảng nào; assistant có đường đi `Case → Customer → Account` trong đồ thị. Phương án thay thế: (a) không có quan hệ `ABOUT`, 8b tự nối bằng thuộc tính `golden_customer_id` (không đụng `sync/wipe.cypher`, nhưng k-hop từ case không đi được bằng cạnh); (b) nạp `Case` trong `aml graph sync` (phải cấp thêm quyền đọc bảng case cho `aml_graph_sync_usr` và sửa spec 6a nhiều hơn). — Trả lời: theo đề xuất mặc định, người dùng duyệt cùng spec.
- [x] Q5. **(cần người dùng quyết)** Luật suy `MATCHES_TYPOLOGY` và nội dung `evidence_ids`? — đề xuất mặc định: dùng `target_typology` đã có của từng rule (rule không có target — `HIGH_VELOCITY`, `DORMANT_REACTIVATION` — không sinh liên kết; trên `small` là 62 trong 309 case không có typology nào); screening `SANCTIONS` → `sanctions_hit`, `PEP` → `pep_hit`, **kể cả mức `REVIEW`**; `evidence_ids` = `txn_id` của `alert_evidence` cộng `<cif>:<entry_id>` của cặp screening, kèm `alert_keys`, `rule_ids`, `reason`. Lý do: một nguồn duy nhất cho ánh xạ rule → typology, và mọi ID trong `evidence_ids` tra lại được ở system of record. Phương án thay thế: chỉ screening mức `ALERT` mới sinh liên kết; hoặc gán hai rule không target vào `mule_ring` (tăng độ phủ, nhưng không có căn cứ trong ground truth). — Trả lời: theo đề xuất mặc định, người dùng duyệt cùng spec.
- [x] Q6. **(cần người dùng quyết)** Node `Regulation` chứa gì khi chưa có văn bản thật? — đề xuất mặc định: ba mục **quy định nội bộ tổng hợp** `REG-001`–`REG-003` trong `KB-POL-001` (báo cáo giao dịch tiền mặt giá trị lớn theo `thresholds.large_cash_vnd`; lưu trữ hồ sơ theo `retention.transactions_months`; thời hạn chuyển cấp khi nghi ngờ), đánh dấu `is_synthetic = true`, **không dẫn số hiệu điều khoản của luật thật**. Lý do: tránh bịa trích dẫn pháp lý; người dùng thêm văn bản thật sau thì chỉ cần thêm file. Phương án thay thế: thêm node tên văn bản thật (ví dụ Luật Phòng, chống rửa tiền) không kèm nội dung điều khoản. — Trả lời: theo đề xuất mặc định, người dùng duyệt cùng spec.
- [x] Q7. **(cần người dùng quyết)** Đồng ý ba sửa kéo theo ở phần 6a / 6b đã duyệt? — đề xuất mặc định: **có** — (1) `WRITE_PREFIXES` thêm `"knowledge/"` và sửa phép khẳng định ở `tests/neo4j_gds/test_static.py`; (2) `sync/wipe.cypher` thêm statement xoá `ABOUT` (12 → 13) và sửa `tests/neo4j_sync/test_config_static.py`; (3) ba chỗ test dọn Neo4j gọi thêm `knowledge/wipe.cypher`. Lý do: lớp tri thức nằm chung instance (Community chỉ có một database người dùng) nên test 6a đang khẳng định "mọi node / mọi constraint" sẽ thấy dữ liệu của 8a; giữ một đường ghi duy nhất qua file `.cypher`. Phương án thay thế: một hàm ghi riêng trong `aml.assistant` (không đụng `WRITE_PREFIXES`, nhưng thành hai đường ghi vào Neo4j) và nới các phép khẳng định của 6a thành "tập con". — Trả lời: đồng ý cả ba sửa kéo theo (người dùng quyết, 2026-10-13).
- [x] Q8. Có đưa `provider: fake` vào config không? — đề xuất mặc định: có — `assistant.provider: ollama | fake`; `fake` dùng `FakeLLM` để test CLI và 8e chạy không cần Ollama, luôn in cảnh báo stderr và ghi `embed_model = fake-embed` vào `KnowledgeState` / audit. Phương án thay thế: `FakeLLM` chỉ tồn tại trong test (CLI không bao giờ chạy được khi Ollama tắt và cache trống). — Trả lời: theo đề xuất mặc định, người dùng duyệt cùng spec.
- [x] Q9. `aml rag build` ghi audit thế nào? — đề xuất mặc định: **một dòng `KNOWLEDGE_BUILD_COMPLETED` mỗi lần build** kèm số đếm và phiên bản; lý do của từng liên kết typology nằm trong thuộc tính `reason` / `rule_ids` / `alert_keys` của quan hệ và dựng lại được từ bảng case; không bảng mới. Phương án thay thế: một dòng audit cho mỗi liên kết `MATCHES_TYPOLOGY` (272 dòng mỗi lần build trên `small`, lặp lại mỗi lần chạy), hoặc bảng `case_typology_matches` trong system of record. — Trả lời: theo đề xuất mặc định, người dùng duyệt cùng spec.
- [x] Q10. Có thêm gói `neo4j-graphrag` (brief: "use where it fits") hoặc `httpx` ở 8a không? — đề xuất mặc định: **không** — client HTTP dùng `urllib` của thư viện chuẩn (như `aml.common.services`), chunk và ghi đồ thị tự viết (khoảng vài trăm dòng, đi qua đúng đường ghi `.cypher` đã có guard). Lý do: `neo4j-graphrag` tự ghi Cypher bằng driver, đi vòng qua `run_write_file`, và kéo thêm phụ thuộc; 8b tự quyết có dùng retriever của gói đó trên index `chunk_embedding` hay không (tên index và thuộc tính `embedding` / `text` đã theo quy ước gói đó đọc được). Phương án thay thế: dùng pipeline của gói đó cho cả việc nạp. — Trả lời: người dùng chọn **dùng `neo4j-graphrag` cho vector retriever ở 8b** (2026-10-13); 8b thêm gói đó vào `pyproject.toml`. 8a giữ nguyên phần của mình: tự chunk, ghi qua file `.cypher`, client HTTP bằng `urllib`; 8a không thêm và không cấm gói nào.
