"""Typed configuration loaded from ``config.yaml`` with env-var overrides.

Secrets never live in ``config.yaml``: they come from the environment or from the
git-ignored ``.env`` file (real env vars win over ``.env``). The same ``.env`` is read by
docker-compose, so container and client credentials have a single source.

Override rules (applied in order):
1. ``AML__<SECTION>__<KEY>[__<SUBKEY>...]=value`` sets any nested key (YAML-parsed value).
2. Credential vars shared with docker-compose (see ``SECRET_ENV_MAP``).
3. ``DB_BACKEND=oracle|duckdb`` is a shortcut for ``db.backend``.
"""

from __future__ import annotations

import math
import os
import re
from datetime import date
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DOTENV_PATH = PROJECT_ROOT / ".env"
ENV_PREFIX = "AML__"
# Phase 8e: question types of the golden set and the retrieval modes that can be compared.
RAG_EVAL_TYPES = ("fact", "multi_hop", "typology", "unanswerable", "injection")
RAG_EVAL_MODES = ("graphrag", "vector")

# docker-compose variable -> config key path (raw strings, not YAML-parsed).
SECRET_ENV_MAP: dict[str, list[str]] = {
    "ORACLE_APP_USER": ["db", "oracle", "user"],
    "ORACLE_APP_PASSWORD": ["db", "oracle", "password"],
    "ORACLE_SYS_PASSWORD": ["db", "oracle", "admin_password"],
    "ORACLE_DEMO_PASSWORD": ["db", "oracle", "demo_password"],
    "NEO4J_PASSWORD": ["neo4j", "password"],
}


class OracleConfig(BaseModel):
    host: str
    port: int
    service: str
    user: str
    password: str
    admin_user: str = "system"
    admin_password: str = ""  # ORACLE_SYS_PASSWORD in .env; only `aml security-setup` uses it
    demo_password: str = ""  # ORACLE_DEMO_PASSWORD in .env; shared by the 4 demo users

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service}"


class DbConfig(BaseModel):
    backend: Literal["oracle", "duckdb"]
    duckdb_path: str
    oracle: OracleConfig
    fallback_to_duckdb: bool = True


class Neo4jConfig(BaseModel):
    uri: str
    user: str
    password: str
    database: str = "neo4j"
    read_procedures: list[str] = []  # fnmatch patterns of procedures the read path may CALL
    read_timeout_seconds: float  # server-side timeout of every read-path query

    @model_validator(mode="after")
    def _timeout_positive(self) -> Neo4jConfig:
        if self.read_timeout_seconds <= 0:
            raise ValueError("neo4j read_timeout_seconds must be > 0")
        return self


class OllamaConfig(BaseModel):
    host: str
    llm_model: str
    embed_model: str


class ProfileConfig(BaseModel):
    customers: int
    transactions: int
    months: int
    counterparties: tuple[int, int]
    typology_scale: int = 1  # multiplies every data.typologies count


class WatchlistConfig(BaseModel):
    entries: int  # total watchlist rows (true hits and traps included)
    true_hits: int  # customers planted on the list (sanctions_hit / pep_hit)
    traps: int  # look-alike entries that match no customer (screening_trap)
    year_only_dob_rate: float  # share of entries with only a birth year
    unknown_dob_rate: float  # share of entries with no DOB information


class RiskMemoConfig(BaseModel):
    background_rate: float  # 0..0.05; share of background transfers given a gambling/crypto memo
    typology_rate: float  # 0..1; share of suspicious-scenario evidence transfers given that memo
    gambling_share: float  # 0..1; probability a planted memo is gambling-like (else crypto-like)

    @model_validator(mode="after")
    def _ranges(self) -> RiskMemoConfig:
        if not 0.0 <= self.background_rate <= 0.05:
            raise ValueError("risk_memos background_rate must be between 0 and 0.05")
        if not 0.0 <= self.typology_rate <= 1.0:
            raise ValueError("risk_memos typology_rate must be between 0 and 1")
        if not 0.0 <= self.gambling_share <= 1.0:
            raise ValueError("risk_memos gambling_share must be between 0 and 1")
        return self


