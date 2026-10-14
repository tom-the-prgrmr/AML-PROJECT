-- Phase 7a: raw alert rows of the sources (Phase 7b-i adds ANOMALY), each tagged with its golden customer.
-- Screening: one row per ALERT / REVIEW pair of screening_current; the event time is the as_of of
-- the first screening run that flagged the pair (screening results carry no event time).
-- Rule / network / anomaly: one row per (alert, account owner) of alerts_current; a golden customer with
-- several accounts in one alert is merged into one item in Python (collect_items).
SELECT 'SCREENING'                                   AS source,
       'SCREENING_' || s.decision                    AS rule_id,
       'SCREENING|' || s.cif || '|' || s.entry_id    AS alert_key,
       s.cif || ':' || s.entry_id                    AS alert_ref,
       s.cif                                         AS cif,
       COALESCE(g.golden_customer_id, 'G-' || s.cif) AS golden_customer_id,
       s.entry_id                                    AS entry_id,
       CAST(f.first_as_of AS TIMESTAMP)              AS event_ts,
       CAST(f.first_as_of AS TIMESTAMP)              AS end_ts,
       0                                             AS amount_vnd,
       0                                             AS txn_count,
       s.reason                                      AS reason,
       CAST(NULL AS VARCHAR)                         AS subject_type,
       CAST(NULL AS VARCHAR)                         AS role,
       s.list_type                                   AS list_type,
       s.decision                                    AS decision,
       s.final_score                                 AS final_score
FROM screening_current s
JOIN (
    SELECT r.cif, r.entry_id, MIN(sr.as_of) AS first_as_of
    FROM screening_results r
    JOIN screening_runs sr ON sr.run_id = r.run_id
    WHERE r.decision IN ('ALERT', 'REVIEW')
    GROUP BY r.cif, r.entry_id
) f ON f.cif = s.cif AND f.entry_id = s.entry_id
LEFT JOIN customer_golden g ON g.cif = s.cif
WHERE s.decision IN ('ALERT', 'REVIEW')
UNION ALL
SELECT a.source,
       a.rule_id,
       a.alert_key,
       CAST(a.alert_id AS VARCHAR),
       aa.cif,
       COALESCE(g.golden_customer_id, 'G-' || aa.cif),
       CAST(NULL AS VARCHAR),
       a.window_start,
       a.window_end,
       a.amount_vnd,
       a.txn_count,
       a.reason,
       a.subject_type,
       aa.role,
       CAST(NULL AS VARCHAR),
       CAST(NULL AS VARCHAR),
       CAST(NULL AS DOUBLE)
FROM alerts_current a
JOIN alert_accounts aa ON aa.alert_id = a.alert_id
LEFT JOIN customer_golden g ON g.cif = aa.cif
WHERE a.source IN ('RULE', 'NETWORK', 'ANOMALY') AND aa.cif IS NOT NULL;
