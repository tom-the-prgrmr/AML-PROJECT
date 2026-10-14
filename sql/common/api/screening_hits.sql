-- Phase 9b: every current screening result; filtering, sorting and paging are done by the caller.
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