class DataConfig(BaseModel):
    profile: Literal["small", "dense", "large"]
    output_dir: str
    reference_date: date
    start_date: date
    profiles: dict[str, ProfileConfig]
    duplicate_person_rate: float
    dq_defect_rate: float
    injection_memos: int
    risk_memos: RiskMemoConfig
    typologies: dict[str, int]  # scenarios injected per typology (before profile scaling)
    watchlist: WatchlistConfig

    @property
    def active(self) -> ProfileConfig:
        return self.profiles[self.profile]


class ThresholdConfig(BaseModel):
    large_cash_vnd: int
    structuring_band_pct: float


class AuditConfig(BaseModel):
    system_actor: str = "system"


class DqConfig(BaseModel):
    max_feed_lag_days: int  # TXN_FEED_STALE: allowed lag of the newest transaction behind as_of
    sample_size: int  # failing entity_ids (ascending) stored in dq_results.sample_ids


class RetentionConfig(BaseModel):
    transactions_months: int  # months kept in the hot table; must be >= the legal minimum (60)
    archive_dir: str  # root directory of the Parquet archive


class ScreeningConfig(BaseModel):
    token_set_weight: float  # weight of rapidfuzz token_set_ratio in the fuzzy score
    jaro_winkler_weight: float  # weight of Jaro-Winkler; the two weights must sum to 1.0
    token_match_min: float  # min Jaro-Winkler for two tokens to count as the same token
    token_length_band: int  # max length difference between two tokens that are compared
    rare_token_max_df_rate: float  # a token is "rare" when doc_freq / n_names <= this
    legal_strong_terms: list[str]  # legal-entity terms that cannot be person names; always dropped
    legal_weak_terms: list[str]  # ambiguous terms; dropped only if a strong term was dropped
    alert_threshold: float  # final_score >= this -> ALERT
    review_threshold: float  # final_score >= this -> REVIEW; also the recording threshold
    dob_tolerance_years: int  # birth-year gap <= this counts as a match
    dob_clear_years: int  # birth-year gap > this -> AUTO_CLEARED
    dob_gap_discount: float  # points off when the gap is in (tolerance, clear]
    nationality_mismatch_discount: float  # points off when both nationalities differ
    gender_mismatch_discount: float  # points off when both genders differ
    sql_length_band: int  # SQL screen: max length gap between two name keys that are compared

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> ScreeningConfig:
        if not math.isclose(self.token_set_weight + self.jaro_winkler_weight, 1.0):
            raise ValueError("screening token_set_weight + jaro_winkler_weight must sum to 1.0")
        return self

    @model_validator(mode="after")
    def _review_not_above_alert(self) -> ScreeningConfig:
        if self.review_threshold > self.alert_threshold:
            raise ValueError("screening review_threshold must not exceed alert_threshold")
        return self


class EntityResolutionConfig(BaseModel):
    match_threshold: float  # match_probability >= this -> MATCH (clustered)
    review_threshold: float  # >= this and < match_threshold -> REVIEW (stored, not clustered)
    name_jw_thresholds: tuple[float, float]  # two Jaro-Winkler levels on name_key, descending
    deterministic_recall: float  # assumed recall of the deterministic rules (prior estimate)
    u_max_pairs: int  # max random pairs used to estimate u
    m_probabilities: dict[str, list[float]]  # comparison -> m per level (null level excluded)

    @model_validator(mode="after")
    def _review_not_above_match(self) -> EntityResolutionConfig:
        if self.review_threshold > self.match_threshold:
            raise ValueError("entity_resolution review_threshold must not exceed match_threshold")
        return self

    @model_validator(mode="after")
    def _m_sums_to_one(self) -> EntityResolutionConfig:
        for name, values in self.m_probabilities.items():
            if not math.isclose(sum(values), 1.0):
                raise ValueError(f"entity_resolution m_probabilities.{name} must sum to 1.0")
        return self


class StructuringRuleConfig(BaseModel):
    window_days: int  # sliding window for counting deposits
    min_deposits: int  # near-threshold cash deposits in the window -> alert


class RapidMovementRuleConfig(BaseModel):
    window_hours: int  # sliding window from each inflow
    min_inflow_vnd: int  # total inflow in the window must reach this
    min_pass_through_pct: float  # share of the inflow sent out in the window, in (0, 1]

    @model_validator(mode="after")
    def _pct_in_range(self) -> RapidMovementRuleConfig:
        if not 0 < self.min_pass_through_pct <= 1:
            raise ValueError("monitoring min_pass_through_pct must be in (0, 1]")
        return self


