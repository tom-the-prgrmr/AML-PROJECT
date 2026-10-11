-- Phase 3c: normalised names for the SQL screen, and the state that incremental screening needs.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_customer_name (
      cif       VARCHAR2(20 CHAR)   PRIMARY KEY,
      name_norm VARCHAR2(300 CHAR)  NOT NULL,
      name_key  VARCHAR2(300 CHAR)  NOT NULL       -- tokens sorted: order-free key
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_list_name (
      entry_id  VARCHAR2(20 CHAR)   NOT NULL,
      name_type VARCHAR2(20 CHAR)   NOT NULL,      -- PRIMARY | AKA | TRANSLITERATION | REORDERED
      name_norm VARCHAR2(300 CHAR)  NOT NULL,
      name_key  VARCHAR2(300 CHAR)  NOT NULL,
      CONSTRAINT pk_screening_list_name PRIMARY KEY (entry_id, name_norm)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

-- Fingerprint of the last screening that covered each entity.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_state (
      entity_type VARCHAR2(20 CHAR)  NOT NULL,     -- customer | watchlist_entry
      entity_id   VARCHAR2(20 CHAR)  NOT NULL,
      fingerprint VARCHAR2(64 CHAR)  NOT NULL,     -- SHA-256 hex
      run_id      NUMBER(12)         NOT NULL,
      CONSTRAINT pk_screening_state PRIMARY KEY (entity_type, entity_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

-- IDF frozen at the last FULL run.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_token_stats (
      token    VARCHAR2(100 CHAR)  PRIMARY KEY,
      doc_freq NUMBER(18)          NOT NULL,
      n_names  NUMBER(18)          NOT NULL,
      run_id   NUMBER(12)          NOT NULL
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/
