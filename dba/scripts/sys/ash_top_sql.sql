-- Runs as SYS by hand (Status: manual), read-only:
--   docker compose exec -T oracle sqlplus -s / as sysdba < dba/scripts/sys/ash_top_sql.sql
-- Top SQL by sampled active time (each ASH sample is about one second of DB time).
-- ASH and AWR belong to the Diagnostics Pack on Enterprise Edition; check your licence.
ALTER SESSION SET CONTAINER = FREEPDB1
/
SELECT 'ash_top_sql' AS label, sql_id, COUNT(*) AS samples, CAST(MAX(session_state) AS VARCHAR2(10)) AS last_state, CAST(MAX(event) AS VARCHAR2(40)) AS last_event FROM v$active_session_history WHERE sql_id IS NOT NULL GROUP BY sql_id ORDER BY COUNT(*) DESC FETCH FIRST 10 ROWS ONLY
/
