# Trace benchmark (Phase 6c)

`aml bench` times the four fund-flow trace methods (`cte_raw`, `cte_edge`, `pgq`, `neo4j`) at 2, 4 and 6 hops
and writes the numbers to a result file, then builds a Markdown table and an SVG chart **from the result
files**. It measures the state a backend is in right now: it never generates data, loads data, runs entity
resolution or syncs Neo4j. It raises no alert and closes nothing. All data is synthetic.

## What is measured

One **cell** is one (account, window T, hops, method). Cells run one after another in the order account, T,
hops, method.

- **Warm-up.** Each cell first runs `bench.warmup_runs` calls (default 1) that are thrown away. The first call
  after a quiet period is clearly slower than later ones (plan compilation, cold caches, a new Neo4j session),
  so it would otherwise dominate a small number of runs. Cold-cache behaviour is not measured.
- **Timed runs.** Then `bench.runs` calls (default 10, at least 5) are timed, back to back.
- **Where the clock is.** Each call is `trace(..., record_audit=False)` and the time kept is
  `TraceResult.seconds`: the query, fetching the answer into a DataFrame, and normalising it (the sort). The
  `prepare` step of `neo4j` (the freshness check of the graph) runs before the clock starts and is **outside**
  the timing. `record_audit=False` means the hundreds of calls leave no `TRACED` rows.
- **Statistics.** `median_ms`, `p95_ms`, `min_ms`, `max_ms` come from the raw times, which are all kept in the
  file. p95 uses linear interpolation between the two nearest ranks at position `(n - 1) * 95 / 100`, the NumPy
  default. With 5 runs that is the fourth slowest time plus 0.8 of the gap to the slowest, and with 10 runs it
  is still close to the slowest. Below about 20 runs treat p95 as "nearly the worst run", not as a tail estimate.
- **Counts.** `n_paths`, `n_accounts`, `n_cycles` and `query_lines` come from the last timed run. `query_lines`
  is the number of non-blank, non-comment lines of the query that ran. It grows with the hop count for `pgq`
  (one `GRAPH_TABLE` block per hop) and is constant for `neo4j` (one Cypher file for all hops).
- **Accounts.** `bench.accounts` if it is not empty. Otherwise `pick_accounts` takes the `bench.top_accounts`
  internal accounts with the most time-ordered 2-hop transfer pairs inside the largest `bench.hours` (ties: the
  smaller `account_id`). The SQL is `sql/<backend>/bench/pick_accounts.sql`. This is the heaviest case, not a
  typical one: "most outgoing transfers" was rejected because on `dense` it picks a payroll account whose
  employees never pass the money on.
- **`cte_edge` is an approximation.** It follows daily edges and keeps the top-K per step, so its path count is
  not comparable with the other three. The report says so in the note column.

## Result files

Each run writes `bench_<profile>_<backend>.json` in `bench.results_dir` (default `results/phase6`), overwriting an
earlier run of the same pair. The file has `meta` (command, start time, commit, versions, machine, row counts of
the real data, run parameters, trace limits, and `sync` with the FULL / INCREMENTAL sync seconds and the lag from
`graph_sync_runs` when a `neo4j` cell ran) and `cells` (with the raw `seconds`). The profile label is only a
label: it comes from the newest `datagen` / `LOADED` audit row (`small-seed42` becomes `small`), `--profile`
overrides it, and `unknown` is used when there is none. The row counts in `meta.dataset` say what the data
really was.

`bench_report.md` and `bench_chart.svg` merge **every** result file in the directory. The chart has one panel per
(file, account) at the largest T, hops on the x axis and the median on a log y axis. The same files give the same
bytes. `aml bench --report-only` rebuilds both without touching a database or the audit log.

## Cell status

- `ok`: timed. The numbers are filled in.
- `skipped`: the method cannot run here, so there is no number. `pgq` on DuckDB (`not available on duckdb`),
  Neo4j not reachable (`neo4j not available: ...`), or a graph that is out of sync with its source (`graph is
  out of sync ...`). `prepare` is tried once per method; later cells of that method are skipped with the same
  reason.
- `error`: the method ran and failed: more than `trace.max_paths` rows, the Neo4j read timeout, or any other
  exception. The reason is `<ExceptionClass>: <message>`. A bad cell never stops the others, and the command still
  exits 0.

A run writes exactly one `BENCHMARKED` audit row (`module=graph`, `entity_type=benchmark`, with a readable
`reason` and the counts of ok / skipped / failed cells).

## Preparing a profile

The benchmark does not prepare anything, so prepare each profile yourself and run the benchmark once per
backend. For the Oracle run, with Oracle and Neo4j up and `ORACLE_*` passwords in `.env`:

```powershell
uv run aml data --profile small
$env:DB_BACKEND = "oracle"
uv run aml init-db
uv run aml load
uv run aml er
uv run aml security-setup
uv run aml graph sync --full
uv run aml bench --profile small
```

For the DuckDB run (three methods, no `pgq`), the same with `DB_BACKEND=duckdb`: load, `aml er`,
`aml graph sync --full` (the graph must be synced from that database), then `aml bench --profile small`. Repeat
with `--profile dense` after re-preparing. Loading a profile into Oracle replaces what was there, and a
`neo4j` cell is only valid when the projection was synced from the backend being measured.

Do not run `aml graph sync`, `aml load` or other heavy work while a benchmark is running. Useful options:
`AML__BENCH__HOURS="[72, 720]"`, `AML__BENCH__RUNS=10`, `AML__BENCH__ACCOUNTS='["A..."]'`.

## Limits

- One machine, one run per (profile, backend), one account by default. Read the numbers as "on this machine, for
  this account", not as a general ranking.
- DuckDB runs in-process; Oracle and Neo4j run in local Docker containers and are reached over `localhost`
  ports. Compare methods only inside one result file (same backend, same data, a graph synced from that backend),
  not DuckDB against Oracle.
- The SQL methods have no timeout. Neo4j has `neo4j.read_timeout_seconds`.
- `cte_edge` is approximate; Neo4j and GDS versions come from the Docker images in `docker-compose.yml`.
- `large` was not benchmarked, and `pgq` is not tuned: the benchmark measures what exists.

## Results

The measured table and chart are in `results/phase6/bench_report.md` and `results/phase6/bench_chart.svg`. They
are filled in after the real runs on `small` and `dense`; no number or conclusion is copied into this file until
then.
