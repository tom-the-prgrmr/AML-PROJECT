-- Phase 5c: per-account features from the NetworkX run. One row per account per run; rows are never
-- updated or deleted. The nx_ prefix marks NetworkX results (Phase 6 writes GDS features elsewhere).
CREATE TABLE IF NOT EXISTS nx_account_features (
    run_id              BIGINT        NOT NULL,
    account_id          VARCHAR(20)   NOT NULL,
    in_degree           BIGINT        NOT NULL,
    out_degree          BIGINT        NOT NULL,
    in_vnd              BIGINT        NOT NULL,
    out_vnd             BIGINT        NOT NULL,
    pagerank            DOUBLE        NOT NULL,
    pagerank_ratio      DOUBLE        NOT NULL,
    cycle_alerts        BIGINT        NOT NULL,
    shared_cluster_id   VARCHAR(200),
    shared_cluster_size BIGINT        NOT NULL,
    is_hub              SMALLINT      NOT NULL,
    PRIMARY KEY (run_id, account_id)
);

CREATE OR REPLACE VIEW nx_account_features_current AS
SELECT f.*
FROM nx_account_features f
WHERE f.run_id = (SELECT MAX(x.run_id) FROM nx_account_features x);
