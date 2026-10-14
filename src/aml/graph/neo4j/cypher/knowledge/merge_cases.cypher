// One Case per row of cases_current, no personal data. ABOUT only when the Customer node exists.
UNWIND $rows AS row
MERGE (c:Case {case_id: row.case_id})
SET c.golden_customer_id = row.golden_customer_id, c.status = row.status,
    c.window_start = row.window_start, c.first_alert_ts = row.first_alert_ts,
    c.last_alert_ts = row.last_alert_ts, c.alerts = row.alerts, c.sources = row.sources,
    c.case_run_id = $case_run_id, c.build_id = $build_id
WITH c, row
OPTIONAL MATCH (u:Customer {golden_customer_id: row.golden_customer_id})
FOREACH (_ IN CASE WHEN u IS NULL THEN [] ELSE [1] END |
    MERGE (c)-[a:ABOUT]->(u)
    SET a.build_id = $build_id);
