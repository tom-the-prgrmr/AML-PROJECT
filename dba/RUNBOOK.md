# AML demo database runbook

DBA notes for the Oracle side of this synthetic-data demo. Everything quoted below was captured on 2026-10-10 from a local docker instance (profile `small`); the values drift over time and are not a benchmark of anything but this laptop. Scripts live under `dba/scripts/` (see the Script index at the end), captured outputs under `results/phase2/`.

## 1. Environment and limits

The database is the `gvenzl/oracle-free` container image (slim variant), started through `docker compose` with the `oracle` profile. `results/phase2/runbook/environment_facts.txt` reports the banner `Oracle AI Database 26ai Free Release 23.26.3.0.0 - Develop, Learn, and Run for Free`, `log_mode` NOARCHIVELOG, `db_recovery_file_dest` empty with size 0, `statistics_level` TYPICAL and `control_management_pack_access` = DIAGNOSTIC+TUNING. The application connects as `aml_owner`, which has the `DB_DEVELOPER_ROLE` plus four explicit grants made by `dba/scripts/sys/010_grant_tuning_views.sql`: SELECT on `V_$SESSION`, `V_$SQL`, `V_$SQL_PLAN` and `V_$SQL_PLAN_STATISTICS_ALL` (confirmed in `results/phase2/runbook/010_grant_tuning_views.txt`). Free edition cannot do everything an Enterprise database can: the NOARCHIVELOG setting means no online backup or point-in-time recovery, and this compose file runs one container with no standby. Which management packs may be used on Free is a licensing question, not a technical one (see section 3).

Every `.txt` under `results/phase2/runbook/` was produced with the same pattern, from Git Bash with `MSYS_NO_PATHCONV=1`, where `<name>` is the script name without extension:

```bash
{ printf 'SET LINESIZE 200 PAGESIZE 500 TRIMSPOOL ON\n'; cat dba/scripts/sys/<name>.sql; } | docker compose exec -T oracle sqlplus -s / as sysdba > results/phase2/runbook/<name>.txt
```

Security operations notes. `src/aml/dba/security.py` issues `CREATE USER ... IDENTIFIED BY` from Python, so the demo password travels in SQL statement text. I have not checked whether this release redacts it in `V$SQL` or in audit records, so treat those as possibly containing it; that is acceptable for synthetic data and would not be for production, where you would provision users out of band. On this instance a missing object privilege is reported as ORA-41900, not the classic ORA-01031: `results/phase2/missing_privilege_error.txt` holds the captured message (`ORA-41900: missing INSERT privilege on "AML_OWNER"."TRANSACTIONS"`), and the Phase 2b tests accept either code. `apply_security` only adds grants; it never revokes, so removing a privilege is a manual step.

## 2. Backup and restore

For this schema the things that need protecting are the `aml_owner` objects (the partitioned `transactions` table, `audit_log`, the data quality tables, the materialized view `acct_edge_daily`) and the Parquet archives that `aml retention` writes before it drops old partitions; those files are the only copy of that history once the partitions are gone, so they belong in the same backup set. A proper RMAN strategy would be a weekly level 0 and daily level 1 incremental of the pluggable database plus archived logs, which is sketched in `dba/scripts/reference/rman_backup_full.rman` and `dba/scripts/reference/rman_restore_pitr.rman`. Those scripts are reference only: the `rman` binary is not available in the slim image, and the database is in NOARCHIVELOG mode, so RMAN online backup and point-in-time recovery are not possible here. `dba/scripts/reference/enable_archivelog.sql` shows what switching on ARCHIVELOG would take (a recovery area, a restart); it was never run.

What is feasible on this setup is a logical export with expdp and impdp (parameters in `dba/scripts/reference/expdp_schema.par`), plus a cold backup of the oradata volume taken while the container is stopped. A restore test worth doing is to impdp the dump into a scratch schema with `remap_schema`, compare row counts per table against the source, and then rebuild derived objects such as `acct_edge_daily` with a complete refresh. Note that the export file is a snapshot at one moment, so anything written after it is lost on restore.

