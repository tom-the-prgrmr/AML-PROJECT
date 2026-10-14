-- Phase 9a: the case queue of the latest run with the latest human decision of each case.
-- Plain SQL, valid on DuckDB and Oracle; filtering, sorting and paging are done by the caller.
SELECT c.case_id,
       c.golden_customer_id,
       c.status,
       c.alerts,
       c.rule_alerts,
       c.network_alerts,
       c.screening_alerts,
       c.sources,
       c.window_start,
       c.first_alert_ts,
       c.last_alert_ts,
       c.reason,
       d.disposition AS disposition,
       d.actor       AS disposition_actor,
       d.decided_on  AS disposition_decided_on
FROM cases_current c
LEFT JOIN case_dispositions_current d ON d.case_id = c.case_id
