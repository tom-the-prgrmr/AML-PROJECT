-- Phase 8e: the size of the data a golden set was built on (kept in its meta and checked before a run).
SELECT 'transactions' AS name, COUNT(*) AS n FROM transactions
UNION ALL
SELECT 'ground_truth' AS name, COUNT(*) AS n FROM ground_truth;
