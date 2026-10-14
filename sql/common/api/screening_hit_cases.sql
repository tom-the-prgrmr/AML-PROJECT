-- Phase 9b: the case of the latest case run that holds a screening pair as an ACTIVE item.
SELECT cif, entry_id, MIN(case_id) AS case_id
FROM case_alerts_current
WHERE source = 'SCREENING' AND status = 'ACTIVE' AND case_id IS NOT NULL
GROUP BY cif, entry_id
