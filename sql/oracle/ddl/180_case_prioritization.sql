-- Phase 7c: case prioritization. A model only RANKS cases: nothing here holds a disposition or a
-- case status, and no row is ever UPDATEd or DELETEd. Features are stored long (one row per case
-- and feature), so a new feature adds rows, not columns. A model is kept whole in the database
-- (coefficients, feature list, parameters, metrics), never as a file, so each score can be traced
-- to the exact model and training data (data_hash) that produced it.
--
-- The JSON columns are VARCHAR2(4000) CHECK (... IS JSON), not the native JSON type: the native
-- type hands fractional numbers back as Decimal, these come back as text that both backends parse
-- the same way. Scores and feature values are BINARY_DOUBLE so a float round-trips exactly.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_features (
      run_id  NUMBER(12)          NOT NULL,                  -- the case run (snapshot) the value was read from
      case_id VARCHAR2(40 CHAR)   NOT NULL,
      feature VARCHAR2(40 CHAR)   NOT NULL,
      value   BINARY_DOUBLE       NOT NULL,
      CONSTRAINT pk_case_features PRIMARY KEY (run_id, case_id, feature)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_models (
      model_id        NUMBER(12)           NOT NULL,
      kind            VARCHAR2(20 CHAR)    NOT NULL,         -- logreg | lightgbm
      version         VARCHAR2(60 CHAR)    NOT NULL,         -- prio/<kind>/<model_id>
      feature_version VARCHAR2(20 CHAR)    NOT NULL,
      trained_ts      TIMESTAMP(6)         NOT NULL,         -- UTC
      as_of           DATE                 NOT NULL,
      seed            NUMBER(18)           NOT NULL,
      cases           NUMBER(18)           NOT NULL,
      suspicious      NUMBER(18)           NOT NULL,
      false_positive  NUMBER(18)           NOT NULL,
      features        VARCHAR2(4000 CHAR)  NOT NULL,
      params          VARCHAR2(4000 CHAR)  NOT NULL,
      metrics         VARCHAR2(4000 CHAR)  NOT NULL,
      artifact        CLOB                 NOT NULL,         -- logreg: JSON coefficients; lightgbm: model text
      data_hash       VARCHAR2(16 CHAR)    NOT NULL,
      actor           VARCHAR2(60 CHAR)    NOT NULL,
      CONSTRAINT pk_case_models PRIMARY KEY (model_id),
      CONSTRAINT ck_case_models_features CHECK (features IS JSON),
      CONSTRAINT ck_case_models_params CHECK (params IS JSON),
      CONSTRAINT ck_case_models_metrics CHECK (metrics IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_scores (
      score_run_id  NUMBER(12)           NOT NULL,
      run_id        NUMBER(12)           NOT NULL,           -- the case run that was scored
      case_id       VARCHAR2(40 CHAR)    NOT NULL,
      model_id      NUMBER(12)           NOT NULL,
      model_version VARCHAR2(60 CHAR)    NOT NULL,
      score         BINARY_DOUBLE        NOT NULL,
      queue_rank    NUMBER(12),                              -- NULL for a CLOSED case
      top_features  VARCHAR2(4000 CHAR)  NOT NULL,
      scored_ts     TIMESTAMP(6)         NOT NULL,           -- UTC
      CONSTRAINT pk_case_scores PRIMARY KEY (score_run_id, case_id),
      CONSTRAINT ck_case_scores_top CHECK (top_features IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW case_model_active AS
    SELECT * FROM case_models WHERE model_id = (SELECT MAX(model_id) FROM case_models)]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW case_scores_current AS
    SELECT * FROM case_scores
    WHERE score_run_id = (
      SELECT MAX(score_run_id) FROM case_scores
      WHERE run_id = (SELECT MAX(run_id) FROM case_runs)
    )]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW case_queue AS
    SELECT c.run_id, c.case_id, c.golden_customer_id, c.window_start, c.first_alert_ts,
           c.last_alert_ts, c.alerts, c.rule_alerts, c.network_alerts, c.screening_alerts,
           c.sources, c.status, c.reason, s.score_run_id, s.model_id, s.model_version, s.score,
           s.queue_rank, s.top_features
    FROM cases_current c
    JOIN case_scores_current s ON s.case_id = c.case_id
    WHERE c.status IN ('OPEN', 'REOPENED')]';
END;
/
