-- Phase 7c: which SUPPRESSED rule / network items of a run touch a ground-truth account of the SAME
-- golden customer as the case. One row per (item, golden customer, scenario account); the caller keeps the rows
-- whose scenario is suspicious. {run_id} is replaced by an integer.
SELECT DISTINCT ca.item_key, ca.golden_customer_id, gt.typology, gt.is_suspicious
FROM case_alerts ca
JOIN alert_accounts aa ON TO_CHAR(aa.alert_id) = ca.alert_ref
LEFT JOIN customer_golden g ON g.cif = aa.cif
JOIN ground_truth gt ON gt.entity_type = 'account' AND gt.entity_id = aa.account_id
WHERE ca.run_id = {run_id}
  AND ca.status = 'SUPPRESSED'
  AND ca.source IN ('RULE', 'NETWORK')
  AND COALESCE(g.golden_customer_id, 'G-' || aa.cif) = ca.golden_customer_id
/
