-- Phase 2a: same shape as the Oracle materialized view; rebuilt by refresh_acct_edge_daily().
CREATE OR REPLACE TABLE acct_edge_daily AS
SELECT from_account_id                 AS src_acct,
       to_account_id                   AS dst_acct,
       CAST(txn_ts AS DATE)            AS day,
       CAST(COUNT(*) AS BIGINT)        AS txn_count,
       CAST(SUM(amount_vnd) AS BIGINT) AS total_amount
FROM transactions
WHERE from_account_id IS NOT NULL AND to_account_id IS NOT NULL
GROUP BY from_account_id, to_account_id, CAST(txn_ts AS DATE);
