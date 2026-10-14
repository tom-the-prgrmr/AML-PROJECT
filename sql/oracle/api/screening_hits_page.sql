-- Phase 9b: one page of the current screening results, ALERT, REVIEW, AUTO_CLEARED, then score desc.
-- :decision NULL = every decision. Counts per decision come from screening_hit_counts.sql.
SELECT cif,
       entry_id,
       list_type,
       matched_name,
       matched_name_type,
       token_set,
       jaro_winkler,
       fuzzy_score,
       coverage,
       name_score,
       final_score,
       dob_gap_years,
       decision,
       reason,
       run_id
FROM screening_current
WHERE (:decision IS NULL OR decision = :decision)
ORDER BY CASE decision WHEN 'ALERT' THEN 0 WHEN 'REVIEW' THEN 1 WHEN 'AUTO_CLEARED' THEN 2 ELSE 3 END,
         final_score DESC NULLS LAST,
         cif,
         entry_id
OFFSET :page_offset ROWS FETCH NEXT :page_limit ROWS ONLY
/
