-- Phase 2b: analyst-facing view with PII masked. Mirrors aml.dba.masking and the Oracle view.
-- Rules: blank gives NULL, name keeps the family name and initials the rest, id keeps 4 chars,
-- phone keeps 3 digits, email keeps 1 char. Digits are matched with [0-9] in all implementations.
CREATE OR REPLACE VIEW customers_masked AS
WITH t AS (
    SELECT
        cif, gender, dob, nationality, occupation, kyc_risk, id_type, address_format,
        ward, district, province,
        NULLIF(regexp_replace(full_name, '^\s+|\s+$', '', 'g'), '') AS n,
        CASE WHEN regexp_matches(id_number, '^\s*$') THEN NULL ELSE id_number END AS i,
        NULLIF(regexp_replace(phone, '[^0-9]', '', 'g'), '') AS p,
        CASE WHEN regexp_matches(email, '^\s*$') THEN NULL ELSE email END AS e
    FROM customers
)
SELECT
    cif,
    CASE
        WHEN n IS NULL THEN NULL
        WHEN NOT regexp_matches(n, '\s') THEN substr(n, 1, 1) || '.'
        ELSE regexp_replace(n, '\s+(\S)\S*', ' \1.', 'g')
    END AS full_name,
    gender,
    CAST(EXTRACT(year FROM dob) AS BIGINT) AS birth_year,
    nationality,
    occupation,
    kyc_risk,
    id_type,
    CASE
        WHEN i IS NULL THEN NULL
        WHEN length(i) <= 4 THEN repeat('*', length(i))
        ELSE repeat('*', length(i) - 4) || right(i, 4)
    END AS id_number,
    CASE
        WHEN p IS NULL THEN NULL
        WHEN length(p) <= 3 THEN repeat('*', length(p))
        ELSE repeat('*', length(p) - 3) || right(p, 3)
    END AS phone,
    CASE
        WHEN e IS NULL THEN NULL
        WHEN position('@' IN e) > 1 THEN substr(e, 1, 1) || '***@' || substr(e, position('@' IN e) + 1)
        ELSE '***'
    END AS email,
    address_format,
    ward,
    district,
    province
FROM t;
