# Fund-flow trace benchmark

Built by `aml bench` from the result files (`bench_*.json`) of this directory. Rebuild it with `aml bench --report-only`.

## dense on duckdb

- Command: `aml bench --profile dense`, started 2026-10-13T04:47:32+00:00 (UTC), 15.538 s in total, commit ab5536f
- Versions: python 3.11.9, aml 0.1.0, duckdb 1.5.6, server v1.5.6, neo4j driver 6.4.0
- Machine: Windows-10-10.0.26200-SP0, Intel64 Family 6 Model 151 Stepping 5, GenuineIntel, 12 logical CPUs
- Data: 5000 customers, 8958 accounts, 306000 transactions, 228235 transfers
- Runs: 1 warm-up and 10 timed runs per cell; hops [2, 4, 6], T [72, 720] h; accounts ['A4173555232'] (picked automatically)
- Trace limits: max_paths 100000, cte_edge min amount 10000000 VND, top-K 5; Neo4j read timeout 60.0 s
- Graph sync: FULL 46.71 s, INCREMENTAL 1.88 s, lag after the last run 0 s

| profile | backend | account | T (h) | hops | method | status | paths | median ms | p95 ms | query lines | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dense | duckdb | A4173555232 | 72 | 2 | cte_raw | ok | 94 | 19.1 | 20.7 | 38 |  |
| dense | duckdb | A4173555232 | 72 | 2 | cte_edge | ok | 5 | 9.7 | 10.1 | 43 | approximate (daily edges, top-K): paths not comparable |
| dense | duckdb | A4173555232 | 72 | 2 | pgq | skipped |  |  |  |  | not available on duckdb |
| dense | duckdb | A4173555232 | 72 | 2 | neo4j | ok | 94 | 15.3 | 16.4 | 58 |  |
| dense | duckdb | A4173555232 | 72 | 4 | cte_raw | ok | 112 | 34.7 | 35.9 | 38 |  |
| dense | duckdb | A4173555232 | 72 | 4 | cte_edge | ok | 5 | 8.7 | 10.3 | 43 | approximate (daily edges, top-K): paths not comparable |
| dense | duckdb | A4173555232 | 72 | 4 | pgq | skipped |  |  |  |  | not available on duckdb |
| dense | duckdb | A4173555232 | 72 | 4 | neo4j | ok | 112 | 17.0 | 18.1 | 58 |  |
| dense | duckdb | A4173555232 | 72 | 6 | cte_raw | ok | 112 | 38.1 | 40.9 | 38 |  |
| dense | duckdb | A4173555232 | 72 | 6 | cte_edge | ok | 5 | 9.0 | 9.5 | 43 | approximate (daily edges, top-K): paths not comparable |
| dense | duckdb | A4173555232 | 72 | 6 | pgq | skipped |  |  |  |  | not available on duckdb |
| dense | duckdb | A4173555232 | 72 | 6 | neo4j | ok | 112 | 16.7 | 19.7 | 58 |  |
| dense | duckdb | A4173555232 | 720 | 2 | cte_raw | ok | 435 | 19.5 | 21.0 | 38 |  |
| dense | duckdb | A4173555232 | 720 | 2 | cte_edge | ok | 11 | 10.3 | 11.0 | 43 | approximate (daily edges, top-K): paths not comparable |
| dense | duckdb | A4173555232 | 720 | 2 | pgq | skipped |  |  |  |  | not available on duckdb |
| dense | duckdb | A4173555232 | 720 | 2 | neo4j | ok | 435 | 30.8 | 33.5 | 58 |  |
| dense | duckdb | A4173555232 | 720 | 4 | cte_raw | ok | 4098 | 50.3 | 69.5 | 38 |  |
| dense | duckdb | A4173555232 | 720 | 4 | cte_edge | ok | 14 | 14.8 | 16.8 | 43 | approximate (daily edges, top-K): paths not comparable |
| dense | duckdb | A4173555232 | 720 | 4 | pgq | skipped |  |  |  |  | not available on duckdb |
| dense | duckdb | A4173555232 | 720 | 4 | neo4j | ok | 4098 | 221.7 | 244.1 | 58 |  |
| dense | duckdb | A4173555232 | 720 | 6 | cte_raw | ok | 12366 | 110.2 | 135.7 | 38 |  |
| dense | duckdb | A4173555232 | 720 | 6 | cte_edge | ok | 14 | 15.2 | 18.8 | 43 | approximate (daily edges, top-K): paths not comparable |
| dense | duckdb | A4173555232 | 720 | 6 | pgq | skipped |  |  |  |  | not available on duckdb |
| dense | duckdb | A4173555232 | 720 | 6 | neo4j | ok | 12366 | 657.5 | 686.3 | 58 |  |

