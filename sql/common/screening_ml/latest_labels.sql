-- Newest simulated label of every current hit.
SELECT l.cif, l.entry_id, l.label, l.origin
FROM screening_ml_labels l
JOIN screening_current c ON c.cif = l.cif AND c.entry_id = l.entry_id
WHERE l.label_id = (
    SELECT MAX(l2.label_id) FROM screening_ml_labels l2
    WHERE l2.cif = l.cif AND l2.entry_id = l.entry_id
)
