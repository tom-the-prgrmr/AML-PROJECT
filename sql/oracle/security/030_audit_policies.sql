-- Phase 2b: unified audit policies. Runs on the admin connection with CURRENT_SCHEMA set to the
-- owner, so the object names below resolve to the owner's tables. ORA-46358 = policy exists.

BEGIN
  EXECUTE IMMEDIATE q'~
    CREATE AUDIT POLICY aml_pii_access
      ACTIONS SELECT ON customers, INSERT ON customers, UPDATE ON customers, DELETE ON customers,
              SELECT ON customer_person, INSERT ON customer_person,
              UPDATE ON customer_person, DELETE ON customer_person,
              SELECT ON customers_masked~';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -46358 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'~
    CREATE AUDIT POLICY aml_audit_log_tamper
      ACTIONS UPDATE ON audit_log, DELETE ON audit_log~';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -46358 THEN RAISE; END IF;
END;
/

AUDIT POLICY aml_pii_access
/
AUDIT POLICY aml_audit_log_tamper
/
