-- Fund-flow trace on the SQL property graph aml_fund_flow (Oracle 23ai only).
-- Binds: :account, :since, :hours (the first block, one hop, does not use :hours).
-- One fixed-length MATCH per hop count 1..6 joined by UNION ALL; aml.graph keeps the first N blocks.
-- Each block states the order (strictly later hops), the window (last hop within :hours of the
-- first), a prefix without repeated accounts, and is_cycle for a last hop that revisits one.
-- Generated once from a template, then stored as plain text.
SELECT * FROM GRAPH_TABLE(aml_fund_flow MATCH (a0 IS account) -[e1 IS transfer]-> (a1 IS account)
  WHERE a0.account_id = :account
    AND (:since IS NULL OR e1.txn_ts >= CAST(:since AS TIMESTAMP))
  COLUMNS (1 AS hop, a0.account_id || '>' || a1.account_id AS path, a1.account_id AS account_id, e1.txn_id AS step_path,
    e1.txn_ts AS first_ts, e1.txn_ts AS last_ts, e1.amount_vnd AS amount_vnd,
    CASE WHEN a1.account_id IN (a0.account_id) THEN 'Y' ELSE 'N' END AS is_cycle))
UNION ALL
SELECT * FROM GRAPH_TABLE(aml_fund_flow MATCH (a0 IS account) -[e1 IS transfer]-> (a1 IS account) -[e2 IS transfer]-> (a2 IS account)
  WHERE a0.account_id = :account
    AND (:since IS NULL OR e1.txn_ts >= CAST(:since AS TIMESTAMP))
    AND e2.txn_ts > e1.txn_ts
    AND e2.txn_ts <= e1.txn_ts + NUMTODSINTERVAL(:hours, 'HOUR')
    AND a1.account_id <> a0.account_id
  COLUMNS (2 AS hop, a0.account_id || '>' || a1.account_id || '>' || a2.account_id AS path, a2.account_id AS account_id, e1.txn_id || '>' || e2.txn_id AS step_path,
    e1.txn_ts AS first_ts, e2.txn_ts AS last_ts, e2.amount_vnd AS amount_vnd,
    CASE WHEN a2.account_id IN (a0.account_id, a1.account_id) THEN 'Y' ELSE 'N' END AS is_cycle))
UNION ALL
SELECT * FROM GRAPH_TABLE(aml_fund_flow MATCH (a0 IS account) -[e1 IS transfer]-> (a1 IS account) -[e2 IS transfer]-> (a2 IS account) -[e3 IS transfer]-> (a3 IS account)
  WHERE a0.account_id = :account
    AND (:since IS NULL OR e1.txn_ts >= CAST(:since AS TIMESTAMP))
    AND e2.txn_ts > e1.txn_ts
    AND e3.txn_ts > e2.txn_ts
    AND e3.txn_ts <= e1.txn_ts + NUMTODSINTERVAL(:hours, 'HOUR')
    AND a1.account_id <> a0.account_id
    AND a2.account_id <> a0.account_id
    AND a2.account_id <> a1.account_id
  COLUMNS (3 AS hop, a0.account_id || '>' || a1.account_id || '>' || a2.account_id || '>' || a3.account_id AS path, a3.account_id AS account_id, e1.txn_id || '>' || e2.txn_id || '>' || e3.txn_id AS step_path,
    e1.txn_ts AS first_ts, e3.txn_ts AS last_ts, e3.amount_vnd AS amount_vnd,
    CASE WHEN a3.account_id IN (a0.account_id, a1.account_id, a2.account_id) THEN 'Y' ELSE 'N' END AS is_cycle))
UNION ALL
SELECT * FROM GRAPH_TABLE(aml_fund_flow MATCH (a0 IS account) -[e1 IS transfer]-> (a1 IS account) -[e2 IS transfer]-> (a2 IS account) -[e3 IS transfer]-> (a3 IS account) -[e4 IS transfer]-> (a4 IS account)
  WHERE a0.account_id = :account
    AND (:since IS NULL OR e1.txn_ts >= CAST(:since AS TIMESTAMP))
    AND e2.txn_ts > e1.txn_ts
    AND e3.txn_ts > e2.txn_ts
    AND e4.txn_ts > e3.txn_ts
    AND e4.txn_ts <= e1.txn_ts + NUMTODSINTERVAL(:hours, 'HOUR')
    AND a1.account_id <> a0.account_id
    AND a2.account_id <> a0.account_id
    AND a2.account_id <> a1.account_id
    AND a3.account_id <> a0.account_id
    AND a3.account_id <> a1.account_id
    AND a3.account_id <> a2.account_id
  COLUMNS (4 AS hop, a0.account_id || '>' || a1.account_id || '>' || a2.account_id || '>' || a3.account_id || '>' || a4.account_id AS path, a4.account_id AS account_id, e1.txn_id || '>' || e2.txn_id || '>' || e3.txn_id || '>' || e4.txn_id AS step_path,
    e1.txn_ts AS first_ts, e4.txn_ts AS last_ts, e4.amount_vnd AS amount_vnd,
    CASE WHEN a4.account_id IN (a0.account_id, a1.account_id, a2.account_id, a3.account_id) THEN 'Y' ELSE 'N' END AS is_cycle))
