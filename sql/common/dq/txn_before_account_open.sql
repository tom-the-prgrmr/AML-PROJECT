-- TXN_BEFORE_ACCOUNT_OPEN: dated before the open_date (00:00) of the sending or receiving account.
SELECT t.txn_id AS entity_id
FROM transactions t
WHERE EXISTS (
    SELECT 1
    FROM accounts a
    WHERE a.account_id IN (t.from_account_id, t.to_account_id)
      AND t.txn_ts < a.open_date
);
