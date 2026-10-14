-- Cases of the latest case run (every status). No names, documents or memos: ids and counts only.
SELECT case_id, golden_customer_id, status, window_start, first_alert_ts, last_alert_ts,
       alerts, sources
FROM cases_current
ORDER BY case_id;
