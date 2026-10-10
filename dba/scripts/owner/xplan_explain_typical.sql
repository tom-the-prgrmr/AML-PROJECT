-- Runs as aml_owner (writes only to the session's own PLAN_TABLE). Status: verified.
-- Estimated plan (TYPICAL) for the "before" tuning query; look at Pstart/Pstop for pruning.
EXPLAIN PLAN SET STATEMENT_ID = 'RUNBOOK_XPLAN' FOR
SELECT from_account_id, COUNT(*) AS txn_count, SUM(amount_vnd) AS total_out
FROM transactions
WHERE TRUNC(txn_ts) BETWEEN DATE '2026-03-01' AND DATE '2026-03-30' AND from_account_id IS NOT NULL
GROUP BY from_account_id HAVING SUM(amount_vnd) >= 400000000
/
SELECT plan_table_output
FROM TABLE(DBMS_XPLAN.DISPLAY('PLAN_TABLE', 'RUNBOOK_XPLAN', 'TYPICAL'))
/
DELETE FROM plan_table WHERE statement_id = 'RUNBOOK_XPLAN'
/
