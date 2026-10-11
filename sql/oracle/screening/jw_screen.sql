SELECT cif, entry_id, MAX(score) AS jw_score
FROM (
  SELECT c.cif AS cif,
         w.entry_id AS entry_id,
         UTL_MATCH.JARO_WINKLER_SIMILARITY(c.name_key, w.name_key) AS score
  FROM screening_customer_name c
  JOIN screening_list_name w
    ON SUBSTR(c.name_key, 1, 1) = SUBSTR(w.name_key, 1, 1)
   AND ABS(LENGTH(c.name_key) - LENGTH(w.name_key)) <= {length_band}
)
WHERE score >= {threshold}
GROUP BY cif, entry_id
/
