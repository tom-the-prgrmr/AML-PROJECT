# Oracle to Neo4j sync (Phase 6a)

Oracle is the system of record. Neo4j is a **read-only investigation projection** built from it; the sync
writes nothing to business tables, raises no alert and closes nothing. Everything here uses synthetic data.

## What is synced

Nodes: `Customer` (one per golden customer from entity resolution), `Account`, `Device`, `Phone`, `Address`.
Relationships: `OWNS`, `USES_DEVICE`, `HAS_PHONE`, `LIVES_AT`, `TRANSFERRED_TO` (one per transaction with both
sides known, keyed by `txn_id`) and `SENT_TO` (one per row of `acct_edge_daily`). All loads are `UNWIND` +
`MERGE`, so re-running never creates duplicates. A `SyncState` node holds the watermark.

On Oracle the sync reads through the read-only user `aml_graph_sync_usr` (role `aml_graph_sync`, 7 `SELECT`
grants, see `ROLE_GRANTS` in `aml.dba.security`). Customer attributes come through the view
`graph_customer_attrs`, which exposes only `cif`, `phone`, `device_id`, `street`, `ward`, `district`,
`province`. Each run is logged in `graph_sync_runs` and in `audit_log`.

## Running it

```powershell
uv run aml graph sync          # incremental (first run, or after the graph was wiped, is a full load)
uv run aml graph sync --full   # wipe the projection and reload everything
uv run aml graph status
```

## Sync lag

Sync lag is measured in data time, because `transactions.txn_ts` is the only timestamp in the source tables:
the newest `txn_ts` in the source minus the sync watermark. `lag_before_seconds` is taken when a run starts,
`lag_after_seconds` when it counts the results. It says how far the graph is behind the source, not how long
a run took (that is `seconds`).

Measured on 2026-10-12 on a dev machine (`small` profile, seed 42, DuckDB source, Neo4j 5.26.31 Community
with a 1 GB heap, one run each):

| Command | Mode | Sent | `seconds` | `lag_after_s` | `in_sync` |
|---|---|---|---|---|---|
| `uv run aml graph sync --full` | FULL | 28,914 nodes, 443,051 relationships | 43.74 | 0 | True |
| `uv run aml graph sync` (nothing new) | INCREMENTAL | 26,927 nodes, 23,849 relationships | 1.93 | 0 | True |

The incremental run still re-sends the customer side and the accounts in full, plus the transfers inside
the 60-minute overlap window (17 `TRANSFERRED_TO`, 1,096 `SENT_TO`); `MERGE` makes that a no-op.

## Consistency

The projection is eventually consistent with Oracle. Between runs the graph can lag behind new transactions,
and a run that fails halfway leaves some `MERGE`d data in the graph (re-running is safe). The watermark and
`graph_sync_runs` only change after a successful run. Customer-side data (customers, devices, phones,
addresses) is always read in full and stale nodes are swept; transfers are read from `watermark - overlap`.
After each run the transfer and daily-edge counts in Neo4j are compared with the source (`in_sync`).
Anything that must be exact should be answered from Oracle.

## When to use `--full`

- the source backend changed (DuckDB to Oracle or back); the sync refuses to continue without it;
- a run reports `OUT OF SYNC`;
- the source was reloaded with `aml load` (it deletes and reloads everything) or entity resolution was re-run
  and you want a clean graph;
- the Neo4j volume was recreated by hand and you want to be certain it is complete.

## Hashed attribute keys

`Device`, `Phone` and `Address` nodes are keyed by a sha256 hash of the normalised value, so the raw value is
not stored in the graph. The hash is unsalted: anyone can hash candidate phone numbers or addresses and compare,
and phone numbers have a small search space. This is obscuring, not anonymisation. Neo4j Community has no
access control, so treat the graph as sensitive as the data it came from.

## Containers

The `neo4j` service is pinned to `neo4j:5.26.31-community` (APOC ships inside the image) and sets
`NEO4J_dbms_usage__report_enabled=false` so no usage data is sent out.
