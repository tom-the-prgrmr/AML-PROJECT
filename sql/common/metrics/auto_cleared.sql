SELECT cif, entry_id, list_type, final_score, reason
FROM screening_current
WHERE decision = 'AUTO_CLEARED'
ORDER BY cif, entry_id
