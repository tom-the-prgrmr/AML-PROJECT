-- Phase 8c typology explainer: rule version and run parameters behind the given alerts.
-- {alert_ids} is replaced by a list of integers (alert ids checked in Python; no free text).
SELECT a.alert_id, a.rule_id, a.rule_version, a.run_id, r.params
FROM alerts a
JOIN monitoring_runs r ON r.run_id = a.run_id AND r.rule_id = a.rule_id
WHERE a.alert_id IN ({alert_ids})
ORDER BY a.alert_id;
