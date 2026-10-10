-- KYC_ID_FORMAT: id_number does not match the pattern of its id_type, or the id_type is unknown.
SELECT cif AS entity_id
FROM customers
WHERE id_type IS NULL
   OR id_type NOT IN ('CCCD', 'CMND', 'PASSPORT')
   OR (id_number IS NOT NULL AND NOT (
          (id_type = 'CCCD' AND regexp_matches(id_number, '^[0-9]{12}$'))
       OR (id_type = 'CMND' AND regexp_matches(id_number, '^[0-9]{9}$'))
       OR (id_type = 'PASSPORT' AND regexp_matches(id_number, '^[A-Z][0-9]{7}$'))
   ));
