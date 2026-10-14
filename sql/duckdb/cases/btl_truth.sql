-- Phase 7b-iii: the ground-truth scenarios each golden customer belongs to, through a customer row
-- (sanctions / PEP subject) or through any of its accounts (any role). One row per
-- (golden customer, typology, is_suspicious); the caller keeps the suspicious ones. This is the
-- label of a below-the-line customer: it is measurement and training data, never a decision.
SELECT DISTINCT COALESCE(g.golden_customer_id, 'G-' || c.cif) AS golden_customer_id,
       gt.typology, gt.is_suspicious
FROM customers c
LEFT JOIN customer_golden g ON g.cif = c.cif
JOIN ground_truth gt ON gt.entity_type = 'customer' AND gt.entity_id = c.cif
UNION
SELECT DISTINCT COALESCE(g.golden_customer_id, 'G-' || c.cif) AS golden_customer_id,
       gt.typology, gt.is_suspicious
FROM customers c
LEFT JOIN customer_golden g ON g.cif = c.cif
JOIN accounts a ON a.cif = c.cif
JOIN ground_truth gt ON gt.entity_type = 'account' AND gt.entity_id = a.account_id;
