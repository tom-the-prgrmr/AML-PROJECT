SELECT run_id, as_of, items, active, cases
FROM case_runs
WHERE run_id = (SELECT MAX(run_id) FROM case_runs)