## 3. Reading AWR, ASH and Statspack

AWR keeps periodic snapshots of instance statistics and ASH samples active sessions once per second into memory (`V$ACTIVE_SESSION_HISTORY`). On 2026-10-10 `results/phase2/runbook/environment_facts.txt` shows 13 AWR snapshots for each of two DBIDs (the CDB root, `con_id` 0, and this PDB, `con_id` 3), an interval of one hour and a retention of eight days (`+00000 01:00:00.0 / +00008 00:00:00.0`) for both, and 1108 rows in ASH. `DBA_HIST_SNAPSHOT` returns one row set per DBID, so an unfiltered `COUNT(*)` double-counts; the scripts group or filter by DBID for that reason. `results/phase2/runbook/awr_snapshots.txt` lists the ten newest snapshots of the PDB, ids 4 to 13, from 2026-10-09 13:00 to 2026-10-10 16:00. Snapshots 4 to 7 are one hour apart; the later ones span between about one and nine and a half hours. I did not capture why; this container is started and stopped by hand, so downtime is the likely cause, but that is an assumption. `results/phase2/runbook/ash_top_sql.txt` ranks SQL_IDs by ASH samples; in this capture the top two were last seen waiting on `log file switch completion` and `online DDL delay`, followed by undo segment extension, CPU and `SQL*Net more data from client`. The script does not show the SQL text, so I am not attributing them to a specific workload here.

Licensing: on Enterprise Edition, AWR, ASH and the related reports (ADDM, `awrrpt.sql`) belong to the Diagnostics Pack and need a separate licence. I am not asserting what Free includes; the instance reports `control_management_pack_access` = DIAGNOSTIC+TUNING, but a parameter value is not an entitlement, so read the Licensing Information User Manual for the exact release before relying on these views. The pack-free alternative is Statspack, installed by `spcreate.sql` as sketched in `dba/scripts/reference/statspack_install.sql` (reference only, not installed here). Typical reading order for any of these reports: top wait events first, then top SQL by elapsed time and by buffer gets, then check whether the busy window matches the workload you meant to measure.

## 4. Reading DBMS_XPLAN output

There are two ways to get a plan. `EXPLAIN PLAN` followed by `DBMS_XPLAN.DISPLAY` shows the optimizer's estimate without running the statement (`dba/scripts/owner/xplan_explain_typical.sql`); it can differ from reality because bind peeking and runtime adaptation are not reflected. `DBMS_XPLAN.DISPLAY_CURSOR` shows the plan of a statement that actually ran. With the `GATHER_PLAN_STATISTICS` hint (or `statistics_level = ALL`) and the format `ALLSTATS LAST`, it adds per-step runtime figures for the last execution (`dba/scripts/owner/xplan_display_cursor_last.sql`, a real example in `results/phase2/tune_demo.txt`). `DISPLAY_CURSOR` reads `V$SQL` and `V$SQL_PLAN_STATISTICS_ALL`, which is why `aml_owner` needs the four V$ grants from section 1; without them the call returns nothing useful.

Columns to read: E-Rows is the optimizer's estimate and A-Rows the actual count; a large gap, such as the estimate of 35 against 8769 actual at the HASH GROUP BY step in the "before" plan, means bad statistics or a predicate the optimizer cannot see through. Buffers is the number of logical reads at that step and below (cumulative), the most stable measure of work. Starts shows how often a step ran. For partitioned tables, Pstart and Pstop show which partitions are touched. `results/phase2/partition_pruning.txt` shows three cases on `transactions`: a one-month range gives PARTITION RANGE SINGLE with Pstart and Pstop both 315, a two-month range gives PARTITION RANGE ITERATOR with 315 to 316, and no predicate gives PARTITION RANGE ALL with 1 to 1048575. Those checks use literal timestamps, not bind variables: with a literal the optimizer can compute the partition numbers at parse time, while with a bind it shows KEY in Pstart/Pstop (pruning decided at run time), which is correct but less readable in a plan.

