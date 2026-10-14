-- Phase 9b: the trend of every rule over all runs (previous value and change included).
-- Plain SQL, valid on DuckDB and Oracle; filtering by rule and by run is done by the caller.
SELECT rule_id,
       table_name,
       dimension,
       run_id,
       run_ts,
       failed_rows,
       fail_rate,
       status,
       prev_failed_rows,
       delta_failed_rows
FROM dq_trend
