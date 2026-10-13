-- Phase 6c: the internal accounts with the most time-ordered 2-hop transfer pairs (DuckDB).
-- Binds: $hours (window between the two hops), $top_n. Ties go to the smaller account_id.
WITH t AS (
    SELECT from_account_id AS src, to_account_id AS dst, txn_ts AS ts
    FROM transactions
    WHERE from_account_id IS NOT NULL AND to_account_id IS NOT NULL
)
SELECT e1.src AS account_id, COUNT(*) AS two_hop_paths
FROM t e1
JOIN t e2 ON e2.src = e1.dst AND e2.ts > e1.ts AND e2.ts <= e1.ts + to_hours($hours)
WHERE e1.src IN (SELECT account_id FROM accounts)
GROUP BY e1.src
ORDER BY two_hop_paths DESC, account_id
LIMIT $top_n;
