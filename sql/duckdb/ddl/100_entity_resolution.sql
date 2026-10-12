-- Phase 4: entity-resolution runs, model parameters, scored pairs and golden ids. Rows are never
-- deleted: every run adds its own run_id; the views below read the latest run. Only cif is stored
-- (no names, phones or ID numbers), and there is no foreign key to customers.
CREATE TABLE IF NOT EXISTS er_runs (
    run_id             BIGINT       PRIMARY KEY,
    run_ts             TIMESTAMP    NOT NULL,             -- UTC
    as_of              DATE         NOT NULL,
    customers_resolved BIGINT       NOT NULL,
    blocked_pairs      BIGINT       NOT NULL,
    match_pairs        BIGINT       NOT NULL,
    review_pairs       BIGINT       NOT NULL,
    clusters           BIGINT       NOT NULL,
    merged_clusters    BIGINT       NOT NULL,
    merged_cifs        BIGINT       NOT NULL,
    match_threshold    DOUBLE       NOT NULL,
    review_threshold   DOUBLE       NOT NULL,
    prior_probability  DOUBLE       NOT NULL,
    version            VARCHAR(40)  NOT NULL,
    splink_version     VARCHAR(20)  NOT NULL,
    config_hash        VARCHAR(16)  NOT NULL
);

CREATE TABLE IF NOT EXISTS er_model (
    run_id         BIGINT        NOT NULL,
    comparison     VARCHAR(20)   NOT NULL,
    level_no       INTEGER       NOT NULL,                -- 0 = null level (no weight)
    label          VARCHAR(100)  NOT NULL,
    is_null_level  INTEGER       NOT NULL,                -- 0/1
    m_probability  DOUBLE,
    u_probability  DOUBLE,
    match_weight   DOUBLE,                                -- log2(m / u)
    PRIMARY KEY (run_id, comparison, level_no)
);

CREATE TABLE IF NOT EXISTS er_pairs (
    run_id            BIGINT        NOT NULL,
    cif_l             VARCHAR(20)   NOT NULL,             -- cif_l < cif_r
    cif_r             VARCHAR(20)   NOT NULL,
    match_weight      DOUBLE        NOT NULL,
    match_probability DOUBLE        NOT NULL,
    mw_prior          DOUBLE        NOT NULL,
    mw_name           DOUBLE        NOT NULL,
    mw_dob            DOUBLE        NOT NULL,
    mw_phone          DOUBLE        NOT NULL,
    mw_email          DOUBLE        NOT NULL,
    mw_address        DOUBLE        NOT NULL,
    mw_id             DOUBLE        NOT NULL,
    decision          VARCHAR(10)   NOT NULL,             -- MATCH | REVIEW
    reason            VARCHAR(500)  NOT NULL,
    PRIMARY KEY (run_id, cif_l, cif_r)
);

CREATE TABLE IF NOT EXISTS er_golden (
    run_id             BIGINT       NOT NULL,
    cif                VARCHAR(20)  NOT NULL,
    golden_customer_id VARCHAR(30)  NOT NULL,
    cluster_size       INTEGER      NOT NULL,
    PRIMARY KEY (run_id, cif)
);

CREATE OR REPLACE VIEW customer_golden AS
SELECT * FROM er_golden WHERE run_id = (SELECT MAX(run_id) FROM er_runs);

CREATE OR REPLACE VIEW er_cluster_weights AS
SELECT g.golden_customer_id,
       g.cluster_size,
       COUNT(*)                      AS pairs,
       ROUND(MIN(p.match_weight), 2) AS min_match_weight,
       ROUND(AVG(p.match_weight), 2) AS avg_match_weight,
       ROUND(AVG(p.mw_name), 2)      AS avg_mw_name,
       ROUND(AVG(p.mw_dob), 2)       AS avg_mw_dob,
       ROUND(AVG(p.mw_phone), 2)     AS avg_mw_phone,
       ROUND(AVG(p.mw_email), 2)     AS avg_mw_email,
       ROUND(AVG(p.mw_address), 2)   AS avg_mw_address,
       ROUND(AVG(p.mw_id), 2)        AS avg_mw_id
FROM er_pairs p
JOIN customer_golden g ON g.cif = p.cif_l
JOIN customer_golden r ON r.cif = p.cif_r AND r.golden_customer_id = g.golden_customer_id
WHERE p.run_id = (SELECT MAX(run_id) FROM er_runs)
  AND p.decision = 'MATCH'
  AND g.cluster_size > 1
GROUP BY g.golden_customer_id, g.cluster_size;
