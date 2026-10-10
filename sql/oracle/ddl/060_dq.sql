-- Phase 2c-ii: data quality framework. Catalogue of rules, one row per (run, rule), trend view.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE dq_rules (
      rule_id           VARCHAR2(40 CHAR)  PRIMARY KEY,
      table_name        VARCHAR2(30 CHAR)  NOT NULL,
      dimension         VARCHAR2(20 CHAR)  NOT NULL,
      scope             VARCHAR2(10 CHAR)  NOT NULL,       -- ROW | TABLE
      description       VARCHAR2(500 CHAR) NOT NULL,
      check_sql         VARCHAR2(100 CHAR) NOT NULL,       -- file under sql/
      label_defect_type VARCHAR2(50 CHAR),                 -- matching defect_type in dq_labels
      max_fail_rate     BINARY_DOUBLE      NOT NULL,
      enabled           BOOLEAN            NOT NULL
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

-- Insert-only: results are never updated or deleted.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE dq_results (
      run_id      NUMBER(12)         NOT NULL,
      rule_id     VARCHAR2(40 CHAR)  NOT NULL,
      run_ts      TIMESTAMP(6)       NOT NULL,             -- UTC
      as_of       DATE               NOT NULL,
      table_name  VARCHAR2(30 CHAR)  NOT NULL,
      dimension   VARCHAR2(20 CHAR)  NOT NULL,
      total_rows  NUMBER(18)         NOT NULL,
      failed_rows NUMBER(18)         NOT NULL,
      fail_rate   BINARY_DOUBLE,                           -- NULL when NO_DATA
      status      VARCHAR2(10 CHAR)  NOT NULL,             -- PASS | FAIL | NO_DATA
      sample_ids  JSON,                                    -- smallest failing ids, ascending
      CONSTRAINT pk_dq_results PRIMARY KEY (run_id, rule_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW dq_trend AS
    SELECT
      rule_id, table_name, dimension, run_id, run_ts, failed_rows, fail_rate, status,
      LAG(failed_rows) OVER (PARTITION BY rule_id ORDER BY run_id) AS prev_failed_rows,
      failed_rows - LAG(failed_rows) OVER (PARTITION BY rule_id ORDER BY run_id)
        AS delta_failed_rows
    FROM dq_results]';
END;
/