## dense on oracle

- Command: `aml bench --profile dense`, started 2026-10-13T04:44:28+00:00 (UTC), 124.315 s in total, commit ab5536f
- Versions: python 3.11.9, aml 0.1.0, oracledb 26.0.1, server 23.26.3.0.0, neo4j driver 6.4.0
- Machine: Windows-10-10.0.26200-SP0, Intel64 Family 6 Model 151 Stepping 5, GenuineIntel, 12 logical CPUs
- Data: 5000 customers, 8958 accounts, 306000 transactions, 228235 transfers
- Runs: 1 warm-up and 10 timed runs per cell; hops [2, 4, 6], T [72, 720] h; accounts ['A4173555232'] (picked automatically)
- Trace limits: max_paths 100000, cte_edge min amount 10000000 VND, top-K 5; Neo4j read timeout 60.0 s
- Graph sync: FULL 50.65 s, INCREMENTAL 2.24 s, lag after the last run 0 s

| profile | backend | account | T (h) | hops | method | status | paths | median ms | p95 ms | query lines | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dense | oracle | A4173555232 | 72 | 2 | cte_raw | ok | 94 | 6.0 | 7.4 | 30 |  |
| dense | oracle | A4173555232 | 72 | 2 | cte_edge | ok | 5 | 4.9 | 6.0 | 38 | approximate (daily edges, top-K): paths not comparable |
| dense | oracle | A4173555232 | 72 | 2 | pgq | ok | 94 | 5.3 | 6.1 | 19 |  |
| dense | oracle | A4173555232 | 72 | 2 | neo4j | ok | 94 | 18.4 | 23.4 | 58 |  |
| dense | oracle | A4173555232 | 72 | 4 | cte_raw | ok | 112 | 7.2 | 8.3 | 30 |  |
| dense | oracle | A4173555232 | 72 | 4 | cte_edge | ok | 5 | 4.5 | 5.7 | 38 | approximate (daily edges, top-K): paths not comparable |
| dense | oracle | A4173555232 | 72 | 4 | pgq | ok | 112 | 146.1 | 166.9 | 49 |  |
| dense | oracle | A4173555232 | 72 | 4 | neo4j | ok | 112 | 17.7 | 20.1 | 58 |  |
| dense | oracle | A4173555232 | 72 | 6 | cte_raw | ok | 112 | 6.9 | 7.4 | 30 |  |
| dense | oracle | A4173555232 | 72 | 6 | cte_edge | ok | 5 | 4.2 | 4.6 | 38 | approximate (daily edges, top-K): paths not comparable |
| dense | oracle | A4173555232 | 72 | 6 | pgq | ok | 112 | 4375.1 | 5101.2 | 99 |  |
| dense | oracle | A4173555232 | 72 | 6 | neo4j | ok | 112 | 18.0 | 28.6 | 58 |  |
| dense | oracle | A4173555232 | 720 | 2 | cte_raw | ok | 435 | 9.2 | 10.1 | 30 |  |
| dense | oracle | A4173555232 | 720 | 2 | cte_edge | ok | 11 | 4.5 | 5.3 | 38 | approximate (daily edges, top-K): paths not comparable |
| dense | oracle | A4173555232 | 720 | 2 | pgq | ok | 435 | 8.2 | 9.5 | 19 |  |
| dense | oracle | A4173555232 | 720 | 2 | neo4j | ok | 435 | 32.5 | 40.8 | 58 |  |
| dense | oracle | A4173555232 | 720 | 4 | cte_raw | ok | 4098 | 73.4 | 88.6 | 30 |  |
| dense | oracle | A4173555232 | 720 | 4 | cte_edge | ok | 14 | 4.4 | 4.8 | 38 | approximate (daily edges, top-K): paths not comparable |
| dense | oracle | A4173555232 | 720 | 4 | pgq | ok | 4098 | 174.7 | 190.4 | 49 |  |
| dense | oracle | A4173555232 | 720 | 4 | neo4j | ok | 4098 | 226.3 | 405.5 | 58 |  |
| dense | oracle | A4173555232 | 720 | 6 | cte_raw | ok | 12366 | 283.4 | 309.1 | 30 |  |
| dense | oracle | A4173555232 | 720 | 6 | cte_edge | ok | 14 | 4.4 | 5.7 | 38 | approximate (daily edges, top-K): paths not comparable |
| dense | oracle | A4173555232 | 720 | 6 | pgq | ok | 12366 | 4542.9 | 4704.4 | 99 |  |
| dense | oracle | A4173555232 | 720 | 6 | neo4j | ok | 12366 | 663.8 | 695.8 | 58 |  |