class HighVelocityRuleConfig(BaseModel):
    window_hours: int  # sliding window
    min_txns: int  # transactions with new counterparties in the window -> alert
    min_total_vnd: int  # and their total must reach this


class FanRuleConfig(BaseModel):
    window_days: int  # sliding window
    min_counterparties: int  # distinct new counterparties in the window -> alert
    min_total_vnd: int  # and the total must reach this


class DormantRuleConfig(BaseModel):
    dormant_days: int  # quiet period before a transaction counts as reactivation
    window_hours: int  # activity window after the reactivating transaction
    min_amount_vnd: int  # total moved in the window must reach this


class MonitoringConfig(BaseModel):
    known_counterparty_days: int  # HIGH_VELOCITY / FAN_*: skip counterparties seen this long ago
    structuring: StructuringRuleConfig
    rapid_movement: RapidMovementRuleConfig
    high_velocity: HighVelocityRuleConfig
    fan_in_out: FanRuleConfig
    dormant_reactivation: DormantRuleConfig

    @model_validator(mode="after")
    def _known_days_positive(self) -> MonitoringConfig:
        if self.known_counterparty_days < 1:
            raise ValueError("monitoring known_counterparty_days must be >= 1")
        return self


class TraceConfig(BaseModel):
    default_hops: int  # N when the caller gives none
    default_hours: int  # T when the caller gives none
    max_hops: int  # ceiling of N; pgq.sql has 6 blocks, so it cannot exceed 6
    max_hours: int  # ceiling of T (bounds the number of paths)
    max_paths: int  # more rows than this -> TraceError, never a silent cut
    edge_min_amount_vnd: int  # cte_edge: drop daily edges whose total_amount is below this
    edge_top_k: int  # cte_edge: daily edges followed at each step; 0 = unlimited

    @model_validator(mode="after")
    def _limits_in_range(self) -> TraceConfig:
        if not 1 <= self.max_hops <= 6:
            raise ValueError("trace max_hops must be between 1 and 6")
        if not 1 <= self.default_hops <= self.max_hops:
            raise ValueError("trace default_hops must be between 1 and max_hops")
        if not 1 <= self.default_hours <= self.max_hours:
            raise ValueError("trace default_hours must be between 1 and max_hours")
        if self.max_paths < 1 or self.edge_min_amount_vnd < 0 or self.edge_top_k < 0:
            raise ValueError("trace max_paths must be >= 1; edge_min_amount_vnd, edge_top_k >= 0")
        return self


class BenchConfig(BaseModel):
    hops: list[int]  # not empty, increasing, each 1..trace.max_hops
    hours: list[int]  # not empty, increasing, each 1..trace.max_hours
    runs: int  # timed runs per cell; >= 5
    warmup_runs: int  # runs thrown away before the timed ones; >= 0
    accounts: list[str]  # empty -> pick_accounts chooses
    top_accounts: int  # how many accounts pick_accounts chooses; 1..10
    results_dir: str

    @model_validator(mode="after")
    def _in_range(self) -> BenchConfig:
        for name in ("hops", "hours"):
            values = getattr(self, name)
            if not values:
                raise ValueError(f"bench {name} must not be empty")
            if any(a >= b for a, b in pairwise(values)):
                raise ValueError(f"bench {name} must be increasing")
        if self.runs < 5:
            raise ValueError("bench runs must be >= 5")
        if self.warmup_runs < 0:
            raise ValueError("bench warmup_runs must be >= 0")
        if not 1 <= self.top_accounts <= 10:
            raise ValueError("bench top_accounts must be between 1 and 10")
        return self


class SharedAttributeConfig(BaseModel):
    min_customers: int  # a cluster needs this many golden customers to raise an alert
    max_customers_per_value: int  # a value shared by more customers than this is ignored

    @model_validator(mode="after")
    def _in_range(self) -> SharedAttributeConfig:
        if self.min_customers < 2:
            raise ValueError("network shared_attributes min_customers must be >= 2")
        if self.max_customers_per_value < 2:
            raise ValueError("network shared_attributes max_customers_per_value must be >= 2")
        return self


