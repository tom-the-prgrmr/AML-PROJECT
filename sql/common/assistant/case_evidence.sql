-- Transactions behind each monitoring / network alert.
SELECT alert_id, txn_id
FROM alert_evidence
ORDER BY alert_id, txn_id;