## 5. Materialized view refresh

`acct_edge_daily` (defined in `sql/oracle/ddl/040_acct_edge_daily.sql`) is a materialized view built as REFRESH COMPLETE ON DEMAND. The reason is cost: this demo loads `transactions` in bulk and the graph edges are only needed after a load, so one complete rebuild per load is cheaper and simpler than keeping a log on every insert. The application refreshes it in `src/aml/dba/edges.py` with `DBMS_MVIEW.REFRESH('ACCT_EDGE_DAILY', 'C', atomic_refresh => FALSE)`. Non-atomic refresh replaces the contents with TRUNCATE plus insert instead of one big DELETE, which is faster and generates less undo, at the price that readers can briefly see an empty view and a failure mid-way leaves it empty or partial. Because it needs a TRUNCATE, it interacts with the schema-level trigger `trg_audit_log_no_truncate` from the 2b security work (`sql/oracle/ddl/050_security_objects.sql`): that `BEFORE TRUNCATE ON SCHEMA` trigger raises an error only when the object is `AUDIT_LOG`, so truncating the materialized view is unaffected while truncating the append-only audit log is refused.

A fast (incremental) refresh would need a MATERIALIZED VIEW LOG on `transactions` created WITH ROWID, SEQUENCE and the used columns, INCLUDING NEW VALUES, and the view query would have to carry COUNT(*) and COUNT(amount_vnd) next to SUM(amount_vnd). The sketch is in `dba/scripts/reference/mv_log_fast_refresh.sql` (reference only, never run). To find out why a view is not fast-refreshable, call `DBMS_MVIEW.EXPLAIN_MVIEW` and read `mv_capabilities_table`. The trade-off is that the log adds work to every DML on the base table and to retention drops, so it only pays off with a steady trickle of changes.

## 6. Partition maintenance

`transactions` is interval partitioned by month on `txn_ts` (`sql/oracle/ddl/020_transactions_partitioning.sql`); Oracle creates new monthly partitions on demand. The anchor partition `p_before_2000` is the single range partition that defines the interval start. Oracle does not allow dropping the last partition of the range section, and trying to do so fails with ORA-14758, so that anchor stays. The primary key index is global, and dropping a partition would leave a global index unusable (later DML fails with ORA-01502), so drops must use `DROP PARTITION ... UPDATE GLOBAL INDEXES`, shown in `dba/scripts/reference/drop_partition_update_global_indexes.sql`. Check index health afterwards with `dba/scripts/owner/partition_and_index_status.sql`. `audit_log` is also partitioned (`sql/oracle/ddl/070_audit_log_partitioning.sql`) but is never purged and is append-only, protected by update/delete and truncate triggers.

`uv run aml retention` is the supported way to drop old data (`src/aml/dba/retention.py`). Operational notes:

- It is a dry run unless you pass `--execute`; the dry run prints the partitions that would go.
- The configured retention cannot go below the legal floor of 60 months; a lower value is rejected before any database query.
- Per partition the order is archive to Parquet, verify the archive, then drop. A partition that holds rows is never dropped without a verified archive; a partition that is empty when re-read just before the drop is dropped with no archive file, and the audit row says so.
- If a run stops with "archive already exists" after an earlier drop failed, do not delete anything blindly: inspect the Parquet file, compare its row count with the partition, move it aside, then rerun. The refusal to overwrite is deliberate.
- A far-future `--as-of` combined with `--execute` moves the cutoff forward and would archive and drop data that is still in retention. Always read the dry run first.
- A failure to write the archive (disk full, permissions) surfaces as an `OSError` traceback, not a friendly message.

## 7. Tuning walkthrough