class CycleConfig(BaseModel):
    min_length: int  # fewest hops in a cycle
    max_length: int  # most hops in a cycle (the search is exponential beyond 6)
    window_hours: int  # the last hop must happen before first hop + window
    min_amount_vnd: int  # transfers below this are ignored
    min_amount_ratio: float  # smallest / largest transfer of a cycle must reach this
    max_search_steps: int  # more steps than this -> NetworkError, never a silent cut

    @model_validator(mode="after")
    def _in_range(self) -> CycleConfig:
        if self.min_length < 3:
            raise ValueError("network cycles min_length must be >= 3")
        if self.max_length < self.min_length:
            raise ValueError("network cycles max_length must be >= min_length")
        if self.max_length > 6:
            raise ValueError("network cycles max_length must be <= 6")
        if not 0 <= self.min_amount_ratio <= 1:
            raise ValueError("network cycles min_amount_ratio must be in [0, 1]")
        if self.window_hours < 1 or self.min_amount_vnd < 0 or self.max_search_steps < 1:
            raise ValueError(
                "network cycles window_hours, max_search_steps must be >= 1; min_amount_vnd >= 0"
            )
        return self


class HubConfig(BaseModel):
    lookback_days: int  # graph built from transfers in this many days before the cutoff
    min_in_degree: int
    min_pagerank_ratio: float  # pagerank * number of accounts with an edge
    min_inflow_vnd: int
    pagerank_alpha: float

    @model_validator(mode="after")
    def _in_range(self) -> HubConfig:
        if self.lookback_days < 1 or self.min_in_degree < 1:
            raise ValueError("network hubs lookback_days, min_in_degree must be >= 1")
        if not 0 < self.pagerank_alpha < 1:
            raise ValueError("network hubs pagerank_alpha must be in (0, 1)")
        if self.min_pagerank_ratio < 0 or self.min_inflow_vnd < 0:
            raise ValueError("network hubs min_pagerank_ratio, min_inflow_vnd must be >= 0")
        return self


class NetworkConfig(BaseModel):
    shared_attributes: SharedAttributeConfig
    cycles: CycleConfig
    hubs: HubConfig


class GraphSyncConfig(BaseModel):
    oracle_user: str  # read-only user; its password is db.oracle.demo_password
    batch_size: int  # rows per UNWIND = one Neo4j transaction
    overlap_minutes: int  # incremental sync re-reads from (watermark - overlap)

    @model_validator(mode="after")
    def _in_range(self) -> GraphSyncConfig:
        if not 1 <= self.batch_size <= 50000:
            raise ValueError("graph_sync batch_size must be between 1 and 50000")
        if self.overlap_minutes < 0:
            raise ValueError("graph_sync overlap_minutes must be >= 0")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,29}", self.oracle_user):
            raise ValueError("graph_sync oracle_user must be a plain identifier")
        return self


class GraphQueryConfig(BaseModel):
    max_rows: int  # run_query: more rows than this is an error, never a silent cut

    @model_validator(mode="after")
    def _in_range(self) -> GraphQueryConfig:
        if self.max_rows < 1:
            raise ValueError("graph_queries max_rows must be >= 1")
        return self


class GdsConfig(BaseModel):
    procedures: list[str]  # fnmatch patterns the GDS runner's own .cypher files may CALL
    graph_prefix: str  # in-memory graph names are <prefix>_accounts, ...
    concurrency: int  # GDS threads; 1 keeps results reproducible
    pagerank_max_iterations: int
    pagerank_tolerance: float
    louvain_max_levels: int
    louvain_max_iterations: int
    louvain_tolerance: float

    @model_validator(mode="after")
    def _in_range(self) -> GdsConfig:
        if not 1 <= self.concurrency <= 4:
            raise ValueError("gds concurrency must be between 1 and 4")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,29}", self.graph_prefix):
            raise ValueError("gds graph_prefix must be a plain identifier")
        if self.pagerank_tolerance <= 0:
            raise ValueError("gds pagerank_tolerance must be > 0")
        if (
            min(self.pagerank_max_iterations, self.louvain_max_levels, self.louvain_max_iterations)
            < 1
        ):
            raise ValueError("gds iteration and level limits must be >= 1")
        if self.louvain_tolerance < 0:
            raise ValueError("gds louvain_tolerance must be >= 0")
        return self


