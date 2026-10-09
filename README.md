# AML Investigation Toolkit (interview demo)

Custom tools that reduce AML investigation effort, on **synthetic data only**:
Vietnamese-name screening, entity resolution, transaction monitoring, SQL-vs-graph network
analysis, alert consolidation/prioritization, and a local GraphRAG investigator assistant.
Oracle is the system of record; Neo4j is a read-only investigation projection.

> Status: **Phase 0 (scaffold)**. Results tables are added phase by phase, each generated
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
