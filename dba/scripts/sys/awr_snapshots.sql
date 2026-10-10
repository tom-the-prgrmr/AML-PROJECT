-- Runs as SYS by hand (Status: manual), read-only:
--   docker compose exec -T oracle sqlplus -s / as sysdba < dba/scripts/sys/awr_snapshots.sql
-- Latest AWR snapshots; their ids are the begin/end pair that awrrpt.sql asks for.
-- DBA_HIST_SNAPSHOT holds one row set per DBID (CDB root and this PDB); filter to the PDB's own.
-- AWR belongs to the Diagnostics Pack on Enterprise Edition; check your licence.
ALTER SESSION SET CONTAINER = FREEPDB1
/
SELECT 'awr_snapshot' AS label, snap_id, TO_CHAR(begin_interval_time, 'YYYY-MM-DD HH24:MI') AS begin_time, TO_CHAR(end_interval_time, 'YYYY-MM-DD HH24:MI') AS end_time FROM dba_hist_snapshot WHERE dbid = (SELECT con_dbid FROM v$database) ORDER BY snap_id DESC FETCH FIRST 10 ROWS ONLY
/
