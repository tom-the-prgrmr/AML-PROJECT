-- Phase 2b: the four least-privilege roles. Runs on the admin connection (aml security-setup).
-- Demo users are created from Python (passwords come from .env, never from a .sql file).
-- ORA-01921 = role already exists.

BEGIN
  EXECUTE IMMEDIATE 'CREATE ROLE aml_app';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -1921 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE ROLE aml_analyst';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -1921 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE ROLE aml_graph_sync';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -1921 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE ROLE aml_auditor';
EXCEPTION WHEN OTHERS THEN
  IF SQLCODE != -1921 THEN RAISE; END IF;
END;
/

GRANT AUDIT_VIEWER TO aml_auditor
/
