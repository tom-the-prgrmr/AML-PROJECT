-- Runs as SYS, once, by hand (Status: manual):
--   docker compose exec -T oracle sqlplus -s / as sysdba < dba/scripts/sys/010_grant_tuning_views.sql
-- Lets aml_owner call DBMS_XPLAN.DISPLAY_CURSOR on its own cursors. The owner name is hard-coded.
ALTER SESSION SET CONTAINER = FREEPDB1
/
GRANT SELECT ON V_$SQL TO AML_OWNER
/
GRANT SELECT ON V_$SQL_PLAN TO AML_OWNER
/
GRANT SELECT ON V_$SQL_PLAN_STATISTICS_ALL TO AML_OWNER
/
GRANT SELECT ON V_$SESSION TO AML_OWNER
/
SELECT 'grant' AS label, CAST(grantee AS VARCHAR2(20)) AS grantee, CAST(table_name AS VARCHAR2(30)) AS view_name, privilege FROM dba_tab_privs WHERE grantee = 'AML_OWNER' AND table_name IN ('V_$SQL', 'V_$SQL_PLAN', 'V_$SQL_PLAN_STATISTICS_ALL', 'V_$SESSION') ORDER BY table_name
/
