export type Source = "live" | "mock";

export interface Envelope<T> {
  source: Source;
  feature: string;
  data: T;
  meta: Record<string, unknown>;
}

export type DispositionValue = "SUSPICIOUS" | "FALSE_POSITIVE";

/** The 3-field summary a row of the case queue carries. */
export interface DispositionSummary {
  disposition: string;
  actor: string;
  decided_on: string;
}

/** The full decision of a case (7 fields), as in GET /cases/{id}. */
export interface Disposition {
  disposition_id: number;
  disposition: string;
  reason: string;
  actor: string;
  origin: string;
  decided_on: string;
  run_id: number;
}

export interface CaseRow {
  case_id: string;
  golden_customer_id: string;
  status: string;
  alerts: number;
  rule_alerts: number;
  network_alerts: number;
  screening_alerts: number;
  sources: string[];
  window_start: string;
  first_alert_ts: string;
  last_alert_ts: string;
  reason: string;
  disposition: DispositionSummary | null;
}

export interface SystemStatus {
  backend: string;
  profile: string;
  seed: number;
  reference_date: string;
  mock: Record<string, boolean>;
  case_run: { run_id: string; as_of: string; cases: number } | null;
}

export interface UserRef {
  actor: string;
  role: string;
}

export interface Me extends UserRef {
  pii: "masked" | "full";
  users: UserRef[];
}

export interface SampleData {
  items: { id: string; label: string; value: number | string }[];
}

export interface CaseAlert {
  item_key: string;
  source: string;
  rule_id: string;
  alert_ref: string;
  cif: string;
  event_ts: string;
  end_ts: string;
  amount_vnd: number;
  reason: string;
}

export interface KycCustomer {
  cif: string;
  kyc_risk: string | null;
  occupation: string | null;
  nationality: string | null;
  gender: string | null;
  birth_year: number | null;
  id_type: string | null;
}

export interface KycBlock {
  risk_rating: string | null;
  cifs: KycCustomer[];
}

export interface LinkedAccount {
  account_id: string;
  cif: string;
  account_type: string | null;
  open_date: string | null;
}

export interface LinkedCifsBlock {
  cluster_size: number;
  cifs: string[];
  accounts: LinkedAccount[];
  er: { pairs: number; min_match_weight: number | null } | null;
}

export interface DqIssuesBlock {
  customer: { cif: string; rule_id: string; dimension: string | null }[];
  transactions: Record<string, number>;
}

export interface TxnSummaryBlock {
  window_start: string;
  window_end: string;
  txn_count: number;
  in_count: number;
  out_count: number;
  in_vnd: number;
  out_vnd: number;
  cash_in_vnd: number;
  cash_out_vnd: number;
  counterparties: number;
  max_txn_vnd: number;
  active_days: number;
  by_channel: Record<string, { count: number; vnd: number }>;
}

export interface Counterparty {
  account_id: string;
  golden_customer_id: string | null;
  direction: string;
  txns: number;
  vnd: number;
}

export interface NetworkBlock {
  source: string;
  features: Record<string, number | string | null>;
  counterparties: Counterparty[];
  shared_alert_cases: string[];
}

export interface HistoryBlock {
  prior_cases: {
    case_id: string;
    first_alert_ts: string | null;
    alerts: number;
    disposition: string | null;
    decided_on: string | null;
  }[];
  prior_alerts: number;
  screening_auto_cleared: number;
  suppressed_items: number;
}

export interface CaseEnrichment {
  kyc: KycBlock;
  linked_cifs: LinkedCifsBlock;
  dq_issues: DqIssuesBlock;
  txn_summary: TxnSummaryBlock;
  network: NetworkBlock;
  history: HistoryBlock;
}

export interface CaseDetail {
  case_id: string;
  run_id: number;
  golden_customer_id: string;
  status: string;
  window_start: string;
  first_alert_ts: string;
  last_alert_ts: string;
  reason: string;
  alerts: CaseAlert[];
  enrichment: CaseEnrichment;
  disposition: Disposition | null;
}
