-- Phase 8e: which of the given ids exist in the system of record. {ids} is replaced by a list of
-- quoted literals that were checked against the id pattern first (no free text reaches this file).
SELECT txn_id AS id FROM transactions WHERE txn_id IN ({ids})
UNION
SELECT account_id AS id FROM accounts WHERE account_id IN ({ids})
UNION
SELECT from_account_id AS id FROM transactions WHERE from_account_id IN ({ids})
UNION
SELECT to_account_id AS id FROM transactions WHERE to_account_id IN ({ids})
UNION
SELECT golden_customer_id AS id FROM customer_golden WHERE golden_customer_id IN ({ids})
UNION
SELECT case_id AS id FROM cases WHERE case_id IN ({ids})
UNION
SELECT cif AS id FROM customers WHERE cif IN ({ids})
UNION
SELECT entry_id AS id FROM watchlist WHERE entry_id IN ({ids});
