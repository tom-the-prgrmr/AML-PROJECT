-- Phase 9b: every data quality result with its rule and the change since the previous run.
-- Plain SQL, valid on DuckDB and Oracle; the run and the ordering are chosen by the caller.
SELECT r.run_id,
       r.rule_id,
       r.run_ts,
       r.as_of,
       r.table_name,
       r.dimension,
       q.scope,
       q.description,
       q.max_fail_rate,
       r.total_rows,
       r.failed_rows,
       r.fail_rate,
       r.status,
       r.sample_ids,
       t.prev_failed_rows,
       t.delta_failed_rows
FROM dq_results r
JOIN dq_rules q ON q.rule_id = r.rule_id
JOIN dq_trend t ON t.rule_id = r.rule_id AND t.run_id = r.run_id
