-- Phase 6b-ii: GDS features computed on the Neo4j projection and written back to the system of
-- record. Append-only: a run adds one gds_runs row and one gds_account_features row per account.
CREATE TABLE IF NOT EXISTS gds_runs (
    run_id              BIGINT       PRIMARY KEY,
    run_ts              TIMESTAMP    NOT NULL,             -- UTC
    as_of               DATE         NOT NULL,
    source_backend      VARCHAR(10)  NOT NULL,
    sync_run_id         BIGINT       NOT NULL,
    txn_watermark       TIMESTAMP,
    gds_version         VARCHAR(30)  NOT NULL,
    accounts            BIGINT       NOT NULL,
    active_accounts     BIGINT       NOT NULL,
    wcc_components      BIGINT       NOT NULL,
    louvain_communities BIGINT       NOT NULL,
    shared_clusters     BIGINT       NOT NULL,
    seconds             DOUBLE       NOT NULL,
    params              JSON
);

CREATE TABLE IF NOT EXISTS gds_account_features (
    run_id              BIGINT       NOT NULL,
    account_id          VARCHAR(20)  NOT NULL,
    in_degree           BIGINT       NOT NULL,
    out_degree          BIGINT       NOT NULL,
    in_vnd              BIGINT       NOT NULL,
    out_vnd             BIGINT       NOT NULL,
    pagerank            DOUBLE       NOT NULL,
    pagerank_ratio      DOUBLE       NOT NULL,
    wcc_id              VARCHAR(20),
    wcc_size            BIGINT       NOT NULL,
    louvain_id          VARCHAR(20),
    louvain_size        BIGINT       NOT NULL,
    shared_cluster_id   VARCHAR(40),
    shared_cluster_size BIGINT       NOT NULL,
    PRIMARY KEY (run_id, account_id)
);

CREATE OR REPLACE VIEW gds_account_features_current AS
SELECT * FROM gds_account_features
WHERE run_id = (SELECT MAX(run_id) FROM gds_account_features);