UNION ALL
SELECT * FROM GRAPH_TABLE(aml_fund_flow MATCH (a0 IS account) -[e1 IS transfer]-> (a1 IS account) -[e2 IS transfer]-> (a2 IS account) -[e3 IS transfer]-> (a3 IS account) -[e4 IS transfer]-> (a4 IS account) -[e5 IS transfer]-> (a5 IS account)
  WHERE a0.account_id = :account
    AND (:since IS NULL OR e1.txn_ts >= CAST(:since AS TIMESTAMP))
    AND e2.txn_ts > e1.txn_ts
    AND e3.txn_ts > e2.txn_ts
    AND e4.txn_ts > e3.txn_ts
    AND e5.txn_ts > e4.txn_ts
    AND e5.txn_ts <= e1.txn_ts + NUMTODSINTERVAL(:hours, 'HOUR')
    AND a1.account_id <> a0.account_id
    AND a2.account_id <> a0.account_id
    AND a2.account_id <> a1.account_id
    AND a3.account_id <> a0.account_id
    AND a3.account_id <> a1.account_id
    AND a3.account_id <> a2.account_id
    AND a4.account_id <> a0.account_id
    AND a4.account_id <> a1.account_id
    AND a4.account_id <> a2.account_id
    AND a4.account_id <> a3.account_id
  COLUMNS (5 AS hop, a0.account_id || '>' || a1.account_id || '>' || a2.account_id || '>' || a3.account_id || '>' || a4.account_id || '>' || a5.account_id AS path, a5.account_id AS account_id, e1.txn_id || '>' || e2.txn_id || '>' || e3.txn_id || '>' || e4.txn_id || '>' || e5.txn_id AS step_path,
    e1.txn_ts AS first_ts, e5.txn_ts AS last_ts, e5.amount_vnd AS amount_vnd,
    CASE WHEN a5.account_id IN (a0.account_id, a1.account_id, a2.account_id, a3.account_id, a4.account_id) THEN 'Y' ELSE 'N' END AS is_cycle))
UNION ALL
SELECT * FROM GRAPH_TABLE(aml_fund_flow MATCH (a0 IS account) -[e1 IS transfer]-> (a1 IS account) -[e2 IS transfer]-> (a2 IS account) -[e3 IS transfer]-> (a3 IS account) -[e4 IS transfer]-> (a4 IS account) -[e5 IS transfer]-> (a5 IS account) -[e6 IS transfer]-> (a6 IS account)
  WHERE a0.account_id = :account
    AND (:since IS NULL OR e1.txn_ts >= CAST(:since AS TIMESTAMP))
    AND e2.txn_ts > e1.txn_ts
    AND e3.txn_ts > e2.txn_ts
    AND e4.txn_ts > e3.txn_ts
    AND e5.txn_ts > e4.txn_ts
    AND e6.txn_ts > e5.txn_ts
    AND e6.txn_ts <= e1.txn_ts + NUMTODSINTERVAL(:hours, 'HOUR')
    AND a1.account_id <> a0.account_id
    AND a2.account_id <> a0.account_id
    AND a2.account_id <> a1.account_id
    AND a3.account_id <> a0.account_id
    AND a3.account_id <> a1.account_id
    AND a3.account_id <> a2.account_id
    AND a4.account_id <> a0.account_id
    AND a4.account_id <> a1.account_id
    AND a4.account_id <> a2.account_id
    AND a4.account_id <> a3.account_id
    AND a5.account_id <> a0.account_id
    AND a5.account_id <> a1.account_id
    AND a5.account_id <> a2.account_id
    AND a5.account_id <> a3.account_id
    AND a5.account_id <> a4.account_id
  COLUMNS (6 AS hop, a0.account_id || '>' || a1.account_id || '>' || a2.account_id || '>' || a3.account_id || '>' || a4.account_id || '>' || a5.account_id || '>' || a6.account_id AS path, a6.account_id AS account_id, e1.txn_id || '>' || e2.txn_id || '>' || e3.txn_id || '>' || e4.txn_id || '>' || e5.txn_id || '>' || e6.txn_id AS step_path,
    e1.txn_ts AS first_ts, e6.txn_ts AS last_ts, e6.amount_vnd AS amount_vnd,
    CASE WHEN a6.account_id IN (a0.account_id, a1.account_id, a2.account_id, a3.account_id, a4.account_id, a5.account_id) THEN 'Y' ELSE 'N' END AS is_cycle))
/