class SuppressionConfig(BaseModel):
    good_guy_days: int  # a good-guy row lasts this many days from the day the case was cleared
    hibernation_days: int  # a pattern sleeps this many days from its latest clearance
    hibernation_min_false_positives: int  # cleared alerts of a pattern before it starts to sleep
    material_change_ratio: float  # amount above ratio x the largest cleared alert wakes the pattern

    @model_validator(mode="after")
    def _in_range(self) -> SuppressionConfig:
        if self.good_guy_days < 1:
            raise ValueError("good_guy_days must be >= 1")
        if self.hibernation_days < 1:
            raise ValueError("hibernation_days must be >= 1")
        if self.hibernation_min_false_positives < 1:
            raise ValueError("hibernation_min_false_positives must be >= 1")
        if self.material_change_ratio < 1.0:
            raise ValueError("material_change_ratio must be >= 1.0")
        return self


class LogRegConfig(BaseModel):
    c: float  # inverse regularisation strength
    max_iter: int

    @model_validator(mode="after")
    def _in_range(self) -> LogRegConfig:
        if self.c <= 0:
            raise ValueError("logreg c must be > 0")
        if self.max_iter < 1:
            raise ValueError("logreg max_iter must be >= 1")
        return self


class LightGbmConfig(BaseModel):
    n_estimators: int
    num_leaves: int
    learning_rate: float
    min_child_samples: int

    @model_validator(mode="after")
    def _in_range(self) -> LightGbmConfig:
        if min(self.n_estimators, self.num_leaves, self.min_child_samples) < 1:
            raise ValueError("lightgbm n_estimators, num_leaves and min_child_samples must be >= 1")
        if self.learning_rate <= 0:
            raise ValueError("lightgbm learning_rate must be > 0")
        return self


class PrioritizationConfig(BaseModel):
    model: Literal["logreg", "lightgbm"]
    simulate_dispositions: bool  # does `aml score` run the simulation step
    simulate_fraction: float  # share of the case groups that get a simulated disposition
    simulated_actor: str  # actor of the simulated dispositions; differs from audit.system_actor
    cv_folds: int
    top_features: int  # contributing features stored with each score
    top_fractions: list[float]  # head / tail shares of the queue used for precision and recall
    logreg: LogRegConfig
    lightgbm: LightGbmConfig

    @model_validator(mode="after")
    def _in_range(self) -> PrioritizationConfig:
        if not 0 < self.simulate_fraction <= 1:
            raise ValueError("simulate_fraction must be in (0, 1]")
        if self.cv_folds < 2:
            raise ValueError("cv_folds must be >= 2")
        if self.top_features < 1:
            raise ValueError("top_features must be >= 1")
        if not self.top_fractions or any(not 0 < f <= 1 for f in self.top_fractions):
            raise ValueError("top_fractions must be a non-empty list of values in (0, 1]")
        return self


class SummaryConfig(BaseModel):
    generator: str  # registered NarrativeGenerator name; Phase 8 adds an LLM-backed one
    language: str  # the template generator only knows "en"


class CasesConfig(BaseModel):
    window_days: int  # a case window is anchored on its first alert and spans this many days
    txn_summary_days: int  # transaction summary ends on the day of the case's last alert
    top_counterparties: int  # largest counterparties kept in the network enrichment
    graph_features: Literal["auto", "networkx", "gds"]  # which account feature table to read
    suppression: SuppressionConfig
    prioritization: PrioritizationConfig
    summary: SummaryConfig

    @model_validator(mode="after")
    def _in_range(self) -> CasesConfig:
        if self.window_days < 1:
            raise ValueError("cases window_days must be >= 1")
        if self.txn_summary_days < 1:
            raise ValueError("cases txn_summary_days must be >= 1")
        if self.top_counterparties < 0:
            raise ValueError("cases top_counterparties must be >= 0")
        return self


class LlmCacheConfig(BaseModel):
    enabled: bool
    dir: str  # git-ignored under data/


class EmbeddingConfig(BaseModel):
    dimensions: int = Field(ge=1, le=4096)  # bge-m3 = 1024
    batch_size: int = Field(ge=1, le=256)  # texts per /api/embed call


class KnowledgeConfig(BaseModel):
    dir: str
    chunk_max_chars: int = Field(ge=200)


