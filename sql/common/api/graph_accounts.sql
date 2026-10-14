-- Phase 9b: owner and golden customer of accounts, for the case graph.
-- {account_filter} is a boolean condition on a.account_id built by the caller.
SELECT a.account_id,
       a.cif,
       g.golden_customer_id
FROM accounts a
LEFT JOIN customer_golden g ON g.cif = a.cif
WHERE {account_filter}
