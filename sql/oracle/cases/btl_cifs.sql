-- Phase 7b-iii: the CIFs of every golden customer (a CIF without a customer_golden row is its own
-- golden customer 'G-<cif>'). Used to build the enrichment of a below-the-line customer.
SELECT COALESCE(g.golden_customer_id, 'G-' || c.cif) AS golden_customer_id, c.cif AS cif
FROM customers c
LEFT JOIN customer_golden g ON g.cif = c.cif
/
