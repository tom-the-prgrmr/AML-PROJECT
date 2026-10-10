-- Phase 2c-ii: data quality framework. Catalogue of rules, one row per (run, rule), trend view.
CREATE TABLE IF NOT EXISTS dq_rules (
    rule_id           VARCHAR(40)  PRIMARY KEY,
    table_name        VARCHAR(30)  NOT NULL,
    dimension         VARCHAR(20)  NOT NULL,
    scope             VARCHAR(10)  NOT NULL,       -- ROW | TABLE
    description       VARCHAR(500) NOT NULL,
    check_sql         VARCHAR(100) NOT NULL,       -- file under sql/
    label_defect_type VARCHAR(50),                 -- matching defect_type in dq_labels
    max_fail_rate     DOUBLE       NOT NULL,
    enabled           BOOLEAN      NOT NULL
);

-- Insert-only: results are never updated or deleted.
CREATE TABLE IF NOT EXISTS dq_results (
    run_id      BIGINT       NOT NULL,
    rule_id     VARCHAR(40)  NOT NULL,
    run_ts      TIMESTAMP    NOT NULL,             -- UTC
    as_of       DATE         NOT NULL,
    table_name  VARCHAR(30)  NOT NULL,
    dimension   VARCHAR(20)  NOT NULL,
    total_rows  BIGINT       NOT NULL,
    failed_rows BIGINT       NOT NULL,
    fail_rate   DOUBLE,                            -- NULL when NO_DATA
    status      VARCHAR(10)  NOT NULL,             -- PASS | FAIL | NO_DATA
    sample_ids  JSON,                              -- smallest failing ids, ascending
    PRIMARY KEY (run_id, rule_id)
);

CREATE OR REPLACE VIEW dq_trend AS
SELECT
    rule_id, table_name, dimension, run_id, run_ts, failed_rows, fail_rate, status,
    LAG(failed_rows) OVER (PARTITION BY rule_id ORDER BY run_id) AS prev_failed_rows,
    failed_rows - LAG(failed_rows) OVER (PARTITION BY rule_id ORDER BY run_id) AS delta_failed_rows
FROM dq_results;
