-- Active alert items of the latest case run that sit in a case (every case status).
SELECT case_id, item_key, source, rule_id, alert_ref, details
FROM case_alerts_current
WHERE status = 'ACTIVE' AND case_id IS NOT NULL
ORDER BY case_id, item_key;
