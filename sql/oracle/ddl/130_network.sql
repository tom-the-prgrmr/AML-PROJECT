-- Phase 5c: per-account features from the NetworkX run. One row per account per run; rows are never
-- updated or deleted. The nx_ prefix marks NetworkX results (Phase 6 writes GDS features elsewhere).
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE nx_account_features (
      run_id              NUMBER(12)          NOT NULL,
      account_id          VARCHAR2(20 CHAR)   NOT NULL,
      in_degree           NUMBER(18)          NOT NULL,
      out_degree          NUMBER(18)          NOT NULL,
      in_vnd              NUMBER(18)          NOT NULL,
      out_vnd             NUMBER(18)          NOT NULL,
      pagerank            BINARY_DOUBLE       NOT NULL,
      pagerank_ratio      BINARY_DOUBLE       NOT NULL,
      cycle_alerts        NUMBER(18)          NOT NULL,
      shared_cluster_id   VARCHAR2(200 CHAR),
      shared_cluster_size NUMBER(18)          NOT NULL,
      is_hub              NUMBER(1)           NOT NULL,
      CONSTRAINT pk_nx_account_features PRIMARY KEY (run_id, account_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW nx_account_features_current AS
    SELECT f.*
    FROM nx_account_features f
    WHERE f.run_id = (SELECT MAX(x.run_id) FROM nx_account_features x)]';
END;
/
