/** Shapes of GET /api/v1/dq/results and /api/v1/dq/trend. */
export type DqStatus = "PASS" | "FAIL" | "NO_DATA";

export interface DqResult {
  rule_id: string;
  table_name: string;
  dimension: string;
  scope: string;
  description: string;
  max_fail_rate: number;
  total_rows: number;
  failed_rows: number;
  fail_rate: number | null;
  status: DqStatus;
  sample_ids: (string | number)[];
  prev_failed_rows: number | null;
  delta_failed_rows: number | null;
}

export interface DqResultsMeta {
  run_id: number | null;
  as_of: string | null;
  run_ts: string | null;
  rules: number;
  passed: number;
  failed: number;
  no_data: number;
}

export interface DqTrendPoint {
  rule_id: string;
  table_name: string;
  dimension: string;
  run_id: number;
  run_ts: string;
  failed_rows: number;
  fail_rate: number | null;
  status: DqStatus;
  prev_failed_rows: number | null;
  delta_failed_rows: number | null;
}

export interface DqTrendMeta {
  runs: number[];
  rules: number;
}
