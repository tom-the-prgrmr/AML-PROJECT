# AML Investigation Toolkit (interview demo)

Custom tools that reduce AML investigation effort, on **synthetic data only**:
Vietnamese-name screening, entity resolution, transaction monitoring, SQL-vs-graph network
analysis, alert consolidation/prioritization, and a local GraphRAG investigator assistant.
Oracle is the system of record; Neo4j is a read-only investigation projection.

> Status: **Phases 0 to 6 done** (scaffold through the Neo4j projection and trace benchmark). Results tables are added phase by phase, each generated
> from an actual run with the command that produced it.

## Quick start

```powershell
uv sync                         # Python 3.11 env + deps
uv run aml status               # config + which optional services are up
uv run aml init-db              # base schema (audit_log) on DuckDB (default)

.\tasks.ps1 up -ComposeProfile oracle   # or: make up PROFILE=oracle
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

All three return the same paths. The recursive CTE is the fastest, the property graph matches it at 2 hops and
falls behind with depth, and Neo4j is 2.3 to 5.2 times slower than the CTE across both profiles while costing a
42 to 51 s full sync and a second service. So Oracle stays the system of record for traces, and Neo4j is an
optional read-only projection for investigation (pattern queries, graph algorithms). The full tables for
`small` and `dense`, p95, the method, the limits and the reasoning are in
[docs/trace-benchmark.md](docs/trace-benchmark.md); the raw results are in
[results/phase6/](results/phase6/bench_report.md).

Related: [docs/neo4j-sync.md](docs/neo4j-sync.md) (sync, lag, consistency),
[docs/neo4j-queries.md](docs/neo4j-queries.md) (Cypher queries), [docs/neo4j-gds.md](docs/neo4j-gds.md) (GDS
features).
