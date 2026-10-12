-- Phase 6a: Oracle -> Neo4j projection. The view exposes only the customer attributes the graph
-- needs (shared-attribute keys), so the sync user needs no grant on customers itself.
-- graph_sync_runs is the run log; the watermark lives in Neo4j (SyncState), not here.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW graph_customer_attrs AS
    SELECT cif, phone, device_id, street, ward, district, province
    FROM customers]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE graph_sync_runs (
      run_id             NUMBER(12)          NOT NULL,
      run_ts             TIMESTAMP(6)        NOT NULL,             -- UTC
      "MODE"             VARCHAR2(12 CHAR)   NOT NULL,             -- FULL | INCREMENTAL (MODE is reserved in DDL)
      source_backend     VARCHAR2(10 CHAR)   NOT NULL,
      source_user        VARCHAR2(30 CHAR),
      since_ts           TIMESTAMP(6),
      watermark_from     TIMESTAMP(6),
      watermark_to       TIMESTAMP(6),
      er_run_id          NUMBER(12)          NOT NULL,
      nodes_sent         NUMBER(18)          NOT NULL,
      rels_sent          NUMBER(18)          NOT NULL,
      pruned             NUMBER(18)          NOT NULL,
      swept              NUMBER(18)          NOT NULL,
      lag_before_seconds NUMBER(18),
      lag_after_seconds  NUMBER(18)          NOT NULL,
      seconds            BINARY_DOUBLE       NOT NULL,
      in_sync            NUMBER(1)           NOT NULL,
      details            JSON,
      CONSTRAINT pk_graph_sync_runs PRIMARY KEY (run_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/
