-- TXN_ACCOUNT_UNKNOWN: an internal account (not EXT-) on either side that is not in accounts.
SELECT t.txn_id AS entity_id
FROM transactions t
WHERE (t.from_account_id IS NOT NULL
       AND t.from_account_id NOT LIKE 'EXT-%'
       AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.account_id = t.from_account_id))
   OR (t.to_account_id IS NOT NULL
       AND t.to_account_id NOT LIKE 'EXT-%'
       AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.account_id = t.to_account_id));
