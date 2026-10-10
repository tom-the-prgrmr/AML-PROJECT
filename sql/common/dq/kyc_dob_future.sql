-- KYC_DOB_FUTURE: date of birth after the as_of date (born on as_of is fine).
SELECT cif AS entity_id
FROM customers
WHERE dob > {as_of};
