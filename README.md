# AML Investigation Toolkit (interview demo)

Custom tools that reduce AML investigation effort, on **synthetic data only**:
Vietnamese-name screening, entity resolution, transaction monitoring, SQL-vs-graph network
analysis, alert consolidation/prioritization, and a local GraphRAG investigator assistant.
Oracle is the system of record; Neo4j is a read-only investigation projection.

> Status: **Phases 0 to 7 done** (scaffold through alert consolidation, suppression, prioritization and case summaries). Results tables are added phase by phase, each generated
> from an actual run with the command that produced it.

## Quick start

```powershell
uv sync                         # Python 3.11 env + deps
uv run aml status               # config + which optional services are up
uv run aml init-db              # base schema (audit_log) on DuckDB (default)

.\tasks.ps1 up -ComposeProfile oracle   # or: make up PROFILE=oracle
.\tasks.ps1 up -ComposeProfile llm -Gpu # Ollama on an NVIDIA GPU (make up PROFILE=llm GPU=1); omit -Gpu for CPU
$env:DB_BACKEND = "oracle"; uv run aml init-db
uv run pytest                   # Oracle/Neo4j/Ollama tests skip if the service is down
```

| Mode | Command | Docker RAM |
|---|---|---|
| DuckDB only | nothing to start | 0 |
| Oracle | `up -ComposeProfile oracle` | ~2.5 GB |
| Neo4j | `up -ComposeProfile graph` | ~2 GB |
| Full stack | `up -ComposeProfile full` | ≥ 8 GB |

Configuration lives in [config.yaml](config.yaml); override any key with
`AML__<SECTION>__<KEY>=value` or `DB_BACKEND=oracle|duckdb`.

## Fund-flow trace: SQL vs property graph vs Neo4j (Phase 6)

The same question ("trace money out of an account, N hops within T hours, time-ordered, no account twice") is
implemented four ways and timed by `uv run aml bench`. Median ms on Oracle for the heaviest account of the
`small` profile over a 30-day window, from the run of 2026-10-13 (10 timed runs per cell, one dev machine):

| hops | paths | recursive CTE (`cte_raw`) | Oracle SQL property graph (`pgq`) | Neo4j Cypher (`neo4j`) |
|---|---|---|---|---|
| 2 | 4,289 | 43.6 | 48.6 | 226.0 |
| 4 | 10,955 | 160.7 | 262.8 | 577.6 |
| 6 | 22,394 | 405.3 | 7588.8 | 1184.1 |

All three return the same number of paths in every cell. The recursive CTE is the fastest, the property graph is
close to it at 2 hops (within 1 ms to 1.8 times slower) and falls far behind with depth, and Neo4j is 2.3 to 5.2 times slower than the CTE across both profiles while costing a
42 to 51 s full sync and a second service. So Oracle stays the system of record for traces, and Neo4j is an
optional read-only projection for investigation (pattern queries, graph algorithms). The full tables for
`small` and `dense`, p95, the method, the limits and the reasoning are in
[docs/trace-benchmark.md](docs/trace-benchmark.md); the raw results are in
[results/phase6/](results/phase6/bench_report.md).

Related: [docs/neo4j-sync.md](docs/neo4j-sync.md) (sync, lag, consistency),
[docs/neo4j-queries.md](docs/neo4j-queries.md) (Cypher queries), [docs/neo4j-gds.md](docs/neo4j-gds.md) (GDS
features).

## Cases: consolidation, suppression, prioritization, summary (Phase 7)

Screening hits, rule alerts and network alerts are merged into **one case per golden customer** over a
90-day window, enriched so an investigator does not need another system (KYC, linked CIFs, data-quality
issues, 90-day activity, network features, prior cases), ranked by a model, and summarised in markdown
without an LLM. The numbers below come from one run on the `small` profile (DuckDB, `as_of` 2026-06-30,
seed 42) on 2026-10-13, starting from empty case tables:

```powershell
uv run aml cases build                                  # 339 alerts -> 475 items -> 335 cases
uv run aml score --eval-out results/phase7/eval.json    # build, simulate dispositions, rebuild, train, score
uv run aml cases suppressed                             # what suppression held back, with the reason
uv run aml cases summary --all --out-dir data/summaries # 309 markdown summaries
```

| Step | Result |
|---|---|
| Consolidation | 339 alerts became 475 case items (a group alert joins the case of every customer in it) and 335 cases |
| Simulated dispositions | 234 cases in 70% of the case groups were given the ground-truth outcome: 200 suspicious, 34 false positive; 101 cases stayed open |
| Suppression after those clearances | 36 screening items held back by the good-guy list, 0 by hibernation; 26 cases left the queue, 309 remained |
| Model `prio/logreg/1` (5 grouped folds, 234 cases) | ROC-AUC 0.9599, PR-AUC 0.9865 at 85.5% prevalence |
| Held-out queue (101 open cases, never trained on) | ROC-AUC 0.9868, PR-AUC 0.9985 at 90.1% prevalence; 8 of the 10 false positives are in the bottom 10% of the queue and all 10 in the bottom 20% |

Running `uv run aml score` a second time on the same data labelled 0 new cases and reproduced the same
queue and the same metrics.

How to read these numbers:

- **The model only ranks.** It never closes, clears or suppresses a case; every score is written to
  `audit_log` with the model version and its top contributing features. Closing a case takes a
  disposition, and only a disposition feeds the good-guy list.
- **The class imbalance is the reverse of production.** On this synthetic data the rules rarely fire on
  normal behaviour, so about 86% of cases are truly suspicious and the minority class is the false
  positive. With that prevalence a random ordering already has about 0.9 precision at the top, so the
  useful measure is how far down the queue the false positives are pushed, not precision at the top.
- **Metrics cover alerted cases only.** Customers who never raised an alert are not sampled, so this says
  nothing about what the rules miss (selection bias; the below-the-line sample is Phase 7b).
- **Labels are simulated.** Dispositions are derived from the generator's ground truth, not from analysts,
  so they are noise-free; real dispositions would be less separable.
- **Hibernation had nothing to act on:** this data has too few repeated false-positive rule alerts. Its
  behaviour is covered by tests on a hand-built fixture, not by this run.

An example summary is in [results/phase7/example_summary.md](results/phase7/example_summary.md) (names and
ID numbers are masked); the full evaluation is in [results/phase7/eval.json](results/phase7/eval.json). The
specs with the rules and acceptance criteria are [case-consolidation](specs/case-consolidation.md),
[case-suppression](specs/case-suppression.md), [case-prioritization](specs/case-prioritization.md) and
[case-summary](specs/case-summary.md).
