-- Phase 6b-ii: GDS features computed on the Neo4j projection and written back to the system of
-- record. Append-only: a run adds one gds_runs row and one gds_account_features row per account.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE gds_runs (
      run_id              NUMBER(12)          NOT NULL,
      run_ts              TIMESTAMP(6)        NOT NULL,             -- UTC
      as_of               DATE                NOT NULL,
      source_backend      VARCHAR2(10 CHAR)   NOT NULL,
      sync_run_id         NUMBER(12)          NOT NULL,
      txn_watermark       TIMESTAMP(6),
      gds_version         VARCHAR2(30 CHAR)   NOT NULL,
      accounts            NUMBER(18)          NOT NULL,
      active_accounts     NUMBER(18)          NOT NULL,
      wcc_components      NUMBER(18)          NOT NULL,
      louvain_communities NUMBER(18)          NOT NULL,
      shared_clusters     NUMBER(18)          NOT NULL,
      seconds             BINARY_DOUBLE       NOT NULL,
      params              JSON,
      CONSTRAINT pk_gds_runs PRIMARY KEY (run_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE gds_account_features (
      run_id              NUMBER(12)          NOT NULL,
      account_id          VARCHAR2(20 CHAR)   NOT NULL,
      in_degree           NUMBER(18)          NOT NULL,
      out_degree          NUMBER(18)          NOT NULL,
      in_vnd              NUMBER(18)          NOT NULL,
      out_vnd             NUMBER(18)          NOT NULL,
      pagerank            BINARY_DOUBLE       NOT NULL,
      pagerank_ratio      BINARY_DOUBLE       NOT NULL,
      wcc_id              VARCHAR2(20 CHAR),
      wcc_size            NUMBER(18)          NOT NULL,
      louvain_id          VARCHAR2(20 CHAR),
      louvain_size        NUMBER(18)          NOT NULL,
      shared_cluster_id   VARCHAR2(40 CHAR),
      shared_cluster_size NUMBER(18)          NOT NULL,
      CONSTRAINT pk_gds_account_features PRIMARY KEY (run_id, account_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW gds_account_features_current AS
    SELECT run_id, account_id, in_degree, out_degree, in_vnd, out_vnd, pagerank, pagerank_ratio,
           wcc_id, wcc_size, louvain_id, louvain_size, shared_cluster_id, shared_cluster_size
    FROM gds_account_features
    WHERE run_id = (SELECT MAX(run_id) FROM gds_account_features)]';
END;
/
