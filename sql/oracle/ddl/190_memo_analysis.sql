-- Phase 8d: memo classification. A memo label is a ranking FEATURE only: nothing here holds an
-- alert, a disposition or a case status, and no row is ever UPDATEd or DELETEd.
-- A memo is classified once per normalised key (digits become #), never per transaction.
-- memo_norm is untrusted text copied from transactions.memo: it is data for a person to read,
-- never an instruction for a model, and it is never copied into a reason or the audit trail.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE memo_runs (
      run_id         NUMBER(12)          NOT NULL,
      run_ts         TIMESTAMP(6)        NOT NULL,          -- UTC
      memo_version   VARCHAR2(20 CHAR)   NOT NULL,          -- normalisation + rules + prompt + schema
      llm_model      VARCHAR2(100 CHAR)  NOT NULL,
      transactions   NUMBER(18)          NOT NULL,
      with_memo      NUMBER(18)          NOT NULL,          -- transactions whose memo is not empty
      distinct_memos NUMBER(18)          NOT NULL,          -- distinct raw memos
      memo_keys      NUMBER(18)          NOT NULL,          -- distinct normalised keys
      reused         NUMBER(18)          NOT NULL,          -- keys that already had a label
      by_rule        NUMBER(18)          NOT NULL,
      by_llm         NUMBER(18)          NOT NULL,
      fallback       NUMBER(18)          NOT NULL,
      llm_calls      NUMBER(18)          NOT NULL,
      keys_left      NUMBER(18)          NOT NULL,          -- > 0: the run stopped early
      seconds        BINARY_DOUBLE       NOT NULL,
      actor          VARCHAR2(60 CHAR)   NOT NULL,
      CONSTRAINT pk_memo_runs PRIMARY KEY (run_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- One row = one answer of the rule layer or of the model for a key.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE memo_classifications (
      run_id        NUMBER(12)           NOT NULL,
      memo_key      VARCHAR2(32 CHAR)    NOT NULL,          -- first 32 hex characters of SHA-256(memo_norm)
      memo_version  VARCHAR2(20 CHAR)    NOT NULL,
      llm_model     VARCHAR2(100 CHAR)   NOT NULL,
      memo_norm     VARCHAR2(4000 CHAR)  NOT NULL,          -- untrusted text, for people to compare
      category      VARCHAR2(30 CHAR)    NOT NULL,          -- one of the six closed categories
      method        VARCHAR2(10 CHAR)    NOT NULL,          -- RULE | LLM | FALLBACK
      attempts      NUMBER(4)            NOT NULL,          -- LLM calls used (RULE: 0)
      pattern       NUMBER(4)            NOT NULL,          -- RULE: number of the pattern that matched, else 0
      transactions  NUMBER(18)           NOT NULL,          -- transactions with this key when it was classified
      reason        VARCHAR2(400 CHAR)   NOT NULL,          -- built from a template, never from memo or model text
      classified_ts TIMESTAMP(6)         NOT NULL,          -- UTC
      CONSTRAINT pk_memo_classifications PRIMARY KEY (run_id, memo_key, memo_version, llm_model)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- A person's label for a key. A change of mind is a new row and the row of the model above is never touched.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE memo_overrides (
      override_id       NUMBER(12)          NOT NULL,
      memo_key          VARCHAR2(32 CHAR)   NOT NULL,
      memo_version      VARCHAR2(20 CHAR)   NOT NULL,       -- context of the decision, for tracing only
      llm_model         VARCHAR2(100 CHAR)  NOT NULL,
      category          VARCHAR2(30 CHAR)   NOT NULL,
      previous_category VARCHAR2(30 CHAR)   NOT NULL,       -- the label in force just before this decision
      previous_method   VARCHAR2(10 CHAR)   NOT NULL,
      reason            VARCHAR2(500 CHAR)  NOT NULL,       -- the person's own words, stored as data
      actor             VARCHAR2(60 CHAR)   NOT NULL,
      decided_ts        TIMESTAMP(6)        NOT NULL,       -- UTC
      CONSTRAINT pk_memo_overrides PRIMARY KEY (override_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- Six counts per case, kept apart from case_features so the Phase 7c feature set stays as it is.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_memo_features (
      run_id       NUMBER(12)          NOT NULL,            -- the case run (snapshot)
      case_id      VARCHAR2(40 CHAR)   NOT NULL,
      memo_version VARCHAR2(20 CHAR)   NOT NULL,
      llm_model    VARCHAR2(100 CHAR)  NOT NULL,
      labels_rev   NUMBER(12)          NOT NULL,            -- newest override_id when the rows were written
      feature      VARCHAR2(40 CHAR)   NOT NULL,
      value        BINARY_DOUBLE       NOT NULL,
      CONSTRAINT pk_case_memo_features
        PRIMARY KEY (run_id, case_id, memo_version, llm_model, labels_rev, feature)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW memo_classifications_current AS
    SELECT c.run_id, c.memo_key, c.memo_version, c.llm_model, c.memo_norm, c.category, c.method,
           c.attempts, c.pattern, c.transactions, c.reason, c.classified_ts
    FROM memo_classifications c
    WHERE c.run_id = (
      SELECT MAX(x.run_id) FROM memo_classifications x
      WHERE x.memo_key = c.memo_key AND x.memo_version = c.memo_version
        AND x.llm_model = c.llm_model
    )]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW memo_overrides_current AS
    SELECT o.override_id, o.memo_key, o.memo_version, o.llm_model, o.category,
           o.previous_category, o.previous_method, o.reason, o.actor, o.decided_ts
    FROM memo_overrides o
    WHERE o.override_id = (
      SELECT MAX(x.override_id) FROM memo_overrides x WHERE x.memo_key = o.memo_key
    )]';
END;
/

-- The label in force: a person's label (HUMAN) wins over the rule or the model.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW memo_labels_current AS
    SELECT c.memo_key,
           c.memo_version,
           c.llm_model,
           c.memo_norm,
           COALESCE(o.category, c.category)                               AS category,
           CASE WHEN o.override_id IS NULL THEN c.method ELSE 'HUMAN' END AS method,
           c.transactions,
           c.category                                                     AS model_category,
           c.method                                                       AS model_method
    FROM memo_classifications_current c
    LEFT JOIN memo_overrides_current o ON o.memo_key = c.memo_key]';
END;
/
