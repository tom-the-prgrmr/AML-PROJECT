-- Phase 8e behaviour check: row counts of the tables that hold decisions. An evaluation run must
-- leave every one of them unchanged (it only reads, and writes audit_log).
SELECT 'case_dispositions' AS name, COUNT(*) AS n FROM case_dispositions
UNION ALL
SELECT 'cases' AS name, COUNT(*) AS n FROM cases
UNION ALL
SELECT 'case_alerts' AS name, COUNT(*) AS n FROM case_alerts
UNION ALL
SELECT 'good_guy_list' AS name, COUNT(*) AS n FROM good_guy_list
UNION ALL
SELECT 'alerts' AS name, COUNT(*) AS n FROM alerts
UNION ALL
SELECT 'screening_results' AS name, COUNT(*) AS n FROM screening_results;
