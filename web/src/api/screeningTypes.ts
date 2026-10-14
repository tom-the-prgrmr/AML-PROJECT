export type SystemDecision = "ALERT" | "REVIEW" | "AUTO_CLEARED";
export type ReviewDecision = "TRUE_MATCH" | "FALSE_MATCH";

export interface HitCustomer {
  cif: string;
  full_name: string | null;
  birth_year: number | null;
  nationality: string | null;
  gender: string | null;
  id_type: string | null;
  id_number: string | null;
}

export interface HitReview {
  decision: ReviewDecision;
  reason: string;
  actor: string;
  decided_on: string;
}

export interface Hit {
  cif: string;
  entry_id: string;
  list_type: string | null;
  matched_name: string;
  matched_name_type: string;
  token_set: number;
  jaro_winkler: number;
  fuzzy_score: number;
  coverage: number;
  name_score: number;
  final_score: number;
  dob_gap_years: number | null;
  decision: SystemDecision;
  reason: string;
  run_id: number;
  customer: HitCustomer | null;
  review: HitReview | null;
  case_id: string | null;
}

export interface HitsMeta {
  pii: string;
  run_id: number | null;
  as_of: string | null;
  total: number;
  limit: number;
  offset: number;
  counts: Record<SystemDecision, number>;
  thresholds: { alert: number; review: number };
}