## small on duckdb

- Command: `aml bench --profile small`, started 2026-10-13T04:48:39+00:00 (UTC), 30.123 s in total, commit ab5536f
- Versions: python 3.11.9, aml 0.1.0, duckdb 1.5.6, server v1.5.6, neo4j driver 6.4.0
- Machine: Windows-10-10.0.26200-SP0, Intel64 Family 6 Model 151 Stepping 5, GenuineIntel, 12 logical CPUs
- Data: 5000 customers, 8958 accounts, 306000 transactions, 214589 transfers
- Runs: 1 warm-up and 10 timed runs per cell; hops [2, 4, 6], T [72, 720] h; accounts ['A5461833942'] (picked automatically)
- Trace limits: max_paths 100000, cte_edge min amount 10000000 VND, top-K 5; Neo4j read timeout 60.0 s
- Graph sync: FULL 44.61 s, INCREMENTAL 1.94 s, lag after the last run 0 s

| profile | backend | account | T (h) | hops | method | status | paths | median ms | p95 ms | query lines | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small | duckdb | A5461833942 | 72 | 2 | cte_raw | ok | 632 | 24.7 | 25.4 | 38 |  |
| small | duckdb | A5461833942 | 72 | 2 | cte_edge | ok | 13 | 12.1 | 12.4 | 43 | approximate (daily edges, top-K): paths not comparable |
| small | duckdb | A5461833942 | 72 | 2 | pgq | skipped |  |  |  |  | not available on duckdb |
| small | duckdb | A5461833942 | 72 | 2 | neo4j | ok | 632 | 43.5 | 50.7 | 58 |  |
| small | duckdb | A5461833942 | 72 | 4 | cte_raw | ok | 658 | 39.2 | 41.2 | 38 |  |
| small | duckdb | A5461833942 | 72 | 4 | cte_edge | ok | 13 | 13.1 | 14.4 | 43 | approximate (daily edges, top-K): paths not comparable |
| small | duckdb | A5461833942 | 72 | 4 | pgq | skipped |  |  |  |  | not available on duckdb |
| small | duckdb | A5461833942 | 72 | 4 | neo4j | ok | 658 | 44.2 | 47.1 | 58 |  |
| small | duckdb | A5461833942 | 72 | 6 | cte_raw | ok | 658 | 41.7 | 44.5 | 38 |  |
| small | duckdb | A5461833942 | 72 | 6 | cte_edge | ok | 13 | 13.4 | 14.2 | 43 | approximate (daily edges, top-K): paths not comparable |
| small | duckdb | A5461833942 | 72 | 6 | pgq | skipped |  |  |  |  | not available on duckdb |
| small | duckdb | A5461833942 | 72 | 6 | neo4j | ok | 658 | 44.3 | 46.7 | 58 |  |
| small | duckdb | A5461833942 | 720 | 2 | cte_raw | ok | 4289 | 33.3 | 36.1 | 38 |  |
| small | duckdb | A5461833942 | 720 | 2 | cte_edge | ok | 26 | 12.4 | 13.8 | 43 | approximate (daily edges, top-K): paths not comparable |
| small | duckdb | A5461833942 | 720 | 2 | pgq | skipped |  |  |  |  | not available on duckdb |
| small | duckdb | A5461833942 | 720 | 2 | neo4j | ok | 4289 | 226.4 | 255.1 | 58 |  |
| small | duckdb | A5461833942 | 720 | 4 | cte_raw | ok | 10955 | 78.3 | 98.3 | 38 |  |
| small | duckdb | A5461833942 | 720 | 4 | cte_edge | ok | 27 | 14.0 | 14.4 | 43 | approximate (daily edges, top-K): paths not comparable |
| small | duckdb | A5461833942 | 720 | 4 | pgq | skipped |  |  |  |  | not available on duckdb |
| small | duckdb | A5461833942 | 720 | 4 | neo4j | ok | 10955 | 600.5 | 619.1 | 58 |  |
| small | duckdb | A5461833942 | 720 | 6 | cte_raw | ok | 22394 | 141.0 | 164.6 | 38 |  |
| small | duckdb | A5461833942 | 720 | 6 | cte_edge | ok | 27 | 14.2 | 14.6 | 43 | approximate (daily edges, top-K): paths not comparable |
| small | duckdb | A5461833942 | 720 | 6 | pgq | skipped |  |  |  |  | not available on duckdb |
| small | duckdb | A5461833942 | 720 | 6 | neo4j | ok | 22394 | 1206.2 | 1368.2 | 58 |  |

