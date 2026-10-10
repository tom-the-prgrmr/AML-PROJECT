-- KYC_CCCD_DOB_MISMATCH: a 12-digit CCCD whose digits 5-6 (birth year) or digit 4 (century and
-- gender) disagree with dob and gender. Digits are compared as strings, never cast to numbers.
SELECT cif AS entity_id
FROM customers
WHERE id_type = 'CCCD'
  AND regexp_matches(id_number, '^[0-9]{12}$')
  AND dob IS NOT NULL
  AND gender IN ('M', 'F')
  AND (
      substr(id_number, 5, 2) <> lpad(CAST(EXTRACT(year FROM dob) % 100 AS VARCHAR), 2, '0')
      OR substr(id_number, 4, 1) <> CASE
          WHEN EXTRACT(year FROM dob) < 2000 THEN CASE gender WHEN 'M' THEN '0' ELSE '1' END
          ELSE CASE gender WHEN 'M' THEN '2' ELSE '3' END
      END
  );
