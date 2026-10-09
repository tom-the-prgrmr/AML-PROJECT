-- Append-only audit trail for every automated or human decision.
-- Phase 2 adds: interval partitioning by month, a trigger blocking UPDATE/DELETE,
-- and grants (INSERT for app roles, SELECT for the auditor role only).
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE audit_log (
      audit_id    NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      event_ts    TIMESTAMP(6)   NOT NULL,          -- UTC
      module      VARCHAR2(40)   NOT NULL,
      entity_type VARCHAR2(40)   NOT NULL,
      entity_id   VARCHAR2(100)  NOT NULL,
      decision    VARCHAR2(40)   NOT NULL,
      reason      VARCHAR2(4000) NOT NULL,
      version     VARCHAR2(100),
      actor       VARCHAR2(100)  NOT NULL,
      details     JSON
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/
