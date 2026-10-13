-- Phase 7b-supp: one row per ACTIVE RULE / NETWORK item of a case whose latest disposition is
-- FALSE_POSITIVE, from the case snapshot that disposition refers to. aml.cases.suppression folds
-- the rows into one pattern per (golden customer, rule).
SELECT a.golden_customer_id AS golden_customer_id,
       a.rule_id            AS rule_id,
       a.item_key           AS item_key,
       a.amount_vnd         AS amount_vnd,
       d.decided_on         AS decided_on
FROM case_dispositions_current d
JOIN case_alerts a ON a.run_id = d.run_id AND a.case_id = d.case_id
WHERE d.disposition = 'FALSE_POSITIVE'
  AND a.status = 'ACTIVE'
  AND a.source IN ('RULE', 'NETWORK')
/
