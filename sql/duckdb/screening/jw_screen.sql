-- Jaro-Winkler on the order-free name key; the 1e-9 keeps a score of exactly 90 from becoming 89.
SELECT cif, entry_id, MAX(score) AS jw_score
FROM (
  SELECT c.cif AS cif,
         w.entry_id AS entry_id,
         CAST(FLOOR(100 * jaro_winkler_similarity(c.name_key, w.name_key) + 1e-9) AS INTEGER) AS score
  FROM screening_customer_name c
  JOIN screening_list_name w
    ON SUBSTR(c.name_key, 1, 1) = SUBSTR(w.name_key, 1, 1)
   AND ABS(LENGTH(c.name_key) - LENGTH(w.name_key)) <= {length_band}
) pairs
WHERE score >= {threshold}
GROUP BY cif, entry_id;
