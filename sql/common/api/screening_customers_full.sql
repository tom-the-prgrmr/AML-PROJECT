-- Phase 9b: customers of screening hits for a supervisor (unmasked); the birth year only.
SELECT cif, full_name, EXTRACT(YEAR FROM dob) AS birth_year, nationality, gender, id_type, id_number
FROM customers
