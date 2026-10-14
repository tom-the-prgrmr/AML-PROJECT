-- Phase 7b-iii: the below-the-line (BTL) sample, a random seeded draw of golden customers with no
-- alert, labelled from the synthetic ground truth. The labels are MEASUREMENT and TRAINING data
-- only: nothing here holds a disposition or a status, no customer is alerted or cased, and no
-- row is ever UPDATEd or DELETEd. A sample is drawn once per (case run, seed, requested size).
--
-- The JSON columns are VARCHAR2 / CLOB CHECK (... IS JSON), like case_models (see 180). SIZE is a
-- reserved word in Oracle, so the sample size column is called sample_size.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE btl_samples (
      sample_id        NUMBER(12)          NOT NULL,
      run_id           NUMBER(12)          NOT NULL,       -- the case run the sample was drawn from
      as_of            DATE                NOT NULL,       -- as_of of that run: end of the feature window
      seed             NUMBER(18)          NOT NULL,
      requested        NUMBER(18)          NOT NULL,       -- the size asked for
      population       NUMBER(18)          NOT NULL,       -- golden customers with no alert in the run
      sample_size      NUMBER(18)          NOT NULL,       -- min(requested, population)
      suspicious       NUMBER(18)          NOT NULL,
      not_suspicious   NUMBER(18)          NOT NULL,
      estimated_missed NUMBER(18)          NOT NULL,       -- round(population * suspicious / sample_size)
      ci_low           BINARY_DOUBLE,                      -- 95 % Wilson interval of suspicious / sample_size
      ci_high          BINARY_DOUBLE,
      version          VARCHAR2(20 CHAR)   NOT NULL,       -- btl/v1
      sampled_ts       TIMESTAMP(6)        NOT NULL,       -- UTC
      actor            VARCHAR2(60 CHAR)   NOT NULL,
      CONSTRAINT pk_btl_samples PRIMARY KEY (sample_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE btl_members (
      sample_id          NUMBER(12)           NOT NULL,
      golden_customer_id VARCHAR2(60 CHAR)    NOT NULL,
      label              VARCHAR2(20 CHAR)    NOT NULL,
      typologies         VARCHAR2(4000 CHAR)  NOT NULL,    -- ground-truth typologies, ascending
      reason             VARCHAR2(400 CHAR)   NOT NULL,
      CONSTRAINT pk_btl_members PRIMARY KEY (sample_id, golden_customer_id),
      CONSTRAINT ck_btl_members_label CHECK (label IN ('SUSPICIOUS', 'NOT_SUSPICIOUS')),
      CONSTRAINT ck_btl_members_typologies CHECK (typologies IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- The 35 case features of a member (long form), computed once per sample from the same enrichment
-- blocks as a case; the ground truth is never read here.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE btl_features (
      sample_id          NUMBER(12)         NOT NULL,
      golden_customer_id VARCHAR2(60 CHAR)  NOT NULL,
      feature            VARCHAR2(40 CHAR)  NOT NULL,
      value              BINARY_DOUBLE      NOT NULL,
      CONSTRAINT pk_btl_features PRIMARY KEY (sample_id, golden_customer_id, feature)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- A model measured on a sample. Every row carries the model version it measured.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE btl_evaluations (
      eval_id       NUMBER(12)           NOT NULL,
      sample_id     NUMBER(12)           NOT NULL,
      model_id      NUMBER(12)           NOT NULL,
      model_version VARCHAR2(60 CHAR)    NOT NULL,
      metrics       VARCHAR2(4000 CHAR)  NOT NULL,
      scores        CLOB                 NOT NULL,         -- {golden_customer_id: score}
      evaluated_ts  TIMESTAMP(6)         NOT NULL,         -- UTC
      actor         VARCHAR2(60 CHAR)    NOT NULL,
      CONSTRAINT pk_btl_evaluations PRIMARY KEY (eval_id),
      CONSTRAINT ck_btl_evaluations_metrics CHECK (metrics IS JSON),
      CONSTRAINT ck_btl_evaluations_scores CHECK (scores IS JSON)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/
