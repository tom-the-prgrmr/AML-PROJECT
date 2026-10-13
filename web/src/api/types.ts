export type Source = "live" | "mock";

export interface Envelope<T> {
  source: Source;
  feature: string;
  data: T;
  meta: Record<string, unknown>;
}

export interface Disposition {
  disposition: string;
  actor: string;
  decided_on: string;
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
  disposition: Disposition | null;
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
  pii: boolean;
  users: UserRef[];
}

export interface SampleData {
  items: { id: string; label: string; value: number | string }[];
}
