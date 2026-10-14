-- Phase 7b-i: unsupervised anomaly detection (isolation forest) per customer-month. A score is a
-- SIGNAL for a person to look at: nothing here holds a disposition or a case status, and no row is
-- ever UPDATEd or DELETEd. Every score row carries the model version that produced it. The model
-- itself is not stored as a file: a run is reproducible from data_hash + params + seed.
--
-- The JSON columns are VARCHAR2(4000) CHECK (... IS JSON), like case_models (see 180).

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE anomaly_runs (
      run_id            NUMBER(12)           NOT NULL,
      run_ts            TIMESTAMP(6)         NOT NULL,          -- UTC
      as_of             DATE                 NOT NULL,
      model_version     VARCHAR2(20 CHAR)    NOT NULL,          -- anomaly/v1/<run_id>
      kind              VARCHAR2(20 CHAR)    NOT NULL,          -- isolation_forest
      feature_version   VARCHAR2(20 CHAR)    NOT NULL,          -- anomaly/v1
      seed              NUMBER(18)           NOT NULL,
      samples           NUMBER(18)           NOT NULL,          -- customer-months scored
      customers         NUMBER(18)           NOT NULL,
      months            NUMBER(18)           NOT NULL,
      alerts            NUMBER(18)           NOT NULL,
      threshold         BINARY_DOUBLE        NOT NULL,          -- score of the lowest-ranked alert (0 without alerts)
      graph_source      VARCHAR2(10 CHAR)    NOT NULL,          -- networkx | gds | none
      monitoring_run_id NUMBER(12)           NOT NULL,          -- the run_id record_run gave the ANOMALY alerts
      data_hash         VARCHAR2(16 CHAR)    NOT NULL,
      features          VARCHAR2(4000 CHAR)  NOT NULL,
      params            VARCHAR2(4000 CHAR)  NOT NULL,          -- config, isolation forest parameters, library versions
      metrics           VARCHAR2(4000 CHAR)  NOT NULL,          -- distribution of the scores
      seconds           BINARY_DOUBLE        NOT NULL,
      actor             VARCHAR2(60 CHAR)    NOT NULL,
      CONSTRAINT pk_anomaly_runs PRIMARY KEY (run_id),
      CONSTRAINT ck_anomaly_runs_features CHECK (features IS JSON),
      CONSTRAINT ck_anomaly_runs_params CHECK (params IS JSON),
      CONSTRAINT ck_anomaly_runs_metrics CHECK (metrics IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE anomaly_scores (
      run_id         NUMBER(12)           NOT NULL,
      cif            VARCHAR2(20 CHAR)    NOT NULL,
      month          VARCHAR2(7 CHAR)     NOT NULL,             -- YYYY-MM
      model_version  VARCHAR2(20 CHAR)    NOT NULL,
      window_start   TIMESTAMP(6)         NOT NULL,
      window_end     TIMESTAMP(6)         NOT NULL,
      score          BINARY_DOUBLE        NOT NULL,             -- higher = more unusual
      rank           NUMBER(12)           NOT NULL,             -- 1 = most unusual of the run
      alerted        NUMBER(1)            NOT NULL,
      top_deviations VARCHAR2(4000 CHAR),                       -- only on alerted rows
      CONSTRAINT pk_anomaly_scores PRIMARY KEY (run_id, cif, month),
      CONSTRAINT ck_anomaly_scores_top CHECK (top_deviations IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- Two ranking features per case; kept apart from case_features so the Phase 7c set stays as it is.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE case_anomaly_features (
      run_id         NUMBER(12)          NOT NULL,              -- the case run (snapshot)
      case_id        VARCHAR2(40 CHAR)   NOT NULL,
      anomaly_run_id NUMBER(12)          NOT NULL,              -- the anomaly run the values were read from
      feature        VARCHAR2(40 CHAR)   NOT NULL,
      value          BINARY_DOUBLE       NOT NULL,
      CONSTRAINT pk_case_anomaly_features PRIMARY KEY (run_id, case_id, anomaly_run_id, feature)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW anomaly_scores_current AS
    SELECT s.run_id, s.cif, s.month, s.model_version, s.window_start, s.window_end, s.score,
           s.rank, s.alerted, s.top_deviations
    FROM anomaly_scores s
    WHERE s.run_id = (SELECT MAX(r.run_id) FROM anomaly_runs r)]';
END;
/

-- `feature_version` of a model that uses the memo and anomaly columns is longer than 20 characters
-- (features/v1+memo/v1+anom/v1 = 27). Widening to the same size again is harmless (idempotent).
BEGIN
  EXECUTE IMMEDIATE 'ALTER TABLE case_models MODIFY (feature_version VARCHAR2(60 CHAR))';
END;
/
