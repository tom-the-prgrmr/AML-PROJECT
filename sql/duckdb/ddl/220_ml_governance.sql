-- Phase 7b-iii: the below-the-line (BTL) sample, a random seeded draw of golden customers with no
-- alert, labelled from the synthetic ground truth. The labels are MEASUREMENT and TRAINING data
-- only: nothing here holds a disposition or a status, no customer is alerted or cased, and no
-- row is ever UPDATEd or DELETEd. A sample is drawn once per (case run, seed, requested size).
CREATE TABLE IF NOT EXISTS btl_samples (
    sample_id        BIGINT        PRIMARY KEY,
    run_id           BIGINT        NOT NULL,        -- the case run the sample was drawn from
    as_of            DATE          NOT NULL,        -- as_of of that run: the end of the feature window
    seed             BIGINT        NOT NULL,
    requested        BIGINT        NOT NULL,        -- the size asked for
    population       BIGINT        NOT NULL,        -- golden customers with no alert in the run
    sample_size      BIGINT        NOT NULL,        -- min(requested, population)
    suspicious       BIGINT        NOT NULL,
    not_suspicious   BIGINT        NOT NULL,
    estimated_missed BIGINT        NOT NULL,        -- round(population * suspicious / sample_size)
    ci_low           DOUBLE,                        -- 95 % Wilson interval of suspicious / sample_size
    ci_high          DOUBLE,
    version          VARCHAR(20)   NOT NULL,        -- btl/v1
    sampled_ts       TIMESTAMP     NOT NULL,        -- UTC
    actor            VARCHAR(60)   NOT NULL
);

CREATE TABLE IF NOT EXISTS btl_members (
    sample_id          BIGINT        NOT NULL,
    golden_customer_id VARCHAR(60)   NOT NULL,
    label              VARCHAR(20)   NOT NULL CHECK (label IN ('SUSPICIOUS', 'NOT_SUSPICIOUS')),
    typologies         JSON          NOT NULL,      -- ground-truth typologies, ascending
    reason             VARCHAR(400)  NOT NULL,
    PRIMARY KEY (sample_id, golden_customer_id)
);

-- The 35 case features of a member (long form), computed once per sample from the same enrichment
-- blocks as a case; the ground truth is never read here.
CREATE TABLE IF NOT EXISTS btl_features (
    sample_id          BIGINT       NOT NULL,
    golden_customer_id VARCHAR(60)  NOT NULL,
    feature            VARCHAR(40)  NOT NULL,
    value              DOUBLE       NOT NULL,
    PRIMARY KEY (sample_id, golden_customer_id, feature)
);

-- A model measured on a sample. Every row carries the model version it measured.
CREATE TABLE IF NOT EXISTS btl_evaluations (
    eval_id       BIGINT        PRIMARY KEY,
    sample_id     BIGINT        NOT NULL,
    model_id      BIGINT        NOT NULL,
    model_version VARCHAR(60)   NOT NULL,
    metrics       JSON          NOT NULL,
    scores        JSON          NOT NULL,           -- {golden_customer_id: score}
    evaluated_ts  TIMESTAMP     NOT NULL,           -- UTC
    actor         VARCHAR(60)   NOT NULL
);