def _check_ranges(model: BaseModel, ranges: dict[str, tuple[float, float]]) -> None:
    """Raise ``<field> must be between <low> and <high>`` for the first field out of range."""
    for name, (low, high) in ranges.items():
        if not low <= getattr(model, name) <= high:
            raise ValueError(f"{name} must be between {low} and {high}")


class RetrievalConfig(BaseModel):  # Phase 8b
    hops: int  # depth of the case graph retriever
    max_transfers: int  # transfers listed for a case
    max_shared: int  # "shares an attribute" facts
    include_memos: bool  # read memos from the system of record for the listed transactions
    max_untrusted_chars: int  # cut for memo / alert reason / names
    max_chunk_chars: int  # cut for chunk text
    top_k: int  # chunks of the vector search
    min_score: float  # chunks below this score are dropped
    max_linked_per_chunk: int  # knowledge nodes fetched per chunk
    max_typology_chunks: int  # extra chunks per typology of the case
    max_context_chars: int  # ceiling of len(render_evidence(...)) returned by retrieve()

    @model_validator(mode="after")
    def _in_range(self) -> RetrievalConfig:
        _check_ranges(
            self,
            {
                "hops": (1, 3),
                "max_transfers": (1, 200),
                "max_shared": (0, 50),
                "max_untrusted_chars": (20, 2000),
                "max_chunk_chars": (200, 8000),
                "top_k": (1, 20),
                "min_score": (0, 1),
                "max_linked_per_chunk": (0, 20),
                "max_typology_chunks": (0, 10),
                "max_context_chars": (500, 100000),
            },
        )
        return self


class Text2CypherConfig(BaseModel):  # Phase 8b
    enabled: bool
    max_rows: int  # LIMIT forced on every generated query
    timeout_seconds: float  # server-side timeout of a generated query
    max_path_length: int  # upper bound of a variable-length pattern
    max_query_chars: int
    max_attempts: int  # generations per question

    @model_validator(mode="after")
    def _in_range(self) -> Text2CypherConfig:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        _check_ranges(
            self,
            {
                "max_rows": (1, 200),
                "max_path_length": (1, 5),
                "max_query_chars": (100, 10000),
                "max_attempts": (1, 3),
            },
        )
        return self


class AssistantConfig(BaseModel):
    provider: Literal["ollama", "fake"]
    request_timeout_seconds: float = Field(gt=0)
    num_ctx: int = Field(ge=512)  # context window sent to Ollama on every chat call
    keep_alive_chat: str  # passed verbatim to Ollama
    keep_alive_embed: str
    cache: LlmCacheConfig
    embedding: EmbeddingConfig
    knowledge: KnowledgeConfig
    vector_procedures: list[
        str
    ]  # separate allow-list for vector queries; not neo4j.read_procedures
    retrieval: RetrievalConfig  # Phase 8b
    text2cypher: Text2CypherConfig  # Phase 8b


class RagEvalConfig(BaseModel):
    questions: dict[str, int]  # exactly the keys of RAG_EVAL_TYPES, each >= 0, total >= 1
    english_per_type: int  # >= 0; the last N questions of each type are asked in English
    modes: list[str]  # not empty, no repeats, each one of RAG_EVAL_MODES
    results_dir: str

    @model_validator(mode="after")
    def _in_range(self) -> RagEvalConfig:
        if set(self.questions) != set(RAG_EVAL_TYPES):
            raise ValueError(f"rag_eval questions must have exactly the keys {RAG_EVAL_TYPES}")
        if any(n < 0 for n in self.questions.values()):
            raise ValueError("rag_eval questions must be >= 0")
        if sum(self.questions.values()) < 1:
            raise ValueError("rag_eval questions must ask at least one question")
        if self.english_per_type < 0:
            raise ValueError("rag_eval english_per_type must be >= 0")
        if not self.modes:
            raise ValueError("rag_eval modes must not be empty")
        for mode in self.modes:
            if mode not in RAG_EVAL_MODES:
                raise ValueError(f"rag_eval: unknown mode {mode!r}")
        if len(set(self.modes)) != len(self.modes):
            raise ValueError("rag_eval modes must not repeat")
        return self