The demo query asks for the 30-day outflow per account in March 2026: sum and count of `transactions` per `from_account_id`, keeping accounts above the large-cash threshold. The slow version wraps the partition key in a function: `WHERE TRUNC(txn_ts) BETWEEN DATE '2026-03-01' AND DATE '2026-03-30'`. The optimizer cannot map a function of `txn_ts` to partitions, so it scans all of them. In the actual plan this shows as PARTITION RANGE ALL (the `ALLSTATS LAST` format has no Pstart/Pstop columns; the EXPLAIN PLAN evidence in `results/phase2/partition_pruning.txt` shows the same operation with Pstart 1 and Pstop 1048575) and a TABLE ACCESS FULL that returned A-Rows 46404 while reading 4449 Buffers. The fix is a half-open range on the bare column: `txn_ts >= TIMESTAMP '2026-03-01 00:00:00' AND txn_ts < TIMESTAMP '2026-03-31 00:00:00'`. The plan becomes PARTITION RANGE SINGLE with the same A-Rows of 46404 but only 752 Buffers; both versions return 155 rows. The evidence file records only the row counts; the acceptance test `tests/runbook/test_tuning.py` compares the full result sets of the two queries on the test fixture. No hints, indexes or statistics changes were involved. (The inclusive `BETWEEN ... AND DATE '2026-03-30'` on a truncated date and the half-open range to 2026-03-31 cover the same days.)

Measured with `uv run aml tune-demo` on profile `small` (`transactions_rows: 306000`), five runs per variant, evidence in `results/phase2/tune_demo.txt`:

| Variant | plan_hash_value | buffer_gets | elapsed_ms_median |
|---|---|---|---|
| before (TRUNC on partition key) | 935595979 | 4449 | 60.391 |
| after (half-open range) | 3905367866 | 752 | 5.339 |

Caveats: this is a laptop docker instance with a warm cache, and elapsed time is the median of 5 runs, so treat the milliseconds as indicative. Buffer gets are the stable metric and the one to compare across machines. The table is small, so the absolute gain is small; the point is the shape of the plan, which scales with table size.

To reproduce: run `dba/scripts/sys/010_grant_tuning_views.sql` as SYS once (section 1), load the small profile into Oracle, then run `uv run aml tune-demo`. Running it without `--out` rewrites `results/phase2/tune_demo.txt`. Afterwards `dba/scripts/owner/xplan_display_cursor_last.sql` prints the actual plan of the latest tagged cursor as `aml_owner`.

## Script index

| Script | Runs as | Status | Purpose |
|---|---|---|---|
| `dba/scripts/owner/partition_and_index_status.sql` | aml_owner | verified | Partitions of transactions with row estimates and index validity |
| `dba/scripts/owner/xplan_display_cursor_last.sql` | aml_owner | verified | Actual plan (ALLSTATS LAST) of the latest tune-demo cursor |
| `dba/scripts/owner/xplan_explain_typical.sql` | aml_owner | verified | Estimated plan (TYPICAL) for the slow tuning query |
| `dba/scripts/sys/010_grant_tuning_views.sql` | SYS | manual | Grants the four V$ views to aml_owner |
| `dba/scripts/sys/ash_top_sql.sql` | SYS | manual | Top SQL by ASH samples |
| `dba/scripts/sys/awr_snapshots.sql` | SYS | manual | Latest AWR snapshots |
| `dba/scripts/sys/environment_facts.sql` | SYS | manual | Version, log mode, parameters, AWR and ASH counts |
| `dba/scripts/reference/drop_partition_update_global_indexes.sql` | none (not run) | reference | Partition drop that maintains global indexes |
| `dba/scripts/reference/enable_archivelog.sql` | none (not run) | reference | Steps to enable ARCHIVELOG |
| `dba/scripts/reference/expdp_schema.par` | none (not run) | reference | Data Pump schema export parameters |
| `dba/scripts/reference/mv_log_fast_refresh.sql` | none (not run) | reference | Materialized view log and fast refresh sketch |
| `dba/scripts/reference/rman_backup_full.rman` | none (not run) | reference | RMAN level 0 and level 1 backup |
| `dba/scripts/reference/rman_restore_pitr.rman` | none (not run) | reference | RMAN point-in-time restore of the PDB |
| `dba/scripts/reference/statspack_install.sql` | none (not run) | reference | Statspack install and snapshot sketch |
