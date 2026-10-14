/** Shape of GET /api/v1/benchmark. */
export interface BenchCell {
  method: string;
  account: string;
  hours: number;
  hops: number;
  status: "ok" | "skipped" | "error";
  reason: string | null;
  exact: boolean;
  runs: number;
  median_ms: number | null;
  p95_ms: number | null;
  min_ms: number | null;
  max_ms: number | null;
  n_paths: number | null;
  n_accounts: number | null;
  n_cycles: number | null;
  query_lines: number | null;
}

export interface BenchRun {
  file: string;
  meta: Record<string, unknown>;
  cells: BenchCell[];
  mismatches: string[];
}

export interface BenchData {
  runs: BenchRun[];
  notes: string[];
}
