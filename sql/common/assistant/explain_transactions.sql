-- Phase 8c typology explainer: evidence transactions of the given alerts. No memo, no names.
-- {alert_ids} is replaced by a list of integers (alert ids checked in Python; no free text).
SELECT e.alert_id, t.txn_id, t.txn_ts, t.from_account_id, t.to_account_id, t.amount_vnd, t.channel
FROM alert_evidence e
JOIN transactions t ON t.txn_id = e.txn_id
WHERE e.alert_id IN ({alert_ids})
ORDER BY t.txn_ts, t.txn_id;
