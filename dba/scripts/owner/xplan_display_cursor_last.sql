-- Runs as aml_owner (read-only). Status: verified.
-- Actual plan (ALLSTATS LAST) of the most recent cursor tagged by `uv run aml tune-demo`.
-- Needs the V$ grants from dba/scripts/sys/010_grant_tuning_views.sql.
SELECT p.plan_table_output
FROM (
  SELECT sql_id, child_number
  FROM v$sql
  WHERE sql_text LIKE 'SELECT /*+ GATHER_PLAN_STATISTICS */ /* aml-tune-demo:%'
  ORDER BY last_active_time DESC, child_number DESC
  FETCH FIRST 1 ROW ONLY
) c,
TABLE(DBMS_XPLAN.DISPLAY_CURSOR(c.sql_id, c.child_number, 'ALLSTATS LAST')) p
/
