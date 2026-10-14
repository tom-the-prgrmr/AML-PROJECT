/** Shapes of GET /trace/methods and GET /accounts/{id}/trace. */

export interface TraceMethodInfo {
  method: string;
  label: string;
  exact: boolean;
  uses_filters: boolean;
  available: boolean;
  reason: string | null;
}

export interface TraceMethodsMeta {
  backend: string;
  default_method: string;
  default_hops: number;
  default_hours: number;
  max_hops: number;
  max_hours: number;
}

export interface TracePath {
  hop: number;
  path: string;
  account_id: string;
  step_path: string;
  first_ts: string | null;
  last_ts: string | null;
  amount_vnd: number;
  is_cycle: boolean;
}

export interface TraceMeta {
  method: string;
  backend: string;
  exact: boolean;
  account_id: string;
  hops: number;
  hours: number;
  since: string | null;
  min_amount_vnd: number;
  top_k: number;
  n_paths: number;
  n_accounts: number;
  n_cycles: number;
  seconds: number;
  query_lines: number;
  total: number;
  limit: number;
  offset: number;
}

export interface TraceQuery {
  account: string;
  method: string;
  hops: number;
  hours: number;
  offset: number;
}
