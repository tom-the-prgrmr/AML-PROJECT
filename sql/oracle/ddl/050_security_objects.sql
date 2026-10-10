-- Phase 2b security objects that need no admin rights: the masked customers view and the
-- triggers that make audit_log append-only. Role/user/grant/audit-policy scripts live in
-- sql/oracle/security/ and run through `aml security-setup`.
-- Rules mirror aml.dba.masking: blank gives NULL, digits are matched with [0-9].
-- An invalid schema-level trigger would break every statement it covers, so check user_errors.

BEGIN
  EXECUTE IMMEDIATE q'~
    CREATE OR REPLACE VIEW customers_masked AS
    WITH t AS (
      SELECT cif, gender, dob, nationality, occupation, kyc_risk, id_type, address_format,
             ward, district, province,
             REGEXP_REPLACE(full_name, '^\s+|\s+$', '') AS n,
             CASE WHEN REGEXP_LIKE(id_number, '^\s*$') THEN NULL ELSE id_number END AS i,
             REGEXP_REPLACE(phone, '[^0-9]', '') AS p,
             CASE WHEN REGEXP_LIKE(email, '^\s*$') THEN NULL ELSE email END AS e
      FROM customers
    )
    SELECT
      cif,
      CASE
        WHEN n IS NULL THEN NULL
        WHEN NOT REGEXP_LIKE(n, '\s') THEN SUBSTR(n, 1, 1) || '.'
        ELSE REGEXP_REPLACE(n, '\s+(\S)\S*', ' \1.')
      END AS full_name,
      gender,
      EXTRACT(YEAR FROM dob) AS birth_year,
      nationality,
      occupation,
      kyc_risk,
      id_type,
      CASE
        WHEN i IS NULL THEN NULL
        WHEN LENGTH(i) <= 4 THEN RPAD('*', LENGTH(i), '*')
        ELSE RPAD('*', LENGTH(i) - 4, '*') || SUBSTR(i, -4)
      END AS id_number,
      CASE
        WHEN p IS NULL THEN NULL
        WHEN LENGTH(p) <= 3 THEN RPAD('*', LENGTH(p), '*')
        ELSE RPAD('*', LENGTH(p) - 3, '*') || SUBSTR(p, -3)
      END AS phone,
      CASE
        WHEN e IS NULL THEN NULL
        WHEN INSTR(e, '@') > 1 THEN SUBSTR(e, 1, 1) || '***@' || SUBSTR(e, INSTR(e, '@') + 1)
        ELSE '***'
      END AS email,
      address_format,
      ward,
      district,
      province
    FROM t~';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'~
    CREATE OR REPLACE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    BEGIN
      RAISE_APPLICATION_ERROR(-20100, 'audit_log is append-only');
    END;~';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'~
    CREATE OR REPLACE TRIGGER trg_audit_log_no_truncate
    BEFORE TRUNCATE ON SCHEMA
    BEGIN
      IF ora_dict_obj_name = 'AUDIT_LOG' THEN
        RAISE_APPLICATION_ERROR(-20101, 'audit_log is append-only');
      END IF;
    END;~';
END;
/