## small on oracle

- Command: `aml bench --profile small`, started 2026-10-13T04:39:23+00:00 (UTC), 211.165 s in total, commit ab5536f
- Versions: python 3.11.9, aml 0.1.0, oracledb 26.0.1, server 23.26.3.0.0, neo4j driver 6.4.0
- Machine: Windows-10-10.0.26200-SP0, Intel64 Family 6 Model 151 Stepping 5, GenuineIntel, 12 logical CPUs
- Data: 5000 customers, 8958 accounts, 306000 transactions, 214589 transfers
- Runs: 1 warm-up and 10 timed runs per cell; hops [2, 4, 6], T [72, 720] h; accounts ['A5461833942'] (picked automatically)
- Trace limits: max_paths 100000, cte_edge min amount 10000000 VND, top-K 5; Neo4j read timeout 60.0 s
- Graph sync: FULL 42.11 s, INCREMENTAL 2.12 s, lag after the last run 0 s

| profile | backend | account | T (h) | hops | method | status | paths | median ms | p95 ms | query lines | note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| small | oracle | A5461833942 | 72 | 2 | cte_raw | ok | 632 | 13.7 | 14.8 | 30 |  |
| small | oracle | A5461833942 | 72 | 2 | cte_edge | ok | 13 | 4.6 | 5.4 | 38 | approximate (daily edges, top-K): paths not comparable |
| small | oracle | A5461833942 | 72 | 2 | pgq | ok | 632 | 25.2 | 26.8 | 19 |  |
| small | oracle | A5461833942 | 72 | 2 | neo4j | ok | 632 | 43.5 | 45.9 | 58 |  |
| small | oracle | A5461833942 | 72 | 4 | cte_raw | ok | 658 | 15.3 | 18.2 | 30 |  |
| small | oracle | A5461833942 | 72 | 4 | cte_edge | ok | 13 | 4.5 | 4.7 | 38 | approximate (daily edges, top-K): paths not comparable |
| small | oracle | A5461833942 | 72 | 4 | pgq | ok | 658 | 182.8 | 199.5 | 49 |  |
| small | oracle | A5461833942 | 72 | 4 | neo4j | ok | 658 | 45.2 | 53.5 | 58 |  |
| small | oracle | A5461833942 | 72 | 6 | cte_raw | ok | 658 | 16.2 | 22.8 | 30 |  |
| small | oracle | A5461833942 | 72 | 6 | cte_edge | ok | 13 | 5.0 | 5.4 | 38 | approximate (daily edges, top-K): paths not comparable |
| small | oracle | A5461833942 | 72 | 6 | pgq | ok | 658 | 7537.7 | 8929.6 | 99 |  |
| small | oracle | A5461833942 | 72 | 6 | neo4j | ok | 658 | 44.5 | 59.0 | 58 |  |
| small | oracle | A5461833942 | 720 | 2 | cte_raw | ok | 4289 | 43.6 | 61.4 | 30 |  |
| small | oracle | A5461833942 | 720 | 2 | cte_edge | ok | 26 | 4.9 | 5.0 | 38 | approximate (daily edges, top-K): paths not comparable |
| small | oracle | A5461833942 | 720 | 2 | pgq | ok | 4289 | 48.6 | 63.7 | 19 |  |
| small | oracle | A5461833942 | 720 | 2 | neo4j | ok | 4289 | 226.0 | 252.3 | 58 |  |
| small | oracle | A5461833942 | 720 | 4 | cte_raw | ok | 10955 | 160.7 | 183.5 | 30 |  |
| small | oracle | A5461833942 | 720 | 4 | cte_edge | ok | 27 | 4.6 | 5.0 | 38 | approximate (daily edges, top-K): paths not comparable |
| small | oracle | A5461833942 | 720 | 4 | pgq | ok | 10955 | 262.8 | 288.4 | 49 |  |
| small | oracle | A5461833942 | 720 | 4 | neo4j | ok | 10955 | 577.6 | 600.5 | 58 |  |
| small | oracle | A5461833942 | 720 | 6 | cte_raw | ok | 22394 | 405.3 | 443.8 | 30 |  |
| small | oracle | A5461833942 | 720 | 6 | cte_edge | ok | 27 | 4.8 | 5.3 | 38 | approximate (daily edges, top-K): paths not comparable |
| small | oracle | A5461833942 | 720 | 6 | pgq | ok | 22394 | 7588.8 | 8404.9 | 99 |  |
| small | oracle | A5461833942 | 720 | 6 | neo4j | ok | 22394 | 1184.1 | 1401.7 | 58 |  |

## Notes

- Time is `TraceResult.seconds`: the query, fetching the answer into a DataFrame and normalising it (sorting). The freshness check of `neo4j` (`prepare`), the warm-up runs and the audit row are outside the clock.
- p95 is taken by linear interpolation between the two nearest ranks (the NumPy default). With fewer than 20 timed runs it is close to the slowest run; min, max and every raw time are in the JSON file.
- `cte_edge` is an approximation (daily edges, top-K), so its number of paths cannot be compared with the exact methods.
- Query lines are the non-blank, non-comment lines of the query that ran. For `pgq` they grow with the number of hops (one GRAPH_TABLE block per hop); for `neo4j` one Cypher file serves every hop count.
- DuckDB runs in-process; Oracle and Neo4j are reached over the network (local Docker ports). Methods are comparable only within one file: same backend, same data, a graph synced from that backend.
- `skipped`: the method cannot run there (wrong backend, service down, graph out of sync). `error`: it ran and failed; the reason is in the note.
- The account is the heaviest case by time-ordered 2-hop paths when it was picked automatically, not a typical one.
