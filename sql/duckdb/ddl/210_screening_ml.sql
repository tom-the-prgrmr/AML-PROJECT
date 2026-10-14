-- Phase 7b-ii: a learned screening-hit model (logistic regression). It only RANKS hits: nothing
-- here holds a decision or a status of a hit, and no row is ever UPDATEd or DELETEd. Simulated
-- investigator labels live in their own table (never in the audit rows that count as a human
-- review), keyed by the pair (cif, entry_id) so a new `aml screen` run does not lose them.
CREATE TABLE IF NOT EXISTS screening_ml_labels (
    label_id    BIGINT        PRIMARY KEY,
    cif         VARCHAR(20)   NOT NULL,
    entry_id    VARCHAR(20)   NOT NULL,
    label       VARCHAR(12)   NOT NULL CHECK (label IN ('TRUE_MATCH', 'FALSE_MATCH')),
    origin      VARCHAR(10)   NOT NULL,         -- SIMULATED
    actor       VARCHAR(60)   NOT NULL,
    reason      VARCHAR(300)  NOT NULL,
    labelled_ts TIMESTAMP     NOT NULL          -- UTC
);

-- One row per pair and feature (long form), for the screening run the pair belongs to.
CREATE TABLE IF NOT EXISTS screening_ml_features (
    result_run_id BIGINT       NOT NULL,        -- screening_current.run_id of the pair
    cif           VARCHAR(20)  NOT NULL,
    entry_id      VARCHAR(20)  NOT NULL,
    feature       VARCHAR(40)  NOT NULL,
    value         DOUBLE       NOT NULL,
    PRIMARY KEY (result_run_id, cif, entry_id, feature)
);

-- A model is kept whole (coefficients, feature list, parameters, metrics), never as a file.
CREATE TABLE IF NOT EXISTS screening_ml_models (
    model_id        BIGINT        PRIMARY KEY,
    version         VARCHAR(60)   NOT NULL,     -- scrml/logreg/<model_id>
    feature_version VARCHAR(60)   NOT NULL,
    kind            VARCHAR(20)   NOT NULL,     -- logreg
    trained_ts      TIMESTAMP     NOT NULL,     -- UTC
    seed            BIGINT        NOT NULL,
    pairs           BIGINT        NOT NULL,
    true_match      BIGINT        NOT NULL,
    false_match     BIGINT        NOT NULL,
    human_labels    BIGINT        NOT NULL,
    features        JSON          NOT NULL,
    params          JSON          NOT NULL,
    metrics         JSON          NOT NULL,
    artifact        VARCHAR       NOT NULL,     -- JSON {features, mean, scale, coef, intercept}
    data_hash       VARCHAR(16)   NOT NULL,
    actor           VARCHAR(60)   NOT NULL
);

-- The exact pairs a model was trained on, so a model card can trace the training data.
CREATE TABLE IF NOT EXISTS screening_ml_training (
    model_id      BIGINT       NOT NULL,
    result_run_id BIGINT       NOT NULL,
    cif           VARCHAR(20)  NOT NULL,
    entry_id      VARCHAR(20)  NOT NULL,
    label         SMALLINT     NOT NULL,        -- 1 = TRUE_MATCH
    origin        VARCHAR(10)  NOT NULL,        -- SIMULATED | HUMAN
    PRIMARY KEY (model_id, cif, entry_id)
);

-- No column named decision or status: a score is a rank, not an outcome.
CREATE TABLE IF NOT EXISTS screening_ml_scores (
    score_run_id  BIGINT        NOT NULL,
    result_run_id BIGINT        NOT NULL,
    cif           VARCHAR(20)   NOT NULL,
    entry_id      VARCHAR(20)   NOT NULL,
    model_id      BIGINT        NOT NULL,
    model_version VARCHAR(60)   NOT NULL,
    score         DOUBLE        NOT NULL,       -- a ranking value, not a calibrated probability
    score_rank    INTEGER       NOT NULL,       -- 1 = most likely a true match of the run
    top_features  JSON          NOT NULL,
    scored_ts     TIMESTAMP     NOT NULL,       -- UTC
    PRIMARY KEY (score_run_id, cif, entry_id)
);

CREATE OR REPLACE VIEW screening_ml_model_active AS
SELECT * FROM screening_ml_models WHERE model_id = (SELECT MAX(model_id) FROM screening_ml_models);

-- The newest scoring run that still has rows in screening_current (a new `aml screen` run
-- replaces the current rows, so scores of the old run stop being current until the next score).
CREATE OR REPLACE VIEW screening_ml_scores_current AS
SELECT s.*
FROM screening_ml_scores s
JOIN screening_current c
  ON c.run_id = s.result_run_id AND c.cif = s.cif AND c.entry_id = s.entry_id
WHERE s.score_run_id = (
    SELECT MAX(s2.score_run_id)
    FROM screening_ml_scores s2
    JOIN screening_current c2
      ON c2.run_id = s2.result_run_id AND c2.cif = s2.cif AND c2.entry_id = s2.entry_id
);
