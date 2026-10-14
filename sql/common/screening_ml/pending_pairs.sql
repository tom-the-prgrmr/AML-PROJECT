-- Current screening hits that have no stored feature row yet.
SELECT r.run_id AS result_run_id, r.cif, r.entry_id, r.matched_name, r.matched_name_type,
       r.list_type
FROM screening_current r
WHERE NOT EXISTS (
    SELECT 1 FROM screening_ml_features f
    WHERE f.result_run_id = r.run_id AND f.cif = r.cif AND f.entry_id = r.entry_id
)
ORDER BY r.run_id, r.cif, r.entry_id
