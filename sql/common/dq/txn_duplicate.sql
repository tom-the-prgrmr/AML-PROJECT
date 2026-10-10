-- TXN_DUPLICATE: every copy except the one with the smallest txn_id in its group.
-- Window partitions treat NULLs as equal, so the comparison is NULL-safe.
SELECT d.txn_id AS entity_id
FROM (
    SELECT txn_id,
           ROW_NUMBER() OVER (
               PARTITION BY from_account_id, to_account_id, txn_ts, amount_vnd, channel
               ORDER BY txn_id
           ) AS rn
    FROM transactions
) d
WHERE d.rn > 1;
