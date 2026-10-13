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

Everything below is copied from `results/phase6/bench_report.md`, which `aml bench` built from four runs on
2026-10-13 (commit `ab5536f`, one dev machine with 12 logical CPUs, Oracle 23.26.3 and Neo4j 5.26.31 Community in
local Docker containers, 1 warm-up and 10 timed runs per cell). Both profiles hold 306,000 transactions; the
account was picked automatically as the heaviest case of its profile. The chart is
`results/phase6/bench_chart.svg`.

The four runs, each after `aml graph sync --full` and one `aml graph sync` from the backend being measured:

```powershell
$env:DB_BACKEND = "oracle"; uv run aml bench --profile small    # and again with the dense profile loaded
$env:DB_BACKEND = "duckdb"; uv run aml bench --profile small    # and again on a DuckDB file holding dense
```

Median ms on **Oracle** (all four methods on the same data; the graph was synced from Oracle):

| profile, account | T (h) | hops | paths | `cte_raw` | `pgq` | `neo4j` | `cte_edge` (approximate) |
|---|---|---|---|---|---|---|---|
| small, `A5461833942` | 72 | 2 | 632 | 13.7 | 25.2 | 43.5 | 4.6 |
| small | 72 | 4 | 658 | 15.3 | 182.8 | 45.2 | 4.5 |
| small | 72 | 6 | 658 | 16.2 | 7537.7 | 44.5 | 5.0 |
| small | 720 | 2 | 4,289 | 43.6 | 48.6 | 226.0 | 4.9 |
| small | 720 | 4 | 10,955 | 160.7 | 262.8 | 577.6 | 4.6 |
| small | 720 | 6 | 22,394 | 405.3 | 7588.8 | 1184.1 | 4.8 |
| dense, `A4173555232` | 72 | 2 | 94 | 6.0 | 5.3 | 18.4 | 4.9 |
| dense | 72 | 4 | 112 | 7.2 | 146.1 | 17.7 | 4.5 |
| dense | 72 | 6 | 112 | 6.9 | 4375.1 | 18.0 | 4.2 |
| dense | 720 | 2 | 435 | 9.2 | 8.2 | 32.5 | 4.5 |
| dense | 720 | 4 | 4,098 | 73.4 | 174.7 | 226.3 | 4.4 |
| dense | 720 | 6 | 12,366 | 283.4 | 4542.9 | 663.8 | 4.4 |

Query lines: `cte_raw` 30, `cte_edge` 38, `pgq` 19 / 49 / 99 at 2 / 4 / 6 hops, `neo4j` 58 at every hop count.
The three exact methods returned the same number of paths in all 12 cells. p95 values, the two DuckDB runs
(`cte_raw` 19 to 141 ms, `neo4j` 15 to 1206 ms, `pgq` skipped) and every raw time are in the report and the JSON
files.

What the numbers say:

- **The recursive CTE on Oracle is the fastest exact method in 10 of the 12 cells** and within 1 ms of `pgq` in
  the other two (dense at 2 hops). It answers a 6-hop trace over a 30-day window in 283 to 405 ms for 12,366 to
  22,394 paths, and in 7 to 16 ms over the default 72-hour window.
- **`pgq` matches the CTE at 2 hops and falls behind as hops are added**: 146 to 263 ms at 4 hops and 4.4 to 7.6 s
  at 6 hops. The time follows the query, not the answer: 112 paths took 4.4 s. The query is one fixed-length
  `GRAPH_TABLE` block per hop count joined by `UNION ALL` (99 lines at 6 hops), and it was not tuned.
- **`neo4j` is 2.3 to 5.2 times slower than the CTE on Oracle** in every cell, but its time follows the size of
  the answer and not the hop count: flat at about 18 ms (dense) and 45 ms (small) over 72 hours, 0.66 to 1.18 s
  for the largest answers. At 6 hops it is 6 to 240 times faster than `pgq`.
- **`cte_edge` stays at 4 to 5 ms everywhere**, but it reads daily aggregates with a top-K cut and returns 5 to
  27 paths, so it is a triage view, not the same answer.
- **The `dense` profile did not make the trace harder.** Its heaviest account produced fewer paths than the one
  of `small` at every setting.

What it costs to run the graph projection (same runs):

| | small | dense |
|---|---|---|
| `aml graph sync --full` from Oracle | 42.11 s | 50.65 s |
| `aml graph sync` with nothing new, from Oracle | 2.12 s | 2.24 s |
| Projection size | 28,914 nodes, 443,051 relationships | 28,914 nodes, 474,737 relationships |

The Neo4j container used about 1.8 GiB of its 2.44 GiB limit after the runs (`docker stats`, one reading). The
other costs are facts about the product and this design, not measurements: Neo4j Community has no role-based
access control, no clustering and no online backup, so read-only access rests on READ sessions plus the
application guard; the projection is only as fresh as its last sync; and it is one more service to patch,
secure, monitor and audit.

## Conclusion

- **SQL is enough for fund-flow tracing at this scale.** A bounded, time-ordered trace out of one account is what
  a recursive CTE with a `CYCLE` clause does well: fastest in the benchmark, 30 lines, in the system of record,
  under its roles and audit policies, with no sync lag. Nothing in these numbers argues for moving the trace.
- **The in-database property graph helps with short, fixed-length patterns.** At 2 hops `pgq` was as fast as the
  CTE and the shortest query to read (19 lines), with no second system to run. For deeper or variable-length
  traces it was the slowest method here, so it is not a replacement for the CTE as written.
- **A separate graph database is not justified by trace speed.** It was slower than Oracle on every cell and
  costs a 42 to 51 s full sync, a second service and weaker access control. What it adds lies outside this
  benchmark: one Cypher file for any hop count, variable-length pattern queries such as cycles and
  shared-attribute clusters ([neo4j-queries.md](neo4j-queries.md)), and graph algorithms
  ([neo4j-gds.md](neo4j-gds.md)). At this data size even those have an in-process alternative (the NetworkX
  detections of Phase 5c produce the same degree and PageRank features), so the case for Neo4j here is
  interactive investigation, not capacity.
- **So the architecture stays as planned:** Oracle is the system of record for rules, traces and reporting, and
  the graph layer is an optional read-only projection for investigators.

Limits of this evidence: one machine, local containers, 306,000 transactions, one (heaviest) account per profile,
10 timed runs, and an untuned `pgq` query. A larger or much deeper graph could change the ranking; the benchmark
is one command to re-run when it does.
