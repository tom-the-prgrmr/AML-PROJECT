-- Runs as SYS by hand (Status: manual), read-only:
--   docker compose exec -T oracle sqlplus -s / as sysdba < dba/scripts/sys/environment_facts.sql
ALTER SESSION SET CONTAINER = FREEPDB1
/
SELECT 'version' AS label, CAST(banner AS VARCHAR2(80)) AS value FROM v$version
/
SELECT 'log_mode' AS label, log_mode AS value FROM v$database
/
SELECT 'parameter ' || name AS label, CAST(NVL(value, '(empty)') AS VARCHAR2(80)) AS value FROM v$parameter WHERE name IN ('control_management_pack_access', 'db_recovery_file_dest', 'db_recovery_file_dest_size', 'statistics_level')
/
SELECT 'awr_snapshot_count dbid=' || dbid || ' con_id=' || con_id AS label, TO_CHAR(COUNT(*)) AS value FROM dba_hist_snapshot GROUP BY dbid, con_id ORDER BY con_id
/
SELECT 'awr_interval_retention dbid=' || dbid || ' con_id=' || con_id AS label, TO_CHAR(snap_interval) || ' / ' || TO_CHAR(retention) AS value FROM dba_hist_wr_control ORDER BY con_id
/
SELECT 'ash_rows' AS label, TO_CHAR(COUNT(*)) AS value FROM v$active_session_history
/
