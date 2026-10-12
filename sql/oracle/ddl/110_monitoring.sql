-- Phase 5a: monitoring runs, alerts, related accounts and evidence. Rows are never updated or deleted:
-- every run adds its own run_id; alerts_current reads the latest run of each rule. No names or memos
-- are stored. txn_legs gives one row per account side of a transaction (EXT-* accounts never appear).
BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE monitoring_runs (
      run_id       NUMBER(12)         NOT NULL,
      rule_id      VARCHAR2(40 CHAR)  NOT NULL,
      run_ts       TIMESTAMP(6)       NOT NULL,             -- UTC
      as_of        DATE               NOT NULL,
      source       VARCHAR2(20 CHAR)  NOT NULL,             -- RULE | NETWORK
      rule_version VARCHAR2(20 CHAR)  NOT NULL,
      params       JSON,                                    -- the parameters substituted into the rule
      alerts       NUMBER(18)         NOT NULL,
      evidence     NUMBER(18)         NOT NULL,
      CONSTRAINT pk_monitoring_runs PRIMARY KEY (run_id, rule_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;   -- ORA-00955: name already used (idempotent)
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE alerts (
      alert_id     NUMBER(18)           PRIMARY KEY,
      run_id       NUMBER(12)           NOT NULL,
      alert_key    VARCHAR2(300 CHAR)   NOT NULL,           -- stable identity across runs
      source       VARCHAR2(20 CHAR)    NOT NULL,           -- RULE | NETWORK
      rule_id      VARCHAR2(40 CHAR)    NOT NULL,
      rule_version VARCHAR2(20 CHAR)    NOT NULL,
      subject_type VARCHAR2(20 CHAR)    NOT NULL,           -- ACCOUNT | ACCOUNT_GROUP
      subject_id   VARCHAR2(200 CHAR)   NOT NULL,
      window_start TIMESTAMP(6)         NOT NULL,
      window_end   TIMESTAMP(6)         NOT NULL,
      txn_count    NUMBER(18)           NOT NULL,
      amount_vnd   NUMBER(18)           NOT NULL,
      reason       VARCHAR2(1000 CHAR)  NOT NULL,
      details      JSON,
      CONSTRAINT uq_alerts_run_key UNIQUE (run_id, alert_key)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE alert_accounts (
      alert_id   NUMBER(18)         NOT NULL,
      account_id VARCHAR2(20 CHAR)  NOT NULL,
      cif        VARCHAR2(20 CHAR),
      role       VARCHAR2(20 CHAR)  NOT NULL,
      CONSTRAINT pk_alert_accounts PRIMARY KEY (alert_id, account_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE TABLE alert_evidence (
      alert_id NUMBER(18)         NOT NULL,
      txn_id   VARCHAR2(20 CHAR)  NOT NULL,
      CONSTRAINT pk_alert_evidence PRIMARY KEY (alert_id, txn_id)
    )]';
EXCEPTION
  WHEN OTHERS THEN
    IF SQLCODE != -955 THEN RAISE; END IF;
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW alerts_current AS
    SELECT a.*
    FROM alerts a
    WHERE a.run_id = (SELECT MAX(r.run_id) FROM monitoring_runs r WHERE r.rule_id = a.rule_id)]';
END;
/

BEGIN
  EXECUTE IMMEDIATE q'[
    CREATE OR REPLACE VIEW txn_legs AS
    SELECT t.to_account_id AS account_id, a.cif, a.open_date, t.txn_id, t.txn_ts, 'IN' AS direction,
           t.amount_vnd, t.from_account_id AS counterparty_id, t.channel, t.branch_id
    FROM transactions t JOIN accounts a ON a.account_id = t.to_account_id
    UNION ALL
    SELECT t.from_account_id, a.cif, a.open_date, t.txn_id, t.txn_ts, 'OUT',
           t.amount_vnd, t.to_account_id, t.channel, t.branch_id
    FROM transactions t JOIN accounts a ON a.account_id = t.from_account_id]';
END;
/
