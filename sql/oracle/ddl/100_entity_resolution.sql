-- Phase 4: entity-resolution runs, model parameters, scored pairs and golden ids. Rows are never
-- deleted: every run adds its own run_id; the views below read the latest run. Only cif is stored
-- (no names, phones or ID numbers), and there is no foreign key to customers.
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE er_runs (
      run_id             NUMBER(12)         PRIMARY KEY,
      run_ts             TIMESTAMP(6)       NOT NULL,             -- UTC
      as_of              DATE               NOT NULL,
      customers_resolved NUMBER(18)         NOT NULL,
      blocked_pairs      NUMBER(18)         NOT NULL,
      match_pairs        NUMBER(18)         NOT NULL,
      review_pairs       NUMBER(18)         NOT NULL,
      clusters           NUMBER(18)         NOT NULL,
      merged_clusters    NUMBER(18)         NOT NULL,
      merged_cifs        NUMBER(18)         NOT NULL,
      match_threshold    BINARY_DOUBLE      NOT NULL,
      review_threshold   BINARY_DOUBLE      NOT NULL,
      prior_probability  BINARY_DOUBLE      NOT NULL,
      version            VARCHAR2(40 CHAR)  NOT NULL,
      splink_version     VARCHAR2(20 CHAR)  NOT NULL,
      config_hash        VARCHAR2(16 CHAR)  NOT NULL
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE er_model (
      run_id         NUMBER(12)          NOT NULL,
      comparison     VARCHAR2(20 CHAR)   NOT NULL,
      level_no       NUMBER(3)           NOT NULL,                -- 0 = null level (no weight)
      label          VARCHAR2(100 CHAR)  NOT NULL,
      is_null_level  NUMBER(1)           NOT NULL,                -- 0/1
      m_probability  BINARY_DOUBLE,
      u_probability  BINARY_DOUBLE,
      match_weight   BINARY_DOUBLE,                               -- log2(m / u)
      CONSTRAINT pk_er_model PRIMARY KEY (run_id, comparison, level_no)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE er_pairs (
      run_id            NUMBER(12)          NOT NULL,
      cif_l             VARCHAR2(20 CHAR)   NOT NULL,             -- cif_l < cif_r
      cif_r             VARCHAR2(20 CHAR)   NOT NULL,
      match_weight      BINARY_DOUBLE       NOT NULL,
      match_probability BINARY_DOUBLE       NOT NULL,
      mw_prior          BINARY_DOUBLE       NOT NULL,
      mw_name           BINARY_DOUBLE       NOT NULL,
      mw_dob            BINARY_DOUBLE       NOT NULL,
      mw_phone          BINARY_DOUBLE       NOT NULL,
      mw_email          BINARY_DOUBLE       NOT NULL,
      mw_address        BINARY_DOUBLE       NOT NULL,
      mw_id             BINARY_DOUBLE       NOT NULL,
      decision          VARCHAR2(10 CHAR)   NOT NULL,             -- MATCH | REVIEW
      reason            VARCHAR2(500 CHAR)  NOT NULL,
      CONSTRAINT pk_er_pairs PRIMARY KEY (run_id, cif_l, cif_r)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE er_golden (
      run_id             NUMBER(12)         NOT NULL,
      cif                VARCHAR2(20 CHAR)  NOT NULL,
      golden_customer_id VARCHAR2(30 CHAR)  NOT NULL,
      cluster_size       NUMBER(9)          NOT NULL,
      CONSTRAINT pk_er_golden PRIMARY KEY (run_id, cif)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW customer_golden AS
    SELECT run_id, cif, golden_customer_id, cluster_size
    FROM er_golden
    WHERE run_id = (SELECT MAX(run_id) FROM er_runs)]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
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
    GROUP BY g.golden_customer_id, g.cluster_size]';
END;
/
