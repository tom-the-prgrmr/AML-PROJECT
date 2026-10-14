SELECT item_key, golden_customer_id, source, rule_id, cif, entry_id,
       suppression_rule, suppression_reason
FROM case_alerts_current
WHERE status = 'SUPPRESSED'
ORDER BY item_key, golden_customer_id
