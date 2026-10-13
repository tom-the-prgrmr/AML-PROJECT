# GDS features on the Neo4j projection (Phase 6b-ii)

Neo4j Graph Data Science (GDS) computes graph features on the projection built by `aml graph sync`; the
results are written back to the system of record (Oracle or DuckDB) as `gds_account_features`. The run only
produces features: it raises no alert, closes nothing and scores nothing. Everything here uses synthetic data.

```powershell
uv run aml graph sync --full     # the graph must be in sync with the database
uv run aml graph gds             # as of data.reference_date
uv run aml graph gds --as-of 2026-06-30
```

The command prints one summary line (`run_id= as_of= accounts= active= wcc_components= louvain_communities=
shared_clusters= seconds= gds=<version>`) and one line per in-memory graph (`<name> nodes=<n> relationships=<n>`).

## How GDS runs without writing to Neo4j

- Each run projects three **in-memory** graphs with Cypher projections (`gds.graph.project`) inside sessions
  opened with `READ_ACCESS`. They live in the heap of the Neo4j server, not in the database.
- Results are read with the `.stream` procedures only. Nothing calls `.write` or `.mutate`, so no node,
  relationship or property is added to Neo4j. The tests compare node, relationship and property-key sets before
  and after a run.
- The three graphs are dropped in a `finally`, also when a stream fails, and any leftover from an earlier crash is
  dropped before projecting.
- The read guard (`guard/v2`) accepts the GDS procedures only for the runner's own `gds/*.cypher` files, through a
  separate allowlist (`gds.procedures` in `config.yaml`: `gds.graph.project`, `gds.graph.drop`, `gds.*.stream`).
  The ordinary read path (`neo4j.read_procedures`) is unchanged, so `aml graph query` and the Phase 8 assistant
  cannot project graphs or call GDS.
- Every Neo4j or GDS error happens before the first write to the database: a failed run leaves no row in
  `gds_account_features`, `gds_runs` or `audit_log`. A successful run adds the feature rows, one `gds_runs` row and
  one `GDS_FEATURES_WRITTEN` audit row with a human-readable `reason`.

## The three graphs

| Graph (`<graph_prefix>_...`) | Contents | Algorithms |
|---|---|---|
| `accounts` | one directed relationship per pair of accounts of **different customers** with `SENT_TO` edges in the look-back window (`network.hubs.lookback_days`, ending the day after `as_of`); properties `total_vnd`, `transfers` | degree (in/out, plain and weighted by `total_vnd`), PageRank |
| `accounts_undirected` | the same pairs, undirected | WCC, Louvain |
| `shared` | `Customer` - shared device / phone / address value, for values held by 2 to `network.shared_attributes.max_customers_per_value` customers, undirected | WCC (shared-attribute clusters) |

The `accounts` graph is exactly the hub graph of the NetworkX detections (Phase 5c), so its degree and PageRank
can be compared with `nx_account_features`. If no pair matches (for example `--as-of` before every transfer), the
graph is empty and its streams are skipped.

## Determinism

- `gds.concurrency: 1`. Degree and WCC give the same result with 1 or 4 threads and PageRank the same within its tolerance, but Louvain does not
  with more than one (GDS 2.13 has no `randomSeed`), so one thread is the setting that makes runs reproducible.
- PageRank uses `dampingFactor = network.hubs.pagerank_alpha`, `maxIterations: 200` and `tolerance: 1e-10`; the
  GDS defaults (20 iterations, 1e-7) did not converge in the prototype.
- GDS component and community codes are internal node ids and change between syncs, so they are never stored.
  Groups are named after their smallest member: the smallest `account_id` for `wcc_id` and `louvain_id`, and
  `SHARED-` plus the smallest CIF for `shared_cluster_id` (the same naming as `NET_SHARED_ATTRIBUTE`).
- Louvain is a greedy heuristic, and its result depends on the order of the nodes in the in-memory graph. The two
  account projections therefore sort their rows (`ORDER BY t.account_id, s.account_id`) so that the order comes
  from the data and not from how Neo4j happened to store it. The run is then reproducible for the same data, the
  same GDS version and one thread, but the number of communities is not a property of the data: on the TINY test
  set, sorting by `(s, t)` instead of `(t, s)` gave 19 communities instead of 20 when this was tried during
  development (2026-10-13, GDS 2.13.13), and a GDS upgrade may change it too. WCC
  components, degrees and PageRank do not have this problem. Treat `louvain_id` as a feature, not as a fact.

## Limits

- The in-memory graphs have fixed names (`gds.graph_prefix` plus the graph name). Two `aml graph gds` runs at the
  same time break each other: the second fails because the graphs exist, and its clean-up drops the graphs the
  first is using. Run one at a time, and not during `aml graph sync`.
