-- Phase 5b: SQL property graph aml_fund_flow for fund-flow tracing (Oracle 23ai only).
-- Vertex table: materialized view acct_node (every account id seen as sender or receiver, EXT-
-- codes included, because `accounts` lacks them). A plain view makes 6-hop queries too slow.
-- Refreshed by aml.graph.schema.refresh_account_nodes right after acct_edge_daily.

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE MATERIALIZED VIEW acct_node
      BUILD IMMEDIATE REFRESH COMPLETE ON DEMAND
    AS
    SELECT src_acct AS account_id FROM acct_edge_daily
    UNION
    SELECT dst_acct AS account_id FROM acct_edge_daily]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -12006) THEN RAISE; END IF;   -- name used / MV already exists
END;
/

BEGIN
  EXECUTE IMMEDIATE 'CREATE UNIQUE INDEX ux_acct_node ON acct_node (account_id)';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955, -1408) THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE PROPERTY GRAPH aml_fund_flow
      VERTEX TABLES (
        acct_node KEY (account_id) LABEL account PROPERTIES (account_id)
      )
      EDGE TABLES (
        transactions KEY (txn_id)
          SOURCE KEY (from_account_id) REFERENCES acct_node (account_id)
          DESTINATION KEY (to_account_id) REFERENCES acct_node (account_id)
          LABEL transfer PROPERTIES (txn_id, txn_ts, amount_vnd, channel)
      )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE NOT IN (-955) THEN RAISE; END IF;   -- property graph already exists
END;
/
