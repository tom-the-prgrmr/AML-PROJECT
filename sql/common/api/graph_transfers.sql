-- Phase 9b: transfers of a window aggregated per (from, to) account pair, for the case graph.
-- Placeholders: {window_start} / {window_end_next} are DATE literals (the end day is whole),
-- {pairs_filter} is a boolean condition on from_account_id / to_account_id built by the caller.
-- Plain SQL, valid on DuckDB and Oracle; ranking and set logic are done by the caller.
SELECT from_account_id,
       to_account_id,
       COUNT(*)        AS txns,
       SUM(amount_vnd) AS vnd,
       MIN(txn_ts)     AS first_ts,
       MAX(txn_ts)     AS last_ts
FROM transactions
WHERE from_account_id IS NOT NULL
  AND to_account_id IS NOT NULL
  AND from_account_id <> to_account_id
  AND txn_ts >= {window_start}
  AND txn_ts < {window_end_next}
  AND {pairs_filter}
GROUP BY from_account_id, to_account_id
