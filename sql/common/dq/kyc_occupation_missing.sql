-- KYC_OCCUPATION_MISSING: customers without an occupation.
SELECT cif AS entity_id
FROM customers
WHERE occupation IS NULL;
