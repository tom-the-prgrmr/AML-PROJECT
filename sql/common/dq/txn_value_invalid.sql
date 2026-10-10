-- TXN_VALUE_INVALID: missing or non-positive amount, missing or unknown channel, missing txn_ts.
SELECT txn_id AS entity_id
FROM transactions
WHERE amount_vnd IS NULL
   OR amount_vnd <= 0
   OR channel IS NULL
   OR channel NOT IN ('CASH', 'CARD', 'INTERNAL_TRANSFER', 'INTERBANK_TRANSFER', 'EBANKING')
   OR txn_ts IS NULL;
