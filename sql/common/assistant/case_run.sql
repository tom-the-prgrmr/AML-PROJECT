-- Id of the latest case run (NULL when `aml cases` never ran).
SELECT MAX(run_id) AS run_id FROM case_runs;
