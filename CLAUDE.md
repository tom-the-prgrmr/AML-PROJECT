# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An interview demo: an AML investigation toolkit that runs on **synthetic data only**. It covers Vietnamese-name screening, entity resolution, transaction monitoring, SQL-vs-graph network analysis, alert consolidation and prioritization, and a local GraphRAG assistant. [PROJECT_BRIEF.md](PROJECT_BRIEF.md) is the full requirements document, and it defines the phases (0–10). Read the section for the current phase before you start work on it. Specs for individual phases sit in [specs/](specs/). They are written in Vietnamese, have frontmatter with `status: approved`, and contain acceptance criteria that tests should implement.

Current state: all phases (0 to 10) are done (`src/aml/datagen/` through `src/aml/cases/`, `src/aml/memo/`, the GraphRAG assistant in `src/aml/assistant/`, the FastAPI + React UI in `src/aml/api/` and `web/`, the Phase 7b ML additions in `src/aml/ml/anomaly/`, `src/aml/screening/ml/`, `src/aml/cases/btl*.py` and `src/aml/governance/`). Phase 10 produced the full [README.md](README.md), [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md) and [docs/WALKTHROUGH.md](docs/WALKTHROUGH.md); when code or results change, update the numbers there from a real run (never by hand).

## Working rules (from the brief, non-negotiable)

- **Phase gates.** Work on one phase at a time. When a phase is finished: run the tests, show a short demo output, commit, then **wait for the user's OK**. Do not skip ahead.
- **Never fabricate results.** Every metric in the README must come from an actual run, together with the command that produced it.
- **Every automated decision is explainable.** It stores a human-readable `reason` and writes to `audit_log` via `aml.common.audit.audit()` / `audit_many()`.
- All data is synthetic, and no external API calls are allowed. LLM work runs locally through Ollama.
- Keep modules small, typed and readable. The user will walk an interviewer through the code.
- The model only ranks alerts. It never auto-closes them. The assistant never clears, closes or files anything.

## Commands

Everything goes through the single CLI `uv run aml <cmd>`. `Makefile` and `tasks.ps1` (for Windows without make) are thin wrappers around it.

```powershell
uv sync                                   # Python 3.11 env
uv run aml status                         # active config + which services are up
uv run aml init-db                        # base schema on the configured backend
uv run pytest                             # all tests
uv run pytest tests/test_db.py::test_split_oracle_script_handles_plsql_and_comments
uv run ruff check . ; uv run ruff format --check .   # lint (= .\tasks.ps1 lint / make lint)
.\tasks.ps1 up -ComposeProfile oracle     # docker: oracle | graph | llm | full  (make up PROFILE=oracle)
$env:DB_BACKEND = "oracle"; uv run aml init-db
```

The verify loop in `.claude/loop.yaml` runs `ruff check`, `ruff format --check` and `pytest -q`. All three must pass.

## Architecture

- **Oracle 23ai Free is the system of record.** Rules, SQL traces and DBA practice run there, including SQL property graphs (`GRAPH_TABLE ... MATCH`). **Neo4j is a read-only investigation projection** synced from Oracle. Neo4j Community has no RBAC, so read-only behaviour comes from READ access-mode sessions plus an application-level guard that rejects write clauses.
- **DuckDB fallback.** Set `DB_BACKEND=duckdb` (the default) to run everything except the Oracle-only features with zero setup. `get_db()` in [src/aml/common/db.py](src/aml/common/db.py) also falls back to DuckDB when Oracle is unreachable, if `db.fallback_to_duckdb` is set.
- **The `Database` abstraction** (`execute`, `query_df`, `run_script`, `insert_df`) keeps business code independent of the backend. Use it. Do not import the drivers directly in feature modules. Each write commits on its own; wrap writes that must not be separated (a row and its audit record) in `with db.transaction():`.
- **SQL lives in `.sql` files.** `sql_file(name)` resolves `sql/<backend>/<name>` first and then `sql/common/<name>`. Dialect conventions:
  - DuckDB scripts are plain statements, each ending with `;`.
  - Oracle scripts follow the SQL*Plus style: **every statement, SQL or PL/SQL, ends with a line containing only `/`**. A statement without that terminator raises an error. DDL is idempotent: wrap it in `EXECUTE IMMEDIATE` and swallow ORA-00955.
- **Config** ([config.yaml](config.yaml) + [src/aml/common/config.py](src/aml/common/config.py)) is a typed pydantic `Settings` object, cached by `get_settings()`. Overrides apply in this order:
  1. `AML__SECTION__KEY=value`, with the value parsed as YAML.
  2. The credential variables in `SECRET_ENV_MAP`.
  3. `DB_BACKEND`.

  Secrets live only in `.env`, which is git-ignored and shared with docker-compose. Real environment variables take precedence over `.env`. Thresholds, profiles (`small`/`dense`/`large`), seeds and model names all belong in config, never hard-coded. In tests, use `load_settings(environ={...})` to build isolated settings.
- **`audit_log`** is append-only. Module-specific extras, such as the assistant's question, generated Cypher or retrieved IDs, go in the JSON `details` column, so the core schema stays the same.
- **Optional services.** Mark a test with `@pytest.mark.oracle`, `@pytest.mark.neo4j` or `@pytest.mark.ollama`. `tests/conftest.py` probes each service once with `aml.common.services` and skips the test with a clear message if the service is down, so `pytest` stays green in DuckDB-only mode. Use the `duck` fixture to get a temporary DuckDB.
- **Determinism.** All generated data must be reproducible from `settings.seed`.

## Planned layout (per the brief)

Each phase gets its own package under `src/aml/`: `datagen/` (writes Parquet to `data/parquet`), `screening/`, `entity_resolution/`, `monitoring/`, `graph/` (with `.cypher` files under `graph/neo4j/`), `cases/`, `ml/anomaly/` and `screening/ml/` (Phase 7b), `assistant/` and `api/` (FastAPI). The investigator UI is a React + TypeScript + Vite SPA in top-level `web/`, served by FastAPI as static files (Phase 9; see the brief for why not Next.js). DBA scripts and `RUNBOOK.md` go in `dba/`. Knowledge-base docs go in `docs/knowledge/`. `data/` is generated and git-ignored.
