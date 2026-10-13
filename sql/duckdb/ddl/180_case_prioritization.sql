-- Phase 7c: case prioritization. A model only RANKS cases: nothing here holds a disposition or a
-- case status, and no row is ever UPDATEd or DELETEd. Features are stored long (one row per case
-- and feature), so a new feature adds rows, not columns. A model is kept whole in the database
-- (coefficients, feature list, parameters, metrics), never as a file, so each score can be traced
-- to the exact model and training data (data_hash) that produced it.
CREATE TABLE IF NOT EXISTS case_features (
    run_id  BIGINT       NOT NULL,                  -- the case run (snapshot) the value was read from
    case_id VARCHAR(40)  NOT NULL,
    feature VARCHAR(40)  NOT NULL,
    value   DOUBLE       NOT NULL,
    PRIMARY KEY (run_id, case_id, feature)
);

CREATE TABLE IF NOT EXISTS case_models (
    model_id        BIGINT        PRIMARY KEY,
    kind            VARCHAR(20)   NOT NULL,         -- logreg | lightgbm
    version         VARCHAR(60)   NOT NULL,         -- prio/<kind>/<model_id>
    feature_version VARCHAR(20)   NOT NULL,
    trained_ts      TIMESTAMP     NOT NULL,         -- UTC
    as_of           DATE          NOT NULL,
    seed            BIGINT        NOT NULL,
    cases           BIGINT        NOT NULL,
    suspicious      BIGINT        NOT NULL,
    false_positive  BIGINT        NOT NULL,
    features        JSON          NOT NULL,
    params          JSON          NOT NULL,
    metrics         JSON          NOT NULL,
    artifact        VARCHAR       NOT NULL,         -- logreg: JSON coefficients; lightgbm: model text
    data_hash       VARCHAR(16)   NOT NULL,
    actor           VARCHAR(60)   NOT NULL
);

CREATE TABLE IF NOT EXISTS case_scores (
    score_run_id  BIGINT        NOT NULL,
    run_id        BIGINT        NOT NULL,           -- the case run that was scored
    case_id       VARCHAR(40)   NOT NULL,
    model_id      BIGINT        NOT NULL,
    model_version VARCHAR(60)   NOT NULL,
    score         DOUBLE        NOT NULL,
    queue_rank    INTEGER,                          -- NULL for a CLOSED case
    top_features  JSON          NOT NULL,
    scored_ts     TIMESTAMP     NOT NULL,           -- UTC
    PRIMARY KEY (score_run_id, case_id)
);

CREATE OR REPLACE VIEW case_model_active AS
SELECT * FROM case_models WHERE model_id = (SELECT MAX(model_id) FROM case_models);

CREATE OR REPLACE VIEW case_scores_current AS
SELECT * FROM case_scores
WHERE score_run_id = (
    SELECT MAX(score_run_id) FROM case_scores
    WHERE run_id = (SELECT MAX(run_id) FROM case_runs)
);

CREATE OR REPLACE VIEW case_queue AS
SELECT c.*, s.score_run_id, s.model_id, s.model_version, s.score, s.queue_rank, s.top_features
FROM cases_current c
JOIN case_scores_current s ON s.case_id = c.case_id
WHERE c.status IN ('OPEN', 'REOPENED');