- Every Neo4j error happens before anything is written. The three writes that follow (`gds_runs`, the feature
  rows, the audit row) are not one transaction. If the second or third fails, the run id is still used up, so the
  next run works; a run row without feature rows or without its audit row is the sign of such a failure.
- Put the GDS jar in `docker/neo4j/plugins/` before the first `docker compose up`. If the file is missing, Docker
  creates an empty directory with the jar's name, GDS does not load and `aml graph gds` fails with
  `GDS plugin not available`. Remove that directory, add the jar and recreate the container.

## Tables

`gds_runs` has one row per run (`run_id`, `run_ts`, `as_of`, `source_backend`, `sync_run_id`, `txn_watermark`,
`gds_version`, counts, `seconds`, `params` JSON). `gds_account_features` has one row per account and run, and the
view `gds_account_features_current` shows the latest run. Rows are never updated or deleted.

| `gds_account_features` | `nx_account_features` (Phase 5c) |
|---|---|
| `in_degree`, `out_degree`, `in_vnd`, `out_vnd` | same columns, same values |
| `pagerank`, `pagerank_ratio` | same definitions (score / total, and x number of nodes); equal within 1e-7 / 2e-4 |
| `wcc_id`, `wcc_size`, `louvain_id`, `louvain_size` | not in 5c |
| `shared_cluster_id`, `shared_cluster_size` | same, but every cluster of 2 or more customers is written (5c only reports clusters from `min_customers`) |

Neither table is granted to any database role. Phase 7 reads the features from the application connection.

## Getting the GDS jar

`docker-compose.yml` mounts `./docker/neo4j/plugins/neo4j-graph-data-science-2.13.13.jar` as
`/plugins/graph-data-science.jar` and sets `NEO4J_PLUGINS` to `["apoc"]` only, so Neo4j does not download GDS at
every start. The jar is git-ignored. Do not mount it `:ro` (the container exits at start-up). Either copy it out
of a container that already has GDS with `docker cp`:

```powershell
docker cp <neo4j-container>:/plugins/graph-data-science.jar docker/neo4j/plugins/neo4j-graph-data-science-2.13.13.jar
```

or download `neo4j-graph-data-science-2.13.13.jar` yourself, then verify it and recreate the container:

```powershell
Get-FileHash docker/neo4j/plugins/neo4j-graph-data-science-2.13.13.jar -Algorithm SHA256
.\tasks.ps1 up -ComposeProfile graph
```

The expected SHA-256 is `17cfceb0c78e897baea3dfcdbd852dff779980bcc1eb444126338694bb053264` (65,774,694 bytes).
`aml graph gds` fails with `GDS plugin not available` when the plugin is missing.

## Upgrading an old dev database

The tables come from `ddl/150_gds.sql`. A database created before Phase 6b-ii needs `uv run aml init-db` (on
Oracle, `DB_BACKEND=oracle`) once before the first `aml graph gds`.

## Measured numbers

These are prototype measurements taken on 2026-10-12 (seed 42, Neo4j 5.26.31 Community, GDS 2.13.13,
`concurrency: 1`) before this command existed; they are not output of `aml graph gds`.

| | MINI-G | MINI-HUB | TINY | `small` |
|---|---|---|---|---|
| account graph nodes / relationships | 6 / 4 | 51 / 47 | 298 / 450 | 4980 / 8610 |
| WCC components / largest | 2 / 4 | 5 / 11 | 9 / 98 | 52 / 2179 |
| Louvain communities / largest | 2 / 4 | 5 / 11 | 20 / 36 | 151 / 82 |
| shared-attribute clusters | 4 | 0 | 2 | 260 |
| whole run (3 graphs, 8 streams, drop) | 0.28 s | 0.28 s | 0.59 s | 1.7-2.5 s |

Degree centralities match `nx_account_features` on every account; PageRank differs by at most 1e-8 and the ratio
by at most 1e-4 (rounding).

From the real command (2026-10-13, dev machine, profile `small` synced from DuckDB, GDS 2.13.13 from the pinned
jar): `uv run aml graph gds` printed

```text
run_id=1 as_of=2026-06-30 accounts=8958 active=4980 wcc_components=52 louvain_communities=151 shared_clusters=260 seconds=3.08 gds=2.13.13
accounts nodes=4980 relationships=8610
accounts_undirected nodes=4980 relationships=17220
shared nodes=905 relationships=1290
```

A second run gave the same counts in 2.235 s. Joined to `nx_account_features_current` (5c, NetworkX) on all 8,958
accounts: `in_degree`, `out_degree`, `in_vnd` and `out_vnd` are equal on every row, and `pagerank` differs by at
most 1e-8 (the rounding of the stored value).