class MemoConfig(BaseModel):  # Phase 8d
    max_chars: int  # a normalised memo is cut at this many characters
    max_retries: int  # extra calls when the model's reply is not a valid category
    max_llm_keys: int  # more memo keys than this need the LLM -> MemoError, never a silent cut
    features: Literal["auto", "off"]  # auto: training uses the memo columns once labels exist
    results_dir: str  # where `aml memo compare` / `aml memo eval` write their JSON
    gold_path: str  # default gold set of `aml memo eval`

    @model_validator(mode="before")
    @classmethod
    def _yaml_off(cls, raw: Any) -> Any:
        """YAML reads the bare word ``off`` as the boolean False; it means the string here."""
        if isinstance(raw, dict) and raw.get("features") is False:
            return {**raw, "features": "off"}
        return raw

    @model_validator(mode="after")
    def _in_range(self) -> MemoConfig:
        if self.max_chars < 20:
            raise ValueError("memo max_chars must be >= 20")
        if self.max_chars > 1000:  # the width of transactions.memo; memo_norm is VARCHAR(4000)
            raise ValueError("memo max_chars must be <= 1000")
        if not 0 <= self.max_retries <= 3:
            raise ValueError("memo max_retries must be between 0 and 3")
        if self.max_llm_keys < 1:
            raise ValueError("memo max_llm_keys must be >= 1")
        return self


class Settings(BaseModel):
    seed: int
    db: DbConfig
    neo4j: Neo4jConfig
    ollama: OllamaConfig
    data: DataConfig
    thresholds: ThresholdConfig
    audit: AuditConfig
    dq: DqConfig
    retention: RetentionConfig
    screening: ScreeningConfig
    entity_resolution: EntityResolutionConfig
    monitoring: MonitoringConfig
    trace: TraceConfig
    network: NetworkConfig
    graph_sync: GraphSyncConfig
    graph_queries: GraphQueryConfig
    gds: GdsConfig
    cases: CasesConfig
    assistant: AssistantConfig
    memo: MemoConfig
    bench: BenchConfig
    rag_eval: RagEvalConfig

    @model_validator(mode="after")
    def _bench_within_trace(self) -> Settings:
        """The benchmark may only ask trace() for values it accepts."""
        if any(not 1 <= h <= self.trace.max_hops for h in self.bench.hops):
            raise ValueError(f"bench hops must be between 1 and {self.trace.max_hops}")
        if any(not 1 <= h <= self.trace.max_hours for h in self.bench.hours):
            raise ValueError(f"bench hours must be between 1 and {self.trace.max_hours}")
        return self

    @model_validator(mode="after")
    def _simulated_actor_is_not_the_system(self) -> Settings:
        if self.cases.prioritization.simulated_actor == self.audit.system_actor:
            raise ValueError("simulated_actor must differ from audit.system_actor")
        return self

    def path(self, relative: str) -> Path:
        """Resolve a config path relative to the project root."""
        p = Path(relative)
        return p if p.is_absolute() else PROJECT_ROOT / p


def _set_nested(tree: dict[str, Any], keys: list[str], value: Any) -> None:
    node = tree
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def apply_env_overrides(raw: dict[str, Any], environ: dict[str, str]) -> dict[str, Any]:
    """Return ``raw`` with env-var overrides applied (mutates and returns ``raw``)."""
    for name, value in environ.items():
        if name.startswith(ENV_PREFIX):
            keys = [k.lower() for k in name[len(ENV_PREFIX) :].split("__") if k]
            if keys:
                _set_nested(raw, keys, yaml.safe_load(value))
    for name, keys in SECRET_ENV_MAP.items():
        if value := environ.get(name):
            _set_nested(raw, keys, value)
    if backend := environ.get("DB_BACKEND"):
        _set_nested(raw, ["db", "backend"], backend.strip().lower())
    return raw


def read_environ(dotenv_path: Path = DOTENV_PATH) -> dict[str, str]:
    """Process env layered over ``.env`` (process env wins, like docker-compose)."""
    merged = {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
    merged.update(os.environ)
    return merged


def load_settings(
    path: Path = DEFAULT_CONFIG_PATH, environ: dict[str, str] | None = None
) -> Settings:
    """Load and validate settings from YAML plus environment (default: env + ``.env``)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = apply_env_overrides(raw, read_environ() if environ is None else environ)
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings."""
    return load_settings()
