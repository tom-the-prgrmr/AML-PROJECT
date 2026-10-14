-- Stored features of the current screening hits, in long form.
SELECT f.result_run_id, f.cif, f.entry_id, f.feature, f.value
FROM screening_ml_features f
JOIN screening_current c
  ON c.run_id = f.result_run_id AND c.cif = f.cif AND c.entry_id = f.entry_id
