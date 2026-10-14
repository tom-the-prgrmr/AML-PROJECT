/** Shapes of `data` for the Phase 9c endpoints (specs/ui-mock-pages.md, "Hợp đồng JSON"). */

// --- Priority scores (GET /cases/scores) ---
export interface TopFeature {
  feature: string;
  value: number;
  contribution: number;
}

export interface CaseScore {
  case_id: string;
  score: number;
  queue_rank: number | null;
  model_version: string;
  top_features: TopFeature[];
}

export interface CaseScores {
  run_id: number | null;
  score_run_id: number | null;
  model_version: string | null;
  queue: number;
  scores: CaseScore[];
}

// --- Case summary (GET /cases/{id}/summary) ---
export interface CaseSummary {
  case_id: string;
  markdown: string;
  generator: string;
  version: string;
  language: string;
  watermark: string;
  citations: string[];
}

// --- Assistant (POST /assistant/chat, /cases/{id}/narrative, GET /cases/{id}/typologies) ---
export type CitationKind = "node" | "transaction" | "chunk" | "alert";

export interface Citation {
  n: number;
  kind: CitationKind;
  id: string;
  label: string;
  node_ids: string[];
  txn_ids: string[];
  excerpt: string | null;
}

export interface Sentence {
  text: string;
  supported: boolean;
  citations: number[];
}

export type AnswerStatus = "answered" | "insufficient_evidence";

export interface Answer {
  answer_id: string;
  case_id: string;
  question: string;
  language: string;
  status: AnswerStatus;
  sentences: Sentence[];
  citations: Citation[];
  retrievers: string[];
  validation: { sentences: number; supported: number; unsupported: number };
  model: string;
  prompt_version: string;
}

export interface NarrativeText {
  case_id: string;
  markdown: string;
  generator: string;
  version: string;
  language: string;
  watermark: string;
  citations: string[];
}

export interface DraftNarrative {
  narrative: NarrativeText;
  citations: Citation[];
}

export interface TypologyTransaction {
  txn_id: string;
  txn_ts: string;
  from_account_id: string | null;
  to_account_id: string | null;
  amount_vnd: number;
  channel: string | null;
}

export interface TypologyChunk {
  chunk_id: string;
  title: string | null;
  excerpt: string | null;
}

export interface TypologyMatch {
  typology: string;
  rule_ids: string[];
  definition: string;
  transactions: TypologyTransaction[];
  chunks: TypologyChunk[];
  citations: Citation[];
}

export interface Typologies {
  case_id: string;
  typologies: TypologyMatch[];
}

export type Rating = "up" | "down";

export interface FeedbackResult {
  answer_id: string;
  rating: Rating;
  actor: string;
}

// --- Metrics ---
export interface Unavailable {
  part: string;
  message: string;
}

export interface Stage {
  tool: string;
  before_label: string;
  after_label: string;
  before: number | null;
  after: number | null;
  removed: number | null;
  reduction_pct: number | null;
  hours_saved: number | null;
}

export interface OriginCount {
  decided: number;
  suspicious: number;
  false_positive: number;
}

export interface CaseRunRef {
  run_id: number;
  as_of: string;
}

export interface Funnel {
  case_run: CaseRunRef | null;
  minutes_per_alert: number;
  stages: Stage[];
  total_hours_saved: number | null;
  conversion: {
    alert_to_case: {
      alerts: number | null;
      items: number | null;
      cases: number | null;
      cases_per_alert: number | null;
    };
    case_to_suspicious: OriginCount & {
      rate: number | null;
      by_origin: Record<string, OriginCount>;
    };
  };
  unavailable: Unavailable[];
}

export interface DetectionRow {
  source: string;
  detection: string;
  baseline: boolean;
  target_typology: string | null;
  alerts: number | null;
  true_positives: number | null;
  false_positives: number | null;
  fp_rate: number | null;
  precision: number | null;
  recall: number | null;
  scenarios: number | null;
  detected: number | null;
}

export interface Detections {
  rows: DetectionRow[];
  unavailable: Unavailable[];
}

export type AutoClearedTruth = "TRUE_HIT" | "NOT_A_HIT";

export interface AutoClearedRow {
  cif: string;
  entry_id: string;
  list_type: string;
  final_score: number;
  reason: string;
  truth: AutoClearedTruth | null;
}

export interface AutoClearedMetrics {
  population: number;
  ground_truth_available: boolean;
  true_hits_in_population: number | null;
  seed: number;
  sample_size: number;
  true_hits_in_sample: number | null;
  sample: AutoClearedRow[];
}

export type SuppressionTruth = "SUSPICIOUS" | "NOT_SUSPICIOUS";

export interface SuppressionRow {
  item_key: string;
  golden_customer_id: string;
  source: string;
  rule_id: string;
  suppression_rule: string;
  suppression_reason: string;
  truth: SuppressionTruth | null;
}

export interface SuppressionMetrics {
  case_run: CaseRunRef | null;
  minutes_per_alert: number;
  stage: Stage | null;
  by_rule: Record<string, number> | null;
  population: number;
  ground_truth_available: boolean;
  suspicious_suppressed: number | null;
  seed: number;
  sample_size: number;
  sample: SuppressionRow[];
  unavailable: Unavailable[];
}
