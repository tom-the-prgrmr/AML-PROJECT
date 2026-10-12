-- Phase 5a: monitoring runs, alerts, related accounts and evidence. Rows are never updated or deleted:
-- every run adds its own run_id; alerts_current reads the latest run of each rule. No names or memos
-- are stored. txn_legs gives one row per account side of a transaction (EXT-* accounts never appear).
CREATE TABLE IF NOT EXISTS monitoring_runs (
    run_id       BIGINT        NOT NULL,
    rule_id      VARCHAR(40)   NOT NULL,
    run_ts       TIMESTAMP     NOT NULL,             -- UTC
    as_of        DATE          NOT NULL,
    source       VARCHAR(20)   NOT NULL,             -- RULE | NETWORK
    rule_version VARCHAR(20)   NOT NULL,
    params       JSON,                               -- the parameters substituted into the rule
    alerts       BIGINT        NOT NULL,
    evidence     BIGINT        NOT NULL,
    PRIMARY KEY (run_id, rule_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id     BIGINT         PRIMARY KEY,
    run_id       BIGINT         NOT NULL,
    alert_key    VARCHAR(300)   NOT NULL,             -- stable identity across runs
    source       VARCHAR(20)    NOT NULL,             -- RULE | NETWORK
    rule_id      VARCHAR(40)    NOT NULL,
    rule_version VARCHAR(20)    NOT NULL,
    subject_type VARCHAR(20)    NOT NULL,             -- ACCOUNT | ACCOUNT_GROUP
    subject_id   VARCHAR(200)   NOT NULL,
    window_start TIMESTAMP      NOT NULL,
    window_end   TIMESTAMP      NOT NULL,
    txn_count    BIGINT         NOT NULL,
    amount_vnd   BIGINT         NOT NULL,
    reason       VARCHAR(1000)  NOT NULL,
    details      JSON,
    UNIQUE (run_id, alert_key)
);

CREATE TABLE IF NOT EXISTS alert_accounts (
    alert_id   BIGINT       NOT NULL,
    account_id VARCHAR(20)  NOT NULL,
    cif        VARCHAR(20),
    role       VARCHAR(20)  NOT NULL,
    PRIMARY KEY (alert_id, account_id)
);

CREATE TABLE IF NOT EXISTS alert_evidence (
    alert_id BIGINT       NOT NULL,
    txn_id   VARCHAR(20)  NOT NULL,
    PRIMARY KEY (alert_id, txn_id)
);

CREATE OR REPLACE VIEW alerts_current AS
SELECT a.*
FROM alerts a
WHERE a.run_id = (SELECT MAX(r.run_id) FROM monitoring_runs r WHERE r.rule_id = a.rule_id);

CREATE OR REPLACE VIEW txn_legs AS
SELECT t.to_account_id AS account_id, a.cif, a.open_date, t.txn_id, t.txn_ts, 'IN' AS direction,
       t.amount_vnd, t.from_account_id AS counterparty_id, t.channel, t.branch_id
FROM transactions t JOIN accounts a ON a.account_id = t.to_account_id
UNION ALL
SELECT t.from_account_id, a.cif, a.open_date, t.txn_id, t.txn_ts, 'OUT',
       t.amount_vnd, t.to_account_id, t.channel, t.branch_id
FROM transactions t JOIN accounts a ON a.account_id = t.from_account_id;
