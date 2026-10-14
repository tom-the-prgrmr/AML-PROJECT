-- Phase 7b-i: unsupervised anomaly detection (isolation forest) per customer-month. A score is a
-- SIGNAL for a person to look at: nothing here holds a disposition or a case status, and no row is
-- ever UPDATEd or DELETEd. Every score row carries the model version that produced it. The model
-- itself is not stored as a file: a run is reproducible from data_hash + params + seed.
CREATE TABLE IF NOT EXISTS anomaly_runs (
    run_id            BIGINT        PRIMARY KEY,
    run_ts            TIMESTAMP     NOT NULL,       -- UTC
    as_of             DATE          NOT NULL,
    model_version     VARCHAR(20)   NOT NULL,       -- anomaly/v1/<run_id>
    kind              VARCHAR(20)   NOT NULL,       -- isolation_forest
    feature_version   VARCHAR(20)   NOT NULL,       -- anomaly/v1
    seed              BIGINT        NOT NULL,
    samples           BIGINT        NOT NULL,       -- customer-months scored
    customers         BIGINT        NOT NULL,
    months            BIGINT        NOT NULL,
    alerts            BIGINT        NOT NULL,
    threshold         DOUBLE        NOT NULL,       -- score of the lowest-ranked alert (0 without alerts)
    graph_source      VARCHAR(10)   NOT NULL,       -- networkx | gds | none
    monitoring_run_id BIGINT        NOT NULL,       -- the run_id record_run gave the ANOMALY alerts
    data_hash         VARCHAR(16)   NOT NULL,
    features          JSON          NOT NULL,
    params            JSON          NOT NULL,       -- config, isolation forest parameters, library versions
    metrics           JSON          NOT NULL,       -- distribution of the scores
    seconds           DOUBLE        NOT NULL,
    actor             VARCHAR(60)   NOT NULL
);

CREATE TABLE IF NOT EXISTS anomaly_scores (
    run_id         BIGINT       NOT NULL,
    cif            VARCHAR(20)  NOT NULL,
    month          VARCHAR(7)   NOT NULL,           -- YYYY-MM
    model_version  VARCHAR(20)  NOT NULL,
    window_start   TIMESTAMP    NOT NULL,
    window_end     TIMESTAMP    NOT NULL,
    score          DOUBLE       NOT NULL,           -- higher = more unusual
    rank           INTEGER      NOT NULL,           -- 1 = most unusual of the run
    alerted        SMALLINT     NOT NULL,
    top_deviations JSON,                            -- only on alerted rows
    PRIMARY KEY (run_id, cif, month)
);

-- Two ranking features per case; kept apart from case_features so the Phase 7c set stays as it is.
CREATE TABLE IF NOT EXISTS case_anomaly_features (
    run_id         BIGINT       NOT NULL,           -- the case run (snapshot)
    case_id        VARCHAR(40)  NOT NULL,
    anomaly_run_id BIGINT       NOT NULL,           -- the anomaly run the values were read from
    feature        VARCHAR(40)  NOT NULL,
    value          DOUBLE       NOT NULL,
    PRIMARY KEY (run_id, case_id, anomaly_run_id, feature)
);

CREATE OR REPLACE VIEW anomaly_scores_current AS
SELECT s.*
FROM anomaly_scores s
WHERE s.run_id = (SELECT MAX(r.run_id) FROM anomaly_runs r);
