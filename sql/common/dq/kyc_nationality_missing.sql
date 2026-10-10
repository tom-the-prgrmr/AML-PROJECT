-- KYC_NATIONALITY_MISSING: customers without a nationality.
SELECT cif AS entity_id
FROM customers
WHERE nationality IS NULL;
