-- Phase 6a: Oracle/DuckDB -> Neo4j projection. The view exposes only the customer attributes the
-- graph needs (shared-attribute keys), so the sync user needs no grant on customers itself.
-- graph_sync_runs is the run log; the watermark lives in Neo4j (SyncState), not here.
CREATE OR REPLACE VIEW graph_customer_attrs AS
SELECT cif, phone, device_id, street, ward, district, province
FROM customers;

CREATE TABLE IF NOT EXISTS graph_sync_runs (
    run_id             BIGINT       PRIMARY KEY,
    run_ts             TIMESTAMP    NOT NULL,             -- UTC
    mode               VARCHAR(12)  NOT NULL,             -- FULL | INCREMENTAL
    source_backend     VARCHAR(10)  NOT NULL,
    source_user        VARCHAR(30),
    since_ts           TIMESTAMP,
    watermark_from     TIMESTAMP,
    watermark_to       TIMESTAMP,
    er_run_id          BIGINT       NOT NULL,
    nodes_sent         BIGINT       NOT NULL,
    rels_sent          BIGINT       NOT NULL,
    pruned             BIGINT       NOT NULL,
    swept              BIGINT       NOT NULL,
    lag_before_seconds BIGINT,
    lag_after_seconds  BIGINT       NOT NULL,
    seconds            DOUBLE       NOT NULL,
    in_sync            SMALLINT     NOT NULL,
    details            JSON
);
