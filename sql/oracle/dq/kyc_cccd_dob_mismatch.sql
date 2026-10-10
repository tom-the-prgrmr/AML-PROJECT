-- KYC_CCCD_DOB_MISMATCH: a 12-digit CCCD whose digits 5-6 (birth year) or digit 4 (century and
-- gender) disagree with dob and gender. Digits are compared as strings, never cast to numbers.
SELECT cif AS entity_id
FROM customers
WHERE id_type = 'CCCD'
  AND REGEXP_LIKE(id_number, '^[0-9]{12}$')
  AND dob IS NOT NULL
  AND gender IN ('M', 'F')
  AND (
      SUBSTR(id_number, 5, 2) <> TO_CHAR(MOD(EXTRACT(YEAR FROM dob), 100), 'FM00')
      OR SUBSTR(id_number, 4, 1) <> CASE
          WHEN EXTRACT(YEAR FROM dob) < 2000 THEN CASE gender WHEN 'M' THEN '0' ELSE '1' END
          ELSE CASE gender WHEN 'M' THEN '2' ELSE '3' END
      END
  )
/
