# Neo4j investigation queries (Phase 6b-i)

Oracle stays the system of record; these queries read the **read-only Neo4j projection** (see `neo4j-sync.md`).
Every query is one `.cypher` file under `src/aml/graph/neo4j/cypher/queries/`, runs through the guard in a
`READ_ACCESS` session, writes nothing to Neo4j, raises no alert and closes nothing. All data is synthetic.

## Trace: the `neo4j` method

`aml trace --method neo4j` (or `trace(..., method="neo4j")`) is the fourth method of the fund-flow trace and
returns the **same rows as `cte_raw`** when the graph matches its source: strict time order, window T anchored on
the first hop, no repeated account in a prefix, a hop back to an earlier account is returned as a cycle and not
extended, one row per prefix. It works with `DB_BACKEND=oracle` and `duckdb`, provided the graph was synced from
that backend.

`queries/trace.cypher` takes the first hop from `(:Account {account_id: $account})` and then has five
`CALL (...) { ... }` layers, one per further hop. Cypher cannot take a parameter as a path-length bound
(`{1,$n}` is a syntax error), so all layers are written out and each switches itself off with `$hops >= k`.
The text, and so `query_lines`, is the same for every `hops`.

### Why not a quantified path pattern

The shortest way to write the trace is a quantified path pattern,
`(()-[r:TRANSFERRED_TO]->() WHERE r.ts > e1.ts AND r.ts <= e1.ts + duration({hours: $hours})){0,5}`. It is
17 lines against 58. It was not used because a predicate inside a quantifier only sees the current repetition and
variables bound before it. It can cut the window T, but it cannot say "each hop is after the previous one" or "no
repeated account". Those two conditions would filter after every walk has been listed, and the number of walks
explodes.

Prototype measurements (2026-10-12, dev machine, Neo4j 5.26.31 Community, profile `small`, account
`A5461833942` with 190 outgoing transfers; these are not benchmark results, 6c measures properly):

| T (hours) | rows at 2 / 4 / 6 hops | `CALL (...) { }` layers (chosen) | quantified path pattern |
|---|---|---|---|
| 72 | 632 / 658 / 658 | 44 / 44 / 42 ms | 894 / 883 / 853 ms (1 run) |
| 168 | 1249 / 1424 / 1429 | 71 / 79 / 83 ms | 15 382 / 15 301 / 16 870 ms (1 run) |
| 720 | 4289 / 10 955 / 22 394 | 221 / 587 / 1206 ms | over 30 s at all three; one run did not finish in 18 minutes |

From the real commands on the implemented code (2026-10-12, same machine, profile `small` synced from DuckDB,
one run each, first call in a new process so the times include a cold query plan):

| Command | Rows | `seconds` |
|---|---|---|
| `aml trace --account A5461833942 --hops 4 --hours 168 --method all`: `cte_raw` | 1424 paths | 0.055 |
| same command: `cte_edge` (approximate by day) | 17 paths | 0.018 |
| same command: `neo4j` (`pgq` is skipped on DuckDB) | 1424 paths | 0.283 |
| `aml graph query cycles` | 15 | 0.450 |
| `aml graph query fan_in` | 7 | 2.994 |
| `aml graph query fan_out` | 25 | 2.754 |
| `aml graph query shared_attributes` | 278 | 0.076 |
| `aml graph query shared_cluster --customer G-CIF00000806` | 21 | 0.224 |

## The five queries (`aml graph query NAME`)

Common parameters: thresholds come from config, `as_of` (default `data.reference_date`) keeps only transfers before
00:00 of the next day, and at most `graph_queries.max_rows` rows are returned. A bigger result is an error, never a
silent cut.

| name | question | takes | thresholds |
|---|---|---|---|
| `cycles` | time-ordered round trips of 3 to 5 transfers | `--account` | `network.cycles.*` |
| `shared_attributes` | devices, phones, addresses carried by 2..N customers | `--customer` | `network.shared_attributes.max_customers_per_value` |
| `shared_cluster` | everyone reachable from one customer through shared values | `--customer` (required) | same as above |
| `fan_in` | accounts with many distinct senders in a short window | `--account` | `monitoring.fan_in_out.*` |
| `fan_out` | accounts with many distinct receivers in a short window | `--account` | `monitoring.fan_in_out.*` |

- **cycles** follows the `NET_CYCLE` definition of 5c: internal accounts of different customers, every transfer at
  or above the amount floor, strictly increasing time, last hop inside the window, smallest amount at least the
  ratio times the largest. The first hop is the earliest one, so each cycle appears once. One row is one cycle;
  5c merges cycles into instances for its alerts. The amount floor is what makes the query finish: without it the
  prototype did not complete in 120 seconds. The search uses a quantified path pattern `{2,5}` after the first hop
  (cycle length 3 to 6) and filters the length with `$min_length` / `$max_length`.
- **shared_attributes** lists `Device`, `Phone` and `Address` nodes (the key is the hash stored by the sync).
- **shared_cluster** uses `ANY SHORTEST` over the pattern customer, value, customer, and only walks through values
  with at most `max_customers_per_value` customers. `distance` is the number of values on the chain, `via` their kinds.
- **fan_in / fan_out** count distinct counterparties, transfers and total VND from each transfer as the window start.
  There is no "known counterparty" filter and no warm-up period as in 5a, so the result is a superset of the 5a
  alerts: it also shows employer payroll and busy background accounts. Read it next to the alerts.

Each successful call writes one `QUERIED` row to `audit_log` (version `query/v1`, entity type `graph_query`) with the
name, parameters and row count. A failed call writes nothing.

## Timeout on the read path

Every read through `run_read` / `run_read_file` has a server-side transaction timeout,
`neo4j.read_timeout_seconds` (default 60). The server stops the query and rolls it back, and the error is
`QueryTimeoutError` (`query exceeded <n> s`). Without it a query keeps running on the server after the client gave up.

The timeout, not the query design, is what bounds the heavy cases: `cycles` enumerates walks of up to six transfers
and relies on the amount floor to stay small, and `fan_in` / `fan_out` open one window per transfer of an account.
On a much larger or denser graph they hit the timeout instead of running on. In `aml trace` a timeout is reported
as `neo4j trace failed: query exceeded <n> s` (exit code 2).

## When the graph does not match its source

The projection is a snapshot of the last sync. Before the trace or a query runs, the graph is compared with the
database (the sync state and the number of `TRANSFERRED_TO` against the number of transfers). The call is refused,
never silently answered and never auto-synced:

| message | meaning | fix |
|---|---|---|
| `graph not synced: run aml graph sync` | no sync state in Neo4j | `aml graph sync` |
| `graph was synced from <x> but the database is <y>` | graph built from the other backend | `aml graph sync --full` |
| `graph is out of sync (a of b transfers)` | transfers were added after the last sync | `aml graph sync` |

With `aml trace --method neo4j` these (and "neo4j not available") exit with code 2; with `--method all` the method is
reported as `method=neo4j skipped: ...` and the other methods still run. `aml graph query` exits 1 for them. The
check only compares the backend and the transfer count, so two things are not detected (a known limit from 6a): a
rewritten transaction with an unchanged count, and a different data set from the same backend that happens to have
the same number of transfers. The check costs one small read on each side per call.
