-- Phase 6c: the internal accounts with the most time-ordered 2-hop transfer pairs (Oracle).
-- Binds: :hours (window between the two hops), :top_n. Ties go to the smaller account_id.
SELECT e1.from_account_id AS account_id, COUNT(*) AS two_hop_paths
FROM transactions e1
JOIN transactions e2
  ON e2.from_account_id = e1.to_account_id
 AND e2.txn_ts > e1.txn_ts
 AND e2.txn_ts <= e1.txn_ts + NUMTODSINTERVAL(:hours, 'HOUR')
WHERE e1.from_account_id IN (SELECT account_id FROM accounts)
  AND e2.to_account_id IS NOT NULL
GROUP BY e1.from_account_id
ORDER BY two_hop_paths DESC, account_id
FETCH FIRST :top_n ROWS ONLY
/
