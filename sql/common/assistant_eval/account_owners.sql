-- Phase 8e golden set: internal account -> golden customer (latest entity-resolution run).
SELECT a.account_id, g.golden_customer_id
FROM accounts a
JOIN customer_golden g ON g.cif = a.cif;
