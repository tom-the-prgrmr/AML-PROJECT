-- Phase 7b-supp: the good-guy list. A screening pair (CIF, watchlist entry) that an investigator
-- cleared as a false positive stays quiet until the row expires or the customer or the entry
-- changes. Append-only: a new clearance adds a row with a higher entry_no, the view reads the
-- newest row of each pair. Hibernation has no table of its own: it is computed from the
-- dispositions and the stored items on every run. No names or document numbers are stored.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE good_guy_list (
      entry_no             NUMBER(12)          NOT NULL,
      cif                  VARCHAR2(20 CHAR)   NOT NULL,
      entry_id             VARCHAR2(40 CHAR)   NOT NULL,
      case_id              VARCHAR2(40 CHAR)   NOT NULL,
      disposition_id       NUMBER(12)          NOT NULL,     -- the FALSE_POSITIVE that produced the row
      cleared_on           DATE                NOT NULL,
      expires_on           DATE                NOT NULL,
      customer_fingerprint VARCHAR2(64 CHAR)   NOT NULL,     -- screening_state at the time of the clearance
      entry_fingerprint    VARCHAR2(64 CHAR)   NOT NULL,
      actor                VARCHAR2(60 CHAR)   NOT NULL,
      created_ts           TIMESTAMP(6)        NOT NULL,     -- UTC
      CONSTRAINT pk_good_guy_list PRIMARY KEY (entry_no)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW good_guy_current AS
    SELECT entry_no, cif, entry_id, case_id, disposition_id, cleared_on, expires_on,
           customer_fingerprint, entry_fingerprint, actor, created_ts
    FROM good_guy_list g
    WHERE entry_no = (
      SELECT MAX(entry_no) FROM good_guy_list WHERE cif = g.cif AND entry_id = g.entry_id
    )]';
END;
/

-- A SUPPRESSED item belongs to no case. 160 already creates the column nullable, this step
-- relaxes a case_alerts table that was created before the suppression phase.
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE case_alerts MODIFY (case_id NULL)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -1451 THEN RAISE; END IF;   -- ORA-01451: column is already nullable (idempotent)
END;
/
