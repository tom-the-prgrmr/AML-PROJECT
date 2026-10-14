-- Phase 9b: number of current screening results per system decision (the filter chips and the total).
SELECT decision, COUNT(*) AS n
FROM screening_current
GROUP BY decision
