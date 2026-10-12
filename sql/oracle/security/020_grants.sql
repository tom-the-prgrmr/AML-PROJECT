-- Phase 2b: object grants, run on the owner connection after apply_schema. Re-run every time
-- because dropping and recreating a table (transactions, acct_edge_daily) loses its grants.
-- Keep in step with ROLE_GRANTS in aml.dba.security. No role sees ground_truth or dq_labels.

GRANT SELECT ON customers TO aml_app
/
GRANT SELECT ON customer_person TO aml_app
/
GRANT SELECT ON admin_unit_mapping TO aml_app
/
GRANT SELECT ON accounts TO aml_app
/
GRANT SELECT ON transactions TO aml_app
/
GRANT SELECT ON watchlist TO aml_app
/
GRANT SELECT ON watchlist_alias TO aml_app
/
GRANT SELECT ON acct_edge_daily TO aml_app
/
GRANT SELECT ON customers_masked TO aml_app
/
GRANT INSERT ON audit_log TO aml_app
/

GRANT SELECT ON customers_masked TO aml_analyst
/
GRANT SELECT ON accounts TO aml_analyst
/
GRANT SELECT ON transactions TO aml_analyst
/
GRANT SELECT ON acct_edge_daily TO aml_analyst
/
GRANT SELECT ON watchlist TO aml_analyst
/
GRANT SELECT ON watchlist_alias TO aml_analyst
/
GRANT SELECT ON admin_unit_mapping TO aml_analyst
/

GRANT SELECT ON customers_masked TO aml_graph_sync
/
GRANT SELECT ON accounts TO aml_graph_sync
/
GRANT SELECT ON transactions TO aml_graph_sync
/
GRANT SELECT ON acct_edge_daily TO aml_graph_sync
/
GRANT SELECT ON graph_customer_attrs TO aml_graph_sync
/
GRANT SELECT ON customer_golden TO aml_graph_sync
/
GRANT SELECT ON admin_unit_mapping TO aml_graph_sync
/

GRANT SELECT ON audit_log TO aml_auditor
/
