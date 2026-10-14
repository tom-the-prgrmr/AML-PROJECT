-- Phase 7b-iii: the below-the-line population of a case run = golden customers with no case_alerts
-- row at all in that run (whatever the status). A CIF without a customer_golden row counts as
-- its own golden customer 'G-<cif>', as in cases/truth_accounts.sql. {run_id} is an integer.
SELECT DISTINCT COALESCE(g.golden_customer_id, 'G-' || c.cif) AS golden_customer_id
FROM customers c
LEFT JOIN customer_golden g ON g.cif = c.cif
WHERE NOT EXISTS (
    SELECT 1 FROM case_alerts ca
    WHERE ca.run_id = {run_id}
      AND ca.golden_customer_id = COALESCE(g.golden_customer_id, 'G-' || c.cif)
)
/
