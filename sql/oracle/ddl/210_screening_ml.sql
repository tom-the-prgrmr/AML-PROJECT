-- Phase 7b-ii: a learned screening-hit model (logistic regression). It only RANKS hits: nothing
-- here holds a decision or a status of a hit, and no row is ever UPDATEd or DELETEd. Simulated
-- investigator labels live in their own table (never in the audit rows that count as a human
-- review), keyed by the pair (cif, entry_id) so a new `aml screen` run does not lose them.
--
-- The JSON columns are VARCHAR2(4000) CHECK (... IS JSON), like case_models (see 180).

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_ml_labels (
      label_id    NUMBER(12)           NOT NULL,
      cif         VARCHAR2(20 CHAR)    NOT NULL,
      entry_id    VARCHAR2(20 CHAR)    NOT NULL,
      label       VARCHAR2(12 CHAR)    NOT NULL,
      origin      VARCHAR2(10 CHAR)    NOT NULL,           -- SIMULATED
      actor       VARCHAR2(60 CHAR)    NOT NULL,
      reason      VARCHAR2(300 CHAR)   NOT NULL,
      labelled_ts TIMESTAMP(6)         NOT NULL,           -- UTC
      CONSTRAINT pk_screening_ml_labels PRIMARY KEY (label_id),
      CONSTRAINT ck_screening_ml_labels_label CHECK (label IN ('TRUE_MATCH', 'FALSE_MATCH'))
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- One row per pair and feature (long form), for the screening run the pair belongs to.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_ml_features (
      result_run_id NUMBER(12)          NOT NULL,          -- screening_current.run_id of the pair
      cif           VARCHAR2(20 CHAR)   NOT NULL,
      entry_id      VARCHAR2(20 CHAR)   NOT NULL,
      feature       VARCHAR2(40 CHAR)   NOT NULL,
      value         BINARY_DOUBLE       NOT NULL,
      CONSTRAINT pk_screening_ml_features PRIMARY KEY (result_run_id, cif, entry_id, feature)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- A model is kept whole (coefficients, feature list, parameters, metrics), never as a file.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_ml_models (
      model_id        NUMBER(12)           NOT NULL,
      version         VARCHAR2(60 CHAR)    NOT NULL,       -- scrml/logreg/<model_id>
      feature_version VARCHAR2(60 CHAR)    NOT NULL,
      kind            VARCHAR2(20 CHAR)    NOT NULL,       -- logreg
      trained_ts      TIMESTAMP(6)         NOT NULL,       -- UTC
      seed            NUMBER(18)           NOT NULL,
      pairs           NUMBER(18)           NOT NULL,
      true_match      NUMBER(18)           NOT NULL,
      false_match     NUMBER(18)           NOT NULL,
      human_labels    NUMBER(18)           NOT NULL,
      features        VARCHAR2(4000 CHAR)  NOT NULL,
      params          VARCHAR2(4000 CHAR)  NOT NULL,
      metrics         VARCHAR2(4000 CHAR)  NOT NULL,
      artifact        CLOB                 NOT NULL,       -- JSON {features, mean, scale, coef, intercept}
      data_hash       VARCHAR2(16 CHAR)    NOT NULL,
      actor           VARCHAR2(60 CHAR)    NOT NULL,
      CONSTRAINT pk_screening_ml_models PRIMARY KEY (model_id),
      CONSTRAINT ck_screening_ml_models_features CHECK (features IS JSON),
      CONSTRAINT ck_screening_ml_models_params CHECK (params IS JSON),
      CONSTRAINT ck_screening_ml_models_metrics CHECK (metrics IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- The exact pairs a model was trained on, so a model card can trace the training data.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_ml_training (
      model_id      NUMBER(12)          NOT NULL,
      result_run_id NUMBER(12)          NOT NULL,
      cif           VARCHAR2(20 CHAR)   NOT NULL,
      entry_id      VARCHAR2(20 CHAR)   NOT NULL,
      label         NUMBER(1)           NOT NULL,          -- 1 = TRUE_MATCH
      origin        VARCHAR2(10 CHAR)   NOT NULL,          -- SIMULATED | HUMAN
      CONSTRAINT pk_screening_ml_training PRIMARY KEY (model_id, cif, entry_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- No column named decision or status: a score is a rank, not an outcome.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE screening_ml_scores (
      score_run_id  NUMBER(12)           NOT NULL,
      result_run_id NUMBER(12)           NOT NULL,
      cif           VARCHAR2(20 CHAR)    NOT NULL,
      entry_id      VARCHAR2(20 CHAR)    NOT NULL,
      model_id      NUMBER(12)           NOT NULL,
      model_version VARCHAR2(60 CHAR)    NOT NULL,
      score         BINARY_DOUBLE        NOT NULL,         -- a ranking value, not a calibrated probability
      score_rank    NUMBER(12)           NOT NULL,         -- 1 = most likely a true match of the run
      top_features  VARCHAR2(4000 CHAR)  NOT NULL,
      scored_ts     TIMESTAMP(6)         NOT NULL,         -- UTC
      CONSTRAINT pk_screening_ml_scores PRIMARY KEY (score_run_id, cif, entry_id),
      CONSTRAINT ck_screening_ml_scores_top CHECK (top_features IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW screening_ml_model_active AS
    SELECT * FROM screening_ml_models WHERE model_id = (SELECT MAX(model_id) FROM screening_ml_models)]';
END;
/

-- The newest scoring run that still has rows in screening_current (a new `aml screen` run
-- replaces the current rows, so scores of the old run stop being current until the next score).
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW screening_ml_scores_current AS
    SELECT s.score_run_id, s.result_run_id, s.cif, s.entry_id, s.model_id, s.model_version,
           s.score, s.score_rank, s.top_features, s.scored_ts
    FROM screening_ml_scores s
    JOIN screening_current c
      ON c.run_id = s.result_run_id AND c.cif = s.cif AND c.entry_id = s.entry_id
    WHERE s.score_run_id = (
      SELECT MAX(s2.score_run_id)
      FROM screening_ml_scores s2
      JOIN screening_current c2
        ON c2.run_id = s2.result_run_id AND c2.cif = s2.cif AND c2.entry_id = s2.entry_id)]';
END;
/
